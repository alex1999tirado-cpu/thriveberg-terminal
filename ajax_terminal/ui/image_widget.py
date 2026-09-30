from __future__ import annotations

from textual.widgets import Static


try:
    from textual_image.widget import Image as Image
except Exception:  # textual-image probes stdout during import and requires a live TTY.
    class Image(Static):
        """Import-safe placeholder used by the native Qt desktop executable."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__("", *args, **kwargs)
            self._image = None

        @property
        def image(self):
            return self._image

        @image.setter
        def image(self, value) -> None:
            self._image = value
            self.update("" if value is None else "[dim]OPEN THE NATIVE CHART VIEW[/]")
