from __future__ import annotations

import time

from src.config import AppConfig
from src.models import (
    AppEvent,
    BrokerGateway,
    EventCategory,
    EventLevel,
)
from src.storage import OrderStorage


class TradeManager:
    """
    Enforces active trade management rules:
    1. The 6 Price Rule: When an open position reaches +6.0 price profit, move SL to Entry (Break Even).
    2. 4-Hour Pending Expiry: Cancel pending Limit orders that remain unfilled after 4 hours.
    """

    def __init__(
        self,
        config: AppConfig,
        gateway: BrokerGateway,
        storage: OrderStorage,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._storage = storage

    def run_cycle(self, now: float | None = None) -> list[AppEvent]:
        current_time = now if now is not None else time.time()
        events: list[AppEvent] = []
        events.extend(self._check_breakeven_positions(current_time))
        events.extend(self._cancel_expired_pending_orders(current_time))
        return events

    def _check_breakeven_positions(self, current_time: float) -> list[AppEvent]:
        events: list[AppEvent] = []
        magic = self._config.mt5.magic_number
        trigger = self._config.strategy.breakeven_trigger_price

        positions = self._gateway.get_open_positions(magic)
        for pos in positions:
            if pos.side.is_sl_at_or_better_than_entry(pos.sl, pos.price_open):
                continue

            tick = self._gateway.get_tick(pos.symbol)
            if tick is None:
                continue

            profit_price = pos.side.profit_in_price(pos.price_open, tick)
            if profit_price < trigger:
                continue

            ok, msg = self._gateway.modify_position_sl(
                ticket=pos.ticket,
                symbol=pos.symbol,
                new_sl=pos.price_open,
                tp=pos.tp,
            )
            if ok:
                self._storage.mark_breakeven_applied(pos.ticket)
                events.append(
                    AppEvent(
                        level=EventLevel.SUCCESS,
                        category=EventCategory.BREAKEVEN_MOVED,
                        title=f"Quy tắc +{trigger:g} Giá (Break Even) #{pos.ticket}",
                        message=(
                            f"Vị thế {pos.side.value} {pos.symbol} #{pos.ticket} đạt +{profit_price:.2f} giá. "
                            f"Đã dời SL về hòa vốn (Entry = {pos.price_open}). {msg}"
                        ),
                        timestamp=current_time,
                    )
                )
            else:
                events.append(
                    AppEvent(
                        level=EventLevel.ERROR,
                        category=EventCategory.BREAKEVEN_MOVED,
                        title=f"Lỗi dời SL Hòa vốn #{pos.ticket}",
                        message=msg,
                        timestamp=current_time,
                    )
                )
        return events

    def _cancel_expired_pending_orders(self, current_time: float) -> list[AppEvent]:
        events: list[AppEvent] = []
        magic = self._config.mt5.magic_number
        expiry_seconds = self._config.strategy.pending_expiry_hours * 3600.0

        pending_orders = self._gateway.get_pending_orders(magic)
        for order in pending_orders:
            created_at = self._storage.get_order_created_at(
                order.ticket, fallback_time=order.time_setup
            )
            elapsed = current_time - created_at
            if elapsed < expiry_seconds:
                continue

            ok, msg = self._gateway.cancel_pending_order(order.ticket)
            if ok:
                self._storage.update_order_status(order.ticket, "EXPIRED_CANCELLED")
                hours_elapsed = elapsed / 3600.0
                events.append(
                    AppEvent(
                        level=EventLevel.WARNING,
                        category=EventCategory.ORDER_EXPIRED,
                        title=f"Tự hủy lệnh chờ quá hạn #{order.ticket}",
                        message=(
                            f"Lệnh {order.side.value} LIMIT {order.symbol} #{order.ticket} @ {order.price_open} "
                            f"chưa khớp sau {hours_elapsed:.2f} giờ (giới hạn {self._config.strategy.pending_expiry_hours:g}h). "
                            f"{msg}"
                        ),
                        timestamp=current_time,
                    )
                )
            else:
                events.append(
                    AppEvent(
                        level=EventLevel.ERROR,
                        category=EventCategory.ORDER_EXPIRED,
                        title=f"Lỗi hủy lệnh chờ #{order.ticket}",
                        message=msg,
                        timestamp=current_time,
                    )
                )
        return events
