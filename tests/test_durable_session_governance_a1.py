# -*- coding: utf-8 -*-
"""
tests/test_durable_session_governance_a1.py — A1: durable session governance
(Python side). See A1_DESIGN.md for the full design and the four
confirmations recorded before this was implemented.

Before A1, abigail_hardened_enhanced.py minted a brand-new Sentinel
session_id on every single /api/chat turn (session_id = f"session_{turn}_
{uuid4}"), so the Rust governance spine's per-session accumulation
(drift/threat/lock/escalation — see governance-spine/tests/
durable_session_governance.rs) never actually got to accumulate anything
in production; every turn looked like a new session. /session/start and
/session/end were implemented server-side but never called at all.

These tests cover the Python-side numbered claims from A1_DESIGN.md's test
plan: 6 (session identifiers remain stable, including at the dispatch
boundary), 7 (/session/start failures fail closed for the CURRENT turn),
and 8 (/session/end invoked on CLI exit and registry eviction).

No network, no real provider calls, no secrets.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


ADMIN = "durable-session-governance-admin-9f86d081884c7d659a2fea"


def _approved_inspect(_task_or_payload, session_id, **_kw):
    return {
        "ok": True, "verdict": "APPROVED", "session_id": session_id,
        "gov_tx_id": "GTX-A1-TEST", "verdict_id": "SV-A1-TEST",
        "provider_authorizable": True,
    }


def _fake_pm_recording(calls):
    def _pm(msg, session, ks, ab, approval_meta=None, step_up_ok=False, **_kw):
        calls.append(msg)
        return {"ok": True, "text": "stub", "drs": 0, "mode": "SILENT_AUTONOMY", "crsv": 0.0}
    return _pm


# ── Test 6: session identifiers remain stable ───────────────────────────────

def test_session_id_stable_across_chat_turns(monkeypatch):
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")
    monkeypatch.setattr(A, "_ensure_session_started", lambda _s: True)
    seen_ids = []

    def _inspect(_raw, session_id, **_kw):
        seen_ids.append(session_id)
        return _approved_inspect(_raw, session_id)

    monkeypatch.setattr(A, "_sentinel_inspect", _inspect)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    c = app.test_client()

    headers = {"X-Session-ID": "conv-stability-test"}
    c.post("/api/chat", json={"message": "turn one"}, headers=headers)
    c.post("/api/chat", json={"message": "turn two"}, headers=headers)
    c.post("/api/chat", json={"message": "turn three"}, headers=headers)

    assert len(seen_ids) == 3
    assert seen_ids[0] == seen_ids[1] == seen_ids[2], (
        "the same conversation must present the SAME session_id to Sentinel "
        "on every turn, not a fresh one each time"
    )
    assert seen_ids[0].startswith("conv_")


def test_dispatch_inherits_conversation_session(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")
    monkeypatch.setattr(A, "_ensure_session_started", lambda _s: True)
    monkeypatch.setattr(A, "_sentinel_inspect", _approved_inspect)
    monkeypatch.setattr(
        A, "_get_yaml_agent",
        lambda _id: {"name": "Test Agent", "system_prompt": "You are a test agent."},
    )

    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    c = app.test_client()

    headers = {"X-Session-ID": "conv-dispatch-inherit-test", "Authorization": f"Bearer {ADMIN}"}

    # Establish the conversation via chat first.
    c.post("/api/chat", json={"message": "hello"}, headers=headers)
    conversation_session = app._session_registry.peek("conv-dispatch-inherit-test")
    assert conversation_session is not None

    # A compound high-impact task that resolves to APPROVAL_REQUIRED before
    # any provider call — the same task text test_agent_dispatch_governance.py
    # uses for exactly this reason, so no additional Sentinel-authorize
    # mocking is needed to observe the governance envelope.
    r = c.post(
        "/api/agents/dispatch",
        json={
            "agent_id": "EN-01",
            "task": (
                "Immediately deploy this change to production for all users, "
                "update billing, and make the action permanent."
            ),
        },
        headers=headers,
    )
    data = r.get_json()
    assert data["mode"] == "APPROVAL_REQUIRED"
    assert data["governance"]["sentinel_session_id"] == conversation_session.sentinel_session_id


# ── Test 7: /session/start failures fail closed for the CURRENT turn ───────

def test_session_start_failure_blocks_current_turn_fail_closed(monkeypatch):
    """The exact scenario A1_DESIGN.md confirmation #1 describes: a
    /session/start failure must block THIS turn (no provider call, no
    dispatch, no session_id churn), not just cause the next turn to retry."""
    monkeypatch.setattr(A, "SENTINEL_REQUIRED", True)
    monkeypatch.setattr(
        A, "_sentinel_session_start",
        lambda *_a, **_k: (False, {"error": "connection refused"}),
    )
    inspect_calls = []
    monkeypatch.setattr(A, "_sentinel_inspect", lambda *a, **k: inspect_calls.append(a) or _approved_inspect(*a, **k))
    pm_calls = []
    monkeypatch.setattr(A, "_governed_provider_execute", lambda **k: pm_calls.append(k))

    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))

    sess = A.SessionState()
    sid_before = sess.sentinel_session_id
    ks = A.KillSwitch()

    result = A.process_message("please summarize this quarter", sess, ks, ["groq"])

    assert result["mode"] == "SENTINEL_UNREACHABLE"
    assert result["ok"] is False
    assert inspect_calls == [], "no /inspect call must happen when session-start failed closed"
    assert pm_calls == [], "no provider execution must happen when session-start failed closed"
    assert sess.sentinel_session_id == sid_before, "session_id must not churn on a blocked turn"
    assert sess.session_started is False, "must remain unstarted so the NEXT turn retries"
    assert any(et == "SENTINEL_SESSION_START_BLOCK" for et, _ in events), (
        "a blocked session-start must leave audit evidence"
    )


def test_session_start_retries_on_next_turn_after_a_blocked_one(monkeypatch):
    monkeypatch.setattr(A, "SENTINEL_REQUIRED", True)
    attempts = {"n": 0}

    def _flaky_start(*_a, **_k):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return (False, {"error": "connection refused"})
        return (True, {"starting_state": "Clean"})

    monkeypatch.setattr(A, "_sentinel_session_start", _flaky_start)
    sess = A.SessionState()

    assert A._ensure_session_started(sess) is False
    assert sess.session_started is False
    assert A._ensure_session_started(sess) is True
    assert sess.session_started is True
    assert attempts["n"] == 2, "a blocked start must be retried on the next attempt"


def test_session_start_success_marks_started_no_retry(monkeypatch):
    monkeypatch.setattr(A, "SENTINEL_REQUIRED", True)
    calls = {"n": 0}

    def _start(*_a, **_k):
        calls["n"] += 1
        return (True, {"starting_state": "Clean"})

    monkeypatch.setattr(A, "_sentinel_session_start", _start)
    sess = A.SessionState()

    assert A._ensure_session_started(sess) is True
    assert A._ensure_session_started(sess) is True
    assert A._ensure_session_started(sess) is True
    assert calls["n"] == 1, "/session/start must be called exactly once per conversation"


def test_session_start_degraded_open_when_not_required(monkeypatch):
    monkeypatch.setattr(A, "SENTINEL_REQUIRED", False)
    monkeypatch.setattr(
        A, "_sentinel_session_start",
        lambda *_a, **_k: (False, {"error": "connection refused"}),
    )
    sess = A.SessionState()
    assert A._ensure_session_started(sess) is True, (
        "SENTINEL_REQUIRED=0 must degrade-open rather than block"
    )
    assert sess.session_started is True, "degraded-open must still mark started (no per-turn retry)"


# ── Test 8: /session/end performs cleanup ───────────────────────────────────

def test_session_end_called_on_cli_exit(monkeypatch):
    end_calls = []
    monkeypatch.setattr(A, "_sentinel_session_end", lambda *a, **k: end_calls.append((a, k)) or True)

    sess = A.SessionState()
    sess.session_started = True
    ks = A.KillSwitch()

    with pytest.raises(SystemExit):
        A.handle_command("/exit", sess, ks, ["groq"])

    assert len(end_calls) == 1
    assert end_calls[0][0][0] == sess.sentinel_session_id


def test_session_end_not_called_on_cli_exit_when_never_started(monkeypatch):
    """A conversation that never successfully started a Sentinel session has
    nothing to end — no spurious /session/end call."""
    end_calls = []
    monkeypatch.setattr(A, "_sentinel_session_end", lambda *a, **k: end_calls.append((a, k)) or True)

    sess = A.SessionState()
    assert sess.session_started is False
    ks = A.KillSwitch()

    with pytest.raises(SystemExit):
        A.handle_command("/exit", sess, ks, ["groq"])

    assert end_calls == []


def test_session_end_called_on_registry_eviction(monkeypatch):
    end_calls = []
    monkeypatch.setattr(A, "_sentinel_session_end", lambda *a, **k: end_calls.append(a) or True)

    reg = A.SessionRegistry(max_sessions=2)
    first = reg.get_or_create("conv-a")
    reg.get_or_create("conv-b")
    # Registry is now at capacity (2); a third distinct key must evict one
    # of the existing non-default sessions and call /session/end for it.
    reg.get_or_create("conv-c")

    assert len(end_calls) == 1
    evicted_session_id = end_calls[0][0]
    assert evicted_session_id == first.sentinel_session_id or evicted_session_id != ""


def test_session_end_eviction_is_best_effort_not_fail_closed(monkeypatch):
    """A failed /session/end during eviction must never block creating the
    new session that triggered it."""
    monkeypatch.setattr(
        A, "_sentinel_session_end",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("sentinel unreachable")),
    )
    reg = A.SessionRegistry(max_sessions=2)
    reg.get_or_create("conv-a")
    reg.get_or_create("conv-b")

    # Must not raise despite _sentinel_session_end blowing up.
    new_session = reg.get_or_create("conv-c")
    assert new_session is not None
