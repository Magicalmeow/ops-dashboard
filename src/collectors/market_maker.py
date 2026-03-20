"""Market Maker metric collector.

Reads:
  - data_cache/mm_paper/equity_curve.tsv: latest equity, P&L, return_pct
  - research/mm_research/data/paper_session_*.json: fills, categories, reward estimate
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

            # Equity curve — latest row
            eq_path = self._resolve_path(paths["equity_curve"])
            if os.path.exists(eq_path):
                self._read_equity_curve(eq_path, metrics)

            # Latest session JSON — fills, categories
            session_dir = self._resolve_path(paths["session_dir"])
            if os.path.isdir(session_dir):
                self._read_latest_session(session_dir, metrics)

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

            # P&L = equity - starting cash (approximate: first row)
            # We'll use return_pct and estimate from equity
            metrics.pnl = equity - cash if inv != 0 else 0
            if equity > 0:
                metrics.exposure_pct = round((inv / equity) * 100, 1)

    def _read_latest_session(self, session_dir: str, metrics: ProjectMetrics):
        """Read the most recent paper_session_*.json for fill counts."""
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

        # P&L from session pnl dict (more accurate than equity curve)
        pnl_data = data.get("pnl", {})
        starting = pnl_data.get("starting_cash", 0)
        equity = pnl_data.get("equity", 0)
        if starting:
            metrics.pnl = round(equity - starting, 2)
            metrics.return_pct = round(((equity - starting) / starting) * 100, 2)

        inv = pnl_data.get("inventory_value", 0)
        if equity > 0:
            metrics.exposure_pct = round((abs(inv) / equity) * 100, 1)
