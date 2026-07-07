# -*- coding: utf-8 -*-
"""
test_approval_gate_failclosed.py — SEC-03 GOV-01.

Invariant: "unable to evaluate approval" must NEVER be treated as "approval
granted." When the orchestration bridge is unavailable or the shadow context
cannot be built, externally reachable entry points must fail CLOSED:
  - synthesize approval-required metadata carrying governance_status=UNAVAILABLE
    and a machine-readable failure_reason,
  - emit a dedicated GOVERNANCE_UNAVAILABLE_FAIL_CLOSED audit event,
  - deny execution before any provider dispatch.

No live provider calls: BACKEND_DISPATCH is stubbed and counted.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

ADMIN = "admintok_GOV01"


def _env(monkeypatch):
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "1")
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", "1000")
    monkeypatch.setenv("ABIGAIL_MAX_ESTIMATED_TOKENS", "8000")


def _no_net(monkeypatch):
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": True, "verdict": "unknown", "approved": True})
    monkeypatch.setattr(A, "try_grounded_answer", lambda *a, **k: None)
    calls = {"backend": 0}

    def _fake_backend(messages=None, system=None, **k):
        calls["backend"] += 1
        return "stubbed model reply"

    monkeypatch.setitem(A.BACKEND_DISPATCH, "groq", _fake_backend)
    return calls


def _client(monkeypatch):
    _env(monkeypatch)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client()


class _Sess:
    def __init__(self):
        self.turn_count = 0
        self.messages = []

    def crsv(self):
        return 0.0

    def record_turn(self, *a, **k):
        self.turn_count += 1

    def drift_warning(self):
        return None


# ── resolver unit ────────────────────────────────────────────────────────────
def test_resolver_fail_closed_when_bridge_unavailable(monkeypatch):
    monkeypatch.setattr(A, "_ORCHESTRATION_BRIDGE_OK", False)
    logs = []
    monkeypatch.setattr(A, "log_event", lambda ev, p=None: logs.append((ev, p)))
    meta, ctx = A._resolve_approval_meta("hi", "chat", _Sess(), ["groq"], {})
    assert meta["human_approval_required"] is True
    assert meta["governance_status"] == "UNAVAILABLE"
    assert meta["failure_reason"] == "orchestration_bridge_unavailable"
    assert ctx is None
    assert any(ev == "GOVERNANCE_UNAVAILABLE_FAIL_CLOSED" for ev, _ in logs)


def test_resolver_fail_closed_when_shadow_ctx_none(monkeypatch):
    monkeypatch.setattr(A, "_ORCHESTRATION_BRIDGE_OK", True)
    monkeypatch.setattr(A, "_build_shadow_ctx", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(A, "log_event", lambda ev, p=None: logs.append((ev, p)))
    meta, ctx = A._resolve_approval_meta("hi", "chat", _Sess(), ["groq"], {})
    assert meta["human_approval_required"] is True
    assert meta["governance_status"] == "UNAVAILABLE"
    assert meta["failure_reason"] == "shadow_context_unavailable"
    assert ctx is None
    assert any(ev == "GOVERNANCE_UNAVAILABLE_FAIL_CLOSED" for ev, _ in logs)


@pytest.mark.skipif(not A._ORCHESTRATION_BRIDGE_OK,
                    reason="orchestration bridge not available")
def test_resolver_passthrough_on_success(monkeypatch):
    # Real bridge, benign request → real ctx, no synthetic governance_status.
    meta, ctx = A._resolve_approval_meta("hello there", "chat", _Sess(), ["groq"], {})
    assert ctx is not None
    assert meta.get("governance_status") != "UNAVAILABLE"
    assert meta.get("human_approval_required") in (False, None)


# ── /api/chat fail-closed ────────────────────────────────────────────────────
def test_chat_bridge_unavailable_returns_approval_required(monkeypatch):
    calls = _no_net(monkeypatch)
    monkeypatch.setattr(A, "_ORCHESTRATION_BRIDGE_OK", False)
    c = _client(monkeypatch)
    r = c.post("/api/chat", json={"message": "please do something normal"})
    body = r.get_json()
    assert body["mode"] == "APPROVAL_REQUIRED"
    assert calls["backend"] == 0


def test_chat_shadow_ctx_failure_returns_approval_required(monkeypatch):
    calls = _no_net(monkeypatch)
    monkeypatch.setattr(A, "_ORCHESTRATION_BRIDGE_OK", True)
    monkeypatch.setattr(A, "_build_shadow_ctx", lambda *a, **k: None)
    c = _client(monkeypatch)
    r = c.post("/api/chat", json={"message": "please do something normal"})
    body = r.get_json()
    assert body["mode"] == "APPROVAL_REQUIRED"
    assert calls["backend"] == 0


def test_chat_happy_path_still_proceeds(monkeypatch):
    # bridge on, benign, low-risk → NOT blocked (guards against over-blocking).
    if not A._ORCHESTRATION_BRIDGE_OK:
        pytest.skip("orchestration bridge not available")
    calls = _no_net(monkeypatch)
    c = _client(monkeypatch)
    r = c.post("/api/chat", json={"message": "compose a short poem about the sea"})
    body = r.get_json()
    assert body["mode"] != "APPROVAL_REQUIRED"
    assert calls["backend"] == 1


# ── /api/agents/dispatch fail-closed ─────────────────────────────────────────
def test_dispatch_bridge_unavailable_returns_approval_required(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)
    calls = _no_net(monkeypatch)
    monkeypatch.setattr(A, "_get_yaml_agent",
                        lambda aid: {"name": "Ezra", "system_prompt": "test agent"})
    monkeypatch.setattr(A, "_ORCHESTRATION_BRIDGE_OK", False)
    c = _client(monkeypatch)
    r = c.post("/api/agents/dispatch",
               json={"agent_id": "ezra", "task": "do a thing"},
               headers={"Authorization": f"Bearer {ADMIN}"})
    body = r.get_json()
    assert body.get("mode") == "APPROVAL_REQUIRED"
    assert calls["backend"] == 0
