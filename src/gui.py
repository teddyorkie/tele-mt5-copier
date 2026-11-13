from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from src.config import AppConfig
from src.models import (
    AppEvent,
    EventLevel,
    PlanStatus,
    SignalPlanResult,
    TPMode,
)
from src.mt5_client import DynamicMT5Gateway
from src.service import CopierService

DEFAULT_SAMPLE_SIGNAL = """\
SELL GOLD🍀🍀
3908 3913 SL 3920
TP 98 76

BUY GOLD🍀🍀
3881 3876 SL 3869
TP 92 15"""


class CopierGUI:
    """Desktop GUI for Phase 1: Signal Textbox Input, Preview, MT5 Limit Execution & Trade Monitoring."""

    def __init__(
        self,
        root: tk.Tk,
        service: CopierService,
        gateway: DynamicMT5Gateway,
        config_path: str = "config.yaml",
    ) -> None:
        self.root = root
        self.service = service
        self.gateway = gateway
        self.config_path = config_path

        self.root.title("MT5 Signal Copier - Giai đoạn 1 (Signal Textbox -> MT5 Limit & Auto BE)")
        self.root.geometry("1120x780")
        self.root.minsize(980, 680)

        self._init_variables()
        self._build_layout()
        self.service.subscribe(self._on_app_event)

        self._refresh_connection_status()
        self._schedule_background_loop()

    def _init_variables(self) -> None:
        cfg = self.service.config
        self.var_symbol = tk.StringVar(value=cfg.mt5.resolve_symbol("GOLD"))
        self.var_lot = tk.StringVar(value=f"{cfg.strategy.lot_per_entry:.2f}")
        self.var_offset = tk.StringVar(value=f"{cfg.strategy.early_entry_offset:.1f}")
        self.var_tp_mode = tk.StringVar(value=cfg.strategy.tp_mode.value)
        self.var_be_price = tk.StringVar(value=f"{cfg.strategy.breakeven_trigger_price:.1f}")
        self.var_expiry_hours = tk.StringVar(value=f"{cfg.strategy.pending_expiry_hours:.1f}")
        self.var_dry_run = tk.BooleanVar(value=cfg.mt5.dry_run)
        self.var_sim_bid = tk.StringVar(value=f"{cfg.mt5.dry_run_bid:.2f}")
        self.var_status = tk.StringVar(value="Đang khởi tạo...")
        self.var_market_price = tk.StringVar(value="Bid: -- | Ask: --")

    def _build_layout(self) -> None:
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Top Status & Settings Panel
        settings_box = ttk.LabelFrame(
            main_frame, text="1. Cấu hình Chiến lược & Kết nối MT5", padding=8
        )
        settings_box.pack(fill=tk.X, pady=(0, 8))

        row1 = ttk.Frame(settings_box)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="Mã GOLD sàn MT5:").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.var_symbol, width=10).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(row1, text="Vol mỗi lệnh (Lot):").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.var_lot, width=7).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(row1, text="Vào sớm (Offset giá):").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.var_offset, width=6).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(row1, text="Chế độ TP:").pack(side=tk.LEFT)
        tp_combo = ttk.Combobox(
            row1,
            textvariable=self.var_tp_mode,
            values=[m.value for m in TPMode],
            width=8,
            state="readonly",
        )
        tp_combo.pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(row1, text="Dời SL Hòa vốn (+giá):").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.var_be_price, width=6).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(row1, text="Hủy lệnh chờ (giờ):").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.var_expiry_hours, width=6).pack(
            side=tk.LEFT, padx=(4, 12)
        )

        ttk.Button(row1, text="Lưu Cấu hình", command=self._on_save_config).pack(
            side=tk.RIGHT, padx=4
        )

        row2 = ttk.Frame(settings_box)
        row2.pack(fill=tk.X, pady=(6, 2))

        ttk.Checkbutton(
            row2,
            text="Chế độ Giả lập (Dry-Run - Không gửi lệnh thật)",
            variable=self.var_dry_run,
            command=self._on_toggle_dry_run,
        ).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(row2, text="Giá Bid giả lập (Dry-Run):").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.var_sim_bid, width=9).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            row2, text="Cập nhật giá giả lập", command=self._on_update_simulated_price
        ).pack(side=tk.LEFT, padx=(2, 14))

        ttk.Button(row2, text="Kết nối lại MT5", command=self._refresh_connection_status).pack(
            side=tk.LEFT
        )

        ttk.Label(
            row2, textvariable=self.var_market_price, font=("Segoe UI", 10, "bold")
        ).pack(side=tk.RIGHT, padx=8)
        ttk.Label(row2, textvariable=self.var_status, foreground="#0055aa").pack(
            side=tk.RIGHT, padx=8
        )

        # 2. Middle Split: Left = Signal Input Textbox, Right = Active Orders & Positions
        middle_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        middle_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        left_box = ttk.LabelFrame(
            middle_pane, text="2. Nhập Tin nhắn Tín hiệu (Signal Textbox)", padding=8
        )
        middle_pane.add(left_box, weight=2)

        self.txt_signal = scrolledtext.ScrolledText(
            left_box, height=11, font=("Consolas", 11), wrap=tk.WORD
        )
        self.txt_signal.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.txt_signal.insert(tk.END, DEFAULT_SAMPLE_SIGNAL)

        btn_bar = ttk.Frame(left_box)
        btn_bar.pack(fill=tk.X)

        ttk.Button(btn_bar, text="Điền mẫu thử", command=self._on_fill_sample).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(btn_bar, text="Xóa trắng", command=self._on_clear_input).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Button(
            btn_bar,
            text="1. Xem trước (Preview Parse)",
            command=self._on_preview_signal,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_bar,
            text="2. ĐẶT LỆNH LIMIT VÀO MT5",
            command=self._on_execute_signal,
        ).pack(side=tk.RIGHT, padx=4)

        right_box = ttk.LabelFrame(
            middle_pane,
            text="3. Lệnh Chờ Limit & Vị thế Đang Mở (Tự động dời SL +6 giá & Hủy sau 4h)",
            padding=8,
        )
        middle_pane.add(right_box, weight=3)

        columns = ("ticket", "kind", "symbol", "side", "vol", "price", "sl", "tp", "note")
        self.tree_orders = ttk.Treeview(
            right_box, columns=columns, show="headings", height=10
        )
        headers = {
            "ticket": ("Ticket", 70),
            "kind": ("Trạng thái", 85),
            "symbol": ("Symbol", 75),
            "side": ("Chiều", 55),
            "vol": ("Lot", 55),
            "price": ("Giá Vào/Limit", 95),
            "sl": ("SL", 80),
            "tp": ("TP", 80),
            "note": ("Ghi chú", 130),
        }
        for col, (label, width) in headers.items():
            self.tree_orders.heading(col, text=label)
            self.tree_orders.column(col, width=width, anchor=tk.CENTER)
        self.tree_orders.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        order_btn_bar = ttk.Frame(right_box)
        order_btn_bar.pack(fill=tk.X)
        ttk.Button(
            order_btn_bar,
            text="Làm mới danh sách",
            command=self._refresh_orders_table,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            order_btn_bar,
            text="Xóa lệnh đã chọn",
            command=self._on_delete_selected_orders,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            order_btn_bar,
            text="Xóa tất cả lệnh",
            command=self._on_delete_all_orders,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            order_btn_bar,
            text="Giả lập trôi qua 4 giờ (Test tự hủy)",
            command=self._on_simulate_four_hours_elapsed,
        ).pack(side=tk.RIGHT)

        # 3. Bottom Log & Alert View
        log_box = ttk.LabelFrame(
            main_frame, text="4. Nhật ký Hoạt động & Cảnh báo (Logs / Alerts)", padding=8
        )
        log_box.pack(fill=tk.BOTH, expand=True)

        self.txt_log = scrolledtext.ScrolledText(
            log_box, height=11, font=("Consolas", 10), state=tk.DISABLED, wrap=tk.WORD
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        self.txt_log.tag_config("INFO", foreground="#004085")
        self.txt_log.tag_config("SUCCESS", foreground="#155724")
        self.txt_log.tag_config("WARNING", foreground="#b35900")
        self.txt_log.tag_config("ERROR", foreground="#a71d2a")

    def _apply_ui_settings_to_config(self) -> bool:
        try:
            cfg = self.service.config
            symbol = self.var_symbol.get().strip().upper() or "XAUUSD"
            cfg.mt5.symbol_map["GOLD"] = symbol
            cfg.mt5.symbol_map["XAUUSD"] = symbol
            cfg.mt5.dry_run = bool(self.var_dry_run.get())
            cfg.mt5.dry_run_bid = float(self.var_sim_bid.get().strip())
            cfg.mt5.dry_run_ask = round(cfg.mt5.dry_run_bid + 0.3, 5)

            cfg.strategy.lot_per_entry = float(self.var_lot.get().strip())
            cfg.strategy.early_entry_offset = float(self.var_offset.get().strip())
            cfg.strategy.tp_mode = TPMode(self.var_tp_mode.get().strip())
            cfg.strategy.breakeven_trigger_price = float(self.var_be_price.get().strip())
            cfg.strategy.pending_expiry_hours = float(self.var_expiry_hours.get().strip())
            cfg.strategy.validate()
            return True
        except ValueError as exc:
            messagebox.showerror("Lỗi cấu hình", str(exc))
            return False

    def _on_save_config(self) -> None:
        if not self._apply_ui_settings_to_config():
            return
        self.service.config.save(self.config_path)
        self._append_log(
            EventLevel.INFO,
            "Lưu cấu hình",
            f"Đã lưu cấu hình vào {self.config_path} thành công.",
        )

    def _on_toggle_dry_run(self) -> None:
        if not self._apply_ui_settings_to_config():
            return
        self._refresh_connection_status()

    def _on_update_simulated_price(self) -> None:
        if not self._apply_ui_settings_to_config():
            return
        bid = self.service.config.mt5.dry_run_bid
        self.gateway.simulator.set_simulated_price(bid)
        self._update_market_price_label()
        self.service.run_trade_manager_step()
        self._refresh_orders_table()
        self._append_log(
            EventLevel.INFO,
            "Giá giả lập Dry-Run",
            f"Đã cập nhật giá giả lập: Bid = {bid:.2f}, Ask = {bid + 0.3:.2f}",
        )

    def _refresh_connection_status(self) -> None:
        ok, msg = self.gateway.connect()
        mode_tag = "[DRY-RUN]" if self.service.config.mt5.dry_run else "[MT5 LIVE/DEMO]"
        self.var_status.set(f"{mode_tag} {msg}")
        self._update_market_price_label()
        self._refresh_orders_table()
        level = EventLevel.INFO if ok else EventLevel.ERROR
        self._append_log(level, "Kết nối MT5", f"{mode_tag} {msg}")

    def _update_market_price_label(self) -> None:
        symbol = self.service.config.mt5.resolve_symbol("GOLD")
        tick = self.gateway.get_tick(symbol)
        if tick is not None:
            self.var_market_price.set(f"{symbol} -> Bid: {tick.bid:.2f} | Ask: {tick.ask:.2f}")
        else:
            self.var_market_price.set(f"{symbol} -> Bid: -- | Ask: --")

    def _on_fill_sample(self) -> None:
        self.txt_signal.delete("1.0", tk.END)
        self.txt_signal.insert(tk.END, DEFAULT_SAMPLE_SIGNAL)

    def _on_clear_input(self) -> None:
        self.txt_signal.delete("1.0", tk.END)

    def _format_plan_summary(self, res: SignalPlanResult) -> str:
        sig = res.signal
        header = (
            f"Kèo {sig.side.value} {res.symbol} | Vùng gốc: {sig.entries} | "
            f"SL: {sig.sl} | TP quy đổi: {sig.tps}"
        )
        if res.status is PlanStatus.READY:
            lines = [f"[HỢP LỆ] {header}"]
            for o in res.orders:
                lines.append(
                    f"   -> Lệnh {o.entry_index}: {o.order_kind.value} {o.volume} lot @ {o.limit_price} "
                    f"(gốc {o.raw_entry_price}, bù sớm {self.service.config.strategy.early_entry_offset:g}) | "
                    f"SL: {o.sl} | TP: {o.tp}"
                )
            return "\n".join(lines)
        return f"[{res.status.value}] {header}\n   -> Lý do: {res.reason}"

    def _on_preview_signal(self) -> None:
        if not self._apply_ui_settings_to_config():
            return
        raw_text = self.txt_signal.get("1.0", tk.END)
        results = self.service.preview_message(raw_text)
        for res in results:
            level = (
                EventLevel.INFO
                if res.status is PlanStatus.READY
                else (
                    EventLevel.WARNING
                    if res.status is PlanStatus.SKIPPED_PRICE_IN_ZONE
                    else EventLevel.ERROR
                )
            )
            self._append_log(level, "Xem trước (Preview)", self._format_plan_summary(res))

    def _on_execute_signal(self) -> None:
        if not self._apply_ui_settings_to_config():
            return
        raw_text = self.txt_signal.get("1.0", tk.END)
        self.service.process_message(raw_text, source_id="gui", allow_duplicate=True)
        self._refresh_orders_table()

    def _on_simulate_four_hours_elapsed(self) -> None:
        future_ts = datetime.now().timestamp() + (
            self.service.config.strategy.pending_expiry_hours * 3600.0 + 5.0
        )
        events = self.service.run_trade_manager_step(now=future_ts)
        self._refresh_orders_table()
        if not events:
            self._append_log(
                EventLevel.INFO,
                "Kiểm tra quá hạn 4h",
                "Không có lệnh chờ nào cần hủy.",
            )

    def _on_delete_selected_orders(self) -> None:
        selected_items = self.tree_orders.selection()
        if not selected_items:
            self._append_log(
                EventLevel.WARNING,
                "Xóa lệnh",
                "Vui lòng chọn ít nhất 1 lệnh trong danh sách để xóa.",
            )
            return

        for item_id in selected_items:
            values = self.tree_orders.item(item_id, "values")
            if not values:
                continue
            ticket = int(values[0])
            self.service.cancel_order(ticket)

        self._refresh_orders_table()

    def _on_delete_all_orders(self) -> None:
        removed = self.service.cancel_all_orders()
        self._refresh_orders_table()
        if removed == 0:
            self._append_log(
                EventLevel.INFO,
                "Xóa tất cả lệnh",
                "Hiện không có lệnh nào trong danh sách để xóa.",
            )

    def _refresh_orders_table(self) -> None:
        for item in self.tree_orders.get_children():
            self.tree_orders.delete(item)

        magic = self.service.config.mt5.magic_number
        for pos in self.gateway.get_open_positions(magic):
            be_done = pos.side.is_sl_at_or_better_than_entry(pos.sl, pos.price_open)
            note = "Đã dời SL Hòa vốn" if be_done else pos.comment
            self.tree_orders.insert(
                "",
                tk.END,
                values=(
                    pos.ticket,
                    "ĐANG MỞ",
                    pos.symbol,
                    pos.side.value,
                    f"{pos.volume:.2f}",
                    f"{pos.price_open:.2f}",
                    f"{pos.sl:.2f}",
                    f"{pos.tp:.2f}",
                    note,
                ),
            )
        for order in self.gateway.get_pending_orders(magic):
            self.tree_orders.insert(
                "",
                tk.END,
                values=(
                    order.ticket,
                    "CHỜ LIMIT",
                    order.symbol,
                    order.side.value,
                    f"{order.volume:.2f}",
                    f"{order.price_open:.2f}",
                    f"{order.sl:.2f}",
                    f"{order.tp:.2f}",
                    order.comment,
                ),
            )

    def _on_app_event(self, event: AppEvent) -> None:
        self._append_log(event.level, event.title, event.message)

    def _append_log(self, level: EventLevel, title: str, message: str) -> None:
        ts_str = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts_str}] [{level.value}] {title}: {message}\n"
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.insert(tk.END, line, level.value)
        self.txt_log.configure(state=tk.DISABLED)
        self.txt_log.update_idletasks()
        self.txt_log.see(tk.END)
        self.txt_log.yview_moveto(1.0)

    def _schedule_background_loop(self) -> None:
        self._update_market_price_label()
        events = self.service.run_trade_manager_step()
        if events:
            self._refresh_orders_table()
        interval_ms = max(500, int(self.service.config.strategy.poll_interval_seconds * 1000))
        self.root.after(interval_ms, self._schedule_background_loop)
