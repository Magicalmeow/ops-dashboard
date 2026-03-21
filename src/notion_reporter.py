"""Notion reporter — pushes daily metrics to a Notion dashboard.

Creates two databases under a target page:
  1. Project Status — one row per project, upserted daily (live dashboard)
  2. Daily History — one row per project per day (trends over time)

Opt-in: only runs if NOTION_TOKEN env var is set.
"""

import json
import logging
import os
from datetime import datetime, timezone

from notion_client import Client

from src.models import Alert, DailyReport, ProjectMetrics

logger = logging.getLogger(__name__)

# Status labels matching status_engine.py indicators
STATUS_MAP = {
    "[OK]": "OK",
    "[WIP]": "WIP",
    "[PAUSE]": "Paused",
    "[BLOCKED]": "Blocked",
    "[ERROR]": "Error",
}


class NotionReporter:

    def __init__(self, token: str = "", page_id: str = "", ids_cache: str = ""):
        self.token = token or os.environ.get("NOTION_TOKEN", "")
        self.page_id = page_id or os.environ.get("NOTION_PAGE_ID", "")
        self.ids_cache = ids_cache or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "notion_ids.json"
        )
        self.client = Client(auth=self.token) if self.token else None
        self._db_ids = self._load_ids()

    def _load_ids(self) -> dict:
        """Load cached database IDs from disk."""
        if os.path.exists(self.ids_cache):
            with open(self.ids_cache) as f:
                return json.load(f)
        return {}

    def _save_ids(self):
        """Persist database IDs to disk."""
        os.makedirs(os.path.dirname(self.ids_cache), exist_ok=True)
        with open(self.ids_cache, "w") as f:
            json.dump(self._db_ids, f, indent=2)

    def push(self, report: DailyReport, dry_run: bool = False) -> bool:
        """Push report data to Notion. Returns True on success."""
        if not self.token or not self.page_id:
            logger.info("Notion not configured (no token or page_id). Skipping.")
            return False

        if dry_run:
            print("[notion] Dry run — would push to Notion:")
            for m in report.project_metrics:
                print(f"  {m.project_name}: pnl=${m.pnl:+.0f}, trades={m.trades}")
            return True

        try:
            self._ensure_databases()
            self._push_status(report)
            self._push_history(report)
            logger.info("Notion push complete.")
            return True
        except Exception as e:
            logger.error(f"Notion push failed: {e}")
            return False

    def _ensure_databases(self):
        """Create the two databases if they don't exist yet."""
        if "status_db" in self._db_ids and "history_db" in self._db_ids:
            return

        if "status_db" not in self._db_ids:
            db = self.client.databases.create(
                parent={"page_id": self.page_id},
                title=[{"type": "text", "text": {"content": "Project Status"}}],
                properties=self._status_schema(),
            )
            self._db_ids["status_db"] = db["id"]
            logger.info(f"Created Project Status database: {db['id']}")

        if "history_db" not in self._db_ids:
            db = self.client.databases.create(
                parent={"page_id": self.page_id},
                title=[{"type": "text", "text": {"content": "Daily History"}}],
                properties=self._history_schema(),
            )
            self._db_ids["history_db"] = db["id"]
            logger.info(f"Created Daily History database: {db['id']}")

        self._save_ids()

    def _status_schema(self) -> dict:
        """Schema for the Project Status database."""
        return {
            "Project": {"title": {}},
            "Priority": {"number": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "OK", "color": "green"},
                        {"name": "WIP", "color": "blue"},
                        {"name": "Paused", "color": "gray"},
                        {"name": "Blocked", "color": "red"},
                        {"name": "Error", "color": "red"},
                    ]
                }
            },
            "P&L": {"number": {"format": "dollar"}},
            "Win Rate": {"number": {"format": "percent"}},
            "Trades (24h)": {"number": {}},
            "Signals (24h)": {"number": {}},
            "Open Positions": {"number": {}},
            "Exposure %": {"number": {"format": "percent"}},
            "Blocker": {"rich_text": {}},
            "Sub-Strategies": {"rich_text": {}},
            "Last Commit": {"rich_text": {}},
            "Last Updated": {"date": {}},
        }

    def _history_schema(self) -> dict:
        """Schema for the Daily History database."""
        return {
            "Project": {"title": {}},
            "Date": {"date": {}},
            "P&L": {"number": {"format": "dollar"}},
            "Win Rate": {"number": {"format": "percent"}},
            "Trades": {"number": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "OK", "color": "green"},
                        {"name": "WIP", "color": "blue"},
                        {"name": "Paused", "color": "gray"},
                        {"name": "Blocked", "color": "red"},
                        {"name": "Error", "color": "red"},
                    ]
                }
            },
        }

    def _push_status(self, report: DailyReport):
        """Upsert one row per project in the Project Status database."""
        db_id = self._db_ids["status_db"]
        alert_map = {}
        for a in report.alerts:
            alert_map.setdefault(a.project_name, []).append(a.message)

        for i, m in enumerate(report.project_metrics):
            status = self._resolve_status(m, report.alerts)
            props = self._build_status_properties(i, m, status, alert_map)

            # Try to find existing row by project name
            existing = self.client.databases.query(
                database_id=db_id,
                filter={"property": "Project", "title": {"equals": m.project_name}},
            )

            if existing["results"]:
                page_id = existing["results"][0]["id"]
                self.client.pages.update(page_id=page_id, properties=props)
            else:
                self.client.pages.create(
                    parent={"database_id": db_id},
                    properties=props,
                )

    def _push_history(self, report: DailyReport):
        """Append one row per project to the Daily History database."""
        db_id = self._db_ids["history_db"]
        today = datetime.now(timezone.utc).date().isoformat()

        for m in report.project_metrics:
            status = self._resolve_status(m, report.alerts)
            props = {
                "Project": {"title": [{"text": {"content": m.project_name}}]},
                "Date": {"date": {"start": today}},
                "P&L": {"number": round(m.pnl, 2)},
                "Win Rate": {"number": round(m.win_rate, 4) if m.win_rate is not None else None},
                "Trades": {"number": m.trades},
                "Status": {"select": {"name": status}},
            }
            self.client.pages.create(
                parent={"database_id": db_id},
                properties=props,
            )

    def _build_status_properties(
        self, rank: int, m: ProjectMetrics, status: str, alert_map: dict
    ) -> dict:
        """Build Notion properties dict for a Project Status row."""
        blockers = alert_map.get(m.project_name, [])
        blocker_text = " | ".join(blockers) if blockers else ""

        # Format sub-strategies
        sub_lines = []
        for sub in m.sub_strategies:
            name = sub["name"]
            nav = sub.get("nav", 0)
            pnl = sub.get("pnl", 0)
            wr = sub.get("win_rate")
            wr_str = f"{wr:.0%}" if wr is not None else "—"
            sub_lines.append(f"{name}: NAV ${nav:,.0f} | ${pnl:+,.0f} | WR {wr_str}")
        sub_text = "\n".join(sub_lines)

        # Last commit (for git projects)
        commit_text = ""
        if m.last_commit_message:
            commit_text = m.last_commit_message[:100]
            if m.last_commit_date:
                days = (datetime.utcnow() - m.last_commit_date.replace(tzinfo=None)).days
                commit_text = f"{days}d ago: {commit_text}"

        props = {
            "Project": {"title": [{"text": {"content": m.project_name}}]},
            "Priority": {"number": rank + 1},
            "Status": {"select": {"name": status}},
            "P&L": {"number": round(m.pnl, 2)},
            "Win Rate": {"number": round(m.win_rate, 4) if m.win_rate is not None else None},
            "Trades (24h)": {"number": m.trades},
            "Signals (24h)": {"number": m.signals},
            "Open Positions": {"number": m.open_positions},
            "Exposure %": {"number": round(m.exposure_pct / 100, 4) if m.exposure_pct else None},
            "Blocker": {"rich_text": [{"text": {"content": blocker_text}}] if blocker_text else []},
            "Sub-Strategies": {"rich_text": [{"text": {"content": sub_text}}] if sub_text else []},
            "Last Commit": {"rich_text": [{"text": {"content": commit_text}}] if commit_text else []},
            "Last Updated": {"date": {"start": m.collected_at.isoformat()}},
        }
        return props

    def _resolve_status(self, m: ProjectMetrics, alerts: list[Alert]) -> str:
        """Determine the Notion status label for a project."""
        if m.error:
            return "Error"

        has_blocker = any(
            a.project_name == m.project_name
            and a.alert_type in ("no_trades", "stale_pnl")
            and a.days_stuck >= 2
            for a in alerts
        )
        if has_blocker:
            return "Blocked"

        if m.collector_type.startswith("trading_"):
            if m.trades > 0 or m.open_positions > 0:
                return "OK"
            return "Paused"
        elif m.collector_type == "git":
            if m.last_commit_date:
                days = (datetime.utcnow() - m.last_commit_date.replace(tzinfo=None)).days
                if days <= 3:
                    return "WIP"
            return "Paused"

        return "Paused"
