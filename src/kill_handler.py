"""Kill/resume handler for Telegram bot — SSHes to Dublin and runs VPS scripts.

Uses subprocess to SSH into Dublin (99.81.160.132) and execute kill-trading.sh
or resume-trading.sh. Manages confirmation state for /kill and /resume commands.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DUBLIN_HOST = os.environ.get("DUBLIN_SSH_HOST", "ubuntu@99.81.160.132")
SSH_OPTS = ["-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]
VALID_TARGETS = {"crypto", "weather", "all"}

ALLOWED_CHAT_IDS: set[str] = set(
    filter(None, os.environ.get("OPS_DASHBOARD_CHAT_ID", "").split(","))
)


def is_authorized(chat_id: str) -> bool:
    """Check if chat_id is in the allowlist for destructive commands."""
    return chat_id in ALLOWED_CHAT_IDS


@dataclass
class PendingAction:
    """A kill or resume awaiting YES confirmation."""
    action: str  # "kill" or "resume"
    target: str  # "crypto", "weather", "all"
    info: str = ""  # resume context from --info


# Per-chat pending confirmations: {chat_id: PendingAction}
_pending: dict[str, PendingAction] = {}


def _ssh_run(command: str) -> tuple[int, str]:
    """Run a command on Dublin via SSH. Returns (returncode, stdout)."""
    full_cmd = ["ssh"] + SSH_OPTS + [DUBLIN_HOST, command]
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return 1, '{"error": "SSH timeout after 30s"}'
    except Exception as e:
        return 1, f'{{"error": "SSH failed: {e}"}}'


def handle_kill(chat_id: str, text: str) -> str:
    """Handle /kill <target> command. Returns response text."""
    parts = text.strip().split()
    if len(parts) < 2:
        return "Usage: /kill crypto | weather | all"

    target = parts[1].lower()
    if target not in VALID_TARGETS:
        return f"Unknown target '{target}'. Use: crypto, weather, or all"

    # Store pending confirmation
    _pending[chat_id] = PendingAction(action="kill", target=target)
    return (
        f"Kill {target} on Dublin?\n\n"
        f"This will:\n"
        f"- Stop the systemd service\n"
        f"- Disable restart\n"
        f"- Cancel all open CLOB orders\n\n"
        f"Reply YES to confirm."
    )


def handle_resume(chat_id: str, text: str) -> str:
    """Handle /resume <target> command. Returns response text."""
    parts = text.strip().split()
    if len(parts) < 2:
        return "Usage: /resume crypto | weather | all"

    target = parts[1].lower()
    if target not in VALID_TARGETS:
        return f"Unknown target '{target}'. Use: crypto, weather, or all"

    # Get kill context first
    rc, output = _ssh_run(f"bash ~/scripts/resume-trading.sh --info {target}")
    if rc != 0:
        return f"Cannot resume: {output}"

    _pending[chat_id] = PendingAction(action="resume", target=target, info=output)

    # Format the context for display
    try:
        info = json.loads(output)
        context_lines = []
        for key in ["crypto", "weather"]:
            if key in info:
                ctx = info[key]
                context_lines.append(
                    f"  {key}: killed at {ctx.get('killed_at', '?')} "
                    f"by {ctx.get('source', '?')} — {ctx.get('reason', '?')}"
                )
        context = "\n".join(context_lines)
    except (json.JSONDecodeError, KeyError):
        context = output

    return f"Resume {target} on Dublin?\n\n{context}\n\nReply YES to confirm."


def handle_confirmation(chat_id: str, text: str) -> Optional[str]:
    """Check if text is a YES confirmation for a pending action.

    Returns response text if handled, None if no pending action for this chat.
    """
    if chat_id not in _pending:
        return None

    pending = _pending.pop(chat_id)

    if text.strip().upper() != "YES":
        return "Cancelled."

    if pending.action == "kill":
        rc, output = _ssh_run(
            f"bash ~/scripts/kill-trading.sh {pending.target} telegram"
        )
        if rc == 0:
            return f"KILL SWITCH ACTIVATED: {pending.target}\n\n{output}"
        else:
            return f"KILL SWITCH — PARTIAL FAILURE:\n\n{output}"

    elif pending.action == "resume":
        rc, output = _ssh_run(
            f"bash ~/scripts/resume-trading.sh {pending.target}"
        )
        if rc == 0:
            return f"RESUMED: {pending.target}\n\n{output}"
        else:
            return f"RESUME FAILED:\n\n{output}"

    return None


def handle_kill_status() -> str:
    """Check kill switch status on Dublin. Returns formatted text."""
    rc, output = _ssh_run(
        'for f in /home/ubuntu/.kill-switch/*; do '
        'if [ -f "$f" ]; then echo "$(basename "$f"): $(cat "$f")"; fi; '
        'done; '
        'if [ ! -d /home/ubuntu/.kill-switch ] || [ -z "$(ls /home/ubuntu/.kill-switch/ 2>/dev/null)" ]; then '
        'echo "No active kill switches"; fi'
    )
    return f"Kill Switch Status:\n\n{output}"
