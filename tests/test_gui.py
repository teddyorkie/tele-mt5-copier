import tkinter as tk
import unittest

from src.config import AppConfig
from src.gui import CopierGUI
from src.models import EventLevel
from src.mt5_client import DynamicMT5Gateway
from src.service import CopierService
from src.storage import OrderStorage
from tests.test_parser import SAMPLE_TELEGRAM_MESSAGE


class GUITestCase(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.cfg = AppConfig()
        self.cfg.mt5.dry_run = True
        self.cfg.mt5.dry_run_bid = 3895.0
        self.cfg.mt5.dry_run_ask = 3895.3
        self.gateway = DynamicMT5Gateway(self.cfg)
        self.storage = OrderStorage(":memory:")
        self.service = CopierService(
            config=self.cfg,
            gateway=self.gateway,
            storage=self.storage,
        )
        self.gui = CopierGUI(
            root=self.root,
            service=self.service,
            gateway=self.gateway,
        )

    def tearDown(self):
        self.storage.close()
        self.root.destroy()

    def test_append_log_auto_scrolls_to_newest_message(self):
        for idx in range(40):
            self.gui._append_log(
                EventLevel.INFO,
                f"Test Log {idx}",
                f"Dòng nhật ký thứ {idx} để kiểm tra tự động cuộn xuống cuối.",
            )
        self.root.update_idletasks()
        _top, bottom = self.gui.txt_log.yview()
        self.assertAlmostEqual(bottom, 1.0, places=2)

    def test_delete_selected_and_delete_all_orders_on_gui(self):
        self.gui.txt_signal.delete("1.0", tk.END)
        self.gui.txt_signal.insert(tk.END, SAMPLE_TELEGRAM_MESSAGE)
        self.gui._on_execute_signal()

        items = self.gui.tree_orders.get_children()
        self.assertEqual(len(items), 4)

        # Select the first order and delete selected
        self.gui.tree_orders.selection_set(items[0])
        self.gui._on_delete_selected_orders()

        remaining_items = self.gui.tree_orders.get_children()
        self.assertEqual(len(remaining_items), 3)
        self.assertEqual(
            len(self.gateway.get_pending_orders(self.cfg.mt5.magic_number)),
            3,
        )

        # Delete all remaining orders
        self.gui._on_delete_all_orders()
        self.assertEqual(len(self.gui.tree_orders.get_children()), 0)
        self.assertEqual(
            self.gateway.get_pending_orders(self.cfg.mt5.magic_number),
            [],
        )
