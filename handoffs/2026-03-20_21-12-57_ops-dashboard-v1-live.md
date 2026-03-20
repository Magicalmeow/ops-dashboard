---
date: 2026-03-20T21:12:57Z
git_commit: 20c2a01
branch: master
repository: C:\Claude Code\ops-dashboard (github.com/Magicalmeow/ops-dashboard)
---

# Handoff: Ops Dashboard V1 — Built, Deployed, Live on Telegram

## Task(s)

**COMPLETED:**
- Grilled user on design (10 questions, resolved all branches)
- Wrote PRD and submitted as GitHub issue #1
- Created 6 implementation issues (#2-#7) as vertical slices
- Built entire system: 4 modules, 6 collectors, 21 tests
- Fixed collectors against real VPS data (format mismatches)
- Deployed to VPS, sent first Telegram report, cron set for daily 08:00 UTC

**IN-PROGRESS / REMAINING:**
- Issue #2 (Telegram bot) — DONE, credentials obtained and configured
- Issue #7 (VPS deploy) — 90% done, two minor issues remain (see below)

**Plan:** `plans/2026-03-20-ops-dashboard-v1.md` — Phases 1-6 complete, Phase 7 mostly complete

## Critical References
- `PRD.md` — Full product requirements with all design decisions
- `config/projects.yaml` — All 6 project configs with VPS paths
- `plans/2026-03-20-ops-dashboard-v1.md` — Implementation plan with checkboxes

## Recent Changes
- `src/collectors/weather.py` — Fixed fallback path for portfolio_state_dir (not just files), fixed timezone-aware timestamp parsing
- `src/collectors/market_maker.py` — Handles new session JSON format (`realized`/`unrealized`/`net_total` keys instead of `starting_cash`/`equity`)
- `src/collectors/git_collector.py` — Replaced `gh` CLI dependency with `curl` to GitHub API, handles private repos gracefully
- `src/collectors/momentum.py:51` — Fixed `(row.get("resolved") or "").strip()` for None values

## Key Decisions
| Decision | Rationale |
|----------|-----------|
| Track workstreams within mono-repo, not split repos | Splitting would be 2-3 day yak-shave; mono-repo stays as-is, new strategies get separate repos going forward |
| Manual priority order (not computed) | User knows their priorities; Weather > MM > Equity > AutoResearch > Decoded > Momentum |
| Telegram compact scorecard (not web dashboard) | User wants phone-glanceable daily push, not another thing to check |
| Nag when blocked 2+ days | User self-identifies as having execution paralysis, wants to be nagged |
| curl for GitHub API instead of gh CLI | gh not installed on VPS and requires auth setup; curl works for public repos |
| New Telegram bot (not reusing equity engine bot) | Clean separation of concerns |

## Failed Approaches
- **Tried:** Using `gh` CLI for GitHub API fallback in git collector
  **Why it failed:** `gh` not installed on VPS, error `[Errno 2] No such file or directory: 'gh'`
  **Lesson:** Replaced with `curl -sf` to GitHub API. Works for public repos. Private repos (equity-engine, autoresearch) need either: clone on VPS, install gh with auth, or use GitHub PAT in curl headers.

- **Tried:** Assuming weather bot timestamps were naive (no timezone)
  **Why it failed:** Real VPS data has `+00:00` timezone suffix. `datetime.fromisoformat()` returns tz-aware datetime, comparison with naive `datetime.utcnow()` would fail.
  **Lesson:** Strip timezone with `.replace(tzinfo=None)` before comparing to naive cutoff.

- **Tried:** Assuming MM session JSON has `starting_cash`/`equity` keys
  **Why it failed:** Real format uses `realized`/`unrealized`/`net_total`/`flatten_cost`/`reward_estimate`
  **Lesson:** Always check real VPS data before writing parsers. The fixture-based tests passed but real format was different.

- **Tried:** `rsync` for deployment
  **Why it failed:** `rsync` not installed in Git Bash on Windows
  **Lesson:** Used `scp` per-file instead. Works fine for small project.

## Learnings
- Weather paper trader generates ~12K trades per day (all from today). This is not a bug — the paper_trades.tsv is an entry audit log with a row per signal per city per bracket.
- MM paper session has $196K P&L with 53K fills — these are paper numbers, not real.
- All weather portfolio state files are at `/opt/wx-bot/data_cache/weather_paper/` (the fallback path), NOT at the main repo path. The config `fallback_base: "/opt/wx-bot"` is critical.
- `pip install` on VPS requires venv (Debian's externally-managed-environment policy).
- Python on Windows is at `/c/Users/MingC/AppData/Roaming/uv/python/cpython-3.12.13-windows-x86_64-none/python.exe` — must use `uv venv` to create local venvs.
- Telegram Bot API: MarkdownV2 parse_mode fails silently on special chars. The reporter has a plain-text fallback.

## Current State
- **What works:**
  - All 6 collectors run on VPS and produce real metrics
  - BlockerDetector correctly identifies 0-trade and stale strategies
  - StatusEngine formats compact scorecard
  - TelegramReporter sends successfully (first message delivered)
  - Daily cron at 08:00 UTC configured
  - 21/21 tests passing locally
  - Metrics history appending to `data/metrics_history.jsonl`

- **What's broken:**
  - Equity Engine shows "GitHub API check failed" — repo is private, curl can't access without auth
  - Auto Research shows same — private repo, no auth
  - MM shows [BLOCKED] with alert "0 trades for 2d" — but it has 53K fills. The blocker detector checks `trades` field which is 0 for MM (MM doesn't resolve trades the same way). Should check `fills` instead for MM collector type.

- **Blocking issues:**
  - None for daily operation — the report sends, just with degraded data for 2 projects

## Artifacts
- `PRD.md` — Full product requirements document
- `config/projects.yaml` — Project configurations with VPS paths
- `plans/2026-03-20-ops-dashboard-v1.md` — Implementation plan (mostly checked off)
- `main.py` — Entry point with --dry-run flag
- `src/models.py` — ProjectMetrics, Alert, DailyReport dataclasses
- `src/collectors/` — 5 collectors (weather, market_maker, decoded, momentum, git_collector)
- `src/blocker_detector.py` — Stagnation detection with JSONL history
- `src/status_engine.py` — Scorecard formatter with priority ordering
- `src/telegram_reporter.py` — Telegram Bot API sender with plain-text fallback
- `tests/test_collectors.py` — 12 tests for all trading collectors
- `tests/test_blocker_detector.py` — 10 tests for blocker detection + status engine
- `tests/fixtures/` — 8 fixture files matching real VPS formats
- `deploy.sh` — Deployment script (rsync-based, needs scp fallback on Windows)
- GitHub issues #1-#7 on Magicalmeow/ops-dashboard

## Telegram Credentials
- Bot token: `8652138549:AAHvEiqSx_ihKh2ZNm6hmbF8cdWQ3p7-Vgk`
- Chat ID: `5274007358`
- Configured in VPS crontab inline (not in .bashrc — cron doesn't source it)

## Action Items & Next Steps
1. **Fix MM blocker false alarm** — In `blocker_detector.py`, for `trading_mm` collector type, check `fills > 0` instead of `trades > 0` to determine activity. MM uses fills, not resolved trades.
2. **Fix Equity Engine / Auto Research visibility** — Either:
   - (a) Clone both repos on VPS: `git clone https://<PAT>@github.com/Magicalmeow/conviction-equity-engine.git /root/conviction-equity-engine`
   - (b) Or add GitHub PAT to curl headers in git_collector.py: `curl -H "Authorization: token <PAT>" ...`
   - Option (a) is better because it also enables handoff parsing.
3. **Commit the updated plan file** — `plans/2026-03-20-ops-dashboard-v1.md` has uncommitted checkbox updates.
4. **Consider reducing weather trade count display** — 12K trades/day is noise. Maybe show "12.1K" or only count trades that passed threshold.
5. **Future: Add `/status` Telegram command** — For on-demand reports instead of waiting for daily cron.

## Other Notes
- User priority order (set 2026-03-20): Weather Bot > Market Maker > Equity Engine > Auto Research > Decoded Crypto > Crypto Momentum
- User feedback saved to memory: never combine new strategies into a single repo going forward
- Memory file `project_priority_ranking.md` created with the priority order
- The user's VPS is at 178.156.235.253 (Hetzner), SSH as root
- VPS Python venv: `/root/ops-dashboard/.venv/bin/python`
