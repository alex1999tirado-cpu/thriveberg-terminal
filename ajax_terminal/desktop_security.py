from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from ajax_terminal.utils.url_security import require_https_url


def open_external_url(value: object) -> bool:
    try:
        safe_url = require_https_url(str(value))
    except ValueError:
        return False
    return bool(QDesktopServices.openUrl(QUrl(safe_url)))


def open_local_path(value: object) -> bool:
    try:
        path = Path(str(value)).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
