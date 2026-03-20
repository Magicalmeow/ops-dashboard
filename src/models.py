"""Core dataclasses for the ops dashboard."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ProjectMetrics:
    """Metrics collected from a single project."""
    project_name: str
    collector_type: str  # "trading_weather", "trading_mm", etc.
    collected_at: datetime = field(default_factory=datetime.utcnow)
    healthy: bool = True
    error: Optional[str] = None

    # Trading metrics (populated for trading collectors)
    trades: int = 0
    pnl: float = 0.0
    win_rate: Optional[float] = None
    signals: int = 0
    fills: int = 0
    exposure_pct: float = 0.0
    open_positions: int = 0
    return_pct: float = 0.0

    # Git metrics (populated for git collectors)
    last_commit_date: Optional[datetime] = None
    last_commit_message: Optional[str] = None
    branch: Optional[str] = None
    handoff_summary: Optional[str] = None

    # Status text (for non-metric summaries)
    status_text: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize for JSONL history."""
        d = {
            "project_name": self.project_name,
            "collector_type": self.collector_type,
            "collected_at": self.collected_at.isoformat(),
            "healthy": self.healthy,
            "error": self.error,
            "trades": self.trades,
            "pnl": round(self.pnl, 2),
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "signals": self.signals,
            "fills": self.fills,
            "exposure_pct": round(self.exposure_pct, 2),
            "open_positions": self.open_positions,
            "return_pct": round(self.return_pct, 2),
        }
        if self.last_commit_date:
            d["last_commit_date"] = self.last_commit_date.isoformat()
        if self.last_commit_message:
            d["last_commit_message"] = self.last_commit_message
        return d


@dataclass
class Alert:
    """A blocker or nag alert for a project."""
    project_name: str
    alert_type: str  # "no_trades", "stale_pnl", "no_commits"
    days_stuck: int
    message: str


@dataclass
class DailyReport:
    """The full daily status report."""
    generated_at: datetime
    project_metrics: list  # List[ProjectMetrics]
    alerts: list  # List[Alert]
    scorecard: str = ""  # Formatted text for Telegram
