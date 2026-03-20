"""Status engine — formats the daily scorecard.

Takes all project metrics + alerts, produces a compact Telegram-friendly report.
"""

from datetime import datetime

from src.models import Alert, DailyReport, ProjectMetrics


# Status indicators
STATUS_OK = "[OK]"
STATUS_WIP = "[WIP]"
STATUS_PAUSE = "[PAUSE]"
STATUS_BLOCKED = "[BLOCKED]"
STATUS_ERROR = "[ERROR]"


class StatusEngine:

    def generate_report(
        self,
        metrics: list[ProjectMetrics],
        alerts: list[Alert],
        priority_order: list[str],
    ) -> DailyReport:
        """Generate the daily status report."""
        # Sort metrics by priority
        priority_map = {name: i for i, name in enumerate(priority_order)}
        sorted_metrics = sorted(
            metrics,
            key=lambda m: priority_map.get(m.project_name, 999),
        )

        # Build alert lookup
        alert_map: dict[str, list[Alert]] = {}
        for alert in alerts:
            alert_map.setdefault(alert.project_name, []).append(alert)

        # Format scorecard
        now = datetime.utcnow()
        lines = [f"Daily Status — {now.strftime('%b %d')}"]
        lines.append("")

        for i, m in enumerate(sorted_metrics, 1):
            project_alerts = alert_map.get(m.project_name, [])
            status = self._determine_status(m, project_alerts)
            line = self._format_project_line(i, m, status)
            lines.append(line)

        # Append nag alerts
        nag_alerts = [a for a in alerts if a.days_stuck >= 2]
        if nag_alerts:
            lines.append("")
            for alert in nag_alerts:
                lines.append(f"⚠️ {alert.project_name.upper()}: {alert.message}")

        scorecard = "\n".join(lines)

        return DailyReport(
            generated_at=now,
            project_metrics=sorted_metrics,
            alerts=alerts,
            scorecard=scorecard,
        )

    def _determine_status(self, m: ProjectMetrics, alerts: list[Alert]) -> str:
        """Assign a status indicator to a project."""
        if m.error:
            return STATUS_ERROR

        has_blocker = any(a.alert_type in ("no_trades", "stale_pnl") and a.days_stuck >= 2 for a in alerts)
        if has_blocker:
            return STATUS_BLOCKED

        if m.collector_type.startswith("trading_"):
            if m.trades > 0 or m.open_positions > 0:
                return STATUS_OK
            return STATUS_PAUSE
        elif m.collector_type == "git":
            if m.last_commit_date:
                days_ago = (datetime.utcnow() - m.last_commit_date.replace(tzinfo=None)).days
                if days_ago <= 3:
                    return STATUS_WIP
                return STATUS_PAUSE
            return STATUS_PAUSE

        return STATUS_PAUSE

    def _format_project_line(self, rank: int, m: ProjectMetrics, status: str) -> str:
        """Format a single project line for the scorecard."""
        name = m.project_name.upper()
        pad = max(1, 12 - len(name))

        if m.collector_type == "trading_weather":
            detail = f"{m.signals} signals | {m.trades} trades | ${m.pnl:+.0f} P&L"
            if m.win_rate is not None:
                detail += f" | {m.win_rate:.0%} WR"

        elif m.collector_type == "trading_mm":
            detail = f"{m.fills} fills | ${m.pnl:+.0f} P&L | {m.exposure_pct:.0f}% exposure"

        elif m.collector_type == "trading_decoded":
            detail = f"{m.trades} trades | ${m.pnl:+.0f} P&L | {m.open_positions} open"
            if m.win_rate is not None:
                detail += f" | {m.win_rate:.0%} WR"

        elif m.collector_type == "trading_momentum":
            detail = f"{m.trades} trades | ${m.pnl:+.0f} P&L | {m.open_positions} pos"
            if m.win_rate is not None:
                detail += f" | {m.win_rate:.0%} WR"

        elif m.collector_type == "git":
            detail = m.status_text or "No data"

        else:
            detail = m.status_text or "Unknown"

        if m.error:
            detail = f"ERROR: {m.error[:50]}"

        return f"{rank}. {name}{' ' * pad}{status} {detail}"
