from __future__ import annotations

from src.config import AppConfig
from src.models import (
    ParsedSignal,
    PlannedOrder,
    PlanStatus,
    PriceTick,
    SignalPlanResult,
    TPMode,
)
from src.parser import resolve_signal_shorthand


def _select_tp_for_entry(tps: tuple[float, ...], entry_index: int, tp_mode: TPMode) -> float:
    if not tps:
        raise ValueError("Signal must contain at least one TP level.")
    if tp_mode is TPMode.TP1 or len(tps) == 1:
        return tps[0]
    if tp_mode is TPMode.TP2:
        return tps[-1]
    # TPMode.SPLIT: Entry 1 -> TP1, Entry 2 -> TP2
    return tps[0] if entry_index == 1 else tps[min(1, len(tps) - 1)]


def plan_signal_orders(
    signal: ParsedSignal,
    tick: PriceTick,
    config: AppConfig,
) -> SignalPlanResult:
    """
    Convert a ParsedSignal into 2 PlannedOrders (Limit) according to strategy rules:
    1. Sort entries by market arrival order; duplicate if only 1 entry is given.
    2. Apply early_entry_offset (e.g., +0.5 for BUY, -0.5 for SELL).
    3. Reject if SL/TP levels are invalid or exceed max_sl_distance.
    4. Skip & notify if current market price is already inside/past the first entry level.
    """
    symbol = config.mt5.resolve_symbol(signal.raw_symbol)
    strat = config.strategy
    side = signal.side
    ref_market = side.market_reference_price(tick)
    signal = resolve_signal_shorthand(signal, ref_market)

    sorted_entries = side.sort_entries_by_arrival(signal.entries)
    if len(sorted_entries) == 1:
        sorted_entries = [sorted_entries[0], sorted_entries[0]]
    else:
        sorted_entries = sorted_entries[:2]

    limit_prices = [
        side.apply_early_offset(raw_e, strat.early_entry_offset) for raw_e in sorted_entries
    ]

    # Validate SL and TP geometry before checking market zone
    for idx, limit_price in enumerate(limit_prices, start=1):
        if not side.is_valid_sl(limit_price, signal.sl):
            return SignalPlanResult(
                signal=signal,
                symbol=symbol,
                status=PlanStatus.REJECTED_INVALID_LEVELS,
                reason=(
                    f"SL ({signal.sl}) không hợp lệ so với giá Limit {idx} ({limit_price}) "
                    f"của lệnh {side.value}."
                ),
            )
        sl_distance = abs(limit_price - signal.sl)
        if sl_distance > strat.max_sl_distance:
            return SignalPlanResult(
                signal=signal,
                symbol=symbol,
                status=PlanStatus.REJECTED_INVALID_LEVELS,
                reason=(
                    f"Khoảng cách SL ({sl_distance:.2f} giá) vượt quá giới hạn an toàn "
                    f"({strat.max_sl_distance:.2f} giá)."
                ),
            )
        assigned_tp = _select_tp_for_entry(signal.tps, idx, strat.tp_mode)
        if not side.is_valid_tp(limit_price, assigned_tp):
            return SignalPlanResult(
                signal=signal,
                symbol=symbol,
                status=PlanStatus.REJECTED_INVALID_LEVELS,
                reason=(
                    f"TP ({assigned_tp}) không hợp lệ so với giá Limit {idx} ({limit_price}) "
                    f"của lệnh {side.value}."
                ),
            )

    ref_market = side.market_reference_price(tick)
    first_limit = limit_prices[0]
    if side.is_market_already_in_zone(first_limit, tick):
        return SignalPlanResult(
            signal=signal,
            symbol=symbol,
            status=PlanStatus.SKIPPED_PRICE_IN_ZONE,
            reference_market_price=ref_market,
            reason=(
                f"Giá thị trường hiện tại ({ref_market}) đã nằm sẵn trong/vượt qua vùng Entry "
                f"{side.value} (Mốc đón 1: {first_limit}, Vùng gốc: {sorted_entries[0]} - {sorted_entries[1]}). "
                f"Hệ thống KHÔNG đặt lệnh và phát cảnh báo."
            ),
        )

    planned_orders: list[PlannedOrder] = []
    for idx, (raw_e, limit_p) in enumerate(zip(sorted_entries, limit_prices), start=1):
        tp_val = _select_tp_for_entry(signal.tps, idx, strat.tp_mode)
        planned_orders.append(
            PlannedOrder(
                symbol=symbol,
                side=side,
                order_kind=side.limit_order_kind,
                entry_index=idx,
                raw_entry_price=raw_e,
                limit_price=limit_p,
                sl=signal.sl,
                tp=tp_val,
                volume=strat.lot_per_entry,
                comment=f"Copier E{idx} ({raw_e})",
            )
        )

    return SignalPlanResult(
        signal=signal,
        symbol=symbol,
        status=PlanStatus.READY,
        orders=tuple(planned_orders),
        reference_market_price=ref_market,
        reason="Hợp lệ, sẵn sàng đặt 2 lệnh Limit.",
    )
