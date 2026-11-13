from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from src.models import TPMode


@dataclass
class TelegramConfig:
    """Configuration reserved for Phase 2 (Telegram Userbot)."""
    api_id: int = 0
    api_hash: str = ""
    session_name: str = "tele_copier_session"
    source_chat_ids: list[int] = field(default_factory=list)
    notify_chat: str = "me"


@dataclass
class MT5Config:
    terminal_path: str = ""
    magic_number: int = 20261113
    deviation_points: int = 20
    dry_run: bool = True
    dry_run_bid: float = 3895.0
    dry_run_ask: float = 3895.3
    symbol_map: dict[str, str] = field(
        default_factory=lambda: {"GOLD": "XAUUSD", "XAUUSD": "XAUUSD"}
    )

    def resolve_symbol(self, raw_symbol: str) -> str:
        key = raw_symbol.strip().upper()
        return self.symbol_map.get(key, key)


@dataclass
class StrategyConfig:
    lot_per_entry: float = 0.01
    early_entry_offset: float = 0.5
    tp_mode: TPMode = TPMode.SPLIT
    breakeven_trigger_price: float = 6.0
    pending_expiry_hours: float = 4.0
    max_sl_distance: float = 30.0
    poll_interval_seconds: float = 1.0

    def validate(self) -> None:
        if self.lot_per_entry <= 0:
            raise ValueError("lot_per_entry phải lớn hơn 0.")
        if not (0.0 <= self.early_entry_offset <= 5.0):
            raise ValueError("early_entry_offset phải nằm trong khoảng 0.0 đến 5.0 giá.")
        if self.breakeven_trigger_price <= 0:
            raise ValueError("breakeven_trigger_price phải lớn hơn 0.")
        if self.pending_expiry_hours <= 0:
            raise ValueError("pending_expiry_hours phải lớn hơn 0.")
        if self.max_sl_distance <= 0:
            raise ValueError("max_sl_distance phải lớn hơn 0.")


@dataclass
class AppConfig:
    mt5: MT5Config = field(default_factory=MT5Config)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    db_path: str = "copier.db"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        mt5_raw = data.get("mt5", {}) or {}
        strat_raw = dict(data.get("strategy", {}) or {})
        tele_raw = data.get("telegram", {}) or {}

        if "tp_mode" in strat_raw and not isinstance(strat_raw["tp_mode"], TPMode):
            strat_raw["tp_mode"] = TPMode(str(strat_raw["tp_mode"]).lower())

        mt5_cfg = MT5Config(**mt5_raw)
        strat_cfg = StrategyConfig(**strat_raw)
        strat_cfg.validate()
        tele_cfg = TelegramConfig(**tele_raw)
        db_path = str(data.get("db_path", "copier.db"))
        return cls(mt5=mt5_cfg, strategy=strat_cfg, telegram=tele_cfg, db_path=db_path)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["strategy"]["tp_mode"] = self.strategy.tp_mode.value
        return raw

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> AppConfig:
        cfg_path = Path(path)
        if not cfg_path.exists():
            cfg = cls()
            cfg.save(cfg_path)
            return cfg
        with cfg_path.open("r", encoding="utf-8") as f:
            text = f.read()
        if yaml is not None:
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text) if text.strip().startswith("{") else {}
        return cls.from_dict(data)

    def save(self, path: str | Path = "config.yaml") -> None:
        self.strategy.validate()
        cfg_path = Path(path)
        with cfg_path.open("w", encoding="utf-8") as f:
            if yaml is not None:
                yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)
            else:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
