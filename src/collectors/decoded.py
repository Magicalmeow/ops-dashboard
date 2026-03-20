"""Decoded Crypto (Strategy Decoder) metric collector.

Reads:
  - data_cache/paper_trading/*_trades.tsv: trade count, P&L, win rate
  - data_cache/paper_trading/*_state.json: open positions, balance
"""

import csv
import glob
import json
import os

from src.collectors.base import BaseCollector
from src.models import ProjectMetrics


class DecodedCollector(BaseCollector):

    def collect(self) -> ProjectMetrics:
        metrics = ProjectMetrics(
            project_name=self.name,
            collector_type=self.config["collector_type"],
        )
        try:
            paths = self.config["paths"]
            trades_dir = self._resolve_path(paths["trades_dir"])
            state_dir = self._resolve_path(paths["state_dir"])

            # Aggregate across all strategy trade files
            if os.path.isdir(trades_dir):
                self._read_trades(trades_dir, metrics)

            # Open positions from state files
            if os.path.isdir(state_dir):
                self._read_state(state_dir, metrics)

        except Exception as e:
            metrics.healthy = False
            metrics.error = str(e)

        return metrics

    def _read_trades(self, trades_dir: str, metrics: ProjectMetrics):
        """Parse all *_trades.tsv files for resolved trade stats."""
        total_pnl = 0.0
        total_wins = 0
        total_resolved = 0
        seen_ids = set()

        for path in glob.glob(os.path.join(trades_dir, "*_trades.tsv")):
            with open(path, "r") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    trade_id = row.get("id", "")
                    resolved = row.get("resolved", "").strip()

                    # Only count resolved rows (trades are written twice: open + close)
                    if resolved != "True":
                        continue
                    if trade_id in seen_ids:
                        continue
                    seen_ids.add(trade_id)

                    total_resolved += 1
                    pnl = float(row.get("pnl", 0))
                    total_pnl += pnl
                    if pnl > 0:
                        total_wins += 1

        metrics.trades = total_resolved
        metrics.pnl = round(total_pnl, 2)
        metrics.win_rate = (total_wins / total_resolved) if total_resolved > 0 else None

    def _read_state(self, state_dir: str, metrics: ProjectMetrics):
        """Read *_state.json for open positions count."""
        total_open = 0
        for path in glob.glob(os.path.join(state_dir, "*_state.json")):
            try:
                with open(path) as f:
                    state = json.load(f)
                total_open += len(state.get("open_trades", []))
            except (json.JSONDecodeError, KeyError):
                continue
        metrics.open_positions = total_open
