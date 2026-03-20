## Problem Statement

I'm running 6 parallel workstreams across trading bots and dev projects (Weather Bot, Market Maker, Decoded Crypto, Crypto Momentum, Equity Engine, Auto Research). I lose track of where each one stands, what's blocked, and what to prioritize. I start new things instead of finishing what's 90% done. There's no single view that tells me "here's where everything is, here's what's stuck, here's what to do next."

I need a daily push notification (Telegram) that gives me a compact scorecard of all projects with live trading metrics, blocker detection, and nagging when something has been stuck for too long — so I actually finish things.

## Solution

A VPS-hosted dashboard system that:

1. **Collects live metrics** from all paper trading strategies running on the VPS (P&L, win rate, trade count, fills, exposure) by reading their TSV/log/state files directly
2. **Collects project status** from non-trading repos (equity engine, auto research) via git log and handoff file parsing
3. **Detects blockers** when metrics stagnate (no trades for 48h, same P&L for 3 days, no commits for 5 days)
4. **Ranks projects** by a user-defined priority order (manually set, not computed)
5. **Sends a daily Telegram scorecard** in compact format — one line per workstream with status emoji, key metrics, and any blocker alerts
6. **Nags** when a high-priority project has been blocked for multiple days on the same issue

The system runs entirely on the Hetzner VPS (178.156.235.253) via daily cron. It uses a new dedicated Telegram bot.

### Scorecard Format

```
Daily Status — Mar 20

1. WEATHER  [OK] 4 signals | 2 trades | +$12 | 75% WR
2. MM       [OK] 167 fills | +$26 P&L | 26% exposure
3. EQUITY   [WIP] Social intel 90% — browser scraper CDP fix
4. RESEARCH [PAUSE] Dormant since Mar 14
5. DECODED  [PAUSE] 0 trades | CLOB prices stale
6. CRYPTO   [BLOCKED] BLOCKED 3d: need Binance fetcher

WARNING: CRYPTO MOMENTUM blocked 3 days on same issue. Fix or park it.
WARNING: DECODED CRYPTO: 0 trades for 48h — check VPS logs.
```

## User Stories

1. As a multi-project trader, I want a daily Telegram message showing all my project statuses at a glance, so that I don't have to SSH into my VPS or open multiple repos to understand where things stand.

2. As a trader running paper strategies on VPS, I want live P&L, trade count, win rate, and fill count pulled directly from my trading logs, so that the dashboard reflects real performance — not stale snapshots.

3. As someone who struggles with execution paralysis, I want projects ranked by my manually-set priority order, so that I always know what to work on next.

4. As someone who starts things and doesn't finish them, I want the dashboard to nag me when a project has been blocked for multiple days, so that I either fix the blocker or consciously park the project.

5. As a trader, I want the Weather Bot scorecard to show signals fired, trades placed, P&L, and win rate, so that I can assess signal quality and execution at a glance.

6. As a market maker, I want the MM scorecard to show fills, P&L (realized + unrealized), and inventory exposure percentage, so that I can monitor market making health.

7. As a strategy decoder operator, I want the Decoded Crypto scorecard to show copied trades, P&L, and tracking error vs the original wallet, so that I know if the copy-trading is working.

8. As a crypto momentum trader, I want the Crypto Momentum scorecard to show trades, P&L, and active position count, so that I can monitor the ETH/SOL strategy.

9. As an equity engine developer, I want the Equity Engine status to show a brief text description (from git log or latest handoff), since it's not yet trading.

10. As an auto research developer, I want the Auto Research status to show last commit date and a brief description, since it's a code improvement tool not a trading system.

11. As a user, I want blocker detection that flags when a trading strategy has 0 trades for 48+ hours, so that I catch deployment failures or data source issues quickly.

12. As a user, I want blocker detection that flags when P&L hasn't changed for 3+ days, so that I catch strategies that are running but not actually trading.

13. As a user, I want blocker detection that flags when a non-trading project has no commits for 5+ days, so that I notice when I've abandoned something.

14. As a user, I want nagging alerts that escalate — mentioning how many days something has been stuck — so that I feel urgency proportional to the delay.

15. As a user, I want to be able to update the priority order by editing a simple config file, so that I can reprioritize without changing code.

16. As a user, I want the dashboard to run on a daily cron job on my VPS with zero manual intervention, so that I get the report even when I'm not actively working.

17. As a user, I want the Telegram message to be compact enough to read on my phone without scrolling, so that I can check status in 10 seconds.

18. As a user, I want a metrics history file (append-only) so that the blocker detector can compare today's metrics to yesterday's and detect stagnation.

19. As a user, I want the system to gracefully handle cases where a project's data files don't exist (e.g., strategy not deployed yet), showing "NOT DEPLOYED" instead of crashing.

20. As a user, I want the dashboard to show the date/time of the last successful data collection per project, so that I can tell if the collector itself is broken.

## Implementation Decisions

### Architecture

The system is a single Python application with 4 modules, deployed on the Hetzner VPS and run via daily cron.

### Module 1: MetricCollector

- **Interface:** `collect(project_config) -> ProjectMetrics`
- Reads TSV/log/state files directly from the VPS filesystem for trading workstreams
- For trading projects (weather, MM, decoded, crypto momentum): parses strategy-specific log files to extract P&L, trade count, win rate, fills, exposure
- For non-trading projects (equity engine, auto research): reads git log (last commit date, message) and parses latest handoff file if present
- Each project has a YAML/JSON config entry defining: project name, collector type (trading vs git), file paths, metric definitions
- Returns a standardized `ProjectMetrics` dataclass with both numeric metrics (for trading) and text status (for non-trading)
- Handles missing files gracefully — returns "NOT DEPLOYED" status

### Module 2: BlockerDetector

- **Interface:** `detect(current_metrics, metrics_history) -> List[Alert]`
- Reads metrics history from an append-only JSON lines file
- Applies configurable rules:
  - `no_trades_hours: 48` — alert if trading strategy has 0 new trades in this window
  - `stale_pnl_days: 3` — alert if P&L unchanged for this many days
  - `no_commits_days: 5` — alert if non-trading project has no new commits
- Each alert includes: project name, alert type, days stuck, suggested action
- Appends current metrics to history file after detection

### Module 3: StatusEngine

- **Interface:** `generate_report(all_metrics, alerts, priority_order) -> DailyReport`
- Takes metrics from all 6 workstreams + alerts from BlockerDetector
- Orders projects by priority (read from config file)
- Assigns status emoji per project: OK (healthy), WIP (in progress, non-trading), PAUSE (dormant/no activity), BLOCKED (blocked)
- Formats the compact scorecard string
- Appends nagging messages for any active alerts

### Module 4: TelegramReporter

- **Interface:** `send(report: DailyReport) -> bool`
- Uses a NEW dedicated Telegram bot (separate from equity engine bot)
- Sends the formatted scorecard via Telegram Bot API
- Returns success/failure for logging
- Bot token and chat ID stored in config file (not hardcoded)

### Configuration

Single YAML config file defining:
- Project list with name, priority, collector type, file paths, metric keys
- Blocker detection thresholds
- Telegram bot token and chat ID
- Cron schedule (default: daily at 08:00 local time)

### Data Flow

```
Cron (daily) -> main.py
  -> MetricCollector.collect() for each project
  -> BlockerDetector.detect() against history
  -> StatusEngine.generate_report()
  -> TelegramReporter.send()
  -> Append metrics to history file
```

### Project Configs

| Project | Collector Type | Key Metrics | Source Files |
|---------|---------------|-------------|-------------|
| Weather Bot | trading | signals, trades, P&L, win rate | signal_log.tsv, paper_trades.tsv |
| Market Maker | trading | fills, P&L, exposure | mm_paper_*.log, state files |
| Decoded Crypto | trading | trades, P&L, tracking error | paper_trader state files |
| Crypto Momentum | trading | trades, P&L, positions | momentum trader state files |
| Equity Engine | git | last commit, branch, handoff summary | git log of conviction-equity-engine |
| Auto Research | git | last commit, branch | git log of autoresearch |

### VPS Deployment

- Deployed to `/root/ops-dashboard/` on the Hetzner VPS
- Cron entry: `0 8 * * * cd /root/ops-dashboard && python main.py >> /var/log/ops-dashboard.log 2>&1`
- Reads other project data from their VPS paths (e.g., `/root/polymarket-kalshi-weather-bot/`, `/opt/wx-bot/`)
- For local-only repos (equity engine, auto research): requires those repos to be cloned on VPS OR uses GitHub API to check last commit

## Testing Decisions

### What makes a good test
Tests should verify external behavior through the module's public interface, not implementation details. Use real fixture files (recorded from actual VPS data) rather than mocks. Each test should be independent and idempotent.

### Modules to test

**MetricCollector (HIGH priority)**
- Parse real TSV fixtures for each trading strategy type
- Verify correct P&L, trade count, win rate extraction
- Verify graceful handling of missing files, empty files, malformed data
- Verify git-based collection returns correct last commit info

**BlockerDetector (HIGH priority)**
- Verify no-trades alert fires after configured threshold
- Verify stale-P&L alert fires when P&L unchanged
- Verify no-commits alert fires for dormant projects
- Verify no false alerts when metrics are healthy
- Verify day-count accuracy in alert messages

**StatusEngine (LOW priority — thin glue)**
- Verify priority ordering matches config
- Verify correct emoji assignment per status type

**TelegramReporter (NO unit tests)**
- Integration test only (send to a test channel)
- Too thin to warrant unit tests

### Test fixtures
- Record actual TSV/log snippets from VPS for each strategy type
- Store in `tests/fixtures/` directory
- No mocking — use real file parsing against real data formats

## Out of Scope

- **Repo splitting** — existing mono-repo stays as-is. This dashboard tracks workstreams within it, not repo boundaries.
- **Web dashboard / HTML UI** — Telegram-only for now. No browser-based dashboard.
- **Automated remediation** — the dashboard detects and reports blockers, it does not fix them.
- **Real-money trading metrics** — paper trading only. When strategies go live, metric sources may change.
- **Historical charting / trend graphs** — metrics history is stored for blocker detection, but no visualization is built.
- **Cross-project dependency tracking** — projects are tracked independently even though they share code.

## Further Notes

- The priority order as of 2026-03-20 is: Weather Bot > Market Maker > Equity Engine > Auto Research > Decoded Crypto > Crypto Momentum. This is user-defined and can be changed via config.
- The system should be resilient to individual project failures — if one collector fails, the others should still run and the report should note which one failed.
- Telegram message must fit on one phone screen without scrolling (~15-20 lines max).
- Future enhancement: add a `/status` command to the Telegram bot for on-demand reports (not in scope for V1).
- Future enhancement: weekly summary with trend arrows comparing this week to last week.