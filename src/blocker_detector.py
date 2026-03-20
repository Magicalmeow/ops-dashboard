"""Blocker detection engine.

Compares current metrics against history to detect stagnation.
Produces nagging alerts when projects are stuck.
"""

import json
import os
from datetime import datetime, timedelta

from src.models import Alert, ProjectMetrics


class BlockerDetector:

    def __init__(self, history_path: str, thresholds: dict):
        self.history_path = history_path
        self.no_trades_hours = thresholds.get("no_trades_hours", 48)
        self.stale_pnl_days = thresholds.get("stale_pnl_days", 3)
        self.no_commits_days = thresholds.get("no_commits_days", 5)

    def detect(self, current_metrics: list[ProjectMetrics]) -> list[Alert]:
        """Check all projects for blockers. Returns alerts."""
        history = self._load_history()
        alerts = []

        for metrics in current_metrics:
            if metrics.error:
                alerts.append(Alert(
                    project_name=metrics.project_name,
                    alert_type="collector_error",
                    days_stuck=0,
                    message=f"Collector error: {metrics.error}",
                ))
                continue

            project_history = [
                h for h in history
                if h.get("project_name") == metrics.project_name
            ]

            if metrics.collector_type.startswith("trading_"):
                alerts.extend(self._check_trading(metrics, project_history))
            elif metrics.collector_type == "git":
                alerts.extend(self._check_git(metrics))

        # Append current metrics to history
        self._append_history(current_metrics)

        return alerts

    def _check_trading(self, metrics: ProjectMetrics, history: list[dict]) -> list[Alert]:
        """Check trading project for no-trades and stale-P&L."""
        alerts = []

        # No trades check
        if metrics.trades == 0 and metrics.open_positions == 0:
            # Count how many consecutive days with 0 trades
            days_stuck = self._count_consecutive_zero_trades(history)
            if days_stuck * 24 >= self.no_trades_hours:
                alerts.append(Alert(
                    project_name=metrics.project_name,
                    alert_type="no_trades",
                    days_stuck=days_stuck,
                    message=f"0 trades for {days_stuck}d. Check if strategy is running on VPS.",
                ))

        # Stale P&L check
        if history:
            days_same_pnl = self._count_days_same_pnl(metrics.pnl, history)
            if days_same_pnl >= self.stale_pnl_days and metrics.trades == 0:
                alerts.append(Alert(
                    project_name=metrics.project_name,
                    alert_type="stale_pnl",
                    days_stuck=days_same_pnl,
                    message=f"P&L unchanged (${metrics.pnl:.2f}) for {days_same_pnl}d. Strategy may be stale.",
                ))

        return alerts

    def _check_git(self, metrics: ProjectMetrics) -> list[Alert]:
        """Check git project for no-commits."""
        alerts = []

        if metrics.last_commit_date:
            commit_dt = metrics.last_commit_date.replace(tzinfo=None)
            days_since = (datetime.utcnow() - commit_dt).days
            if days_since >= self.no_commits_days:
                alerts.append(Alert(
                    project_name=metrics.project_name,
                    alert_type="no_commits",
                    days_stuck=days_since,
                    message=f"No commits for {days_since}d. Dormant or abandoned?",
                ))

        return alerts

    def _count_consecutive_zero_trades(self, history: list[dict]) -> int:
        """Count consecutive days with 0 trades from most recent history."""
        days = 0
        for entry in reversed(history):
            if entry.get("trades", 0) == 0:
                days += 1
            else:
                break
        return days

    def _count_days_same_pnl(self, current_pnl: float, history: list[dict]) -> int:
        """Count consecutive days where P&L matches current."""
        days = 0
        for entry in reversed(history):
            if abs(entry.get("pnl", 0) - current_pnl) < 0.01:
                days += 1
            else:
                break
        return days

    def _load_history(self) -> list[dict]:
        """Load metrics history from JSONL file."""
        if not os.path.exists(self.history_path):
            return []

        entries = []
        with open(self.history_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries

    def _append_history(self, metrics_list: list[ProjectMetrics]):
        """Append current metrics to history file."""
        os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
        with open(self.history_path, "a") as f:
            for m in metrics_list:
                f.write(json.dumps(m.to_dict()) + "\n")
