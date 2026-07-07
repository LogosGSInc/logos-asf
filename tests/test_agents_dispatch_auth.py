# -*- coding: utf-8 -*-
"""
test_agents_dispatch_auth.py — SEC-03 EP-02 (+ RTR-09).

/api/agents/dispatch must be admin-gated and run the same governance gates as the
chat path before any provider dispatch:
  - auth FIRST (401 no/bad token, 503 server token unset) — prevents wallet-DoS
    and agent enumeration;
  - Sentinel hard-block, HAAP, MM-03 approval, and SEC-02 cost gate all run before
    the provider is ever called.
RTR-09: the admin token is compared in constant time (hmac.compare_digest).

No live provider calls: BACKEND_DISPATCH is stubbed and counted.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

TOKEN = "admintok_EP02_test"


def _base_env(monkeypatch, turns=1000, tokens=8000):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "1")
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", str(turns))
    monkeypatch.setenv("ABIGAIL_MAX_ESTIMATED_TOKENS", str(tokens))


def _setup(monkeypatch, verdict="unknown"):
    """Stub agent registry, Sentinel, and the backend (counted). Returns calls dict."""
    monkeypatch.setattr(A, "_get_yaml_agent",
                        lambda aid: {"name": "Ezra", "system_prompt": "You are a test agent."})
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": True, "verdict": verdict, "approved": True})
    calls = {"backend": 0}

    def _fake_backend(messages=None, system=None, **k):
        calls["backend"] += 1
        return "stubbed agent output"

    monkeypatch.setitem(A.BACKEND_DISPATCH, "groq", _fake_backend)
    return calls


def _app(monkeypatch):
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client()


def _auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def _post(client, body, headers=None):
    return client.post("/api/agents/dispatch", json=body, headers=headers or {})


# ── auth first (EP-02 + RTR-09) ──────────────────────────────────────────────
def test_unauthenticated_is_401_and_no_provider_call(monkeypatch):
    _base_env(monkeypatch)
    calls = _setup(monkeypatch)
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "do something"})
    assert r.status_code == 401
    assert calls["backend"] == 0


def test_wrong_token_is_401(monkeypatch):
    _base_env(monkeypatch)
    calls = _setup(monkeypatch)
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "hi"},
              headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 401
    assert calls["backend"] == 0


def test_server_token_unset_fails_closed_503(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    calls = _setup(monkeypatch)
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "hi"}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 503
    assert calls["backend"] == 0


def test_auth_precedes_agent_lookup_no_enumeration(monkeypatch):
    _base_env(monkeypatch)
    # agent lookup would 404, but unauth must 401 first (no enumeration signal)
    monkeypatch.setattr(A, "_get_yaml_agent", lambda aid: None)
    monkeypatch.setattr(A, "_sentinel_inspect", lambda *a, **k: {"verdict": "unknown"})
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "definitely-not-real", "task": "hi"})
    assert r.status_code == 401


# ── governance gates run before provider dispatch ────────────────────────────
def test_authenticated_benign_dispatches(monkeypatch):
    _base_env(monkeypatch)
    calls = _setup(monkeypatch)
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "summarize this"}, headers=_auth())
    body = r.get_json()
    assert r.status_code == 200
    assert body["ok"] is True
    assert body["text"] == "stubbed agent output"
    assert calls["backend"] == 1


def test_sentinel_hard_block_before_dispatch(monkeypatch):
    _base_env(monkeypatch)
    calls = _setup(monkeypatch, verdict="quarantined")
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "malicious"}, headers=_auth())
    assert r.status_code == 403
    assert r.get_json().get("blocked") is True
    assert calls["backend"] == 0


def test_haap_violation_before_dispatch(monkeypatch):
    _base_env(monkeypatch)
    calls = _setup(monkeypatch)

    def _raise(*a, **k):
        raise A.HAAPViolation("HAAP block for test")

    monkeypatch.setattr(A, "haap_gate", _raise)
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "injection"}, headers=_auth())
    assert r.status_code == 403
    assert calls["backend"] == 0


def test_cost_gate_blocks_before_dispatch(monkeypatch):
    _base_env(monkeypatch, turns=0)   # zero budget -> cost block
    calls = _setup(monkeypatch)
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "expensive"}, headers=_auth())
    body = r.get_json()
    assert body.get("mode") == "COST_BLOCKED"
    assert calls["backend"] == 0


@pytest.mark.skipif(not A._ORCHESTRATION_BRIDGE_OK,
                    reason="orchestration bridge not available")
def test_high_risk_returns_approval_required_before_dispatch(monkeypatch):
    _base_env(monkeypatch)
    calls = _setup(monkeypatch)
    c = _app(monkeypatch)
    r = _post(c, {"agent_id": "ezra", "task": "please plan my week",
                  "risk_level": "high"}, headers=_auth())
    body = r.get_json()
    assert body.get("mode") == "APPROVAL_REQUIRED"
    assert calls["backend"] == 0


# ── RTR-09: constant-time admin comparison ───────────────────────────────────
def test_require_admin_token_uses_constant_time_compare(monkeypatch):
    import hmac
    calls = {"n": 0}
    real = hmac.compare_digest

    def _spy(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(A.hmac, "compare_digest", _spy)

    class _Req:
        headers = {"Authorization": f"Bearer {TOKEN}"}

    ok, status, _ = A.require_admin_token(
        type("R", (), {"headers": {"Authorization": f"Bearer {TOKEN}"}})())
    assert ok is True and status == 200
    assert calls["n"] >= 1   # constant-time compare was actually used
