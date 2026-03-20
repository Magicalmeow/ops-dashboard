"""Weather Bot metric collector.

Reads:
  - signal_log.tsv: signals fired (passes_threshold=True)
  - paper_trades.tsv: trade count, per-strategy breakdown
  - data_cache/weather_paper/*_state.json: P&L, win rate from portfolio state
"""

import csv
import glob
import json
import os
from datetime import datetime, timedelta, timezone

from src.collectors.base import BaseCollector
from src.models import ProjectMetrics


class WeatherCollector(BaseCollector):

    def collect(self) -> ProjectMetrics:
        metrics = ProjectMetrics(
            project_name=self.name,
            collector_type=self.config["collector_type"],
        )
        try:
            base = self.config["base_path"]
            fallback = self.config.get("fallback_base")
            paths = self.config["paths"]

            signal_path = self._find_file(base, fallback, paths["signal_log"])
            trades_path = self._find_file(base, fallback, paths["paper_trades"])

            # Portfolio state — try base, then fallback
            state_dir = os.path.join(base, paths["portfolio_state_dir"])
            if not os.path.isdir(state_dir) and fallback:
                state_dir = os.path.join(fallback, paths["portfolio_state_dir"])

            # Signals (last 24h, passes_threshold=True)
            if signal_path:
                metrics.signals = self._count_signals(signal_path)

            # Trades (last 24h)
            if trades_path:
                metrics.trades = self._count_trades(trades_path)

            # P&L + win rate from portfolio state files
            pnl, win_rate, positions = self._read_portfolio_state(state_dir)
            metrics.pnl = pnl
            metrics.win_rate = win_rate
            metrics.open_positions = positions

        except Exception as e:
            metrics.healthy = False
            metrics.error = str(e)

        return metrics

    def _find_file(self, base: str, fallback: str, relative: str) -> str | None:
        """Try base path, then fallback."""
        primary = os.path.join(base, relative)
        if os.path.exists(primary):
            return primary
        if fallback:
            secondary = os.path.join(fallback, relative)
            if os.path.exists(secondary):
                return secondary
        return None

    def _parse_timestamp(self, ts: str) -> datetime:
        """Parse ISO timestamp, stripping timezone to compare with UTC naive."""
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt

    def _count_signals(self, path: str) -> int:
        """Count signals with passes_threshold=True in last 24h."""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        count = 0
        with open(path, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if (row.get("passes_threshold") or "").strip() == "True":
                    ts = row.get("timestamp", "")
                    try:
                        dt = self._parse_timestamp(ts)
                        if dt >= cutoff:
                            count += 1
                    except (ValueError, TypeError):
                        count += 1
        return count

    def _count_trades(self, path: str) -> int:
        """Count trades in last 24h."""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        count = 0
        with open(path, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                ts = row.get("timestamp", "")
                try:
                    dt = self._parse_timestamp(ts)
                    if dt >= cutoff:
                        count += 1
                except (ValueError, TypeError):
                    count += 1
        return count

    def _read_portfolio_state(self, state_dir: str) -> tuple:
        """Read all *_state.json files, aggregate P&L and win rate."""
        total_pnl = 0.0
        total_wins = 0
        total_resolved = 0
        total_open = 0

        if not os.path.isdir(state_dir):
            return 0.0, None, 0

        for path in glob.glob(os.path.join(state_dir, "*_state.json")):
            try:
                with open(path) as f:
                    state = json.load(f)
                portfolio = state.get("portfolio", {})
                balance = portfolio.get("balance", 0)
                starting = portfolio.get("starting_balance", 0)
                if starting:
                    total_pnl += balance - starting

                open_trades = state.get("open_trades", [])
                total_open += len(open_trades)

                # Win rate from resolved trades
                for trade in state.get("resolved_trades", []):
                    total_resolved += 1
                    if trade.get("resolution") == "WIN":
                        total_wins += 1
            except (json.JSONDecodeError, KeyError):
                continue

        win_rate = (total_wins / total_resolved) if total_resolved > 0 else None
        return total_pnl, win_rate, total_open
