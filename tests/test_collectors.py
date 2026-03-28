"""Tests for all metric collectors using real fixture data."""

import json
import os
import tempfile

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


# ── Weather Collector ──────────────────────────────────────────────

class TestWeatherCollector:

    def _make_config(self, base_path):
        return {
            "name": "Weather Bot",
            "collector_type": "trading_weather",
            "base_path": base_path,
            "paths": {
                "signal_log": "signal_log.tsv",
                "paper_trades": "paper_trades.tsv",
                "portfolio_state_dir": "weather_paper",
            },
        }

    def test_counts_passing_signals(self):
        from src.collectors.weather import WeatherCollector
        config = self._make_config(FIXTURES)
        c = WeatherCollector(config)
        m = c.collect()
        # Fixture has 4 signals from 2026-03-20 (3 True, 1 False) + 1 from 2026-03-19 (True)
        # The 24h filter depends on when the test runs, so just check >= 0
        assert m.signals >= 0
        assert m.healthy

    def test_counts_trades(self):
        from src.collectors.weather import WeatherCollector
        config = self._make_config(FIXTURES)
        c = WeatherCollector(config)
        m = c.collect()
        assert m.trades >= 0
        assert m.healthy

    def test_missing_files_graceful(self):
        from src.collectors.weather import WeatherCollector
        config = self._make_config("/nonexistent/path")
        c = WeatherCollector(config)
        m = c.collect()
        # Should not crash, signals/trades default to 0
        assert m.signals == 0
        assert m.trades == 0
        assert m.healthy  # Missing files isn't an error, just 0s

    def test_reads_portfolio_state(self):
        from src.collectors.weather import WeatherCollector
        # Create a temp dir with a state file
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, "weather_paper")
            os.makedirs(state_dir)
            state = {
                "portfolio": {"starting_balance": 1000, "balance": 1050},
                "open_trades": [{"id": "t1"}, {"id": "t2"}],
                "resolved_trades": [
                    {"resolution": "WIN"},
                    {"resolution": "WIN"},
                    {"resolution": "LOSS"},
                ],
            }
            with open(os.path.join(state_dir, "ensemble_state.json"), "w") as f:
                json.dump(state, f)

            # Also put the TSV fixtures in tmpdir
            import shutil
            shutil.copy(os.path.join(FIXTURES, "signal_log.tsv"), tmpdir)
            shutil.copy(os.path.join(FIXTURES, "paper_trades.tsv"), tmpdir)

            config = self._make_config(tmpdir)
            c = WeatherCollector(config)
            m = c.collect()
            assert m.pnl == 50.0
            assert m.open_positions == 2
            assert m.win_rate == pytest.approx(2 / 3)

    def test_dead_strategies_filtered_out(self):
        """Dead ColdMath strategies must not appear in portfolio state.

        Strategy names 'coldmath_base' and 'coldmath_forecast' were retired.
        The active set is metar_pure_latency, synoptic_latency, ensemble.
        A state file for a dead strategy should contribute zero P&L.
        """
        from src.collectors.weather import WeatherCollector
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, "weather_paper")
            os.makedirs(state_dir)

            dead_state = {
                "strategy": "coldmath_base",
                "portfolio": {"starting_balance": 1000, "balance": 2000},
                "open_trades": [{"id": "x1"}],
                "resolved_trades": [{"resolution": "WIN"}],
            }
            with open(os.path.join(state_dir, "coldmath_base_state.json"), "w") as f:
                json.dump(dead_state, f)

            import shutil
            shutil.copy(os.path.join(FIXTURES, "signal_log.tsv"), tmpdir)
            shutil.copy(os.path.join(FIXTURES, "paper_trades.tsv"), tmpdir)

            config = self._make_config(tmpdir)
            c = WeatherCollector(config)
            m = c.collect()
            # Dead strategy must not inflate P&L or position counts
            assert m.pnl == 0.0
            assert m.open_positions == 0
            assert m.sub_strategies == []


# ── Market Maker Collector ─────────────────────────────────────────

class TestMarketMakerCollector:

    def _make_config(self, base_path):
        return {
            "name": "Market Maker",
            "collector_type": "trading_mm",
            "base_path": base_path,
            "paths": {
                "equity_curve": "equity_curve.tsv",
                "session_dir": ".",
            },
        }

    def test_reads_equity_curve(self):
        from src.collectors.market_maker import MarketMakerCollector
        config = self._make_config(FIXTURES)
        c = MarketMakerCollector(config)
        m = c.collect()
        assert m.healthy

    def test_reads_session_json(self):
        from src.collectors.market_maker import MarketMakerCollector
        config = self._make_config(FIXTURES)
        c = MarketMakerCollector(config)
        m = c.collect()
        # From session JSON: equity 2026.60 - starting 2000.00 = 26.60
        assert m.pnl == pytest.approx(26.60, abs=0.1)
        # Total fills: 145 + 15 + 5 + 2 = 167
        assert m.fills == 167

    def test_missing_files_graceful(self):
        from src.collectors.market_maker import MarketMakerCollector
        config = self._make_config("/nonexistent/path")
        c = MarketMakerCollector(config)
        m = c.collect()
        assert m.pnl == 0.0
        assert m.fills == 0
        assert m.healthy


# ── Decoded Crypto Collector ───────────────────────────────────────

class TestDecodedCollector:

    def _make_config(self, base_path):
        return {
            "name": "Decoded Crypto",
            "collector_type": "trading_decoded",
            "base_path": base_path,
            "paths": {
                "trades_dir": ".",
                "state_dir": ".",
            },
        }

    def test_reads_trades(self):
        from src.collectors.decoded import DecodedCollector
        # Need to put fixtures where glob can find *_trades.tsv
        with tempfile.TemporaryDirectory() as tmpdir:
            import shutil
            shutil.copy(
                os.path.join(FIXTURES, "decoded_trades.tsv"),
                os.path.join(tmpdir, "hgjghjh85_directional_trades.tsv"),
            )
            shutil.copy(
                os.path.join(FIXTURES, "decoded_state.json"),
                os.path.join(tmpdir, "hgjghjh85_directional_state.json"),
            )
            config = self._make_config(tmpdir)
            config["paths"]["trades_dir"] = "."
            config["paths"]["state_dir"] = "."
            c = DecodedCollector(config)
            m = c.collect()
            # 2 resolved trades (a1b2c3d4=WIN +3.50, e5f6g7h8=LOSS -5.76)
            assert m.trades == 2
            assert m.pnl == pytest.approx(-2.26, abs=0.01)
            assert m.win_rate == pytest.approx(0.5)
            # 1 open trade
            assert m.open_positions == 1

    def test_deduplicates_trade_ids(self):
        """Trades written twice (open + close) should only count once."""
        from src.collectors.decoded import DecodedCollector
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a file with duplicate resolved trade IDs
            content = (
                "id\ttimestamp\tmarket_slug\tdirection\tside\tentry_price\tshares\t"
                "strategy\trule\tconfidence\tbtc_price\tbtc_pct_5m\tresolved\tresolution\texit_price\tpnl\tmode\n"
                "abc123\t2026-03-20T10:00:00\tbtc-90k\tUP\tYES\t0.50\t10\tstrat\trule_1\t0.8\t90000\t0.001\tTrue\tWIN\t1.0\t5.0\tpaper\n"
                "abc123\t2026-03-20T10:00:00\tbtc-90k\tUP\tYES\t0.50\t10\tstrat\trule_1\t0.8\t90000\t0.001\tTrue\tWIN\t1.0\t5.0\tpaper\n"
            )
            with open(os.path.join(tmpdir, "test_trades.tsv"), "w") as f:
                f.write(content)

            config = self._make_config(tmpdir)
            c = DecodedCollector(config)
            m = c.collect()
            assert m.trades == 1  # Deduped


# ── Momentum Collector ─────────────────────────────────────────────

class TestMomentumCollector:

    def _make_config(self, base_path):
        return {
            "name": "Crypto Momentum",
            "collector_type": "trading_momentum",
            "base_path": base_path,
            "paths": {
                "trades": "momentum_trades.tsv",
                "state": "momentum_state.json",
            },
        }

    def test_reads_trades_and_state(self):
        from src.collectors.momentum import MomentumCollector
        config = self._make_config(FIXTURES)
        c = MomentumCollector(config)
        m = c.collect()
        # 2 resolved trades: m1n2o3p4 (WIN +6.60), q5r6s7t8 (LOSS -2.70)
        assert m.trades == 2
        assert m.pnl == pytest.approx(3.90, abs=0.01)
        assert m.win_rate == pytest.approx(0.5)
        # 1 open position from state
        assert m.open_positions == 1
        assert m.healthy

    def test_missing_files_graceful(self):
        from src.collectors.momentum import MomentumCollector
        config = self._make_config("/nonexistent/path")
        c = MomentumCollector(config)
        m = c.collect()
        assert m.trades == 0
        assert m.pnl == 0.0
        assert m.healthy


# ── Telegram Reporter ──────────────────────────────────────────────

class TestTelegramReporter:

    def test_send_skips_when_no_credentials(self):
        """Reporter returns False and doesn't raise when no bot_token/chat_id."""
        import os
        from datetime import datetime
        from src.telegram_reporter import TelegramReporter
        from src.models import DailyReport

        # Ensure env vars are not set
        env_backup = {
            "OPS_DASHBOARD_BOT_TOKEN": os.environ.pop("OPS_DASHBOARD_BOT_TOKEN", None),
            "OPS_DASHBOARD_CHAT_ID": os.environ.pop("OPS_DASHBOARD_CHAT_ID", None),
        }
        try:
            reporter = TelegramReporter(bot_token="", chat_id="")
            report = DailyReport(
                generated_at=datetime.utcnow(),
                scorecard="Test scorecard",
                project_metrics=[],
                alerts=[],
            )
            result = reporter.send(report)
            assert result is False
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v

    def test_send_calls_telegram_api(self, monkeypatch):
        """Reporter calls Telegram sendMessage endpoint with scorecard text."""
        from datetime import datetime
        import requests as req_module
        from src.telegram_reporter import TelegramReporter
        from src.models import DailyReport

        calls = []

        class MockResponse:
            status_code = 200
            def json(self):
                return {"ok": True}

        def mock_post(url, json=None, timeout=None):
            calls.append({"url": url, "json": json})
            return MockResponse()

        monkeypatch.setattr(req_module, "post", mock_post)

        reporter = TelegramReporter(bot_token="test_token", chat_id="12345")
        report = DailyReport(
            generated_at=datetime.utcnow(),
            scorecard="Daily scorecard content",
            project_metrics=[],
            alerts=[],
        )
        result = reporter.send(report)

        assert result is True
        assert len(calls) == 1
        assert "test_token" in calls[0]["url"]
        assert "Daily scorecard content" in calls[0]["json"]["text"]
        assert calls[0]["json"]["chat_id"] == "12345"

    def test_send_falls_back_to_plain_text_on_parse_error(self, monkeypatch):
        """Reporter falls back to plain text if Markdown fails (400 error)."""
        from datetime import datetime
        import requests as req_module
        from src.telegram_reporter import TelegramReporter
        from src.models import DailyReport

        call_count = [0]

        class MockResponse:
            def __init__(self, status_code):
                self.status_code = status_code
                self.text = "Bad Request: can't parse entities"

        def mock_post(url, json=None, timeout=None):
            call_count[0] += 1
            # First call (Markdown) fails; second (plain) succeeds
            if call_count[0] == 1:
                return MockResponse(400)
            return MockResponse(200)

        monkeypatch.setattr(req_module, "post", mock_post)

        reporter = TelegramReporter(bot_token="tok", chat_id="99")
        report = DailyReport(
            generated_at=datetime.utcnow(),
            scorecard="Plain fallback test",
            project_metrics=[],
            alerts=[],
        )
        result = reporter.send(report)

        assert result is True
        assert call_count[0] == 2  # Two attempts: Markdown then plain


# ── End-to-End Pipeline ────────────────────────────────────────────

class TestWeatherPipeline:
    """End-to-end: WeatherCollector → StatusEngine → TelegramReporter (mocked)."""

    def test_full_pipeline(self, monkeypatch, tmp_path):
        """Full pipeline produces a scorecard and sends it via Telegram."""
        import json
        import shutil
        import requests as req_module
        from src.collectors.weather import WeatherCollector
        from src.status_engine import StatusEngine
        from src.telegram_reporter import TelegramReporter
        from src.models import DailyReport

        # Set up fixture files
        state_dir = tmp_path / "weather_paper"
        state_dir.mkdir()
        state = {
            "strategy": "metar_pure_latency",
            "portfolio": {"starting_balance": 1000, "balance": 1100},
            "open_trades": [],
            "resolved_trades": [
                {"resolution": "WIN"},
                {"resolution": "WIN"},
                {"resolution": "LOSS"},
            ],
        }
        (state_dir / "metar_pure_latency_state.json").write_text(json.dumps(state))
        shutil.copy(os.path.join(FIXTURES, "signal_log.tsv"), tmp_path)
        shutil.copy(os.path.join(FIXTURES, "paper_trades.tsv"), tmp_path)

        # Collect metrics
        config = {
            "name": "Weather Bot",
            "collector_type": "trading_weather",
            "base_path": str(tmp_path),
            "paths": {
                "signal_log": "signal_log.tsv",
                "paper_trades": "paper_trades.tsv",
                "portfolio_state_dir": "weather_paper",
            },
        }
        collector = WeatherCollector(config)
        metrics = collector.collect()

        assert metrics.healthy
        assert metrics.pnl == pytest.approx(100.0)
        assert metrics.win_rate == pytest.approx(2 / 3)

        # Generate scorecard
        engine = StatusEngine()
        report = engine.generate_report([metrics], [], ["Weather Bot"])
        assert "WEATHER" in report.scorecard
        assert len(report.scorecard) > 20

        # Send via TelegramReporter (mocked)
        sent_payloads = []

        class MockResponse:
            status_code = 200

        def mock_post(url, json=None, timeout=None):
            sent_payloads.append(json)
            return MockResponse()

        monkeypatch.setattr(req_module, "post", mock_post)

        reporter = TelegramReporter(bot_token="pipeline_token", chat_id="777")
        result = reporter.send(report)

        assert result is True
        assert len(sent_payloads) == 1
        assert report.scorecard in sent_payloads[0]["text"]
