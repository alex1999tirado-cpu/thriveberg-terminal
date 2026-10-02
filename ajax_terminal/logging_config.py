from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ajax_terminal.secure_settings import user_data_directory


def log_path() -> Path:
    return user_data_directory() / "logs" / "thriveberg.log"


def configure_logging() -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not any(getattr(handler, "_thriveberg_handler", False) for handler in root.handlers):
        handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler._thriveberg_handler = True
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    _install_exception_hooks()


def _install_exception_hooks() -> None:
    if getattr(_install_exception_hooks, "_installed", False):
        return
    original = sys.excepthook

    def exception_hook(exc_type, exc_value, exc_traceback) -> None:
        logging.getLogger("thriveberg.crash").critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )
        original(exc_type, exc_value, exc_traceback)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("thriveberg.crash").critical(
            "Unhandled thread exception in %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = exception_hook
    threading.excepthook = thread_hook
    _install_exception_hooks._installed = True
