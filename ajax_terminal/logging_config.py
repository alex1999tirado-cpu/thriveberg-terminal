from __future__ import annotations

import logging
from pathlib import Path


def configure_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler("logs/ajax.log", encoding="utf-8"),
        ],
    )
