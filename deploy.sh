#!/bin/bash
# Deploy ops-dashboard to VPS
# Usage: ./deploy.sh [--skip-clone]
#
# Steps:
#   1. rsync code to /root/ops-dashboard on VPS
#   2. pip install -r requirements.txt
#   3. Clone git-collector repos if not already present (issue #5)
#   4. Set up daily cron at 08:00 UTC (idempotent)
#   5. Set up log rotation for /var/log/ops-dashboard.log
#   6. Run --dry-run to verify with real data
#
# Environment variables (set on VPS before running):
#   OPS_DASHBOARD_BOT_TOKEN  — Telegram bot token
#   OPS_DASHBOARD_CHAT_ID    — Telegram chat ID
#   NOTION_TOKEN             — Notion integration token (optional)
#   NOTION_PAGE_ID           — Notion page ID (optional)

set -e

VPS="root@178.156.235.253"
REMOTE_DIR="/root/ops-dashboard"
SKIP_CLONE="${1:-}"

echo "Deploying ops-dashboard to $VPS:$REMOTE_DIR..."

# ── Step 1: Sync files ────────────────────────────────────────────────────────
rsync -avz --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'data/' \
  --exclude '.pytest_cache' \
  . "$VPS:$REMOTE_DIR/"

# ── Step 2: Install dependencies ─────────────────────────────────────────────
ssh "$VPS" "cd $REMOTE_DIR && pip install -r requirements.txt -q"

# ── Step 3: Clone git-collector repos (issue #5) ─────────────────────────────
# Git collectors need the repos cloned on the VPS to read git log locally.
# Falls back to GitHub API if repos are absent, but local is preferred.
if [[ "$SKIP_CLONE" != "--skip-clone" ]]; then
  echo "Cloning git-collector repos (skip with --skip-clone if already present)..."
  ssh "$VPS" "
    if [ ! -d /root/conviction-equity-engine/.git ]; then
      git clone https://github.com/Magicalmeow/conviction-equity-engine /root/conviction-equity-engine || true
    else
      echo 'conviction-equity-engine already cloned'
    fi
    if [ ! -d /root/polymarket-intel/.git ]; then
      git clone https://github.com/Magicalmeow/polymarket-intel /root/polymarket-intel || true
    else
      echo 'polymarket-intel already cloned'
    fi
    if [ ! -d /root/crypto-15min-bot/.git ]; then
      git clone https://github.com/Magicalmeow/crypto-15min-bot /root/crypto-15min-bot || true
    else
      echo 'crypto-15min-bot already cloned'
    fi
  "
fi

# ── Step 4: Set up cron (idempotent) ─────────────────────────────────────────
CRON_CMD="0 8 * * * cd $REMOTE_DIR && python main.py >> /var/log/ops-dashboard.log 2>&1"
ssh "$VPS" "(crontab -l 2>/dev/null | grep -v 'ops-dashboard' ; echo '$CRON_CMD') | crontab -"
echo "Cron set: daily at 08:00 UTC"

# ── Step 5: Log rotation ──────────────────────────────────────────────────────
ssh "$VPS" "cat > /etc/logrotate.d/ops-dashboard << 'EOF'
/var/log/ops-dashboard.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF"
echo "Log rotation configured (/etc/logrotate.d/ops-dashboard)"

# ── Step 6: Verify with dry-run ───────────────────────────────────────────────
echo "Verifying with dry-run..."
ssh "$VPS" "cd $REMOTE_DIR && python main.py --dry-run"

echo ""
echo "Deployed. Cron set for daily at 08:00 UTC."
echo "Logs: ssh $VPS 'tail -f /var/log/ops-dashboard.log'"
echo ""
echo "To set Telegram: ssh $VPS 'export OPS_DASHBOARD_BOT_TOKEN=... OPS_DASHBOARD_CHAT_ID=...'"
echo "To set Notion:   ssh $VPS 'export NOTION_TOKEN=ntn_... NOTION_PAGE_ID=...'"
echo ""
echo "To deploy crypto-prediction Binance fallback (issue #15):"
echo "  ./deploy_crypto_prediction.sh"
