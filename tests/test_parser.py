import unittest

from src.models import TradeSide
from src.parser import parse_message, resolve_shorthand_price


SAMPLE_TELEGRAM_MESSAGE = """\
SELL GOLD🍀🍀
3908 3913 SL 3920
TP 98 76

BUY GOLD🍀🍀
3881 3876 SL 3869
TP 92 15
"""


class ParserTestCase(unittest.TestCase):
    def test_parse_sample_dual_signal_message(self):
        signals = parse_message(SAMPLE_TELEGRAM_MESSAGE)
        self.assertEqual(len(signals), 2)

        sell_sig = signals[0]
        self.assertIs(sell_sig.side, TradeSide.SELL)
        self.assertEqual(sell_sig.raw_symbol, "GOLD")
        self.assertEqual(sell_sig.entries, (3908.0, 3913.0))
        self.assertEqual(sell_sig.sl, 3920.0)
        self.assertEqual(sell_sig.tps, (3898.0, 3876.0))

        buy_sig = signals[1]
        self.assertIs(buy_sig.side, TradeSide.BUY)
        self.assertEqual(buy_sig.raw_symbol, "GOLD")
        self.assertEqual(buy_sig.entries, (3881.0, 3876.0))
        self.assertEqual(buy_sig.sl, 3869.0)
        self.assertEqual(buy_sig.tps, (3892.0, 3915.0))

    def test_resolve_shorthand_price_across_century_boundaries(self):
        tp1_sell = resolve_shorthand_price(3908.0, 98.0, must_be_above=False)
        self.assertEqual(tp1_sell, 3898.0)
        tp2_sell = resolve_shorthand_price(tp1_sell, 76.0, must_be_above=False)
        self.assertEqual(tp2_sell, 3876.0)

        tp1_buy = resolve_shorthand_price(3881.0, 92.0, must_be_above=True)
        self.assertEqual(tp1_buy, 3892.0)
        tp2_buy = resolve_shorthand_price(tp1_buy, 15.0, must_be_above=True)
        self.assertEqual(tp2_buy, 3915.0)

    def test_parse_hyphenated_and_parenthesized_formats(self):
        msg = """
        Buy XAUUSD 🔥
        3813 - 3808 (SL 3801)
        TP 23 - 35
        """
        signals = parse_message(msg)
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertIs(sig.side, TradeSide.BUY)
        self.assertEqual(sig.raw_symbol, "XAUUSD")
        self.assertEqual(sig.entries, (3813.0, 3808.0))
        self.assertEqual(sig.sl, 3801.0)
        self.assertEqual(sig.tps, (3823.0, 3835.0))

    def test_parse_shorthand_second_entry_and_sl(self):
        msg = """
        BUY GOLD
        3813 - 08 (SL 01)
        TP 23 35
        """
        signals = parse_message(msg)
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig.entries, (3813.0, 3808.0))
        self.assertEqual(sig.sl, 3801.0)
        self.assertEqual(sig.tps, (3823.0, 3835.0))

    def test_parse_ignores_non_signal_chat_messages(self):
        chat_text = "Chúc mừng anh em kèo GOLD ăn 100 pip nhé! 🍀🍀 Quản lý vốn tốt."
        self.assertEqual(parse_message(chat_text), [])

    def test_parse_all_shorthand_message_with_round_tag_across_centuries(self):
        msg = """BUY GOLD🍀🍀
13 08 SL 01 (Round 2)
TP 25 48"""

        for prefix, current_price in (
            (3800.0, 3895.3),
            (3800.0, 3820.0),
            (3900.0, 3920.0),
            (4000.0, 4020.0),
        ):
            with self.subTest(prefix=int(prefix // 100), current_price=current_price):
                signals = parse_message(msg, reference_price=current_price)
                self.assertEqual(len(signals), 1)
                sig = signals[0]
                self.assertIs(sig.side, TradeSide.BUY)
                self.assertEqual(sig.raw_symbol, "GOLD")
                self.assertEqual(sig.entries, (prefix + 13.0, prefix + 8.0))
                self.assertEqual(sig.sl, prefix + 1.0)
                self.assertEqual(sig.tps, (prefix + 25.0, prefix + 48.0))

        sell_shorthand = """SELL GOLD🍀🍀
08 13 SL 20
TP 98 76"""
        sell_signals = parse_message(sell_shorthand, reference_price=3895.0)
        self.assertEqual(len(sell_signals), 1)
        self.assertEqual(sell_signals[0].entries, (3908.0, 3913.0))
        self.assertEqual(sell_signals[0].sl, 3920.0)
        self.assertEqual(sell_signals[0].tps, (3898.0, 3876.0))

