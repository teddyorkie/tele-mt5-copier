from __future__ import annotations

import re

from src.models import ParsedSignal, TradeSide

_HEADER_PATTERN = re.compile(
    r"\b(?P<side>BUY|SELL)\s+(?P<symbol>[A-Za-z]{3,10})\b",
    re.IGNORECASE,
)

_ENTRY_SL_PATTERN = re.compile(
    r"(?P<e1>\d+(?:\.\d+)?)"
    r"(?:\s*[-/,\s]\s*(?P<e2>\d+(?:\.\d+)?))?"
    r"\s*\(?SL\s*:?\s*(?P<sl>\d+(?:\.\d+)?)\)?",
    re.IGNORECASE,
)

_TP_PATTERN = re.compile(
    r"\bTP\s*:?\s*(?P<tps>\d+(?:\.\d+)?(?:\s*[-/,\s]\s*\d+(?:\.\d+)?)*)",
    re.IGNORECASE,
)

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def resolve_shorthand_price(
    reference_price: float,
    raw_value: float,
    *,
    must_be_above: bool | None = None,
) -> float:
    """
    Convert a 2-digit shorthand price (e.g. 98, 76, 92, 15) into a full price
    relative to `reference_price`, handling century crossings (38xx <-> 39xx).
    Full prices (>= 100) are returned unchanged.
    """
    if raw_value >= 100.0 or reference_price < 100.0:
        return round(float(raw_value), 5)

    century = int(reference_price // 100) * 100
    candidate = century + raw_value

    if must_be_above is True:
        if candidate <= reference_price:
            candidate += 100.0
    elif must_be_above is False:
        if candidate >= reference_price:
            candidate -= 100.0
    else:
        candidates = (candidate - 100.0, candidate, candidate + 100.0)
        candidate = min(candidates, key=lambda c: abs(c - reference_price))

    return round(candidate, 5)


def _parse_block(
    side: TradeSide,
    raw_symbol: str,
    block_text: str,
    reference_price: float | None = None,
) -> ParsedSignal | None:
    entry_sl_match = _ENTRY_SL_PATTERN.search(block_text)
    if not entry_sl_match:
        return None

    e1_raw = float(entry_sl_match.group("e1"))
    if e1_raw < 100.0 and reference_price is not None and reference_price >= 100.0:
        e1 = resolve_shorthand_price(
            reference_price,
            e1_raw,
            must_be_above=(side is TradeSide.SELL),
        )
    else:
        e1 = e1_raw

    e2_raw = entry_sl_match.group("e2")
    sl_raw = float(entry_sl_match.group("sl"))

    entries: list[float] = [e1]
    if e2_raw is not None:
        e2 = resolve_shorthand_price(e1, float(e2_raw), must_be_above=None)
        entries.append(e2)

    sl_must_be_above = side is TradeSide.SELL
    anchor_for_sl = max(entries) if side is TradeSide.SELL else min(entries)
    sl = resolve_shorthand_price(anchor_for_sl, sl_raw, must_be_above=sl_must_be_above)

    tp_match = _TP_PATTERN.search(block_text[entry_sl_match.end() :]) or _TP_PATTERN.search(
        block_text
    )
    if not tp_match:
        return None

    raw_tp_numbers = [float(x) for x in _NUMBER_PATTERN.findall(tp_match.group("tps"))]
    if not raw_tp_numbers:
        return None

    tp_must_be_above = side is TradeSide.BUY
    resolved_tps: list[float] = []
    ref_price = entries[0]
    for raw_tp in raw_tp_numbers:
        tp_val = resolve_shorthand_price(ref_price, raw_tp, must_be_above=tp_must_be_above)
        resolved_tps.append(tp_val)
        ref_price = tp_val

    return ParsedSignal(
        side=side,
        raw_symbol=raw_symbol.upper(),
        entries=tuple(entries),
        sl=sl,
        tps=tuple(resolved_tps),
        raw_text=block_text.strip(),
    )


def resolve_signal_shorthand(signal: ParsedSignal, reference_price: float) -> ParsedSignal:
    """
    Resolve a ParsedSignal whose entries were given in 2-digit shorthand (e.g. 13 08 SL 01)
    against the current market `reference_price` (e.g. 38xx, 39xx, 40xx).
    """
    if not signal.entries or signal.entries[0] >= 100.0 or reference_price < 100.0:
        return signal

    if signal.raw_text:
        reparsed = _parse_block(
            signal.side,
            signal.raw_symbol,
            signal.raw_text,
            reference_price=reference_price,
        )
        if reparsed is not None:
            return reparsed

    e1 = resolve_shorthand_price(
        reference_price,
        signal.entries[0],
        must_be_above=(signal.side is TradeSide.SELL),
    )
    entries = [e1]
    for raw_e in signal.entries[1:]:
        entries.append(resolve_shorthand_price(e1, raw_e, must_be_above=None))

    sl_must_be_above = signal.side is TradeSide.SELL
    anchor_for_sl = max(entries) if signal.side is TradeSide.SELL else min(entries)
    sl = resolve_shorthand_price(anchor_for_sl, signal.sl, must_be_above=sl_must_be_above)

    tp_must_be_above = signal.side is TradeSide.BUY
    resolved_tps: list[float] = []
    ref_price = e1
    for raw_tp in signal.tps:
        tp_val = resolve_shorthand_price(ref_price, raw_tp, must_be_above=tp_must_be_above)
        resolved_tps.append(tp_val)
        ref_price = tp_val

    return ParsedSignal(
        side=signal.side,
        raw_symbol=signal.raw_symbol,
        entries=tuple(entries),
        sl=sl,
        tps=tuple(resolved_tps),
        raw_text=signal.raw_text,
    )


def parse_message(text: str, reference_price: float | None = None) -> list[ParsedSignal]:
    """
    Parse a raw message (from GUI textbox or Telegram) into one or more ParsedSignals.
    If `reference_price` is provided, 2-digit shorthand first entries (e.g. `13 08 SL 01`)
    are automatically resolved to the nearest century (e.g. 38xx / 39xx / 40xx).
    Returns an empty list if the text does not contain valid trading signals.
    """
    if not text or not text.strip():
        return []

    matches = list(_HEADER_PATTERN.finditer(text))
    if not matches:
        return []

    signals: list[ParsedSignal] = []
    active_ref = reference_price
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block_text = text[start:end]
        side = TradeSide(match.group("side").upper())
        raw_symbol = match.group("symbol").upper()

        parsed = _parse_block(side, raw_symbol, block_text, reference_price=active_ref)
        if parsed is not None:
            signals.append(parsed)
            if reference_price is None and parsed.entries and parsed.entries[0] >= 100.0:
                active_ref = parsed.entries[0]

    return signals
