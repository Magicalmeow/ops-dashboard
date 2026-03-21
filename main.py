"""Ops Dashboard — Daily project status reporter.

Usage:
  python main.py              # Collect metrics, detect blockers, send to Telegram
  python main.py --dry-run    # Print scorecard to stdout, don't send
  python main.py --bot        # Run Telegram bot (long-polling, responds to /update)
"""

import logging
import os
import sys

import yaml

from src.collectors import create_collector
from src.blocker_detector import BlockerDetector
from src.models import ProjectMetrics
from src.status_engine import StatusEngine
from src.telegram_reporter import TelegramReporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_config(path: str = None) -> dict:
    """Load project config from YAML."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "config", "projects.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def collect_all(config: dict) -> list[ProjectMetrics]:
    """Run all collectors, catching per-project errors."""
    results = []
    for project in config["projects"]:
        try:
            collector = create_collector(project)
            metrics = collector.collect()
        except Exception as e:
            metrics = ProjectMetrics(
                project_name=project["name"],
                collector_type=project.get("collector_type", "unknown"),
                healthy=False,
                error=f"Collector init failed: {e}",
            )
        results.append(metrics)
    return results


def generate_report(config: dict) -> "DailyReport":
    """Collect metrics and generate a full report."""
    from datetime import datetime
    metrics = collect_all(config)

    # Detect blockers
    history_path = os.path.join(os.path.dirname(__file__), "data", "metrics_history.jsonl")
    thresholds = config.get("blocker_thresholds", {})
    detector = BlockerDetector(history_path, thresholds)
    alerts = detector.detect(metrics)

    # Generate report
    priority_order = [p["name"] for p in sorted(config["projects"], key=lambda p: p["priority"])]
    engine = StatusEngine()
    return engine.generate_report(metrics, alerts, priority_order)


def main():
    dry_run = "--dry-run" in sys.argv
    bot_mode = "--bot" in sys.argv

    # Load config
    config = load_config()

    if bot_mode:
        # Run as long-polling Telegram bot
        tg_config = config.get("telegram", {})
        reporter = TelegramReporter(
            bot_token=tg_config.get("bot_token", ""),
            chat_id=tg_config.get("chat_id", ""),
        )
        reporter.run_bot(lambda: generate_report(config))
        return

    # Normal mode: collect once, send
    print("[dashboard] Collecting metrics...")
    report = generate_report(config)

    for m in report.project_metrics:
        status = "OK" if m.healthy else f"ERROR: {m.error}"
        print(f"  {m.project_name}: {status}")

    print()
    print(report.scorecard)
    print()

    if dry_run:
        print("[dashboard] Dry run — not sending to Telegram.")
        # Still show Notion dry-run output
        _push_notion(report, config, dry_run=True)
        return

    # Send to Telegram
    tg_config = config.get("telegram", {})
    reporter = TelegramReporter(
        bot_token=tg_config.get("bot_token", ""),
        chat_id=tg_config.get("chat_id", ""),
    )
    reporter.send(report)

    # Push to Notion (opt-in, won't block Telegram)
    _push_notion(report, config)


def _push_notion(report, config: dict, dry_run: bool = False):
    """Push report to Notion if configured. Failures are logged, never fatal."""
    if not os.environ.get("NOTION_TOKEN"):
        return
    try:
        from src.notion_reporter import NotionReporter
        notion_config = config.get("notion", {})
        notion = NotionReporter(
            page_id=notion_config.get("page_id", ""),
        )
        notion.push(report, dry_run=dry_run)
    except Exception as e:
        logging.error(f"Notion push failed (non-fatal): {e}")


if __name__ == "__main__":
    main()
