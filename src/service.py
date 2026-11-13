from __future__ import annotations

import time

from src.config import AppConfig
from src.models import (
    AppEvent,
    BrokerGateway,
    EventCategory,
    EventLevel,
    EventListener,
    PlanStatus,
    SignalPlanResult,
)
from src.parser import parse_message, resolve_signal_shorthand
from src.planner import plan_signal_orders
from src.storage import OrderStorage
from src.trade_manager import TradeManager


class CopierService:
    """
    Unified application facade shared by Phase 1 (GUI Textbox) and Phase 2 (Telegram Userbot).
    Decouples message ingestion, planning, order placement, trade management, and notifications.
    """

    def __init__(
        self,
        config: AppConfig,
        gateway: BrokerGateway,
        storage: OrderStorage,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.storage = storage
        self.trade_manager = TradeManager(config=config, gateway=gateway, storage=storage)
        self._listeners: list[EventListener] = []

    def subscribe(self, listener: EventListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def emit(self, event: AppEvent) -> None:
        for listener in list(self._listeners):
            listener(event)

    def preview_message(self, raw_text: str) -> list[SignalPlanResult]:
        """Parse and plan orders without sending them to MT5."""
        signals = parse_message(raw_text)
        if not signals:
            self.emit(
                AppEvent(
                    level=EventLevel.WARNING,
                    category=EventCategory.SIGNAL_PARSED,
                    title="Không tìm thấy tín hiệu hợp lệ",
                    message="Nội dung nhập vào không khớp định dạng tín hiệu BUY/SELL.",
                )
            )
            return []

        results: list[SignalPlanResult] = []
        for sig in signals:
            symbol = self.config.mt5.resolve_symbol(sig.raw_symbol)
            tick = self.gateway.get_tick(symbol)
            if tick is None:
                results.append(
                    SignalPlanResult(
                        signal=sig,
                        symbol=symbol,
                        status=PlanStatus.REJECTED_INVALID_LEVELS,
                        reason=f"Không lấy được giá Bid/Ask của mã {symbol} từ MT5.",
                    )
                )
                continue
            plan_res = plan_signal_orders(sig, tick, self.config)
            results.append(plan_res)
        return results

    def process_message(
        self,
        raw_text: str,
        *,
        source_id: str = "gui",
        message_id: str = "",
        allow_duplicate: bool = True,
        now: float | None = None,
    ) -> list[SignalPlanResult]:
        """
        Parse, validate, check entry zone, and place Limit orders on MT5.
        Emits structured AppEvents for UI display (Phase 1) and Telegram alerts (Phase 2).
        """
        current_time = now if now is not None else time.time()
        signals = parse_message(raw_text)
        if not signals:
            self.emit(
                AppEvent(
                    level=EventLevel.WARNING,
                    category=EventCategory.SIGNAL_PARSED,
                    title="Không tìm thấy tín hiệu",
                    message="Tin nhắn không chứa cấu trúc tín hiệu BUY/SELL hợp lệ.",
                    timestamp=current_time,
                )
            )
            return []

        results: list[SignalPlanResult] = []
        for sig in signals:
            symbol = self.config.mt5.resolve_symbol(sig.raw_symbol)
            tick = self.gateway.get_tick(symbol)
            if tick is not None:
                sig = resolve_signal_shorthand(sig, sig.side.market_reference_price(tick))

            fp = sig.fingerprint()
            if not allow_duplicate and self.storage.is_signal_processed(
                source_id, message_id, fp
            ):
                continue

            if tick is None:
                err_res = SignalPlanResult(
                    signal=sig,
                    symbol=symbol,
                    status=PlanStatus.REJECTED_INVALID_LEVELS,
                    reason=f"Không lấy được giá Bid/Ask cho {symbol}. Kiểm tra kết nối MT5.",
                )
                results.append(err_res)
                self.emit(
                    AppEvent(
                        level=EventLevel.ERROR,
                        category=EventCategory.SYSTEM,
                        title=f"Lỗi lấy giá {symbol}",
                        message=err_res.reason,
                        timestamp=current_time,
                    )
                )
                continue

            plan_res = plan_signal_orders(sig, tick, self.config)
            results.append(plan_res)

            if plan_res.status is PlanStatus.SKIPPED_PRICE_IN_ZONE:
                self.emit(
                    AppEvent(
                        level=EventLevel.WARNING,
                        category=EventCategory.ZONE_ALERT,
                        title=f"⚠️ CẢNH BÁO: Giá đã nằm trong vùng Entry ({sig.side.value} {symbol})",
                        message=plan_res.reason,
                        timestamp=current_time,
                    )
                )
                if not allow_duplicate:
                    self.storage.record_processed_signal(source_id, message_id, fp, current_time)
                continue

            if plan_res.status is PlanStatus.REJECTED_INVALID_LEVELS:
                self.emit(
                    AppEvent(
                        level=EventLevel.ERROR,
                        category=EventCategory.SIGNAL_PARSED,
                        title=f"Từ chối tín hiệu {sig.side.value} {symbol}",
                        message=plan_res.reason,
                        timestamp=current_time,
                    )
                )
                continue

            all_placed = True
            for planned_order in plan_res.orders:
                exec_res = self.gateway.place_limit_order(
                    order=planned_order,
                    magic=self.config.mt5.magic_number,
                    deviation=self.config.mt5.deviation_points,
                )
                if exec_res.success:
                    self.storage.record_placed_order(
                        ticket=exec_res.ticket,
                        order=planned_order,
                        created_at=current_time,
                    )
                    self.emit(
                        AppEvent(
                            level=EventLevel.SUCCESS,
                            category=EventCategory.ORDER_PLACED,
                            title=f"✅ Đặt lệnh thành công #{exec_res.ticket}",
                            message=exec_res.message,
                            timestamp=current_time,
                        )
                    )
                else:
                    all_placed = False
                    self.emit(
                        AppEvent(
                            level=EventLevel.ERROR,
                            category=EventCategory.ORDER_PLACED,
                            title=f"❌ Đặt lệnh thất bại ({planned_order.order_kind.value})",
                            message=exec_res.message,
                            timestamp=current_time,
                        )
                    )

            if all_placed and not allow_duplicate:
                self.storage.record_processed_signal(source_id, message_id, fp, current_time)

        return results

    def run_trade_manager_step(self, now: float | None = None) -> list[AppEvent]:
        events = self.trade_manager.run_cycle(now=now)
        for ev in events:
            self.emit(ev)
        return events

    def cancel_order(self, ticket: int, now: float | None = None) -> bool:
        """Cancel a pending order or close an open position by ticket."""
        current_time = now if now is not None else time.time()
        magic = self.config.mt5.magic_number

        pending_tickets = {o.ticket for o in self.gateway.get_pending_orders(magic)}
        if ticket in pending_tickets:
            ok, msg = self.gateway.cancel_pending_order(ticket)
            status_label = "MANUAL_CANCELLED"
            action_title = f"Đã xóa lệnh chờ #{ticket}"
        else:
            ok, msg = self.gateway.close_position(ticket)
            status_label = "MANUAL_CLOSED"
            action_title = f"Đã đóng vị thế #{ticket}"

        if ok:
            self.storage.update_order_status(ticket, status_label)
            self.emit(
                AppEvent(
                    level=EventLevel.INFO,
                    category=EventCategory.ORDER_CANCELLED,
                    title=action_title,
                    message=msg,
                    timestamp=current_time,
                )
            )
            return True

        self.emit(
            AppEvent(
                level=EventLevel.ERROR,
                category=EventCategory.ORDER_CANCELLED,
                title=f"Lỗi xóa lệnh #{ticket}",
                message=msg,
                timestamp=current_time,
            )
        )
        return False

    def cancel_all_orders(self, now: float | None = None) -> int:
        """Cancel all pending orders and close all open positions belonging to this copier."""
        current_time = now if now is not None else time.time()
        magic = self.config.mt5.magic_number
        tickets = [o.ticket for o in self.gateway.get_pending_orders(magic)] + [
            p.ticket for p in self.gateway.get_open_positions(magic)
        ]
        removed_count = 0
        for ticket in tickets:
            if self.cancel_order(ticket, now=current_time):
                removed_count += 1
        return removed_count
