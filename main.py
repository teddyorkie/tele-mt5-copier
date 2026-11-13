from __future__ import annotations

from pathlib import Path
import tkinter as tk

from src.config import AppConfig
from src.gui import CopierGUI
from src.mt5_client import DynamicMT5Gateway
from src.service import CopierService
from src.storage import OrderStorage

BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    config_path = BASE_DIR / "config.yaml"
    config = AppConfig.load(config_path)
    db_path = Path(config.db_path)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    gateway = DynamicMT5Gateway(config)
    storage = OrderStorage(db_path)
    service = CopierService(config=config, gateway=gateway, storage=storage)

    root = tk.Tk()
    _app = CopierGUI(
        root=root,
        service=service,
        gateway=gateway,
        config_path=str(config_path),
    )
    try:
        root.mainloop()
    finally:
        gateway.shutdown()
        storage.close()


if __name__ == "__main__":
    main()
