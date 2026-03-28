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

            # P&L + win rate from portfolio state files (per-strategy)
            pnl, win_rate, positions, subs = self._read_portfolio_state(state_dir)
            metrics.pnl = pnl
            metrics.win_rate = win_rate
            metrics.open_positions = positions
            metrics.sub_strategies = subs

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
        """Read all *_state.json files, return aggregates + per-strategy breakdown."""
        total_pnl = 0.0
        total_wins = 0
        total_resolved = 0
        total_open = 0
        sub_strategies = []

        if not os.path.isdir(state_dir):
            return 0.0, None, 0, []

        # Active strategies to report (updated from ColdMath to current latency strategies)
        ACTIVE_STRATEGIES = {"metar_pure_latency", "synoptic_latency", "ensemble"}
        for path in sorted(glob.glob(os.path.join(state_dir, "*_state.json"))):
            try:
                with open(path) as f:
                    state = json.load(f)

                name = state.get("strategy", os.path.basename(path).replace("_state.json", ""))
                if name not in ACTIVE_STRATEGIES:
                    continue
                portfolio = state.get("portfolio", {})
                balance = portfolio.get("balance", 0)
                starting = portfolio.get("starting_balance", 0)
                pnl = state.get("total_pnl_mtm", balance - starting if starting else 0)
                nav = state.get("nav", balance)
                max_dd = state.get("max_drawdown", 0)
                sharpe = state.get("sharpe", 0)
                unrealized = state.get("unrealized_pnl", 0)

                # Open positions — dict keyed by position ID, or list of trade dicts
                open_pos_raw = state.get("open_positions", state.get("open_trades", {}))
                n_open = len(open_pos_raw)
                total_open += n_open

                # Closed positions — list of dicts (supports "won" bool or "resolution" string)
                closed = state.get("closed_positions", state.get("resolved_trades", []))
                n_closed = len(closed)
                wins = sum(
                    1 for c in closed
                    if c.get("won") or c.get("resolution") == "WIN"
                )
                wr = wins / n_closed if n_closed else None

                total_pnl += pnl
                total_resolved += n_closed
                total_wins += wins

                sub_strategies.append({
                    "name": name,
                    "nav": nav,
                    "pnl": pnl,
                    "unrealized": unrealized,
                    "open": n_open,
                    "closed": n_closed,
                    "win_rate": wr,
                    "max_dd": max_dd,
                    "sharpe": sharpe,
                })

            except (json.JSONDecodeError, KeyError):
                continue

        win_rate = (total_wins / total_resolved) if total_resolved > 0 else None
        return total_pnl, win_rate, total_open, sub_strategies
