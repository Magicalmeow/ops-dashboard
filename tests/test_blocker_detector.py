"""Tests for the blocker detection engine."""

import json
import os
import tempfile
from datetime import datetime, timedelta

import pytest
import yaml

from src.blocker_detector import BlockerDetector
from src.models import ProjectMetrics


class TestBlockerDetector:

    def _make_detector(self, history_entries=None, **kwargs):
        """Create a detector with optional pre-populated history."""
        tmpdir = tempfile.mkdtemp()
        history_path = os.path.join(tmpdir, "history.jsonl")
        if history_entries:
            with open(history_path, "w") as f:
                for entry in history_entries:
                    f.write(json.dumps(entry) + "\n")

        thresholds = {
            "no_trades_hours": kwargs.get("no_trades_hours", 48),
            "stale_pnl_days": kwargs.get("stale_pnl_days", 3),
            "no_commits_days": kwargs.get("no_commits_days", 5),
        }
        return BlockerDetector(history_path, thresholds), history_path

    def test_no_alerts_when_healthy(self):
        detector, _ = self._make_detector()
        metrics = [
            ProjectMetrics(
                project_name="Weather Bot",
                collector_type="trading_weather",
                trades=5,
                pnl=50.0,
                open_positions=2,
            ),
        ]
        alerts = detector.detect(metrics)
        assert len(alerts) == 0

    def test_no_trades_alert(self):
        # History: 3 days of 0 trades
        history = [
            {"project_name": "Weather Bot", "trades": 0, "pnl": 0.0,
             "collected_at": (datetime.utcnow() - timedelta(days=i)).isoformat()}
            for i in range(3)
        ]
        detector, _ = self._make_detector(history)
        metrics = [
            ProjectMetrics(
                project_name="Weather Bot",
                collector_type="trading_weather",
                trades=0,
                pnl=0.0,
                open_positions=0,
            ),
        ]
        alerts = detector.detect(metrics)
        no_trade_alerts = [a for a in alerts if a.alert_type == "no_trades"]
        assert len(no_trade_alerts) == 1
        assert no_trade_alerts[0].days_stuck >= 2

    def test_stale_pnl_alert(self):
        # History: 4 days of same P&L
        history = [
            {"project_name": "MM", "trades": 0, "pnl": 26.60,
             "collected_at": (datetime.utcnow() - timedelta(days=i)).isoformat()}
            for i in range(4)
        ]
        detector, _ = self._make_detector(history)
        metrics = [
            ProjectMetrics(
                project_name="MM",
                collector_type="trading_mm",
                trades=0,
                pnl=26.60,
            ),
        ]
        alerts = detector.detect(metrics)
        stale_alerts = [a for a in alerts if a.alert_type == "stale_pnl"]
        assert len(stale_alerts) == 1
        assert stale_alerts[0].days_stuck >= 3

    def test_no_commits_alert(self):
        detector, _ = self._make_detector()
        metrics = [
            ProjectMetrics(
                project_name="Auto Research",
                collector_type="git",
                last_commit_date=datetime.utcnow() - timedelta(days=10),
                last_commit_message="old commit",
            ),
        ]
        alerts = detector.detect(metrics)
        commit_alerts = [a for a in alerts if a.alert_type == "no_commits"]
        assert len(commit_alerts) == 1
        assert commit_alerts[0].days_stuck >= 5

    def test_no_false_alert_for_recent_commit(self):
        detector, _ = self._make_detector()
        metrics = [
            ProjectMetrics(
                project_name="Equity Engine",
                collector_type="git",
                last_commit_date=datetime.utcnow() - timedelta(days=2),
                last_commit_message="recent work",
            ),
        ]
        alerts = detector.detect(metrics)
        assert len(alerts) == 0

    def test_collector_error_alert(self):
        detector, _ = self._make_detector()
        metrics = [
            ProjectMetrics(
                project_name="Broken",
                collector_type="trading_weather",
                healthy=False,
                error="File not found",
            ),
        ]
        alerts = detector.detect(metrics)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "collector_error"

    def test_appends_to_history(self):
        detector, history_path = self._make_detector()
        metrics = [
            ProjectMetrics(
                project_name="Test",
                collector_type="trading_weather",
                trades=5,
                pnl=100.0,
            ),
        ]
        detector.detect(metrics)

        with open(history_path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["project_name"] == "Test"
        assert entry["trades"] == 5
        assert entry["pnl"] == 100.0


class TestStatusEngine:

    def test_scorecard_format(self):
        from src.status_engine import StatusEngine
        metrics = [
            ProjectMetrics(
                project_name="Weather Bot",
                collector_type="trading_weather",
                signals=4, trades=2, pnl=12.0, win_rate=0.75,
            ),
            ProjectMetrics(
                project_name="Market Maker",
                collector_type="trading_mm",
                fills=167, pnl=26.0, exposure_pct=26.0,
            ),
        ]
        engine = StatusEngine()
        report = engine.generate_report(
            metrics, [], ["Weather Bot", "Market Maker"],
        )
        assert "WEATHER BOT" in report.scorecard
        assert "MARKET MAKER" in report.scorecard
        assert "4 signals" in report.scorecard
        assert "167 fills" in report.scorecard

    def test_priority_ordering(self):
        from src.status_engine import StatusEngine
        metrics = [
            ProjectMetrics(project_name="B", collector_type="git", status_text="second"),
            ProjectMetrics(project_name="A", collector_type="git", status_text="first"),
        ]
        engine = StatusEngine()
        report = engine.generate_report(metrics, [], ["A", "B"])
        lines = report.scorecard.split("\n")
        project_lines = [l for l in lines if l.strip().startswith(("1.", "2."))]
        assert "A" in project_lines[0]
        assert "B" in project_lines[1]

    def test_nag_alerts_appended(self):
        from src.models import Alert
        from src.status_engine import StatusEngine
        metrics = [
            ProjectMetrics(project_name="Stuck", collector_type="trading_weather"),
        ]
        alerts = [
            Alert(project_name="Stuck", alert_type="no_trades", days_stuck=5,
                  message="0 trades for 5d"),
        ]
        engine = StatusEngine()
        report = engine.generate_report(metrics, alerts, ["Stuck"])
        assert "0 trades for 5d" in report.scorecard


class TestThresholdsFromConfig:
    """Verify that blocker thresholds are driven by projects.yaml (issue #6).

    The acceptance criterion "Thresholds configurable via projects.yaml" requires
    that changing threshold values in config changes detector behaviour — i.e. the
    thresholds are NOT hardcoded anywhere in the detector.
    """

    def _detector_from_yaml(self, yaml_text: str):
        """Build a BlockerDetector using thresholds parsed from a YAML string."""
        config = yaml.safe_load(yaml_text)
        thresholds = config.get("blocker_thresholds", {})
        tmpdir = tempfile.mkdtemp()
        history_path = os.path.join(tmpdir, "history.jsonl")
        return BlockerDetector(history_path, thresholds)

    def test_no_trades_threshold_respected(self):
        """A tight no_trades_hours=24 triggers after 1 day; default 48 would not."""
        yaml_text = """
blocker_thresholds:
  no_trades_hours: 24
  stale_pnl_days: 3
  no_commits_days: 5
"""
        detector = self._detector_from_yaml(yaml_text)
        # Provide 1 day of history with 0 trades
        history = [{"project_name": "WX", "trades": 0, "pnl": 0.0,
                    "collected_at": (datetime.utcnow() - timedelta(days=1)).isoformat()}]
        tmpdir = tempfile.mkdtemp()
        hp = os.path.join(tmpdir, "h.jsonl")
        with open(hp, "w") as f:
            for e in history:
                f.write(json.dumps(e) + "\n")
        detector.history_path = hp

        metrics = [ProjectMetrics(project_name="WX", collector_type="trading_weather",
                                  trades=0, pnl=0.0, open_positions=0)]
        alerts = detector.detect(metrics)
        no_trade_alerts = [a for a in alerts if a.alert_type == "no_trades"]
        assert len(no_trade_alerts) == 1, "tight threshold should fire"

    def test_no_trades_threshold_not_triggered_when_loose(self):
        """A loose no_trades_hours=240 (10d) does NOT fire after 1 day of zero trades."""
        yaml_text = """
blocker_thresholds:
  no_trades_hours: 240
  stale_pnl_days: 3
  no_commits_days: 5
"""
        detector = self._detector_from_yaml(yaml_text)
        # Only 1 day of history with 0 trades — well under 240h threshold
        history = [{"project_name": "WX", "trades": 0, "pnl": 0.0,
                    "collected_at": (datetime.utcnow() - timedelta(days=1)).isoformat()}]
        tmpdir = tempfile.mkdtemp()
        hp = os.path.join(tmpdir, "h.jsonl")
        with open(hp, "w") as f:
            for e in history:
                f.write(json.dumps(e) + "\n")
        detector.history_path = hp

        metrics = [ProjectMetrics(project_name="WX", collector_type="trading_weather",
                                  trades=0, pnl=0.0, open_positions=0)]
        alerts = detector.detect(metrics)
        no_trade_alerts = [a for a in alerts if a.alert_type == "no_trades"]
        assert len(no_trade_alerts) == 0, "loose threshold must not fire prematurely"

    def test_projects_yaml_thresholds_loaded_correctly(self):
        """The shipped projects.yaml has the correct default thresholds."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "projects.yaml"
        )
        with open(config_path) as f:
            config = yaml.safe_load(f)

        thresholds = config.get("blocker_thresholds", {})
        assert thresholds.get("no_trades_hours") == 48
        assert thresholds.get("stale_pnl_days") == 3
        assert thresholds.get("no_commits_days") == 5
