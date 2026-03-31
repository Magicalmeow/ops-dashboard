"""Tests for kill_handler — Telegram kill/resume confirmation state machine.

Stubs _ssh_run at module level to avoid real SSH calls.
Tests cover: validation, state machine, authorization.
"""

import src.kill_handler as kh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_ssh(returncode: int, stdout: str):
    """Replace _ssh_run with a stub. Returns the original for restoration."""
    original = kh._ssh_run
    kh._ssh_run = lambda cmd: (returncode, stdout)
    return original


def _restore_ssh(original):
    kh._ssh_run = original


# ---------------------------------------------------------------------------
# handle_kill
# ---------------------------------------------------------------------------

def test_handle_kill_missing_target():
    result = kh.handle_kill("chat1", "/kill")
    assert "Usage" in result


def test_handle_kill_invalid_target():
    result = kh.handle_kill("chat1", "/kill bitcoin")
    assert "Unknown target" in result


def test_handle_kill_valid_crypto():
    kh._pending.clear()
    result = kh.handle_kill("chat1", "/kill crypto")
    assert "Kill crypto" in result
    assert "YES" in result
    assert "chat1" in kh._pending
    assert kh._pending["chat1"].action == "kill"
    assert kh._pending["chat1"].target == "crypto"
    kh._pending.clear()


def test_handle_kill_valid_all():
    kh._pending.clear()
    result = kh.handle_kill("chat1", "/kill all")
    assert "Kill all" in result
    assert kh._pending["chat1"].target == "all"
    kh._pending.clear()


# ---------------------------------------------------------------------------
# handle_resume
# ---------------------------------------------------------------------------

def test_handle_resume_missing_target():
    result = kh.handle_resume("chat2", "/resume")
    assert "Usage" in result


def test_handle_resume_invalid_target():
    result = kh.handle_resume("chat2", "/resume litecoin")
    assert "Unknown target" in result


def test_handle_resume_valid_target():
    kh._pending.clear()
    orig = _stub_ssh(0, '{"crypto": {"killed_at": "2026-03-31", "source": "telegram", "reason": "test"}}')
    try:
        result = kh.handle_resume("chat2", "/resume crypto")
        assert "Resume crypto" in result
        assert "YES" in result
        assert "chat2" in kh._pending
        assert kh._pending["chat2"].action == "resume"
    finally:
        _restore_ssh(orig)
        kh._pending.clear()


def test_handle_resume_ssh_failure():
    kh._pending.clear()
    orig = _stub_ssh(1, '{"error": "no kill file"}')
    try:
        result = kh.handle_resume("chat2", "/resume crypto")
        assert "Cannot resume" in result
        assert "chat2" not in kh._pending
    finally:
        _restore_ssh(orig)


# ---------------------------------------------------------------------------
# handle_confirmation
# ---------------------------------------------------------------------------

def test_confirmation_no_pending():
    kh._pending.clear()
    result = kh.handle_confirmation("chat3", "YES")
    assert result is None


def test_confirmation_not_yes():
    kh._pending.clear()
    kh._pending["chat3"] = kh.PendingAction(action="kill", target="crypto")
    result = kh.handle_confirmation("chat3", "no")
    assert result == "Cancelled."
    assert "chat3" not in kh._pending


def test_confirmation_yes_kill_success():
    kh._pending.clear()
    kh._pending["chat3"] = kh.PendingAction(action="kill", target="crypto")
    orig = _stub_ssh(0, "service stopped")
    try:
        result = kh.handle_confirmation("chat3", "YES")
        assert "KILL SWITCH ACTIVATED" in result
        assert "chat3" not in kh._pending
    finally:
        _restore_ssh(orig)


def test_confirmation_yes_kill_failure():
    kh._pending.clear()
    kh._pending["chat3"] = kh.PendingAction(action="kill", target="weather")
    orig = _stub_ssh(1, "partial error")
    try:
        result = kh.handle_confirmation("chat3", "YES")
        assert "PARTIAL FAILURE" in result
    finally:
        _restore_ssh(orig)


def test_confirmation_yes_resume_success():
    kh._pending.clear()
    kh._pending["chat3"] = kh.PendingAction(action="resume", target="crypto")
    orig = _stub_ssh(0, "service started")
    try:
        result = kh.handle_confirmation("chat3", "YES")
        assert "RESUMED" in result
    finally:
        _restore_ssh(orig)


def test_confirmation_yes_resume_failure():
    kh._pending.clear()
    kh._pending["chat3"] = kh.PendingAction(action="resume", target="crypto")
    orig = _stub_ssh(1, "resume error")
    try:
        result = kh.handle_confirmation("chat3", "YES")
        assert "RESUME FAILED" in result
    finally:
        _restore_ssh(orig)


# ---------------------------------------------------------------------------
# handle_kill_status
# ---------------------------------------------------------------------------

def test_kill_status():
    orig = _stub_ssh(0, "crypto: killed at 2026-03-31")
    try:
        result = kh.handle_kill_status()
        assert "Kill Switch Status" in result
        assert "crypto" in result
    finally:
        _restore_ssh(orig)


# ---------------------------------------------------------------------------
# is_authorized
# ---------------------------------------------------------------------------

def test_is_authorized_valid(monkeypatch):
    monkeypatch.setattr(kh, "ALLOWED_CHAT_IDS", {"12345", "67890"})
    assert kh.is_authorized("12345") is True
    assert kh.is_authorized("99999") is False


def test_is_authorized_empty(monkeypatch):
    monkeypatch.setattr(kh, "ALLOWED_CHAT_IDS", set())
    assert kh.is_authorized("12345") is False
