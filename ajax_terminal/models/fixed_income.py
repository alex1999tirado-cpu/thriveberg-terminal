from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ajax_terminal.models.quote import DataQuality


@dataclass(slots=True)
class CreditBenchmark:
    symbol: str
    name: str
    rating: str
    effective_yield_pct: float | None = None
    yield_change_bp: float | None = None
    oas_bp: float | None = None
    oas_change_bp: float | None = None
    provider: str = "UNKNOWN"
    quality: DataQuality = DataQuality.UNAVAILABLE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
