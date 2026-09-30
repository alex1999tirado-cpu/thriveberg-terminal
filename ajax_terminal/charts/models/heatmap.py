from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HeatmapChart:
    title: str
    x_labels: list[str]
    y_labels: list[str]
    values: list[tuple[int, int, float | None]]
    unit: str = ""
