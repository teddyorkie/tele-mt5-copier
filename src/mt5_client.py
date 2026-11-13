from __future__ import annotations

import itertools
import threading
import time
from typing import Any

from src.config import AppConfig
from src.models import (
    BrokerGateway,
    MT5OrderKind,
    OpenPosition,
    OrderExecutionResult,
    PendingOrder,
    PlannedOrder,
    PriceTick,
    TradeSide,
)

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


class SimulatedMT5Gateway:
    """
    In-memory MT5 simulator for Dry-Run mode and automated tests.
    Supports placing limit orders, triggering fills when simulated price crosses limit,
    modifying SL to Break Even, and cancelling expired pending orders.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._connected = True
        self._ticket_counter = itertools.count(10001)
        self._pending: dict[int, PendingOrder] = {}
        self._positions: dict[int, OpenPosition] = {}

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> tuple[bool, str]:
        self._connected = True
        return True, "Đã kết nối chế độ Giả lập (Dry-Run Simulator)."

    def shutdown(self) -> None:
        self._connected = False

    def set_simulated_price(self, bid: float, ask: float | None = None) -> None:
        with self._lock:
            self._config.mt5.dry_run_bid = float(bid)
            self._config.mt5.dry_run_ask = float(ask) if ask is not None else round(bid + 0.3, 5)
            self._check_simulated_fills()

    def _check_simulated_fills(self) -> None:
        bid = self._config.mt5.dry_run_bid
        ask = self._config.mt5.dry_run_ask
        filled_tickets: list[int] = []
        for ticket, order in self._pending.items():
            should_fill = (
                (order.side is TradeSide.BUY and ask <= order.price_open)
                or (order.side is TradeSide.SELL and bid >= order.price_open)
            )
            if should_fill:
                filled_tickets.append(ticket)
                self._positions[ticket] = OpenPosition(
                    ticket=ticket,
                    symbol=order.symbol,
                    side=order.side,
                    volume=order.volume,
                    price_open=order.price_open,
                    sl=order.sl,
                    tp=order.tp,
                    magic=order.magic,
                    comment=order.comment,
                )
        for ticket in filled_tickets:
            self._pending.pop(ticket, None)

    def get_tick(self, symbol: str) -> PriceTick | None:
        with self._lock:
            self._check_simulated_fills()
            return PriceTick(
                symbol=symbol,
                bid=self._config.mt5.dry_run_bid,
                ask=self._config.mt5.dry_run_ask,
                timestamp=time.time(),
            )

    def place_limit_order(
        self, order: PlannedOrder, magic: int, deviation: int
    ) -> OrderExecutionResult:
        with self._lock:
            ticket = next(self._ticket_counter)
            now = time.time()
            self._pending[ticket] = PendingOrder(
                ticket=ticket,
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                price_open=order.limit_price,
                sl=order.sl,
                tp=order.tp,
                time_setup=now,
                magic=magic,
                comment=order.comment,
            )
            return OrderExecutionResult(
                success=True,
                ticket=ticket,
                order=order,
                message=(
                    f"[DRY-RUN] Đã đặt {order.order_kind.value} #{ticket}: "
                    f"{order.symbol} {order.volume} lot @ {order.limit_price} "
                    f"(SL: {order.sl}, TP: {order.tp})"
                ),
                retcode=10009,
            )

    def get_open_positions(self, magic: int) -> list[OpenPosition]:
        with self._lock:
            self._check_simulated_fills()
            return [p for p in self._positions.values() if p.magic == magic]

    def get_pending_orders(self, magic: int) -> list[PendingOrder]:
        with self._lock:
            self._check_simulated_fills()
            return [o for o in self._pending.values() if o.magic == magic]

    def modify_position_sl(
        self, ticket: int, symbol: str, new_sl: float, tp: float
    ) -> tuple[bool, str]:
        with self._lock:
            pos = self._positions.get(ticket)
            if pos is None:
                return False, f"Không tìm thấy vị thế đang mở #{ticket}."
            self._positions[ticket] = OpenPosition(
                ticket=pos.ticket,
                symbol=pos.symbol,
                side=pos.side,
                volume=pos.volume,
                price_open=pos.price_open,
                sl=new_sl,
                tp=tp,
                magic=pos.magic,
                comment=pos.comment,
            )
            return True, f"[DRY-RUN] Đã cập nhật SL vị thế #{ticket} -> {new_sl}"

    def cancel_pending_order(self, ticket: int) -> tuple[bool, str]:
        with self._lock:
            removed = self._pending.pop(ticket, None)
            if removed is None:
                return False, f"Không tìm thấy lệnh chờ #{ticket} để hủy."
            return True, f"[DRY-RUN] Đã hủy lệnh chờ #{ticket} ({removed.side.value} @ {removed.price_open})"

    def close_position(self, ticket: int) -> tuple[bool, str]:
        with self._lock:
            removed = self._positions.pop(ticket, None)
            if removed is None:
                return False, f"Không tìm thấy vị thế #{ticket} để đóng."
            return True, f"[DRY-RUN] Đã đóng vị thế #{ticket} ({removed.side.value} @ {removed.price_open})"


class LiveMT5Gateway:
    """Real MetaTrader 5 terminal gateway using the official MetaTrader5 Python library."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connected = False

    def is_connected(self) -> bool:
        if mt5 is None or not self._connected:
            return False
        return mt5.terminal_info() is not None

    def connect(self) -> tuple[bool, str]:
        if mt5 is None:
            return False, "Thư viện MetaTrader5 chưa được cài đặt."

        terminal_path = self._config.mt5.terminal_path.strip()
        ok = mt5.initialize(terminal_path) if terminal_path else mt5.initialize()
        if not ok:
            err = mt5.last_error()
            self._connected = False
            return False, f"Kết nối MT5 thất bại: {err}"

        self._connected = True
        acc = mt5.account_info()
        acc_str = f"Tài khoản #{acc.login} ({acc.server})" if acc else "MT5 Terminal"
        return True, f"Đã kết nối MT5 thành công: {acc_str}"

    def shutdown(self) -> None:
        if mt5 is not None and self._connected:
            mt5.shutdown()
        self._connected = False

    def _ensure_symbol_selected(self, symbol: str) -> Any | None:
        if not self.is_connected() and not self.connect()[0]:
            return None
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                return None
        return info

    def _resolve_filling_mode(self, symbol_info: Any) -> int:
        filling = getattr(symbol_info, "filling_mode", 0)
        if filling & 1:
            return mt5.ORDER_FILLING_FOK
        if filling & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def get_tick(self, symbol: str) -> PriceTick | None:
        info = self._ensure_symbol_selected(symbol)
        if info is None:
            return None
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return None
        return PriceTick(
            symbol=symbol,
            bid=float(tick.bid),
            ask=float(tick.ask),
            timestamp=float(getattr(tick, "time", time.time())),
        )

    def place_limit_order(
        self, order: PlannedOrder, magic: int, deviation: int
    ) -> OrderExecutionResult:
        info = self._ensure_symbol_selected(order.symbol)
        if info is None:
            return OrderExecutionResult(
                success=False,
                ticket=0,
                order=order,
                message=f"Không tìm thấy hoặc không thể kích hoạt mã {order.symbol} trên MT5.",
            )

        digits = int(info.digits)
        order_type = (
            mt5.ORDER_TYPE_BUY_LIMIT
            if order.order_kind is MT5OrderKind.BUY_LIMIT
            else mt5.ORDER_TYPE_SELL_LIMIT
        )
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": order.symbol,
            "volume": float(order.volume),
            "type": order_type,
            "price": round(order.limit_price, digits),
            "sl": round(order.sl, digits),
            "tp": round(order.tp, digits),
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": order.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._resolve_filling_mode(info),
        }

        res = mt5.order_send(request)
        if res is None:
            return OrderExecutionResult(
                success=False,
                ticket=0,
                order=order,
                message=f"MT5 order_send trả về None: {mt5.last_error()}",
            )

        retcode = int(res.retcode)
        if retcode != mt5.TRADE_RETCODE_DONE:
            return OrderExecutionResult(
                success=False,
                ticket=0,
                order=order,
                message=f"MT5 từ chối lệnh (retcode={retcode}): {res.comment}",
                retcode=retcode,
            )

        ticket = int(res.order)
        return OrderExecutionResult(
            success=True,
            ticket=ticket,
            order=order,
            message=(
                f"Đã đặt {order.order_kind.value} #{ticket}: "
                f"{order.symbol} {order.volume} lot @ {order.limit_price} "
                f"(SL: {order.sl}, TP: {order.tp})"
            ),
            retcode=retcode,
        )

    def get_open_positions(self, magic: int) -> list[OpenPosition]:
        if not self.is_connected() and not self.connect()[0]:
            return []
        raw_positions = mt5.positions_get()
        if not raw_positions:
            return []
        result: list[OpenPosition] = []
        for p in raw_positions:
            if int(p.magic) != int(magic):
                continue
            side = TradeSide.BUY if int(p.type) == mt5.POSITION_TYPE_BUY else TradeSide.SELL
            result.append(
                OpenPosition(
                    ticket=int(p.ticket),
                    symbol=str(p.symbol),
                    side=side,
                    volume=float(p.volume),
                    price_open=float(p.price_open),
                    sl=float(p.sl),
                    tp=float(p.tp),
                    magic=int(p.magic),
                    comment=str(getattr(p, "comment", "")),
                )
            )
        return result

    def get_pending_orders(self, magic: int) -> list[PendingOrder]:
        if not self.is_connected() and not self.connect()[0]:
            return []
        raw_orders = mt5.orders_get()
        if not raw_orders:
            return []
        result: list[PendingOrder] = []
        for o in raw_orders:
            if int(o.magic) != int(magic):
                continue
            side = (
                TradeSide.BUY
                if int(o.type) in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)
                else TradeSide.SELL
            )
            result.append(
                PendingOrder(
                    ticket=int(o.ticket),
                    symbol=str(o.symbol),
                    side=side,
                    volume=float(o.volume_current),
                    price_open=float(o.price_open),
                    sl=float(o.sl),
                    tp=float(o.tp),
                    time_setup=float(getattr(o, "time_setup", time.time())),
                    magic=int(o.magic),
                    comment=str(getattr(o, "comment", "")),
                )
            )
        return result

    def modify_position_sl(
        self, ticket: int, symbol: str, new_sl: float, tp: float
    ) -> tuple[bool, str]:
        info = self._ensure_symbol_selected(symbol)
        digits = int(info.digits) if info else 2
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": symbol,
            "sl": round(new_sl, digits),
            "tp": round(tp, digits),
        }
        res = mt5.order_send(request)
        if res is None or int(res.retcode) != mt5.TRADE_RETCODE_DONE:
            comment = getattr(res, "comment", str(mt5.last_error()))
            return False, f"Lỗi dời SL vị thế #{ticket}: {comment}"
        return True, f"Đã dời SL vị thế #{ticket} về {round(new_sl, digits)}"

    def cancel_pending_order(self, ticket: int) -> tuple[bool, str]:
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": int(ticket),
        }
        res = mt5.order_send(request)
        if res is None or int(res.retcode) != mt5.TRADE_RETCODE_DONE:
            comment = getattr(res, "comment", str(mt5.last_error()))
            return False, f"Lỗi hủy lệnh chờ #{ticket}: {comment}"
        return True, f"Đã hủy lệnh chờ #{ticket} trên MT5."

    def close_position(self, ticket: int) -> tuple[bool, str]:
        if not self.is_connected() and not self.connect()[0]:
            return False, "Chưa kết nối MT5."
        raw_positions = mt5.positions_get(ticket=int(ticket))
        if not raw_positions:
            return False, f"Không tìm thấy vị thế #{ticket} trên MT5."
        pos = raw_positions[0]
        symbol = str(pos.symbol)
        info = self._ensure_symbol_selected(symbol)
        tick = mt5.symbol_info_tick(symbol) if info else None
        if info is None or tick is None:
            return False, f"Không lấy được giá đóng vị thế #{ticket} ({symbol})."
        is_buy = int(pos.type) == mt5.POSITION_TYPE_BUY
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        close_price = float(tick.bid) if is_buy else float(tick.ask)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(ticket),
            "symbol": symbol,
            "volume": float(pos.volume),
            "type": close_type,
            "price": round(close_price, int(info.digits)),
            "deviation": int(self._config.mt5.deviation_points),
            "magic": int(pos.magic),
            "comment": "Copier Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._resolve_filling_mode(info),
        }
        res = mt5.order_send(request)
        if res is None or int(res.retcode) != mt5.TRADE_RETCODE_DONE:
            comment = getattr(res, "comment", str(mt5.last_error()))
            return False, f"Lỗi đóng vị thế #{ticket}: {comment}"
        return True, f"Đã đóng vị thế #{ticket} trên MT5."


class DynamicMT5Gateway:
    """
    Delegates calls to either SimulatedMT5Gateway (when dry_run=True)
    or LiveMT5Gateway (when dry_run=False) without requiring code changes.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self.simulator = SimulatedMT5Gateway(config)
        self.live = LiveMT5Gateway(config)

    @property
    def active(self) -> BrokerGateway:
        return self.simulator if self._config.mt5.dry_run else self.live

    def is_connected(self) -> bool:
        return self.active.is_connected()

    def connect(self) -> tuple[bool, str]:
        return self.active.connect()

    def shutdown(self) -> None:
        self.live.shutdown()
        self.simulator.shutdown()

    def get_tick(self, symbol: str) -> PriceTick | None:
        return self.active.get_tick(symbol)

    def place_limit_order(
        self, order: PlannedOrder, magic: int, deviation: int
    ) -> OrderExecutionResult:
        return self.active.place_limit_order(order, magic, deviation)

    def get_open_positions(self, magic: int) -> list[OpenPosition]:
        return self.active.get_open_positions(magic)

    def get_pending_orders(self, magic: int) -> list[PendingOrder]:
        return self.active.get_pending_orders(magic)

    def modify_position_sl(
        self, ticket: int, symbol: str, new_sl: float, tp: float
    ) -> tuple[bool, str]:
        return self.active.modify_position_sl(ticket, symbol, new_sl, tp)

    def cancel_pending_order(self, ticket: int) -> tuple[bool, str]:
        return self.active.cancel_pending_order(ticket)

    def close_position(self, ticket: int) -> tuple[bool, str]:
        return self.active.close_position(ticket)
