"""Status engine — formats the daily scorecard.

Takes all project metrics + alerts, produces a 3-section Telegram-friendly report:
  1. WEATHER — per-strategy performance (NAV, P&L, ROI, DD)
  2. CRYPTO — per-strategy performance (Balance, P&L, ROI, WR, Sortino)
  3. PROJECTS — git repo activity (last commit, days ago)
"""

from datetime import datetime

from src.models import Alert, DailyReport, ProjectMetrics


# Status indicators
STATUS_OK = "[OK]"
STATUS_WIP = "[WIP]"
STATUS_PAUSE = "[PAUSE]"
STATUS_BLOCKED = "[BLOCKED]"
STATUS_ERROR = "[ERROR]"

WEATHER_STARTING_BALANCE = 3000


class StatusEngine:

    def generate_report(
        self,
        metrics: list[ProjectMetrics],
        alerts: list[Alert],
        priority_order: list[str],
    ) -> DailyReport:
        """Generate the daily status report in 3 sections."""
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

        # Categorize by section
        weather = [m for m in sorted_metrics if m.collector_type == "trading_weather"]
        crypto = [m for m in sorted_metrics if m.collector_type in ("trading_crypto", "trading_mm", "trading_decoded", "trading_momentum")]
        projects = [m for m in sorted_metrics if m.collector_type == "git"]

        now = datetime.utcnow()
        lines = [f"Daily Status — {now.strftime('%b %d')}"]

        # Section 1: Weather Performance
        if weather:
            lines.append("")
            lines.append("━━ WEATHER ━━")
            for m in weather:
                lines.append(f"  {m.project_name.upper()}: {m.signals} signals, {m.trades} trades")
                if m.error:
                    lines.append(f"    ERROR: {m.error[:60]}")
                    continue
                for sub in m.sub_strategies:
                    lines.append(self._format_weather_sub(sub))

        # Section 2: Crypto Performance
        if crypto:
            lines.append("")
            lines.append("━━ CRYPTO ━━")
            for m in crypto:
                lines.append(f"  {m.project_name.upper()}: {m.fills} fills")
                if m.error:
                    lines.append(f"    ERROR: {m.error[:60]}")
                    continue
                # Sort sub-strategies by P&L descending
                subs = sorted(m.sub_strategies, key=lambda s: s.get("pnl", 0), reverse=True)
                for sub in subs:
                    lines.append(self._format_crypto_sub(sub))

        # Section 3: Projects
        if projects:
            lines.append("")
            lines.append("━━ PROJECTS ━━")
            for idx, m in enumerate(projects, start=1):
                proj_alerts = alert_map.get(m.project_name, [])
                status = self._determine_status(m, proj_alerts)
                lines.append(self._format_git_project(m, status, idx))

        # Nag alerts
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

    def _format_weather_sub(self, sub: dict) -> str:
        """Format a weather sub-strategy line."""
        name = sub["name"]
        nav = sub.get("nav", 0)
        pnl = sub.get("pnl", 0)
        roi = ((nav - WEATHER_STARTING_BALANCE) / WEATHER_STARTING_BALANCE * 100) if nav else 0
        max_dd = sub.get("max_dd", 0)
        n_open = sub.get("open", 0)
        n_closed = sub.get("closed", 0)
        wr = sub.get("win_rate")

        wr_str = f"{wr:.0%} WR" if wr is not None else "no resolves"

        return (
            f"  {name}: NAV ${nav:,.0f} | ${pnl:+,.0f} P&L | "
            f"{roi:+.1f}% ROI | {max_dd * 100:.1f}% DD | "
            f"{n_open} open, {n_closed} closed | {wr_str}"
        )

    def _format_crypto_sub(self, sub: dict) -> str:
        """Format a crypto sub-strategy line."""
        name = sub["name"]
        bal = sub.get("balance", 500)
        pnl = sub.get("pnl", 0)
        roi = sub.get("roi", 0)
        wr = sub.get("win_rate", 0)
        sortino = sub.get("sortino", 0)
        settled = sub.get("settled", 0)
        n_open = sub.get("open", 0)
        runtime_h = sub.get("runtime_hours", 0)

        # Format runtime: "<1h", "5h", "2d", etc.
        if runtime_h < 1:
            runtime_str = "<1h"
        elif runtime_h < 48:
            runtime_str = f"{runtime_h:.0f}h"
        else:
            runtime_str = f"{runtime_h / 24:.0f}d"

        return (
            f"  {name}: ${bal:,.0f} | ${pnl:+,.0f} | "
            f"{roi:+.1f}% | {wr:.0f}% WR | "
            f"{sortino:.1f} Sort | {settled}/{n_open} | {runtime_str}"
        )

    def _format_git_project(self, m: ProjectMetrics, status: str, idx: int = 0) -> str:
        """Format a git project line."""
        name = m.project_name
        prefix = f"{idx}. " if idx else "  "
        if m.last_commit_date:
            days_ago = (datetime.utcnow() - m.last_commit_date.replace(tzinfo=None)).days
            msg = m.last_commit_message or ""
            if len(msg) > 40:
                msg = msg[:37] + "..."
            return f"{prefix}{name} {status} {days_ago}d ago — {msg}"
        elif m.error:
            return f"{prefix}{name} {status} {m.error[:50]}"
        else:
            return f"{prefix}{name} {status} {m.status_text or 'No data'}"
