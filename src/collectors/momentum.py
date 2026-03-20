"""Crypto Momentum metric collector.

Reads:
  - data_cache/momentum_trading/momentum_trades.tsv: trades, P&L, win rate
  - data_cache/momentum_trading/momentum_state.json: balance, open positions
"""

import csv
import json
import os

from src.collectors.base import BaseCollector
from src.models import ProjectMetrics


class MomentumCollector(BaseCollector):

    def collect(self) -> ProjectMetrics:
        metrics = ProjectMetrics(
            project_name=self.name,
            collector_type=self.config["collector_type"],
        )
        try:
            paths = self.config["paths"]
            trades_path = self._resolve_path(paths["trades"])
            state_path = self._resolve_path(paths["state"])

            if os.path.exists(trades_path):
                self._read_trades(trades_path, metrics)

            if os.path.exists(state_path):
                self._read_state(state_path, metrics)

        except Exception as e:
            metrics.healthy = False
            metrics.error = str(e)

        return metrics

    def _read_trades(self, path: str, metrics: ProjectMetrics):
        """Parse momentum_trades.tsv for resolved trade stats."""
        total_pnl = 0.0
        total_wins = 0
        total_resolved = 0
        seen_ids = set()

        with open(path, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                trade_id = row.get("id", "")
                resolved = (row.get("resolved") or "").strip()

                if resolved != "True":
                    continue
                if trade_id in seen_ids:
                    continue
                seen_ids.add(trade_id)

                total_resolved += 1
                pnl = float(row.get("net_pnl", 0))
                total_pnl += pnl
                if pnl > 0:
                    total_wins += 1

        metrics.trades = total_resolved
        metrics.pnl = round(total_pnl, 2)
        metrics.win_rate = (total_wins / total_resolved) if total_resolved > 0 else None

    def _read_state(self, path: str, metrics: ProjectMetrics):
        """Read momentum_state.json for open positions and balance."""
        with open(path) as f:
            state = json.load(f)

        metrics.open_positions = len(state.get("open_positions", []))

        # Balance for return calculation
        balance = state.get("balance", 0)
        high_water = state.get("high_water_mark", 0)
        if high_water > 0:
            metrics.return_pct = round(((balance - high_water) / high_water) * 100, 2)
