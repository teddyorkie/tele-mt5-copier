from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
import time

from src.models import PlannedOrder


class OrderStorage:
    """Thread-safe SQLite storage for signal deduplication and order lifecycle tracking."""

    def __init__(self, db_path: str | Path = "copier.db") -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_signals (
                    signal_key TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_orders (
                    ticket INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    volume REAL NOT NULL,
                    limit_price REAL NOT NULL,
                    sl REAL NOT NULL,
                    tp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    breakeven_applied INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def is_signal_processed(self, source_id: str, message_id: str, fingerprint: str) -> bool:
        key = f"{source_id}:{message_id}:{fingerprint}"
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM processed_signals WHERE signal_key = ?", (key,)
            ).fetchone()
            return row is not None

    def record_processed_signal(
        self,
        source_id: str,
        message_id: str,
        fingerprint: str,
        now: float | None = None,
    ) -> None:
        key = f"{source_id}:{message_id}:{fingerprint}"
        ts = now if now is not None else time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO processed_signals
                (signal_key, source_id, message_id, fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, source_id, message_id, fingerprint, ts),
            )

    def record_placed_order(
        self,
        ticket: int,
        order: PlannedOrder,
        created_at: float | None = None,
    ) -> None:
        ts = created_at if created_at is not None else time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO tracked_orders
                (ticket, symbol, side, volume, limit_price, sl, tp, created_at, status, breakeven_applied)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0)
                """,
                (
                    ticket,
                    order.symbol,
                    order.side.value,
                    order.volume,
                    order.limit_price,
                    order.sl,
                    order.tp,
                    ts,
                ),
            )

    def get_order_created_at(self, ticket: int, fallback_time: float) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT created_at FROM tracked_orders WHERE ticket = ?", (ticket,)
            ).fetchone()
            return float(row["created_at"]) if row is not None else fallback_time

    def is_breakeven_applied(self, ticket: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT breakeven_applied FROM tracked_orders WHERE ticket = ?", (ticket,)
            ).fetchone()
            return bool(row["breakeven_applied"]) if row is not None else False

    def mark_breakeven_applied(self, ticket: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tracked_orders SET breakeven_applied = 1, status = 'OPEN_BE' WHERE ticket = ?",
                (ticket,),
            )

    def update_order_status(self, ticket: int, status: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tracked_orders SET status = ? WHERE ticket = ?",
                (status, ticket),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
