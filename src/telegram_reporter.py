"""Telegram reporter — sends the daily scorecard via Telegram Bot API.

Supports two modes:
  1. Push mode (send): one-shot send via cron
  2. Bot mode (run_bot): long-polling, responds to /update command
"""

import logging
import os
import threading

import requests

from src.models import DailyReport

logger = logging.getLogger(__name__)


class TelegramReporter:

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or os.environ.get("OPS_DASHBOARD_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("OPS_DASHBOARD_CHAT_ID", "")

    def send(self, report: DailyReport) -> bool:
        """Send the scorecard to Telegram. Returns True on success."""
        if not self.bot_token or not self.chat_id:
            print("[telegram] No bot_token or chat_id configured. Skipping send.")
            return False

        return self._send_message(self.chat_id, report.scorecard)

    def _send_message(self, chat_id: str, text: str) -> bool:
        """Send a text message to a chat. Tries code block, falls back to plain."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Try as code block first (monospace, preserves alignment)
        payload = {
            "chat_id": chat_id,
            "text": f"```\n{text}\n```",
            "parse_mode": "MarkdownV2",
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True

            # Fallback: plain text
            payload["text"] = text
            del payload["parse_mode"]
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True

            logger.error(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")
            return False
        except requests.RequestException as e:
            logger.error(f"Telegram request failed: {e}")
            return False

    def run_bot(self, report_fn):
        """Run long-polling bot that responds to /update with a fresh report.

        Args:
            report_fn: callable that returns a DailyReport (re-collects metrics each call)
        """
        if not self.bot_token:
            logger.error("No bot_token configured. Cannot start bot.")
            return

        logger.info("Telegram bot started — listening for /update")
        offset = 0

        while True:
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                resp = requests.get(url, params={
                    "offset": offset,
                    "timeout": 30,
                }, timeout=35)

                if resp.status_code != 200:
                    logger.warning(f"getUpdates failed: {resp.status_code}")
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if text.startswith("/update") or text.startswith("/start"):
                        logger.info(f"/update from chat {chat_id}")
                        try:
                            report = report_fn()
                            self._send_message(chat_id, report.scorecard)
                        except Exception as e:
                            self._send_message(chat_id, f"Error generating report: {e}")

            except requests.exceptions.ReadTimeout:
                continue  # normal for long-polling
            except Exception as e:
                logger.error(f"Bot loop error: {e}")
                import time
                time.sleep(5)
