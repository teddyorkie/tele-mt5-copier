from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Callable, Protocol, Sequence


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def limit_order_kind(self) -> MT5OrderKind:
        return MT5OrderKind.BUY_LIMIT if self is TradeSide.BUY else MT5OrderKind.SELL_LIMIT

    def apply_early_offset(self, entry_price: float, offset: float) -> float:
        """
        Apply early entry offset so limit orders trigger slightly before exact entry.
        - BUY (price drops from above): enter higher -> entry + offset
        - SELL (price rises from below): enter lower -> entry - offset
        """
        if self is TradeSide.BUY:
            return round(entry_price + offset, 5)
        return round(entry_price - offset, 5)

    def sort_entries_by_arrival(self, entries: Sequence[float]) -> list[float]:
        """
        Sort entry zone points in the order market price will reach them first.
        - BUY: price approaches from above -> highest entry is Entry 1.
        - SELL: price approaches from below -> lowest entry is Entry 1.
        """
        return sorted(entries, reverse=(self is TradeSide.BUY))

    def market_reference_price(self, tick: PriceTick) -> float:
        """BUY orders trigger on Ask; SELL orders trigger on Bid."""
        return tick.ask if self is TradeSide.BUY else tick.bid

    def is_market_already_in_zone(self, first_limit_price: float, tick: PriceTick) -> bool:
        """
        Check if current market price has already reached or entered the entry zone.
        - BUY_LIMIT requires current Ask > first_limit_price. If Ask <= first_limit_price, already in zone.
        - SELL_LIMIT requires current Bid < first_limit_price. If Bid >= first_limit_price, already in zone.
        """
        ref = self.market_reference_price(tick)
        if self is TradeSide.BUY:
            return ref <= first_limit_price
        return ref >= first_limit_price

    def profit_in_price(self, open_price: float, tick: PriceTick) -> float:
        """Calculate unrealized profit in price units (points/dollars on Gold)."""
        if self is TradeSide.BUY:
            return tick.bid - open_price
        return open_price - tick.ask

    def is_sl_at_or_better_than_entry(
        self, current_sl: float, open_price: float, tolerance: float = 1e-4
    ) -> bool:
        """Check whether Stop Loss has already been moved to Break Even (or better)."""
        if current_sl <= 0:
            return False
        if self is TradeSide.BUY:
            return current_sl >= open_price - tolerance
        return current_sl <= open_price + tolerance

    def is_valid_sl(self, entry_price: float, sl: float) -> bool:
        if self is TradeSide.BUY:
            return sl < entry_price
        return sl > entry_price

    def is_valid_tp(self, entry_price: float, tp: float) -> bool:
        if self is TradeSide.BUY:
            return tp > entry_price
        return tp < entry_price


class MT5OrderKind(str, Enum):
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"


class PlanStatus(str, Enum):
    READY = "READY"
    SKIPPED_PRICE_IN_ZONE = "SKIPPED_PRICE_IN_ZONE"
    REJECTED_INVALID_LEVELS = "REJECTED_INVALID_LEVELS"


class TPMode(str, Enum):
    SPLIT = "split"   # Entry 1 -> TP1, Entry 2 -> TP2
    TP1 = "tp1"       # Both entries -> TP1
    TP2 = "tp2"       # Both entries -> TP2


class EventLevel(str, Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class EventCategory(str, Enum):
    SIGNAL_PARSED = "SIGNAL_PARSED"
    ZONE_ALERT = "ZONE_ALERT"
    ORDER_PLACED = "ORDER_PLACED"
    BREAKEVEN_MOVED = "BREAKEVEN_MOVED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True)
class PriceTick:
    symbol: str
    bid: float
    ask: float
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ParsedSignal:
    side: TradeSide
    raw_symbol: str
    entries: tuple[float, ...]
    sl: float
    tps: tuple[float, ...]
    raw_text: str = ""

    def fingerprint(self) -> str:
        payload = (
            f"{self.side.value}|{self.raw_symbol.upper()}|"
            f"{','.join(f'{e:.4f}' for e in self.entries)}|"
            f"{self.sl:.4f}|"
            f"{','.join(f'{t:.4f}' for t in self.tps)}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PlannedOrder:
    symbol: str
    side: TradeSide
    order_kind: MT5OrderKind
    entry_index: int
    raw_entry_price: float
    limit_price: float
    sl: float
    tp: float
    volume: float
    comment: str


@dataclass(frozen=True)
class SignalPlanResult:
    signal: ParsedSignal
    symbol: str
    status: PlanStatus
    orders: tuple[PlannedOrder, ...] = ()
    reason: str = ""
    reference_market_price: float | None = None


@dataclass(frozen=True)
class OrderExecutionResult:
    success: bool
    ticket: int
    order: PlannedOrder
    message: str
    retcode: int = 0


@dataclass(frozen=True)
class OpenPosition:
    ticket: int
    symbol: str
    side: TradeSide
    volume: float
    price_open: float
    sl: float
    tp: float
    magic: int
    comment: str = ""


@dataclass(frozen=True)
class PendingOrder:
    ticket: int
    symbol: str
    side: TradeSide
    volume: float
    price_open: float
    sl: float
    tp: float
    time_setup: float
    magic: int
    comment: str = ""


@dataclass(frozen=True)
class AppEvent:
    level: EventLevel
    category: EventCategory
    title: str
    message: str
    timestamp: float = field(default_factory=time.time)


EventListener = Callable[[AppEvent], None]


class BrokerGateway(Protocol):
    def is_connected(self) -> bool: ...
    def connect(self) -> tuple[bool, str]: ...
    def shutdown(self) -> None: ...
    def get_tick(self, symbol: str) -> PriceTick | None: ...
    def place_limit_order(
        self, order: PlannedOrder, magic: int, deviation: int
    ) -> OrderExecutionResult: ...
    def get_open_positions(self, magic: int) -> list[OpenPosition]: ...
    def get_pending_orders(self, magic: int) -> list[PendingOrder]: ...
    def modify_position_sl(
        self, ticket: int, symbol: str, new_sl: float, tp: float
    ) -> tuple[bool, str]: ...
    def cancel_pending_order(self, ticket: int) -> tuple[bool, str]: ...
    def close_position(self, ticket: int) -> tuple[bool, str]: ...
