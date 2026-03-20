"""Telegram reporter — sends the daily scorecard via Telegram Bot API."""

import os

import requests

from src.models import DailyReport


class TelegramReporter:

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or os.environ.get("OPS_DASHBOARD_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("OPS_DASHBOARD_CHAT_ID", "")

    def send(self, report: DailyReport) -> bool:
        """Send the scorecard to Telegram. Returns True on success."""
        if not self.bot_token or not self.chat_id:
            print("[telegram] No bot_token or chat_id configured. Skipping send.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": f"```\n{report.scorecard}\n```",
            "parse_mode": "MarkdownV2",
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print("[telegram] Scorecard sent successfully.")
                return True
            else:
                # Fallback: send without markdown if formatting fails
                payload["text"] = report.scorecard
                del payload["parse_mode"]
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    print("[telegram] Scorecard sent (plain text fallback).")
                    return True
                print(f"[telegram] Failed: {resp.status_code} {resp.text[:200]}")
                return False
        except requests.RequestException as e:
            print(f"[telegram] Request failed: {e}")
            return False
