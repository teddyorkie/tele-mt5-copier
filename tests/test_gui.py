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
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        for child in list(self.root.winfo_children()):
            child.destroy()
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
        if self.gui._after_id is not None:
            try:
                self.root.after_cancel(self.gui._after_id)
            except tk.TclError:
                pass
        self.storage.close()

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

    def test_trader_ui_layout_three_config_rows_uppercase_dry_run_and_compact_signal_box(self):
        self.assertEqual(len(self.gui.config_rows), 3)
        dry_run_text = self.gui.chk_dry_run.cget("text")
        self.assertIn("DRY-RUN", dry_run_text)
        self.assertEqual(dry_run_text, dry_run_text.upper())
        self.assertEqual(
            self.gui.chk_dry_run.nametowidget(self.gui.chk_dry_run.winfo_parent()),
            self.gui.config_rows[0],
        )
        self.assertLessEqual(int(self.gui.txt_signal.cget("height")), 7)
        self.assertLessEqual(int(self.gui.txt_signal.cget("width")), 38)

