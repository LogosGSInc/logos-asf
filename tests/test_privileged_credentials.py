# -*- coding: utf-8 -*-
"""
tests/test_privileged_credentials.py — C4: centralized privileged-credential
validation policy.

Before C4, ABIGAIL_ADMIN_TOKEN/ABIGAIL_DEMO_TOKEN validation was fragmented
across require_admin_token(), the web app's _request_authority()/_valid_step_up(),
command_bus.py's _resolve_surface(), and startup_checks() — each with its own
(sometimes missing) placeholder/length checks and a mix of `==`/`!=` and
constant-time comparisons. These tests pin the single centralized policy in
abigail/privileged_credentials.py and prove every call site now goes through it.

No network. No real provider calls. No secrets — every token used here is a
synthetic, non-placeholder test literal >=43 characters (the same floor the
policy enforces), except where a test is specifically exercising rejection of
something shorter/placeholder-shaped.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402
import command_bus as CB  # noqa: E402
import privileged_credentials as pc  # noqa: E402


def _padded_placeholder(marker):
    """A value that CONTAINS a known placeholder marker but is padded to
    >=43 chars, so placeholder-detection is proven independently of the
    length check."""
    s = marker
    while len(s) < pc.MIN_PRIVILEGED_TOKEN_LENGTH:
        s += "-x"
    assert len(s) >= pc.MIN_PRIVILEGED_TOKEN_LENGTH
    return s


STRONG_ADMIN = "strong-admin-token-9f86d081884c7d659a2feaa0c55ad015a3bf4f1b"
STRONG_ADMIN_WRONG = "strong-admin-token-wrong-2b0b822cd15d6c15b0f00a08d1234567"
STRONG_DEMO = "strong-demo-token-3bf4f1b2b0b822cd15d6c15b0f00a08d123456789a"

assert len(STRONG_ADMIN) >= pc.MIN_PRIVILEGED_TOKEN_LENGTH
assert len(STRONG_ADMIN_WRONG) >= pc.MIN_PRIVILEGED_TOKEN_LENGTH
assert len(STRONG_DEMO) >= pc.MIN_PRIVILEGED_TOKEN_LENGTH
assert STRONG_ADMIN != STRONG_ADMIN_WRONG != STRONG_DEMO


def _mkreq(headers=None):
    class H(dict):
        def get(self, k, d=""):
            return dict.get(self, k, d)
    r = type("R", (), {})()
    r.headers = H(headers or {})
    return r


# ── centralized validator: configured-value validation ─────────────────────

def test_empty_admin_token_rejected(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", "")
    assert pc.resolve_configured_token("ABIGAIL_ADMIN_TOKEN") is None
    assert pc.validate_privileged_token("") is pc.CredentialError.EMPTY


def test_whitespace_admin_token_rejected(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", "   \t  ")
    assert pc.resolve_configured_token("ABIGAIL_ADMIN_TOKEN") is None
    assert pc.validate_privileged_token("   \t  ") is pc.CredentialError.WHITESPACE
    # Leading/trailing whitespace ambiguity: rejected even with real content inside.
    padded_with_space = " " + STRONG_ADMIN
    assert pc.validate_privileged_token(padded_with_space) is pc.CredentialError.WHITESPACE


def test_short_admin_token_rejected(monkeypatch):
    short = "a" * (pc.MIN_PRIVILEGED_TOKEN_LENGTH - 1)
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", short)
    assert pc.resolve_configured_token("ABIGAIL_ADMIN_TOKEN") is None
    assert pc.validate_privileged_token(short) is pc.CredentialError.TOO_SHORT


@pytest.mark.parametrize("marker", [
    "PLACEHOLDER",
    "CHANGE_ME",
    "CHANGEME",
    "GENERATE_A_STRONG_RANDOM_TOKEN_HERE",
    "YOUR_ADMIN_TOKEN_HERE",
    "example-token",
    "test-token",
])
def test_placeholder_admin_token_rejected(monkeypatch, marker):
    padded = _padded_placeholder(marker)
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", padded)
    assert pc.resolve_configured_token("ABIGAIL_ADMIN_TOKEN") is None
    assert pc.validate_privileged_token(padded) is pc.CredentialError.PLACEHOLDER


@pytest.mark.parametrize("marker", [
    "PLACEHOLDER",
    "GENERATE_A_STRONG_RANDOM_TOKEN_HERE",
    "YOUR_DEMO_TOKEN_HERE",
])
def test_placeholder_demo_token_rejected(monkeypatch, marker):
    padded = _padded_placeholder(marker)
    monkeypatch.setenv("ABIGAIL_DEMO_TOKEN", padded)
    assert pc.resolve_configured_token("ABIGAIL_DEMO_TOKEN") is None


def test_valid_strong_admin_token_accepted(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    assert pc.resolve_configured_token("ABIGAIL_ADMIN_TOKEN") == STRONG_ADMIN
    assert pc.credential_matches(STRONG_ADMIN, "ABIGAIL_ADMIN_TOKEN") is True


def test_wrong_strong_admin_token_rejected(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    assert pc.credential_matches(STRONG_ADMIN_WRONG, "ABIGAIL_ADMIN_TOKEN") is False


def test_malformed_presented_token_rejected(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    for malformed in ("", "   ", None, "short", "\x00\x01garbage"):
        assert pc.credential_matches(malformed, "ABIGAIL_ADMIN_TOKEN") is False


def test_admin_token_cannot_substitute_for_demo_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    monkeypatch.setenv("ABIGAIL_DEMO_TOKEN", STRONG_DEMO)
    assert pc.credential_matches(STRONG_ADMIN, "ABIGAIL_DEMO_TOKEN") is False
    assert pc.credential_matches(STRONG_DEMO, "ABIGAIL_ADMIN_TOKEN") is False


def test_configured_placeholder_fails_closed(monkeypatch):
    """A placeholder-configured token fails CLOSED (503, same as missing) —
    never 401 — because require_admin_token treats it as not configured at
    all, not as 'configured but I typed the wrong thing'."""
    placeholder = _padded_placeholder("PLACEHOLDER")
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", placeholder)
    ok, st, err = A.require_admin_token(_mkreq({"Authorization": f"Bearer {placeholder}"}))
    assert ok is False
    assert st == 503


# ── require_admin_token(): the fail-closed admin route guard ───────────────

def test_demo_token_cannot_authorize_admin_route(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    monkeypatch.setenv("ABIGAIL_DEMO_TOKEN", STRONG_DEMO)
    ok, st, err = A.require_admin_token(_mkreq({"Authorization": f"Bearer {STRONG_DEMO}"}))
    assert ok is False and st == 401


def test_admin_route_accepts_valid_strong_admin_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    ok, st, err = A.require_admin_token(_mkreq({"Authorization": f"Bearer {STRONG_ADMIN}"}))
    assert ok is True and st == 200 and err is None


# ── startup: fail closed on invalid configuration ───────────────────────────

def test_startup_rejects_invalid_privileged_token(monkeypatch):
    monkeypatch.setattr(A, "_secure_touch", lambda *_a, **_k: None)
    monkeypatch.setattr(A, "_load_env_file", lambda *_a, **_k: None)
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _padded_placeholder("PLACEHOLDER"))
    monkeypatch.setenv("ABIGAIL_DEMO_TOKEN", STRONG_DEMO)
    with pytest.raises(SystemExit):
        A.startup_checks("ollama", web_mode=True)


def test_startup_accepts_valid_privileged_tokens(monkeypatch):
    monkeypatch.setattr(A, "_secure_touch", lambda *_a, **_k: None)
    monkeypatch.setattr(A, "_load_env_file", lambda *_a, **_k: None)
    monkeypatch.setattr(A, "log_event", lambda *_a, **_k: None)
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    monkeypatch.setenv("ABIGAIL_DEMO_TOKEN", STRONG_DEMO)
    A.startup_checks("ollama", web_mode=True)  # must not raise


# ── command_bus.py: authority resolution ────────────────────────────────────

def test_command_bus_rejects_placeholder_admin_token(monkeypatch):
    placeholder = _padded_placeholder("PLACEHOLDER")
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", placeholder)
    surface, _ = CB._resolve_surface("203.0.113.5", f"Bearer {placeholder}")
    assert surface != "TRUSTED_OPERATOR"


def test_command_bus_accepts_valid_strong_admin_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    surface, _ = CB._resolve_surface("203.0.113.5", f"Bearer {STRONG_ADMIN}")
    assert surface == "TRUSTED_OPERATOR"


# ── setup.sh: never prints the live admin token ─────────────────────────────

def test_setup_script_does_not_print_live_admin_token():
    text = (Path(__file__).parent.parent / "setup.sh").read_text()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo") or stripped.startswith("printf"):
            assert "$ADMIN_TOKEN" not in stripped, (
                f"setup.sh must never echo the live admin token, found: {stripped!r}"
            )
    assert "Admin token generated and stored in .abigail.env" in text


# ── audit/error hygiene: credential values never appear in logs or errors ──

def test_credential_values_absent_from_logs_and_errors(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", STRONG_ADMIN)
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))

    ok, st, err = A.require_admin_token(
        _mkreq({"Authorization": f"Bearer {STRONG_ADMIN_WRONG}"}))
    assert ok is False
    assert STRONG_ADMIN not in (err or "")
    assert STRONG_ADMIN_WRONG not in (err or "")

    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    r = app.test_client().get(
        "/api/audit/tail", headers={"Authorization": f"Bearer {STRONG_ADMIN_WRONG}"})
    assert r.status_code == 401
    assert STRONG_ADMIN not in r.get_data(as_text=True)
    assert STRONG_ADMIN_WRONG not in r.get_data(as_text=True)

    for _et, data in events:
        blob = str(data)
        assert STRONG_ADMIN not in blob
        assert STRONG_ADMIN_WRONG not in blob
