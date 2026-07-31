# -*- coding: utf-8 -*-
"""
tests/test_boundary_hardening_c6.py — C6: remaining network/deployment
boundary hardening on the Python (Flask) side.

Before C6: there was no Flask MAX_CONTENT_LENGTH (an oversized request body
was unbounded — the only size-adjacent control was the /api/chat token
estimate gate, which only inspects the "message" string, not overall body
bytes, and only on that one route), and the Anthropic provider call was the
only one of six outbound provider/Sentinel clients with no explicit
app-level timeout (every other client already passed GROQ_TIMEOUT or an
explicit seconds value).

No network, no real provider calls, no secrets.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


# ── resolve_max_request_bytes(): pure validation ─────────────────────────────

def test_max_request_bytes_default(monkeypatch):
    monkeypatch.delenv("ABIGAIL_MAX_REQUEST_BYTES", raising=False)
    assert A.resolve_max_request_bytes() == A._DEFAULT_MAX_REQUEST_BYTES


def test_max_request_bytes_env_override(monkeypatch):
    monkeypatch.setenv("ABIGAIL_MAX_REQUEST_BYTES", "2048")
    assert A.resolve_max_request_bytes() == 2048


@pytest.mark.parametrize("bad", ["not-a-number", "", "1.5", "  "])
def test_max_request_bytes_invalid_falls_back_to_default(monkeypatch, bad):
    monkeypatch.setenv("ABIGAIL_MAX_REQUEST_BYTES", bad)
    assert A.resolve_max_request_bytes() == A._DEFAULT_MAX_REQUEST_BYTES


@pytest.mark.parametrize("bad", ["0", "-1", "-1000"])
def test_max_request_bytes_non_positive_falls_back_to_default(monkeypatch, bad):
    """A configured 0/negative value is a misconfiguration, not an
    intentional 'reject every request with a body' policy — it must not
    silently disable or invert the protection."""
    monkeypatch.setenv("ABIGAIL_MAX_REQUEST_BYTES", bad)
    assert A.resolve_max_request_bytes() == A._DEFAULT_MAX_REQUEST_BYTES


# ── Flask app wiring ─────────────────────────────────────────────────────────

def test_build_web_app_configures_max_content_length(monkeypatch):
    monkeypatch.setenv("ABIGAIL_MAX_REQUEST_BYTES", "4096")
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    assert app.config["MAX_CONTENT_LENGTH"] == 4096


def test_oversized_request_body_rejected_413(monkeypatch):
    monkeypatch.setenv("ABIGAIL_MAX_REQUEST_BYTES", "16")
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    c = app.test_client()
    oversized_body = b'{"message": "' + b"x" * 200 + b'"}'
    assert len(oversized_body) > 16
    r = c.post("/api/chat", data=oversized_body, content_type="application/json")
    assert r.status_code == 413


def test_small_request_body_still_accepted(monkeypatch):
    """The size boundary must not weaken normal, in-budget requests."""
    monkeypatch.delenv("ABIGAIL_MAX_REQUEST_BYTES", raising=False)
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")

    def _fake_pm(msg, session, ks, ab, approval_meta=None, step_up_ok=False):
        return {"ok": True, "text": "stub", "drs": 0, "mode": "SILENT_AUTONOMY", "crsv": 0.0}

    monkeypatch.setattr(A, "process_message", _fake_pm)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    r = app.test_client().post("/api/chat", json={"message": "hello"})
    assert r.status_code == 200


# ── Outbound provider call timeouts ──────────────────────────────────────────

def test_anthropic_call_uses_explicit_timeout(monkeypatch):
    """Every other provider client (Groq/Perplexity/Ollama/OpenAI/xAI/Sentinel)
    already passes an explicit timeout; Anthropic was the one gap."""
    import anthropic

    captured = {}

    class _FakeMessages:
        def create(self, **kwargs):
            class _Content:
                text = "ok"
            class _Resp:
                content = [_Content()]
            return _Resp()

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-not-a-real-secret-value-0000000000")

    result = A.call_anthropic([{"role": "user", "content": "hi"}], "system prompt")

    assert result == "ok"
    assert captured.get("timeout") == A.GROQ_TIMEOUT
