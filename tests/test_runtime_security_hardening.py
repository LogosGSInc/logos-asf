# -*- coding: utf-8 -*-
"""
test_runtime_security_hardening.py — SEC-02 immediate runtime hardening.

Covers: localhost-default bind (L3-1), fail-closed admin auth (L1-1), the
deterministic local Cost Governor pre-inference gate (L7-1), and MM-02 preservation
(command bus wins & bypasses inference/orchestration; normal chat keeps additive
orchestration metadata). No provider calls, no network, no secrets.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────────
def _mkreq(headers=None):
    class H(dict):
        def get(self, k, d=""):
            return dict.get(self, k, d)
    r = type("R", (), {})()
    r.headers = H(headers or {})
    return r


class _Sess:
    def __init__(self, turns=0):
        self.turn_count = turns

    def crsv(self):
        return 0.0


def _budget(monkeypatch, turns=1000, tokens=8000, enabled="1"):
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", enabled)
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", str(turns))
    monkeypatch.setenv("ABIGAIL_MAX_ESTIMATED_TOKENS", str(tokens))


def _app(monkeypatch, turns=1000, tokens=8000):
    _budget(monkeypatch, turns, tokens)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client(), sess


# ── L3-1: bind host ──────────────────────────────────────────────────────────
def test_default_bind_is_localhost(monkeypatch):
    monkeypatch.delenv("ABIGAIL_BIND_HOST", raising=False)
    monkeypatch.delenv("ABIGAIL_ALLOW_NONLOCAL_BIND", raising=False)
    assert A.resolve_bind_host() == "127.0.0.1"


def test_nonlocal_bind_refused_without_flag(monkeypatch):
    monkeypatch.setenv("ABIGAIL_BIND_HOST", "0.0.0.0")
    monkeypatch.delenv("ABIGAIL_ALLOW_NONLOCAL_BIND", raising=False)
    assert A.resolve_bind_host() == "127.0.0.1"


def test_nonlocal_bind_allowed_with_explicit_flag(monkeypatch):
    monkeypatch.setenv("ABIGAIL_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("ABIGAIL_ALLOW_NONLOCAL_BIND", "1")
    assert A.resolve_bind_host() == "0.0.0.0"


def test_localhost_alias_normalizes(monkeypatch):
    monkeypatch.setenv("ABIGAIL_BIND_HOST", "localhost")
    assert A.resolve_bind_host() == "127.0.0.1"


# ── L1-1: admin auth fail-closed ────────────────────────────────────────────
def test_admin_fail_closed_when_server_token_unset(monkeypatch):
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    ok, st, err = A.require_admin_token(_mkreq())
    assert ok is False and st == 503


def test_admin_rejects_missing_client_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", "server-side-admin-token")
    ok, st, err = A.require_admin_token(_mkreq())
    assert ok is False and st == 401


def test_admin_rejects_wrong_token_without_leaking(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", "server-side-admin-token")
    ok, st, err = A.require_admin_token(_mkreq({"X-HAAP-Token": "nope"}))
    assert ok is False and st == 401
    assert "server-side-admin-token" not in (err or "")


def test_admin_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", "server-side-admin-token")
    ok, st, err = A.require_admin_token(
        _mkreq({"Authorization": "Bearer server-side-admin-token"}))
    assert ok is True and st == 200 and err is None


# ── L1-1 at the route layer ─────────────────────────────────────────────────
def test_audit_tail_fail_closed_when_unset(monkeypatch):
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    c, _ = _app(monkeypatch)
    r = c.get("/api/audit/tail")
    assert r.status_code == 503


def test_audit_tail_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", "the-real-admin-token")
    c, _ = _app(monkeypatch)
    r = c.get("/api/audit/tail", headers={"X-HAAP-Token": "wrong"})
    assert r.status_code == 401
    assert "the-real-admin-token" not in r.get_data(as_text=True)


def test_audit_tail_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", "the-real-admin-token")
    c, _ = _app(monkeypatch)
    r = c.get("/api/audit/tail", headers={"Authorization": "Bearer the-real-admin-token"})
    assert r.status_code == 200
    assert "the-real-admin-token" not in r.get_data(as_text=True)


def test_dept_kill_fail_closed_when_unset(monkeypatch):
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    c, _ = _app(monkeypatch)
    r = c.post("/api/agents/ENG/kill", json={})
    assert r.status_code == 503


# ── L7-1: cost governor (unit) ──────────────────────────────────────────────
def test_cost_zero_budget_blocks(monkeypatch):
    _budget(monkeypatch, turns=0, tokens=8000)
    ok, meta = A.check_chat_cost_budget("hello", "chat", _Sess())
    assert ok is False and meta["decision"] == "block_zero_budget"


def test_cost_allows_normal_low_risk(monkeypatch):
    _budget(monkeypatch, turns=1000, tokens=8000)
    ok, meta = A.check_chat_cost_budget("hello world", "chat", _Sess(turns=1))
    assert ok is True and meta["decision"] == "allow"


def test_cost_blocks_oversized_request(monkeypatch):
    _budget(monkeypatch, turns=1000, tokens=5)
    ok, meta = A.check_chat_cost_budget("x" * 400, "chat", _Sess())
    assert ok is False and meta["decision"] == "block_request_too_large"


def test_cost_blocks_when_turns_exhausted(monkeypatch):
    _budget(monkeypatch, turns=3, tokens=8000)
    ok, meta = A.check_chat_cost_budget("hi", "chat", _Sess(turns=3))
    assert ok is False and meta["decision"] == "block_turns_exhausted"


# ── L7-1: cost gate runs BEFORE provider dispatch (route) ───────────────────
def test_cost_gate_blocks_before_process_message(monkeypatch):
    _budget(monkeypatch, turns=0, tokens=8000)  # zero budget => block
    called = {"n": 0}

    def _fake_pm(*a, **k):
        called["n"] += 1
        return {"ok": True, "text": "should not run", "drs": 0, "mode": "X", "crsv": 0.0}

    monkeypatch.setattr(A, "process_message", _fake_pm)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    r = app.test_client().post("/api/chat", json={"message": "hello"})
    body = r.get_json()
    assert body["mode"] == "COST_BLOCKED"
    assert called["n"] == 0  # provider/process_message path never invoked


# ── MM-02 preservation ──────────────────────────────────────────────────────
def test_normal_chat_keeps_orchestration_and_cost(monkeypatch):
    def _fake_pm(msg, session, ks, ab, approval_meta=None, step_up_ok=False):
        return {"ok": True, "text": "stubbed reply", "drs": 0,
                "mode": "SILENT_AUTONOMY", "crsv": 0.0}

    monkeypatch.setattr(A, "process_message", _fake_pm)
    c, _ = _app(monkeypatch)
    r = c.post("/api/chat", json={"message": "give me a harmless check"})
    body = r.get_json()
    assert body["ok"] is True
    assert body["cost"]["decision"] == "allow"
    if A._ORCHESTRATION_BRIDGE_OK:
        assert body["orchestration"]["orchestration_mode"] == "shadow"
        # additive metadata must not carry the raw prompt
        assert "give me a harmless check" not in str(body["orchestration"])


def test_command_bus_bypasses_inference_and_orchestration(monkeypatch):
    called = {"pm": 0}

    def _fake_pm(*a, **k):
        called["pm"] += 1
        return {"ok": True}

    monkeypatch.setattr(A, "process_message", _fake_pm)
    monkeypatch.setattr(A, "_COMMAND_BUS_OK", True)
    monkeypatch.setattr(
        A, "_try_operator_command_fn",
        lambda *a, **k: {"ok": True, "mode": "OPERATOR_CMD", "text": "status ok",
                         "source": "governed endpoint read · no model inference"})
    c, _ = _app(monkeypatch)
    r = c.post("/api/chat", json={"message": "status"})
    body = r.get_json()
    assert body["mode"] == "OPERATOR_CMD"
    assert "orchestration" not in body   # command bus returns before orchestration
    assert "cost" not in body            # ...and before the cost gate
    assert called["pm"] == 0             # no model inference


# ── secret hygiene ───────────────────────────────────────────────────────────
def test_repo_local_abigail_env_is_gitignored():
    gi = (Path(__file__).parent.parent / ".gitignore").read_text()
    assert ".abigail.env" in gi
