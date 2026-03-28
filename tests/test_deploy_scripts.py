"""Smoke tests for VPS deploy scripts (issue #7 and #15).

Verifies that:
- deploy.sh is syntactically valid bash
- deploy_crypto_prediction.sh is syntactically valid bash
- Both scripts reference the correct VPS address
- deploy.sh sets up the expected cron schedule
- deploy_crypto_prediction.sh references all 9 prediction services + crypto-paper
"""

import os
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_SH = os.path.join(REPO_ROOT, "deploy.sh")
DEPLOY_CRYPTO_SH = os.path.join(REPO_ROOT, "deploy_crypto_prediction.sh")

VPS_IP = "178.156.235.253"
EXPECTED_SERVICES = [
    "btc-baseline-5m",
    "btc-hybrid-5m",
    "btc-hybrid-value-5m",
    "btc-mm-5m",
    "btc-obimb-5m",
    "btc-regime-5m",
    "btc-zscore-5m",
    "eth-baseline-5m",
    "sol-baseline-5m",
    "crypto-paper",
]


class TestDeployShSyntax:

    def test_deploy_sh_exists(self):
        assert os.path.isfile(DEPLOY_SH), "deploy.sh missing from repo root"

    def test_deploy_sh_is_valid_bash(self):
        result = subprocess.run(
            ["bash", "-n", DEPLOY_SH],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"deploy.sh syntax error:\n{result.stderr}"

    def test_deploy_sh_targets_correct_vps(self):
        with open(DEPLOY_SH) as f:
            content = f.read()
        assert VPS_IP in content, f"deploy.sh must reference VPS {VPS_IP}"

    def test_deploy_sh_sets_daily_cron(self):
        with open(DEPLOY_SH) as f:
            content = f.read()
        # Should configure cron at 08:00 UTC
        assert "0 8 * * *" in content, "deploy.sh must set up 08:00 UTC daily cron"

    def test_deploy_sh_has_dry_run_step(self):
        with open(DEPLOY_SH) as f:
            content = f.read()
        assert "--dry-run" in content, "deploy.sh must run --dry-run verification step"


class TestDeployCryptoScriptSyntax:

    def test_script_exists(self):
        assert os.path.isfile(DEPLOY_CRYPTO_SH), "deploy_crypto_prediction.sh missing"

    def test_script_is_valid_bash(self):
        result = subprocess.run(
            ["bash", "-n", DEPLOY_CRYPTO_SH],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"syntax error:\n{result.stderr}"

    def test_script_targets_correct_vps(self):
        with open(DEPLOY_CRYPTO_SH) as f:
            content = f.read()
        assert VPS_IP in content, f"deploy_crypto_prediction.sh must reference VPS {VPS_IP}"

    def test_all_prediction_services_referenced(self):
        with open(DEPLOY_CRYPTO_SH) as f:
            content = f.read()
        missing = [svc for svc in EXPECTED_SERVICES if svc not in content]
        assert not missing, f"Missing services in deploy script: {missing}"

    def test_script_references_fallback_candles(self):
        with open(DEPLOY_CRYPTO_SH) as f:
            content = f.read()
        assert "fallback_candles.py" in content, \
            "deploy script must verify fallback_candles.py presence after pull"

    def test_script_has_verify_mode(self):
        with open(DEPLOY_CRYPTO_SH) as f:
            content = f.read()
        assert "--verify" in content, \
            "deploy script must support --verify flag for smoke-test-only mode"
