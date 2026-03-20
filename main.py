"""Ops Dashboard — Daily project status reporter.

Usage:
  python main.py              # Collect metrics, detect blockers, send to Telegram
  python main.py --dry-run    # Print scorecard to stdout, don't send
"""

import os
import sys

import yaml

from src.collectors import create_collector
from src.blocker_detector import BlockerDetector
from src.models import ProjectMetrics
from src.status_engine import StatusEngine
from src.telegram_reporter import TelegramReporter


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


def main():
    dry_run = "--dry-run" in sys.argv

    # Load config
    config = load_config()

    # Collect metrics from all projects
    print("[dashboard] Collecting metrics...")
    metrics = collect_all(config)

    for m in metrics:
        status = "OK" if m.healthy else f"ERROR: {m.error}"
        print(f"  {m.project_name}: {status}")

    # Detect blockers
    history_path = os.path.join(os.path.dirname(__file__), "data", "metrics_history.jsonl")
    thresholds = config.get("blocker_thresholds", {})
    detector = BlockerDetector(history_path, thresholds)
    alerts = detector.detect(metrics)

    if alerts:
        print(f"[dashboard] {len(alerts)} alert(s) detected:")
        for a in alerts:
            print(f"  {a.project_name}: {a.message}")

    # Generate report
    priority_order = [p["name"] for p in sorted(config["projects"], key=lambda p: p["priority"])]
    engine = StatusEngine()
    report = engine.generate_report(metrics, alerts, priority_order)

    # Output
    print()
    print(report.scorecard)
    print()

    if dry_run:
        print("[dashboard] Dry run — not sending to Telegram.")
        return

    # Send to Telegram
    tg_config = config.get("telegram", {})
    reporter = TelegramReporter(
        bot_token=tg_config.get("bot_token", ""),
        chat_id=tg_config.get("chat_id", ""),
    )
    reporter.send(report)


if __name__ == "__main__":
    main()
