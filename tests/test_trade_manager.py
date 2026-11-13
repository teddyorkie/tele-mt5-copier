from pathlib import Path
import unittest

from src.config import AppConfig
from src.models import AppEvent, EventCategory, PlanStatus
from src.mt5_client import SimulatedMT5Gateway
from src.service import CopierService
from src.storage import OrderStorage
from tests.test_parser import SAMPLE_TELEGRAM_MESSAGE


def _create_test_service(initial_bid: float = 3895.0) -> tuple[CopierService, SimulatedMT5Gateway, list[AppEvent]]:
    cfg = AppConfig()
    cfg.mt5.dry_run = True
    cfg.mt5.dry_run_bid = initial_bid
    cfg.mt5.dry_run_ask = round(initial_bid + 0.3, 5)
    cfg.strategy.lot_per_entry = 0.01
    cfg.strategy.early_entry_offset = 0.5
    cfg.strategy.breakeven_trigger_price = 6.0
    cfg.strategy.pending_expiry_hours = 4.0

    gateway = SimulatedMT5Gateway(cfg)
    storage = OrderStorage(":memory:")
    service = CopierService(config=cfg, gateway=gateway, storage=storage)
    events: list[AppEvent] = []
    service.subscribe(events.append)
    return service, gateway, events


class TradeManagerTestCase(unittest.TestCase):
    def test_load_default_config_file(self):
        cfg_path = Path(__file__).resolve().parent.parent / "config.yaml"
        cfg = AppConfig.load(cfg_path)
        self.assertEqual(cfg.strategy.lot_per_entry, 0.01)
        self.assertEqual(cfg.strategy.early_entry_offset, 0.5)
        self.assertEqual(cfg.strategy.breakeven_trigger_price, 6.0)
        self.assertEqual(cfg.strategy.pending_expiry_hours, 4.0)

    def test_service_places_four_limit_orders_for_dual_signal_when_price_in_middle(self):
        service, gateway, _events = _create_test_service(initial_bid=3895.0)
        results = service.process_message(SAMPLE_TELEGRAM_MESSAGE, now=1000.0)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.status is PlanStatus.READY for r in results))

        pending = gateway.get_pending_orders(service.config.mt5.magic_number)
        self.assertEqual(len(pending), 4)
        prices = [o.price_open for o in pending]
        self.assertEqual(prices, [3907.5, 3912.5, 3881.5, 3876.5])

    def test_service_notifies_and_skips_when_price_already_in_entry_zone(self):
        service, gateway, events = _create_test_service(initial_bid=3909.0)
        results = service.process_message(SAMPLE_TELEGRAM_MESSAGE, now=1000.0)

        self.assertIs(results[0].status, PlanStatus.SKIPPED_PRICE_IN_ZONE)
        self.assertIs(results[1].status, PlanStatus.READY)

        zone_alerts = [e for e in events if e.category is EventCategory.ZONE_ALERT]
        self.assertEqual(len(zone_alerts), 1)
        self.assertIn("3909.0", zone_alerts[0].message)

        pending = gateway.get_pending_orders(service.config.mt5.magic_number)
        self.assertEqual(len(pending), 2)

    def test_six_price_rule_moves_sl_to_breakeven_once(self):
        service, gateway, _events = _create_test_service(initial_bid=3895.0)
        service.process_message(
            "BUY GOLD\n3881 3876 SL 3869\nTP 92 15",
            now=1000.0,
        )

        gateway.set_simulated_price(bid=3881.2, ask=3881.5)
        open_pos = gateway.get_open_positions(service.config.mt5.magic_number)
        self.assertEqual(len(open_pos), 1)
        self.assertEqual(open_pos[0].price_open, 3881.5)
        self.assertEqual(open_pos[0].sl, 3869.0)

        gateway.set_simulated_price(bid=3887.0, ask=3887.3)
        ev_step1 = service.run_trade_manager_step(now=1100.0)
        self.assertEqual(ev_step1, [])

        gateway.set_simulated_price(bid=3887.5, ask=3887.8)
        ev_step2 = service.run_trade_manager_step(now=1200.0)
        self.assertEqual(len(ev_step2), 1)
        self.assertIs(ev_step2[0].category, EventCategory.BREAKEVEN_MOVED)

        updated_pos = gateway.get_open_positions(service.config.mt5.magic_number)[0]
        self.assertEqual(updated_pos.sl, 3881.5)

        ev_step3 = service.run_trade_manager_step(now=1205.0)
        self.assertEqual(ev_step3, [])

    def test_pending_orders_cancelled_automatically_after_four_hours(self):
        service, gateway, _events = _create_test_service(initial_bid=3895.0)
        t0 = 10_000.0
        service.process_message(
            "SELL GOLD\n3908 3913 SL 3920\nTP 98 76",
            now=t0,
        )
        self.assertEqual(len(gateway.get_pending_orders(service.config.mt5.magic_number)), 2)

        ev_before = service.run_trade_manager_step(now=t0 + 14_340.0)
        self.assertEqual(ev_before, [])
        self.assertEqual(len(gateway.get_pending_orders(service.config.mt5.magic_number)), 2)

        ev_after = service.run_trade_manager_step(now=t0 + 14_401.0)
        self.assertEqual(len(ev_after), 2)
        self.assertTrue(all(e.category is EventCategory.ORDER_EXPIRED for e in ev_after))
        self.assertEqual(gateway.get_pending_orders(service.config.mt5.magic_number), [])

    def test_service_processes_all_shorthand_message_using_current_market_price(self):
        msg = """BUY GOLD🍀🍀
13 08 SL 01 (Round 2)
TP 25 48"""
        for century_base, market_bid in (
            (3800.0, 3895.0),
            (3800.0, 3825.0),
            (3900.0, 3925.0),
            (4000.0, 4025.0),
        ):
            with self.subTest(century=int(century_base // 100), market_bid=market_bid):
                service, gateway, _events = _create_test_service(initial_bid=market_bid)
                results = service.process_message(msg, now=1000.0)
                self.assertEqual(len(results), 1)
                self.assertIs(results[0].status, PlanStatus.READY)
                self.assertEqual(results[0].signal.entries, (century_base + 13.0, century_base + 8.0))
                self.assertEqual(results[0].signal.sl, century_base + 1.0)
                self.assertEqual(results[0].signal.tps, (century_base + 25.0, century_base + 48.0))

                pending = gateway.get_pending_orders(service.config.mt5.magic_number)
                self.assertEqual(len(pending), 2)
                self.assertEqual(
                    [o.price_open for o in pending],
                    [century_base + 13.5, century_base + 8.5],
                )

    def test_service_cancel_single_and_all_created_orders(self):
        service, gateway, _events = _create_test_service(initial_bid=3895.0)
        service.process_message(SAMPLE_TELEGRAM_MESSAGE, now=1000.0)
        magic = service.config.mt5.magic_number

        pending = gateway.get_pending_orders(magic)
        self.assertEqual(len(pending), 4)

        first_ticket = pending[0].ticket
        ok = service.cancel_order(first_ticket, now=1005.0)
        self.assertTrue(ok)

        remaining = gateway.get_pending_orders(magic)
        self.assertEqual(len(remaining), 3)
        self.assertNotIn(first_ticket, [o.ticket for o in remaining])

        cancelled_count = service.cancel_all_orders(now=1010.0)
        self.assertEqual(cancelled_count, 3)
        self.assertEqual(gateway.get_pending_orders(magic), [])

