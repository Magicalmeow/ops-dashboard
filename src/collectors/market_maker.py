"""Market Maker metric collector.

Reads:
  - data_cache/mm_paper/equity_curve.tsv: latest equity, P&L, return_pct
  - research/mm_research/data/paper_session_*.json: fills, P&L (realized/unrealized)
"""

import csv
import glob
import json
import os

from src.collectors.base import BaseCollector
from src.models import ProjectMetrics


class MarketMakerCollector(BaseCollector):

    def collect(self) -> ProjectMetrics:
        metrics = ProjectMetrics(
            project_name=self.name,
            collector_type=self.config["collector_type"],
        )
        try:
            paths = self.config["paths"]

            # Latest session JSON — fills, P&L (primary source)
            session_dir = self._resolve_path(paths["session_dir"])
            if os.path.isdir(session_dir):
                self._read_latest_session(session_dir, metrics)

            # Equity curve as fallback
            eq_path = self._resolve_path(paths["equity_curve"])
            if os.path.exists(eq_path) and metrics.pnl == 0.0:
                self._read_equity_curve(eq_path, metrics)

        except Exception as e:
            metrics.healthy = False
            metrics.error = str(e)

        return metrics

    def _read_equity_curve(self, path: str, metrics: ProjectMetrics):
        """Read the last row of equity_curve.tsv for current state."""
        last_row = None
        with open(path, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                last_row = row

        if last_row:
            cash = float(last_row.get("cash", 0))
            inv = float(last_row.get("inventory_value", 0))
            equity = float(last_row.get("equity", 0))
            metrics.return_pct = float(last_row.get("return_pct", 0))
            if equity > 0:
                metrics.exposure_pct = round((abs(inv) / equity) * 100, 1)

    def _read_latest_session(self, session_dir: str, metrics: ProjectMetrics):
        """Read the most recent paper_session_*.json for fill counts and P&L."""
        sessions = sorted(glob.glob(os.path.join(session_dir, "paper_session_*.json")))
        if not sessions:
            return

        with open(sessions[-1]) as f:
            data = json.load(f)

        # Total fills across all categories
        total_fills = 0
        categories = data.get("categories", {})
        for cat_data in categories.values():
            total_fills += cat_data.get("fills", 0)
        metrics.fills = total_fills

        # P&L from session — handles both old format (starting_cash/equity)
        # and new format (realized/unrealized/net_total)
        pnl_data = data.get("pnl", {})

        if "net_total" in pnl_data:
            # New format: realized + unrealized + reward_estimate
            metrics.pnl = round(pnl_data.get("net_total", 0), 2)
            metrics.return_pct = round(
                (pnl_data.get("net_total", 0) / 3000) * 100, 2  # vs starting bankroll
            ) if pnl_data.get("net_total") else 0

        elif "starting_cash" in pnl_data:
            # Old format
            starting = pnl_data.get("starting_cash", 0)
            equity = pnl_data.get("equity", 0)
            if starting:
                metrics.pnl = round(equity - starting, 2)
                metrics.return_pct = round(((equity - starting) / starting) * 100, 2)

        # Exposure from equity curve if available
        inv = pnl_data.get("unrealized", pnl_data.get("inventory_value", 0))
        total = pnl_data.get("net_total", 0) + 3000  # approximate equity
        if total > 0:
            metrics.exposure_pct = round((abs(inv) / total) * 100, 1)
