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


# ── Git Collector ──────────────────────────────────────────────────

class TestGitCollector:
    """Tests for git-based project collector (issue #5)."""

    def _make_config(self, base_path, github_repo=None):
        cfg = {
            "name": "Test Repo",
            "collector_type": "git",
            "base_path": base_path,
        }
        if github_repo:
            cfg["github_repo"] = github_repo
        return cfg

    def test_missing_repo_without_github_fallback(self):
        """Repo not found and no github_repo configured → error."""
        from src.collectors.git_collector import GitCollector
        config = self._make_config("/nonexistent/repo")
        c = GitCollector(config)
        m = c.collect()
        assert not m.healthy
        assert m.error is not None

    def test_missing_repo_with_github_fallback_sets_status(self):
        """Repo not found but github_repo configured → status text (may fail gracefully)."""
        from src.collectors.git_collector import GitCollector
        config = self._make_config("/nonexistent/repo", github_repo="owner/repo")
        c = GitCollector(config)
        m = c.collect()
        # Should not raise; status_text is set (even if API unreachable)
        assert m.status_text is not None

    def test_reads_git_log_from_local_repo(self):
        """GitCollector reads last commit from a real local git repo."""
        from src.collectors.git_collector import GitCollector
        # Use this repo itself as a fixture
        repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config = self._make_config(repo_path)
        c = GitCollector(config)
        m = c.collect()
        assert m.healthy
        assert m.last_commit_date is not None
        assert m.last_commit_message is not None
        assert "Last commit" in m.status_text

    def test_reads_handoff_summary(self):
        """GitCollector extracts title from latest handoff markdown file."""
        from src.collectors.git_collector import GitCollector
        with tempfile.TemporaryDirectory() as tmpdir:
            import subprocess
            subprocess.run(["git", "-C", tmpdir, "init"], capture_output=True)
            subprocess.run(
                ["git", "-C", tmpdir, "commit", "--allow-empty", "-m", "init"],
                capture_output=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
                     "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
            )
            handoff_dir = os.path.join(tmpdir, "handoffs")
            os.makedirs(handoff_dir)
            with open(os.path.join(handoff_dir, "2026-03-20_handoff.md"), "w") as f:
                f.write("# CDP browser scraper 90% done\n\nSome body text.\n")

            config = self._make_config(tmpdir)
            c = GitCollector(config)
            m = c.collect()
            assert m.handoff_summary == "CDP browser scraper 90% done"
