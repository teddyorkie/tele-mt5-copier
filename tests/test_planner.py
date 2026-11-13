import unittest

from src.config import AppConfig
from src.models import (
    MT5OrderKind,
    ParsedSignal,
    PlanStatus,
    PriceTick,
    TPMode,
    TradeSide,
)
from src.planner import plan_signal_orders


def _make_config(offset: float = 0.5, tp_mode: TPMode = TPMode.SPLIT) -> AppConfig:
    cfg = AppConfig()
    cfg.strategy.lot_per_entry = 0.01
    cfg.strategy.early_entry_offset = offset
    cfg.strategy.tp_mode = tp_mode
    cfg.strategy.max_sl_distance = 30.0
    return cfg


class PlannerTestCase(unittest.TestCase):
    def test_plan_sell_signal_with_early_offset_when_market_outside_zone(self):
        signal = ParsedSignal(
            side=TradeSide.SELL,
            raw_symbol="GOLD",
            entries=(3908.0, 3913.0),
            sl=3920.0,
            tps=(3898.0, 3876.0),
        )
        tick = PriceTick(symbol="XAUUSD", bid=3895.0, ask=3895.3)
        result = plan_signal_orders(signal, tick, _make_config(offset=0.5))

        self.assertIs(result.status, PlanStatus.READY)
        self.assertEqual(len(result.orders), 2)

        o1, o2 = result.orders
        self.assertIs(o1.order_kind, MT5OrderKind.SELL_LIMIT)
        self.assertEqual(o1.raw_entry_price, 3908.0)
        self.assertEqual(o1.limit_price, 3907.5)
        self.assertEqual(o1.sl, 3920.0)
        self.assertEqual(o1.tp, 3898.0)
        self.assertEqual(o1.volume, 0.01)

        self.assertIs(o2.order_kind, MT5OrderKind.SELL_LIMIT)
        self.assertEqual(o2.raw_entry_price, 3913.0)
        self.assertEqual(o2.limit_price, 3912.5)
        self.assertEqual(o2.sl, 3920.0)
        self.assertEqual(o2.tp, 3876.0)
        self.assertEqual(o2.volume, 0.01)

    def test_plan_buy_signal_with_early_offset_when_market_outside_zone(self):
        signal = ParsedSignal(
            side=TradeSide.BUY,
            raw_symbol="GOLD",
            entries=(3881.0, 3876.0),
            sl=3869.0,
            tps=(3892.0, 3915.0),
        )
        tick = PriceTick(symbol="XAUUSD", bid=3895.0, ask=3895.3)
        result = plan_signal_orders(signal, tick, _make_config(offset=0.5))

        self.assertIs(result.status, PlanStatus.READY)
        self.assertEqual(len(result.orders), 2)

        o1, o2 = result.orders
        self.assertIs(o1.order_kind, MT5OrderKind.BUY_LIMIT)
        self.assertEqual(o1.raw_entry_price, 3881.0)
        self.assertEqual(o1.limit_price, 3881.5)
        self.assertEqual(o1.sl, 3869.0)
        self.assertEqual(o1.tp, 3892.0)

        self.assertIs(o2.order_kind, MT5OrderKind.BUY_LIMIT)
        self.assertEqual(o2.raw_entry_price, 3876.0)
        self.assertEqual(o2.limit_price, 3876.5)
        self.assertEqual(o2.sl, 3869.0)
        self.assertEqual(o2.tp, 3915.0)

    def test_plan_skips_and_warns_when_price_already_in_sell_zone(self):
        signal = ParsedSignal(
            side=TradeSide.SELL,
            raw_symbol="GOLD",
            entries=(3908.0, 3913.0),
            sl=3920.0,
            tps=(3898.0, 3876.0),
        )
        tick = PriceTick(symbol="XAUUSD", bid=3909.0, ask=3909.3)
        result = plan_signal_orders(signal, tick, _make_config(offset=0.5))

        self.assertIs(result.status, PlanStatus.SKIPPED_PRICE_IN_ZONE)
        self.assertEqual(result.orders, ())
        self.assertIn("3909.0", result.reason)

    def test_plan_skips_and_warns_when_price_already_in_buy_zone(self):
        signal = ParsedSignal(
            side=TradeSide.BUY,
            raw_symbol="GOLD",
            entries=(3881.0, 3876.0),
            sl=3869.0,
            tps=(3892.0, 3915.0),
        )
        tick = PriceTick(symbol="XAUUSD", bid=3878.7, ask=3879.0)
        result = plan_signal_orders(signal, tick, _make_config(offset=0.5))

        self.assertIs(result.status, PlanStatus.SKIPPED_PRICE_IN_ZONE)
        self.assertEqual(result.orders, ())
        self.assertIn("3879.0", result.reason)

    def test_plan_rejects_excessive_sl_distance(self):
        signal = ParsedSignal(
            side=TradeSide.BUY,
            raw_symbol="GOLD",
            entries=(3881.0, 3876.0),
            sl=3800.0,
            tps=(3892.0, 3915.0),
        )
        tick = PriceTick(symbol="XAUUSD", bid=3895.0, ask=3895.3)
        result = plan_signal_orders(signal, tick, _make_config(offset=0.5))

        self.assertIs(result.status, PlanStatus.REJECTED_INVALID_LEVELS)
        self.assertEqual(result.orders, ())
