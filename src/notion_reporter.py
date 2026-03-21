"""Notion reporter — pushes daily metrics to a Notion dashboard.

Creates two databases under a target page:
  1. Project Status — one row per project, upserted daily (live dashboard)
  2. Daily History — one row per project per day (trends over time)

Opt-in: only runs if NOTION_TOKEN env var is set.
Uses requests directly (no SDK version headaches).
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests

from src.models import Alert, DailyReport, ProjectMetrics

logger = logging.getLogger(__name__)

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionReporter:

    def __init__(self, token: str = "", page_id: str = "", ids_cache: str = ""):
        self.token = token or os.environ.get("NOTION_TOKEN", "")
        self.page_id = page_id or os.environ.get("NOTION_PAGE_ID", "32a2861350dc802d9ed6f1da7f46c331")
        self.ids_cache = ids_cache or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "notion_ids.json"
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }
        self._db_ids = self._load_ids()

    def _load_ids(self) -> dict:
        if os.path.exists(self.ids_cache):
            with open(self.ids_cache) as f:
                return json.load(f)
        return {}

    def _save_ids(self):
        os.makedirs(os.path.dirname(self.ids_cache), exist_ok=True)
        with open(self.ids_cache, "w") as f:
            json.dump(self._db_ids, f, indent=2)

    def _api(self, method: str, path: str, body: dict = None) -> dict:
        """Make a Notion API call. Raises on failure."""
        url = f"{API_BASE}{path}"
        resp = requests.request(method, url, headers=self.headers, json=body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def push(self, report: DailyReport, dry_run: bool = False) -> bool:
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
        if "status_db" in self._db_ids and "history_db" in self._db_ids:
            return

        if "status_db" not in self._db_ids:
            db = self._api("POST", "/databases", {
                "parent": {"page_id": self.page_id},
                "title": [{"type": "text", "text": {"content": "Project Status"}}],
                "properties": self._status_schema(),
            })
            self._db_ids["status_db"] = db["id"]
            logger.info(f"Created Project Status database: {db['id']}")

        if "history_db" not in self._db_ids:
            db = self._api("POST", "/databases", {
                "parent": {"page_id": self.page_id},
                "title": [{"type": "text", "text": {"content": "Daily History"}}],
                "properties": self._history_schema(),
            })
            self._db_ids["history_db"] = db["id"]
            logger.info(f"Created Daily History database: {db['id']}")

        self._save_ids()

    def _status_schema(self) -> dict:
        return {
            "Project": {"title": {}},
            "Priority": {"number": {}},
            "Status": {"select": {"options": [
                {"name": "OK", "color": "green"},
                {"name": "WIP", "color": "blue"},
                {"name": "Paused", "color": "gray"},
                {"name": "Blocked", "color": "red"},
                {"name": "Error", "color": "red"},
            ]}},
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
        return {
            "Project": {"title": {}},
            "Date": {"date": {}},
            "P&L": {"number": {"format": "dollar"}},
            "Win Rate": {"number": {"format": "percent"}},
            "Trades": {"number": {}},
            "Status": {"select": {"options": [
                {"name": "OK", "color": "green"},
                {"name": "WIP", "color": "blue"},
                {"name": "Paused", "color": "gray"},
                {"name": "Blocked", "color": "red"},
                {"name": "Error", "color": "red"},
            ]}},
        }

    def _query_db(self, db_id: str, filter_body: dict) -> list:
        """Query a Notion database with a filter."""
        result = self._api("POST", f"/databases/{db_id}/query", {"filter": filter_body})
        return result.get("results", [])

    def _push_status(self, report: DailyReport):
        db_id = self._db_ids["status_db"]
        alert_map = {}
        for a in report.alerts:
            alert_map.setdefault(a.project_name, []).append(a.message)

        for i, m in enumerate(report.project_metrics):
            status = self._resolve_status(m, report.alerts)
            props = self._build_status_properties(i, m, status, alert_map)

            # Upsert: find existing row by project name
            existing = self._query_db(db_id, {
                "property": "Project",
                "title": {"equals": m.project_name},
            })

            if existing:
                page_id = existing[0]["id"]
                self._api("PATCH", f"/pages/{page_id}", {"properties": props})
            else:
                self._api("POST", "/pages", {
                    "parent": {"database_id": db_id},
                    "properties": props,
                })

    def _push_history(self, report: DailyReport):
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
            self._api("POST", "/pages", {
                "parent": {"database_id": db_id},
                "properties": props,
            })

    def _build_status_properties(
        self, rank: int, m: ProjectMetrics, status: str, alert_map: dict
    ) -> dict:
        blockers = alert_map.get(m.project_name, [])
        blocker_text = " | ".join(blockers) if blockers else ""

        sub_lines = []
        for sub in m.sub_strategies:
            name = sub["name"]
            nav = sub.get("nav", 0)
            pnl = sub.get("pnl", 0)
            wr = sub.get("win_rate")
            wr_str = f"{wr:.0%}" if wr is not None else "—"
            sub_lines.append(f"{name}: NAV ${nav:,.0f} | ${pnl:+,.0f} | WR {wr_str}")
        sub_text = "\n".join(sub_lines)

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
