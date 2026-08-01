# -*- coding: utf-8 -*-
"""
tests/test_session_boundary.py — Gate 0 (GovMem convergence): session
isolation must key off X-Session-ID, not remote_addr.

GovMem accumulates drift/threat/lock state per Sentinel session_id
(governance-spine/src/govmem.rs). The tests below against the backend
(_resolve_chat_session / SessionRegistry) pass against the code as it was
BEFORE Gate 0's client-side change too — that backend resolution already
preferred the header over remote_addr. They're kept as a regression lock on
real, load-bearing behavior, not as evidence Gate 0 fixed something there.

The actual pre-Gate-0 gap was that no client ever sent the header, so real
traffic always fell back to remote_addr. `test_client_surfaces_emit_session_header`
below locks the fix that closes THAT gap — the one thing this gate actually
changed. Without it, a future refactor could drop the header from the JS and
every suite here would stay green.

See FINDINGS.md SESSION_ID_CLIENT_CONTROLLED: moving the session key to a
client-supplied value fixes NAT bleed but makes drift accumulation resettable
by any adversary willing to mint a fresh id per request. Not addressed here —
tracked as Q-08/Q-03 follow-up.

No network, no real provider calls, no secrets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

_STATIC_DIR = Path(__file__).parent.parent / "static"


def _approved_inspect(_task_or_payload, session_id, **_kw):
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

    def _inspect(_raw, session_id, **_kw):
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


def test_client_surfaces_emit_session_header():
    """The actual Gate 0 gap: no HTML/JS surface sent X-Session-ID, so real
    traffic always fell back to remote_addr regardless of backend support.
    Locks that every /api/chat-calling surface attaches the header — a
    source-grep guard, matching this repo's existing store1_apply pattern
    (training/tests/test_review_queue.py::test_no_store1_apply_in_source),
    so a refactor that silently drops the header fails CI instead of prod."""
    checked = 0
    for name in ("abigail.js", "dashboard.html", "operator.html"):
        src = (_STATIC_DIR / name).read_text()
        # Every /api/chat call site in these files must be accompanied by
        # the header somewhere in the same request construction — checked
        # loosely (header string present at all in a file that calls
        # /api/chat) since each surface wires it through differently
        # (inline header dict, extraHeaders param, etc).
        if "/api/chat" in src:
            assert "X-Session-ID" in src, (
                f"{name} calls /api/chat but never sends X-Session-ID — "
                "this silently reverts that surface's users to sharing "
                "governance state by remote_addr"
            )
            checked += 1
    assert checked == 3, (
        "expected all three known /api/chat-calling surfaces "
        "(abigail.js, dashboard.html, operator.html) to still exist and "
        "still call /api/chat; update this test if a surface was added, "
        "removed, or renamed"
    )
