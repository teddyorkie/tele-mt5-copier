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

    # Sleek Dark Trader Terminal Palette
    BG_ROOT = "#0b0f19"
    BG_PANEL = "#111827"
    BG_INPUT = "#090d16"
    BG_BUTTON = "#1e293b"
    BG_BUTTON_HOVER = "#334155"
    FG_PRIMARY = "#e2e8f0"
    FG_MUTED = "#94a3b8"
    ACCENT_CYAN = "#38bdf8"
    ACCENT_GOLD = "#fbbf24"
    ACCENT_GREEN = "#10b981"
    ACCENT_GREEN_HOVER = "#059669"
    ACCENT_BLUE = "#0284c7"
    ACCENT_BLUE_HOVER = "#0369a1"
    ACCENT_RED = "#e11d48"
    ACCENT_RED_HOVER = "#be123c"

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
        self._after_id: str | None = None

        self.root.title("MT5 SIGNAL COPIER PRO — TERMINAL GIAO DỊCH TỰ ĐỘNG")
        self.root.geometry("1160x760")
        self.root.minsize(1000, 660)
        self.root.configure(bg=self.BG_ROOT)

        self._configure_trader_theme()
        self._init_variables()
        self._build_layout()
        self.service.subscribe(self._on_app_event)

        self._refresh_connection_status()
        self._schedule_background_loop()

    def _configure_trader_theme(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure(".", background=self.BG_PANEL, foreground=self.FG_PRIMARY, font=("Segoe UI", 9))
        style.configure("TFrame", background=self.BG_PANEL)
        style.configure("Root.TFrame", background=self.BG_ROOT)
        style.configure("TPanedwindow", background=self.BG_ROOT)

        style.configure(
            "TLabelframe",
            background=self.BG_PANEL,
            foreground=self.ACCENT_CYAN,
            bordercolor="#1e293b",
            lightcolor="#1e293b",
            darkcolor="#1e293b",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=self.BG_PANEL,
            foreground=self.ACCENT_CYAN,
            font=("Segoe UI", 9, "bold"),
        )

        style.configure("TLabel", background=self.BG_PANEL, foreground=self.FG_PRIMARY)
        style.configure("Muted.TLabel", background=self.BG_PANEL, foreground=self.FG_MUTED)
        style.configure(
            "Ticker.TLabel",
            background="#090d16",
            foreground="#34d399",
            font=("Consolas", 10, "bold"),
            padding=(8, 3),
        )
        style.configure(
            "Status.TLabel",
            background=self.BG_PANEL,
            foreground=self.ACCENT_CYAN,
            font=("Segoe UI", 9, "bold"),
        )

        style.configure(
            "TEntry",
            fieldbackground=self.BG_INPUT,
            foreground="#f8fafc",
            insertcolor=self.ACCENT_CYAN,
            bordercolor="#334155",
            lightcolor="#334155",
            darkcolor="#334155",
            padding=4,
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.BG_INPUT,
            background=self.BG_BUTTON,
            foreground="#f8fafc",
            arrowcolor=self.ACCENT_CYAN,
            padding=3,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.BG_INPUT)],
            foreground=[("readonly", "#f8fafc")],
            selectbackground=[("readonly", self.BG_INPUT)],
            selectforeground=[("readonly", self.ACCENT_CYAN)],
        )

        style.configure(
            "DryRun.TCheckbutton",
            background=self.BG_PANEL,
            foreground=self.ACCENT_GOLD,
            indicatorbackground=self.BG_INPUT,
            indicatorforeground=self.ACCENT_GOLD,
            font=("Segoe UI", 9, "bold"),
            padding=(4, 2),
        )
        style.map(
            "DryRun.TCheckbutton",
            background=[("active", self.BG_PANEL)],
            foreground=[("active", "#fde047")],
        )

        # Trader Action Buttons
        style.configure(
            "Secondary.TButton",
            background=self.BG_BUTTON,
            foreground=self.FG_PRIMARY,
            bordercolor="#334155",
            focusthickness=0,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 4),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", self.BG_BUTTON_HOVER), ("pressed", "#475569")],
            foreground=[("active", "#ffffff")],
        )

        style.configure(
            "Accent.TButton",
            background=self.ACCENT_BLUE,
            foreground="#ffffff",
            bordercolor=self.ACCENT_BLUE,
            focusthickness=0,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 4),
        )
        style.map(
            "Accent.TButton",
            background=[("active", self.ACCENT_BLUE_HOVER), ("pressed", "#075985")],
            foreground=[("active", "#ffffff")],
        )

        style.configure(
            "Execute.TButton",
            background=self.ACCENT_GREEN,
            foreground="#ffffff",
            bordercolor=self.ACCENT_GREEN,
            focusthickness=0,
            font=("Segoe UI", 10, "bold"),
            padding=(12, 6),
        )
        style.map(
            "Execute.TButton",
            background=[("active", self.ACCENT_GREEN_HOVER), ("pressed", "#047857")],
            foreground=[("active", "#ffffff")],
        )

        style.configure(
            "Danger.TButton",
            background=self.ACCENT_RED,
            foreground="#ffffff",
            bordercolor=self.ACCENT_RED,
            focusthickness=0,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 4),
        )
        style.map(
            "Danger.TButton",
            background=[("active", self.ACCENT_RED_HOVER), ("pressed", "#9f1239")],
            foreground=[("active", "#ffffff")],
        )

        # Treeview Trader Table
        style.configure(
            "Treeview",
            background=self.BG_INPUT,
            fieldbackground=self.BG_INPUT,
            foreground=self.FG_PRIMARY,
            rowheight=25,
            bordercolor="#1e293b",
            font=("Consolas", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#1e293b",
            foreground=self.ACCENT_CYAN,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padding=(4, 5),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#334155")],
        )
        style.map(
            "Treeview",
            background=[("selected", "#1d4ed8")],
            foreground=[("selected", "#ffffff")],
        )

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
        main_frame = ttk.Frame(self.root, style="Root.TFrame", padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Top Status & Settings Panel (3 Sleek Rows, DRY-RUN in CAPITAL CASE on Row 1)
        settings_box = ttk.LabelFrame(
            main_frame, text="⚡ 1. CẤU HÌNH CHIẾN LƯỢC & KẾT NỐI MT5", padding=(10, 6)
        )
        settings_box.pack(fill=tk.X, pady=(0, 8))

        # Row 1: DRY-RUN (CAPITAL CASE) on top + Reconnect + Live Market Price & Status
        row1 = ttk.Frame(settings_box)
        row1.pack(fill=tk.X, pady=(2, 4))

        self.chk_dry_run = ttk.Checkbutton(
            row1,
            text="CHẾ ĐỘ GIẢ LẬP (DRY-RUN - KHÔNG GỬI LỆNH THẬT)",
            variable=self.var_dry_run,
            command=self._on_toggle_dry_run,
            style="DryRun.TCheckbutton",
        )
        self.chk_dry_run.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Button(
            row1,
            text="⟳ KẾT NỐI LẠI MT5",
            command=self._refresh_connection_status,
            style="Secondary.TButton",
        ).pack(side=tk.LEFT, padx=4)

        ttk.Label(
            row1, textvariable=self.var_market_price, style="Ticker.TLabel"
        ).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(
            row1, textvariable=self.var_status, style="Status.TLabel"
        ).pack(side=tk.RIGHT, padx=8)

        # Row 2: Core Strategy Parameters + Save Config Button
        row2 = ttk.Frame(settings_box)
        row2.pack(fill=tk.X, pady=4)

        ttk.Label(row2, text="SYMBOL MT5:", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.var_symbol, width=9, font=("Consolas", 9, "bold")).pack(
            side=tk.LEFT, padx=(4, 12)
        )

        ttk.Label(row2, text="VOL (LOT):", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.var_lot, width=6, font=("Consolas", 9, "bold")).pack(
            side=tk.LEFT, padx=(4, 12)
        )

        ttk.Label(row2, text="OFFSET VÀO SỚM:", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.var_offset, width=5, font=("Consolas", 9, "bold")).pack(
            side=tk.LEFT, padx=(4, 12)
        )

        ttk.Label(row2, text="CHẾ ĐỘ TP:", style="Muted.TLabel").pack(side=tk.LEFT)
        tp_combo = ttk.Combobox(
            row2,
            textvariable=self.var_tp_mode,
            values=[m.value for m in TPMode],
            width=7,
            state="readonly",
            font=("Consolas", 9, "bold"),
        )
        tp_combo.pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(row2, text="BE (+GIÁ):", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.var_be_price, width=5, font=("Consolas", 9, "bold")).pack(
            side=tk.LEFT, padx=(4, 12)
        )

        ttk.Label(row2, text="HỦY CHỜ (GIỜ):", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(
            row2, textvariable=self.var_expiry_hours, width=5, font=("Consolas", 9, "bold")
        ).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Button(
            row2,
            text="💾 LƯU CẤU HÌNH",
            command=self._on_save_config,
            style="Accent.TButton",
        ).pack(side=tk.RIGHT, padx=2)

        # Row 3: Dry-Run Price Simulator & Expiry Test Controls
        row3 = ttk.Frame(settings_box)
        row3.pack(fill=tk.X, pady=(4, 2))

        ttk.Label(row3, text="GIÁ BID GIẢ LẬP (DRY-RUN):", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self.var_sim_bid, width=9, font=("Consolas", 9, "bold")).pack(
            side=tk.LEFT, padx=(6, 8)
        )
        ttk.Button(
            row3,
            text="⚡ CẬP NHẬT GIÁ GIẢ LẬP",
            command=self._on_update_simulated_price,
            style="Secondary.TButton",
        ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Button(
            row3,
            text="⏱ GIẢ LẬP TRÔI QUA 4 GIỜ (TEST TỰ HỦY)",
            command=self._on_simulate_four_hours_elapsed,
            style="Secondary.TButton",
        ).pack(side=tk.RIGHT, padx=2)

        self.config_rows = (row1, row2, row3)

        # 2. Middle Split: Left = Compact Signal Input Textbox, Right = Active Orders & Positions
        middle_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        middle_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        left_box = ttk.LabelFrame(
            middle_pane, text="📡 2. TÍN HIỆU (SIGNAL INPUT)", padding=8
        )
        middle_pane.add(left_box, weight=1)

        self.txt_signal = scrolledtext.ScrolledText(
            left_box,
            width=32,
            height=6,
            font=("Consolas", 10),
            wrap=tk.WORD,
            bg=self.BG_INPUT,
            fg="#f8fafc",
            insertbackground=self.ACCENT_CYAN,
            selectbackground="#1d4ed8",
            relief=tk.FLAT,
            padx=6,
            pady=6,
        )
        self.txt_signal.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.txt_signal.insert(tk.END, DEFAULT_SAMPLE_SIGNAL)

        btn_bar_top = ttk.Frame(left_box)
        btn_bar_top.pack(fill=tk.X, pady=(0, 4))

        ttk.Button(
            btn_bar_top,
            text="Mẫu thử",
            command=self._on_fill_sample,
            style="Secondary.TButton",
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            btn_bar_top,
            text="Xóa",
            command=self._on_clear_input,
            style="Secondary.TButton",
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            btn_bar_top,
            text="🔍 1. XEM TRƯỚC (PREVIEW)",
            command=self._on_preview_signal,
            style="Accent.TButton",
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True)

        btn_bar_bottom = ttk.Frame(left_box)
        btn_bar_bottom.pack(fill=tk.X)
        ttk.Button(
            btn_bar_bottom,
            text="🚀 2. ĐẶT LỆNH LIMIT VÀO MT5",
            command=self._on_execute_signal,
            style="Execute.TButton",
        ).pack(fill=tk.X, expand=True)

        right_box = ttk.LabelFrame(
            middle_pane,
            text="📊 3. LỆNH CHỜ LIMIT & VỊ THẾ ĐANG MỞ (AUTO BE +6 GIÁ & HỦY SAU 4H)",
            padding=8,
        )
        middle_pane.add(right_box, weight=3)

        columns = ("ticket", "kind", "symbol", "side", "vol", "price", "sl", "tp", "note")
        self.tree_orders = ttk.Treeview(
            right_box, columns=columns, show="headings", height=7
        )
        headers = {
            "ticket": ("TICKET", 70),
            "kind": ("TRẠNG THÁI", 90),
            "symbol": ("SYMBOL", 75),
            "side": ("CHIỀU", 60),
            "vol": ("LOT", 55),
            "price": ("GIÁ VÀO/LIMIT", 100),
            "sl": ("SL", 80),
            "tp": ("TP", 80),
            "note": ("GHI CHÚ", 140),
        }
        for col, (label, width) in headers.items():
            self.tree_orders.heading(col, text=label)
            self.tree_orders.column(col, width=width, anchor=tk.CENTER)
        self.tree_orders.tag_configure("BUY", foreground="#34d399")
        self.tree_orders.tag_configure("SELL", foreground="#f87171")
        self.tree_orders.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        order_btn_bar = ttk.Frame(right_box)
        order_btn_bar.pack(fill=tk.X)
        ttk.Button(
            order_btn_bar,
            text="⟳ LÀM MỚI DANH SÁCH",
            command=self._refresh_orders_table,
            style="Secondary.TButton",
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            order_btn_bar,
            text="✖ XÓA LỆNH ĐÃ CHỌN",
            command=self._on_delete_selected_orders,
            style="Danger.TButton",
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            order_btn_bar,
            text="🗑 XÓA TẤT CẢ LỆNH",
            command=self._on_delete_all_orders,
            style="Danger.TButton",
        ).pack(side=tk.LEFT, padx=(0, 6))

        # 3. Bottom Log & Alert View
        log_box = ttk.LabelFrame(
            main_frame, text="🖥 4. NHẬT KÝ HOẠT ĐỘNG & CẢNH BÁO (TERMINAL LOGS)", padding=8
        )
        log_box.pack(fill=tk.BOTH, expand=True)

        self.txt_log = scrolledtext.ScrolledText(
            log_box,
            height=10,
            font=("Consolas", 10),
            state=tk.DISABLED,
            wrap=tk.WORD,
            bg=self.BG_INPUT,
            fg=self.FG_PRIMARY,
            insertbackground=self.ACCENT_CYAN,
            relief=tk.FLAT,
            padx=6,
            pady=6,
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        self.txt_log.tag_config("INFO", foreground="#38bdf8")
        self.txt_log.tag_config("SUCCESS", foreground="#34d399")
        self.txt_log.tag_config("WARNING", foreground="#fbbf24")
        self.txt_log.tag_config("ERROR", foreground="#fb7185")

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
                tags=(pos.side.value,),
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
                tags=(order.side.value,),
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
        self._after_id = self.root.after(interval_ms, self._schedule_background_loop)
