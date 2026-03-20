#!/bin/bash
# Deploy ops-dashboard to VPS
# Usage: ./deploy.sh

set -e

VPS="root@178.156.235.253"
REMOTE_DIR="/root/ops-dashboard"

echo "Deploying ops-dashboard to $VPS:$REMOTE_DIR..."

# Sync files (exclude local data, __pycache__, .git)
rsync -avz --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'data/' \
  --exclude '.pytest_cache' \
  . "$VPS:$REMOTE_DIR/"

# Install dependencies
ssh "$VPS" "cd $REMOTE_DIR && pip install -r requirements.txt -q"

# Set up cron (idempotent — removes old entry first)
CRON_CMD="0 8 * * * cd $REMOTE_DIR && python main.py >> /var/log/ops-dashboard.log 2>&1"
ssh "$VPS" "(crontab -l 2>/dev/null | grep -v 'ops-dashboard' ; echo '$CRON_CMD') | crontab -"

# Verify
echo "Verifying..."
ssh "$VPS" "cd $REMOTE_DIR && python main.py --dry-run"

echo ""
echo "Deployed. Cron set for daily at 08:00 UTC."
echo "To test: ssh $VPS 'cd $REMOTE_DIR && python main.py --dry-run'"
echo "To set Telegram: export OPS_DASHBOARD_BOT_TOKEN=... OPS_DASHBOARD_CHAT_ID=..."
