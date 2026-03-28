#!/bin/bash
# Deploy crypto-prediction Binance fallback fixes to Hetzner VPS.
# Issue #15: Binance REST is geo-blocked (HTTP 451) from Hetzner Ashburn.
#            Fixes in fallback_candles.py / klines_bootstrap.py were committed
#            on Mar 21 but never deployed. This script deploys them.
#
# Usage:
#   ./deploy_crypto_prediction.sh           # full deploy
#   ./deploy_crypto_prediction.sh --verify  # verify only (no restart)
#
# Prerequisites:
#   SSH key ~/.ssh/id_ed25519 authorised on the VPS.
#   Run from any machine that has network access to 178.156.235.253.

set -euo pipefail

VPS="root@178.156.235.253"
CRYPTO_PRED="/opt/crypto-prediction"
CRYPTO_BOT="/opt/crypto-15min-bot"

VERIFY_ONLY="${1:-}"

# ── Services to restart ───────────────────────────────────────────────────────
PREDICTION_SERVICES=(
  btc-baseline-5m
  btc-hybrid-5m
  btc-hybrid-value-5m
  btc-mm-5m
  btc-obimb-5m
  btc-regime-5m
  btc-zscore-5m
  eth-baseline-5m
  sol-baseline-5m
)
PAPER_SERVICE="crypto-paper"

log() { echo "[deploy] $*"; }

# ── Verify-only mode ─────────────────────────────────────────────────────────
if [[ "$VERIFY_ONLY" == "--verify" ]]; then
  log "--- Verification mode (no restarts) ---"
  log "Checking fallback_candles.py exists on VPS..."
  ssh "$VPS" "test -f $CRYPTO_PRED/data/fallback_candles.py && echo 'OK: fallback_candles.py present' || echo 'MISSING: fallback_candles.py not found'"

  log "Checking klines_bootstrap.py for fallback references..."
  ssh "$VPS" "grep -l 'fallback' $CRYPTO_PRED/data/klines_bootstrap.py 2>/dev/null && echo 'OK: fallback logic present' || echo 'MISSING: no fallback in klines_bootstrap.py'"

  log "Checking recent journal for Coinbase/Kraken candle fetches..."
  ssh "$VPS" "journalctl -u btc-baseline-5m -n 20 --no-pager 2>/dev/null || echo 'No journal entries'"

  log "Checking Dublin exec engine signal count..."
  ssh ubuntu@99.81.160.132 "journalctl -u exec-engine -n 10 --no-pager 2>/dev/null || echo 'Cannot check Dublin'"
  exit 0
fi

# ── Step 1: Pull latest code ──────────────────────────────────────────────────
log "Step 1/4 — Pulling crypto-prediction..."
ssh "$VPS" "cd $CRYPTO_PRED && git pull"

log "Step 1/4 — Pulling crypto-15min-bot..."
ssh "$VPS" "cd $CRYPTO_BOT && git pull"

# ── Step 2: Verify fallback files landed ────────────────────────────────────
log "Step 2/4 — Verifying fallback_candles.py exists..."
ssh "$VPS" "test -f $CRYPTO_PRED/data/fallback_candles.py" || {
  echo "ERROR: fallback_candles.py not found after pull. Aborting."
  exit 1
}
log "  fallback_candles.py OK"

# ── Step 3: Restart services ────────────────────────────────────────────────
log "Step 3/4 — Restarting 9 prediction services..."
for svc in "${PREDICTION_SERVICES[@]}"; do
  log "  restarting $svc..."
  ssh "$VPS" "systemctl restart $svc"
done

log "Step 3/4 — Restarting $PAPER_SERVICE..."
ssh "$VPS" "systemctl restart $PAPER_SERVICE"

# ── Step 4: Smoke test ───────────────────────────────────────────────────────
log "Step 4/4 — Waiting 30s then checking journal for candle data..."
sleep 30

log "  btc-baseline-5m journal (last 20 lines):"
ssh "$VPS" "journalctl -u btc-baseline-5m -n 20 --no-pager"

log ""
log "  Look for 'coinbase' or 'kraken' in the output above."
log "  If you still see 'rest_failed' or 'Binance', the fallback did not activate."
log ""
log "  To check Dublin exec engine signal count:"
log "  ssh ubuntu@99.81.160.132 'journalctl -u exec-engine -n 10'"
log ""
log "Deployment complete."
log "If candle data is flowing, the Dublin exec engine signal count should increase from 62."
