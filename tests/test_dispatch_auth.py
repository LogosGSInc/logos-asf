# -*- coding: utf-8 -*-
"""
tests/test_dispatch_auth.py — /api/agents/dispatch fail-closed admin authentication

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

/api/agents/dispatch runs a governed agent's system_prompt through live, billable model
inference. It previously had no authentication — only a content-based haap_gate. These
tests prove the route is now admin-authenticated fail-closed, that rejection happens
BEFORE any provider call, and that an authenticated request enters the capability-bound governed
execution boundary with complete authority evidence.

No real provider or Sentinel capability calls — the governed execution boundary
is replaced with a call-recording fake. No secrets.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


_ADMIN = "dispatch-admin-token-9f86d081884c7d659a2feaa0c55ad015a"


class _Recorder:
    """Fake backend that records every inference call so we can assert it was / wasn't hit."""
    def __init__(self):
        self.calls = []
    def __call__(self, messages=None, system=None, **kw):
        self.calls.append({"messages": messages, "system": system})
        return "fake agent response"


def _app(monkeypatch):
    rec = _Recorder()

    # A1: no real Sentinel reachable in tests — treat the session as already
    # started (unrelated to what this file tests).
    monkeypatch.setattr(A, "_ensure_session_started", lambda _session: True)

    # A resolvable agent, independent of on-disk YAML.
    monkeypatch.setattr(
        A,
        "_get_yaml_agent",
        lambda _id: {
            "name": "Test Agent",
            "system_prompt": "You are a test agent.",
        },
    )

    # Deterministic authoritative Sentinel decision with the transaction-bound
    # evidence now required by capability authorization.
    monkeypatch.setattr(
        A,
        "_sentinel_inspect",
        lambda _task, _session_id: {
            "ok": True,
            "verdict": "APPROVED",
            "tool_calls_disabled": False,
            "enhanced_logging": False,
            "gov_tx_id": "GTX-DISPATCH-TEST",
            "verdict_id": "SV-DISPATCH-TEST",
        },
    )

    # No real Sentinel capability calls or provider inference. Record the exact
    # governed execution invocation instead.
    def _fake_governed_provider_execute(**kwargs):
        rec.calls.append(kwargs)
        return (
            "fake agent response",
            {
                "execution_status": "completed",
                "capability_outcome": "CAPABILITY_CONSUMED",
                "outbound_verdict": "APPROVED",
                "gov_tx_id": kwargs["gov_tx_id"],
                "verdict_id": kwargs["expected_verdict_id"],
                "decision_id": "DEC-DISPATCH-TEST",
                "capability_id": "CAP-DISPATCH-TEST",
                "backend": kwargs["provider"],
                "model": "test-model",
            },
        )

    monkeypatch.setattr(
        A,
        "_governed_provider_execute",
        _fake_governed_provider_execute,
    )

    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client(), rec


_BODY = {"agent_id": "EN-01", "task": "summarize the quarterly status report"}


# ── unauthenticated / bad token: rejected BEFORE inference ─────────────────────

def test_dispatch_rejects_missing_token_before_inference(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c, rec = _app(monkeypatch)
    r = c.post("/api/agents/dispatch", json=_BODY)
    assert r.status_code == 401
    assert rec.calls == [], "inference ran despite missing auth — rejection is not before dispatch"


def test_dispatch_rejects_wrong_token_before_inference(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c, rec = _app(monkeypatch)
    r = c.post("/api/agents/dispatch", json=_BODY, headers={"X-HAAP-Token": "nope"})
    assert r.status_code == 401
    assert rec.calls == []


def test_dispatch_fail_closed_when_server_token_unset(monkeypatch):
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    c, rec = _app(monkeypatch)
    r = c.post("/api/agents/dispatch", json=_BODY)
    assert r.status_code == 503  # misconfiguration fails closed
    assert rec.calls == []


def test_dispatch_auth_rejected_is_audited(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append(et))
    c, rec = _app(monkeypatch)
    c.post("/api/agents/dispatch", json=_BODY)
    assert "DISPATCH_AUTH_REJECTED" in events


# ── authenticated: enters capability-bound governed execution ─────────────────

def test_dispatch_authenticated_succeeds_and_runs_inference(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c, rec = _app(monkeypatch)
    r = c.post("/api/agents/dispatch", json=_BODY,
               headers={"Authorization": f"Bearer {_ADMIN}"})
    assert r.status_code == 200
    assert len(rec.calls) == 1, (
        "authenticated dispatch did not invoke exactly one governed execution"
    )

    call = rec.calls[0]
    assert call["system"] == "You are a test agent."
    assert call["provider"] == "groq"
    assert call["gov_tx_id"] == "GTX-DISPATCH-TEST"
    assert call["expected_verdict_id"] == "SV-DISPATCH-TEST"
    assert call["messages"] == [{
        "role": "user",
        "content": _BODY["task"],
    }]

    data = r.get_json()
    assert data["governance"]["execution_status"] == "completed"
    assert data["governance"]["capability_outcome"] == "CAPABILITY_CONSUMED"
    assert data["governance"]["outbound_verdict"] == "APPROVED"


def test_dispatch_authenticated_response_shape_unchanged(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c, rec = _app(monkeypatch)
    r = c.post("/api/agents/dispatch", json=_BODY,
               headers={"Authorization": f"Bearer {_ADMIN}"})
    data = r.get_json()
    for key in (
        "ok",
        "agent_id",
        "agent_name",
        "text",
        "drs",
        "mode",
        "crsv",
        "governance",
    ):
        assert key in data, f"authenticated dispatch response missing key {key!r}"

    for key in (
        "execution_status",
        "capability_outcome",
        "outbound_verdict",
        "gov_tx_id",
        "verdict_id",
        "decision_id",
        "capability_id",
        "backend",
        "model",
    ):
        assert key in data["governance"], (
            f"dispatch governance evidence missing key {key!r}"
        )
    assert data["ok"] is True
    assert data["agent_id"] == "EN-01"
    assert data["text"] == "fake agent response"
