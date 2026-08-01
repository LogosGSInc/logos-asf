# -*- coding: utf-8 -*-
"""
tests/test_session_boundary.py — Gate 0 (GovMem convergence): session
isolation must key off X-Session-ID, not remote_addr.

GovMem accumulates drift/threat/lock state per Sentinel session_id
(governance-spine/src/govmem.rs). Before this test existed, nothing asserted
that two distinct conversations sharing one client IP (e.g. behind one NAT,
or two tabs from the same browser) get distinct Sentinel sessions. If they
collapsed onto one session, one user's accumulated drift would silently
gate another user's requests.

No network, no real provider calls, no secrets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


def _approved_inspect(_task_or_payload, session_id):
    return {
        "ok": True, "verdict": "APPROVED", "session_id": session_id,
        "gov_tx_id": "GTX-G0-TEST", "verdict_id": "SV-G0-TEST",
        "provider_authorizable": True,
    }


def test_same_remote_addr_distinct_session_id_headers_isolated(monkeypatch):
    """Two requests carrying the same (simulated) remote_addr but different
    X-Session-ID headers must resolve to distinct Sentinel session_ids —
    i.e. distinct GovMem accumulation buckets, distinct lock state."""
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")
    monkeypatch.setattr(A, "_ensure_session_started", lambda _s: True)
    seen_ids = []

    def _inspect(_raw, session_id):
        seen_ids.append(session_id)
        return _approved_inspect(_raw, session_id)

    monkeypatch.setattr(A, "_sentinel_inspect", _inspect)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    c = app.test_client()

    # Flask's test client issues every request from the same synthetic
    # remote_addr ("127.0.0.1") by default — this is the "same NAT-shared
    # client" scenario the header exists to break out of.
    c.post("/api/chat", json={"message": "hello from user A"},
           headers={"X-Session-ID": "conv-user-a"})
    c.post("/api/chat", json={"message": "hello from user B"},
           headers={"X-Session-ID": "conv-user-b"})

    assert len(seen_ids) == 2
    assert seen_ids[0] != seen_ids[1], (
        "two different X-Session-ID values from the same remote_addr must "
        "not collapse onto the same Sentinel/GovMem session — accumulated "
        "drift and lock state would bleed between unrelated conversations"
    )


def test_session_registry_holds_distinct_state_per_session_id(monkeypatch):
    """Directly against the registry: distinct X-Session-ID keys must
    produce distinct SessionState objects (distinct sentinel_session_id),
    never a shared one keyed by remote_addr."""
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")
    monkeypatch.setattr(A, "_ensure_session_started", lambda _s: True)
    monkeypatch.setattr(A, "_sentinel_inspect", _approved_inspect)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])

    registry = app._session_registry
    a = registry.get_or_create("conv-user-a")
    b = registry.get_or_create("conv-user-b")

    assert a is not b
    assert a.sentinel_session_id != b.sentinel_session_id
