# Ops Dashboard V1 — Implementation Plan

**PRD:** https://github.com/Magicalmeow/ops-dashboard/issues/1
**Created:** 2026-03-20

## Phase 1: Project Scaffolding + Config + Dataclasses

- [x] Create project structure: `src/`, `tests/`, `tests/fixtures/`, `config/`
- [x] Create `config/projects.yaml` with all 6 project definitions
- [x] Create `src/models.py` — `ProjectMetrics`, `Alert`, `DailyReport` dataclasses
- [x] Create `requirements.txt` (pyyaml, requests)
- [x] Create `main.py` entry point (skeleton)

### Success criteria
- `python -c "from src.models import ProjectMetrics, Alert, DailyReport"` works

## Phase 2: MetricCollector — All Trading Collectors

- [x] Create `src/collectors/base.py` — `BaseCollector` interface
- [x] Create `src/collectors/weather.py` — parses `signal_log.tsv` + `paper_trades.tsv`
  - Metrics: signals_fired (passes_threshold=True count), trades (row count), P&L (sum from portfolio state), win_rate
- [x] Create `src/collectors/market_maker.py` — parses `equity_curve.tsv` + latest `paper_session_*.json`
  - Metrics: fills, P&L (equity - starting_cash), exposure (inventory_value/equity), return_pct
- [x] Create `src/collectors/decoded.py` — parses `data_cache/paper_trading/*_trades.tsv` + `*_state.json`
  - Metrics: trades (resolved rows), P&L (sum of pnl column), win_rate, open_positions
- [x] Create `src/collectors/momentum.py` — parses `data_cache/momentum_trading/momentum_trades.tsv` + `momentum_state.json`
  - Metrics: trades, P&L (sum net_pnl), positions, win_rate
- [x] Create `src/collectors/__init__.py` with factory function
- [x] Create test fixtures from real file formats in `tests/fixtures/`
- [x] Write tests for all 4 trading collectors

### VPS File Paths (from codebase analysis)

| Strategy | Files | VPS Path Prefix |
|----------|-------|-----------------|
| Weather | signal_log.tsv, paper_trades.tsv, data_cache/weather_paper/*_state.json | /opt/wx-bot/ OR /root/polymarket-kalshi-weather-bot/ |
| MM | data_cache/mm_paper/equity_curve.tsv, research/mm_research/data/paper_session_*.json | /root/polymarket-kalshi-weather-bot/ |
| Decoded | data_cache/paper_trading/*_trades.tsv, *_state.json | /root/polymarket-kalshi-weather-bot/ |
| Momentum | data_cache/momentum_trading/momentum_trades.tsv, momentum_state.json | /root/polymarket-kalshi-weather-bot/ |

### Success criteria
- All trading collector tests pass
- `python -c "from src.collectors import create_collector"` works

## Phase 3: Git-Based Collectors

- [x] Create `src/collectors/git_collector.py` — reads git log + latest handoff
  - Uses subprocess to run `git -C <repo_path> log -1 --format='%H|%ai|%s'`
  - Parses latest handoff file from `handoffs/` directory
  - Metrics: last_commit_date, last_commit_message, handoff_summary (if exists)
- [ ] Write tests for git collector (skipped — requires real git repo fixture)

### Success criteria
- Git collector test passes with a mock repo directory

## Phase 4: BlockerDetector

- [x] Create `src/blocker_detector.py`
  - Reads metrics history from `data/metrics_history.jsonl`
  - Rules: no_trades_hours (48), stale_pnl_days (3), no_commits_days (5)
  - Returns List[Alert] with project_name, alert_type, days_stuck, message
  - Appends current metrics to history
- [x] Write tests for all detection rules

### Success criteria
- All blocker detector tests pass
- Correctly identifies stale, blocked, and healthy states

## Phase 5: StatusEngine + TelegramReporter

- [x] Create `src/status_engine.py`
  - Takes all metrics + alerts + priority order
  - Assigns status: OK, WIP, PAUSE, BLOCKED
  - Formats compact scorecard string (fits phone screen)
- [x] Create `src/telegram_reporter.py`
  - Sends scorecard via Telegram Bot API (requests, no SDK)
  - Config: bot_token, chat_id from YAML
- [x] Write test for StatusEngine formatting

### Success criteria
- StatusEngine produces correct scorecard format
- TelegramReporter sends successfully (integration test, manual)

## Phase 6: Main Entry Point + Integration

- [x] Wire up `main.py`: load config → collect all → detect blockers → generate report → send
- [x] Graceful error handling: if one collector fails, others still run
- [x] Logging to stdout (cron will capture)
- [x] End-to-end dry-run test

### Success criteria
- `python main.py --dry-run` prints a correctly formatted scorecard
- `python main.py` sends to Telegram (requires bot setup)

## Phase 7: VPS Deployment

- [x] Create `deploy.sh` script (rsync to VPS, install deps, set up cron)
- [ ] Document Telegram bot setup steps in README
- [ ] Set up cron: `0 8 * * * cd /root/ops-dashboard && python main.py`
- [ ] Clone equity-engine + autoresearch repos on VPS

### Success criteria
- Script deploys to VPS successfully
- Cron fires and sends first real report
