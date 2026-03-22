"""Crypto Prediction strategy collector.

Reads SQLite DBs from /opt/crypto-prediction/ for all active strategies.
Each strategy has its own DB with a `trades` table.
"""

import math
import os
import sqlite3
import subprocess
from datetime import datetime, timezone

from src.collectors.base import BaseCollector
from src.models import ProjectMetrics


# (display_name, db_filename, starting_balance, systemd_service)
CRYPTO_STRATEGIES = [
    ("BTC-BASELINE-5M", "btc_baseline.db", 500, "btc-baseline-5m"),
    ("BTC-REGIME-5M", "btc_regime.db", 500, "btc-regime-5m"),
    ("BTC-HYBRID-5M", "btc_hybrid.db", 500, "btc-hybrid-5m"),
    ("BTC-OBIMB-5M", "btc_obimb.db", 500, "btc-obimb-5m"),
    ("ETH-BASELINE-5M", "eth_baseline.db", 500, "eth-baseline-5m"),
    ("BTC-HYBRID-VAL", "btc_hybrid_value.db", 500, "btc-hybrid-value-5m"),
    ("BTC-MM-5M", "btc_mm.db", 500, "btc-mm-5m"),
    ("BTC-ZSCORE-5M", "btc_zscore.db", 500, "btc-zscore-5m"),
    ("SOL-BASELINE-5M", "sol_baseline.db", 500, "sol-baseline-5m"),
]


class CryptoPredictionCollector(BaseCollector):

    def collect(self) -> ProjectMetrics:
        metrics = ProjectMetrics(
            project_name=self.name,
            collector_type=self.config["collector_type"],
        )
        try:
            base = self.config["base_path"]
            total_pnl = 0.0
            total_settled = 0
            total_wins = 0
            total_open = 0
            subs = []

            for display_name, db_file, starting_bal, service in CRYPTO_STRATEGIES:
                db_path = os.path.join(base, db_file)
                sub = self._read_strategy_db(display_name, db_path, starting_bal, service)
                subs.append(sub)
                total_pnl += sub.get("pnl", 0)
                total_settled += sub.get("settled", 0)
                total_wins += sub.get("wins", 0)
                total_open += sub.get("open", 0)

            metrics.pnl = round(total_pnl, 2)
            metrics.trades = total_settled
            metrics.open_positions = total_open
            metrics.win_rate = (total_wins / total_settled) if total_settled > 0 else None
            metrics.sub_strategies = subs

        except Exception as e:
            metrics.healthy = False
            metrics.error = str(e)

        return metrics

    def _read_strategy_db(self, name: str, db_path: str, starting_bal: float, service: str) -> dict:
        """Read a single strategy's SQLite DB and compute metrics."""
        sub = {
            "name": name,
            "balance": starting_bal,
            "pnl": 0,
            "roi": 0,
            "max_dd": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "sortino": 0,
            "settled": 0,
            "open": 0,
            "wins": 0,
            "runtime_hours": 0,
            "service_status": self._check_service(service),
        }

        if not os.path.exists(db_path):
            return sub

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            resolved = conn.execute(
                "SELECT * FROM trades WHERE resolved=1 ORDER BY timestamp"
            ).fetchall()
            n_open = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE resolved=0"
            ).fetchone()[0]
            first_trade_ts = conn.execute(
                "SELECT MIN(timestamp) FROM trades"
            ).fetchone()[0]
            conn.close()

            sub["open"] = n_open

            # Compute runtime from first trade
            if first_trade_ts:
                try:
                    first_dt = datetime.fromisoformat(first_trade_ts)
                    if first_dt.tzinfo is None:
                        first_dt = first_dt.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    runtime_hours = (now - first_dt).total_seconds() / 3600
                    sub["runtime_hours"] = round(runtime_hours, 1)
                except (ValueError, TypeError):
                    pass

            if not resolved:
                return sub

            pnls = [r["pnl_usd"] for r in resolved if r["pnl_usd"] is not None]
            if not pnls:
                return sub

            total_pnl = sum(pnls)
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]

            sub["pnl"] = round(total_pnl, 2)
            sub["balance"] = round(starting_bal + total_pnl, 2)
            sub["roi"] = round(total_pnl / starting_bal * 100, 1) if starting_bal else 0
            sub["settled"] = len(pnls)
            sub["wins"] = len(wins)
            sub["win_rate"] = round(len(wins) / len(pnls) * 100, 1) if pnls else 0

            gross_wins = sum(wins)
            gross_losses = sum(abs(x) for x in losses)
            sub["profit_factor"] = round(gross_wins / gross_losses, 2) if gross_losses else 0
            sub["avg_win"] = round(gross_wins / len(wins), 2) if wins else 0
            sub["avg_loss"] = round(-gross_losses / len(losses), 2) if losses else 0

            # Max drawdown
            cum = 0
            peak = 0
            mdd = 0
            for p in pnls:
                cum += p
                if cum > peak:
                    peak = cum
                dd = cum - peak
                if dd < mdd:
                    mdd = dd
            sub["max_dd"] = round(mdd, 2)

            # Sortino ratio (annualized)
            if len(pnls) > 1:
                mean_return = sum(pnls) / len(pnls)
                downside_sq = [min(0, p) ** 2 for p in pnls]
                dd_std = math.sqrt(sum(downside_sq) / len(downside_sq))
                sub["sortino"] = round(mean_return / dd_std * math.sqrt(365), 2) if dd_std > 0 else 0

        except Exception:
            pass

        return sub

    def _check_service(self, service_name: str) -> str:
        """Check systemd service status."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", f"{service_name}.service"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"
