# -*- coding: utf-8 -*-
"""
test_p0_corrective_sprint.py — ABIGAIL-SPRINT-01 Phase 0 corrective-fix verification.

Evidence-based checks for:
  P0-1  Sentinel fail-closed enforcement (offline blocks; audited as unreachable)
  P0-2  RESTRICTED / HAAP_GATED verdict enforcement (covered in test_sentinel_verdict_case)
  P0-3  Per-session keyed state (no cross-session bleed) + bounded history window
  P0-4  Real Ed25519 handoff-packet signing + verifier (covered in test_orchestration_handoff_packet)
  P0-5  One real governed swarm endpoint end-to-end (signed+verified packets, one gov_tx_id,
        actual work product — not a template)

No network. No real provider calls (BACKEND_DISPATCH is stubbed). No secrets.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


def _app(monkeypatch, admin_token="p0-admin-token-9f86d081884c7d659a2feaa0c55ad015a3bf4f1b"):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", admin_token)
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app, admin_token


# ── P0-1: Sentinel fail-closed at the HTTP layer ──────────────────────────────

def test_p0_1_offline_sentinel_blocks_via_http(monkeypatch):
    """With the real Sentinel offline (default in this env) and SENTINEL_REQUIRED on,
    a chat request is hard-blocked as unreachable — not degraded, not passed through."""
    monkeypatch.setattr(A, "SENTINEL_REQUIRED", True)
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": False, "verdict": "sentinel_offline",
                                         "approved": False, "error": "connect refused"})
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    app, _ = _app(monkeypatch)
    r = app.test_client().post("/api/chat", json={"message": "hello there"})
    body = r.get_json()
    assert body["ok"] is False
    assert body["mode"] == "SENTINEL_UNREACHABLE"
    assert "SENTINEL_UNREACHABLE_BLOCK" in [et for et, _ in events]
    # It must NOT be attributed to a normal Python-gate verdict.
    assert body["mode"] not in ("BLOCKED", "SILENT_AUTONOMY", "PUBLIC_ASSIST")


# ── P0-3: per-session isolation (no cross-session bleed) ──────────────────────

def test_p0_3_sessions_do_not_bleed(monkeypatch):
    """Two distinct session ids get isolated SessionState — turn counts and message
    history do not cross-contaminate."""
    # Stub the pipeline so we exercise the registry wiring without provider/sentinel.
    def _fake_pm(msg, session, ks, ab, approval_meta=None, step_up_ok=False):
        session.record_turn(msg, 0, [])
        session.append_message("user", msg)
        return {"ok": True, "text": "ok", "drs": 0, "mode": "SILENT_AUTONOMY",
                "crsv": session.crsv()}
    monkeypatch.setattr(A, "process_message", _fake_pm)
    app, _ = _app(monkeypatch)
    c = app.test_client()

    c.post("/api/chat", json={"message": "A-1"}, headers={"X-Session-ID": "alice"})
    c.post("/api/chat", json={"message": "A-2"}, headers={"X-Session-ID": "alice"})
    c.post("/api/chat", json={"message": "B-1"}, headers={"X-Session-ID": "bob"})

    reg = app._session_registry
    alice = reg.peek("alice")
    bob = reg.peek("bob")
    assert alice.turn_count == 2, "alice should have exactly her two turns"
    assert bob.turn_count == 1, "bob should have exactly his one turn"
    alice_msgs = [m["content"] for m in alice.messages]
    bob_msgs = [m["content"] for m in bob.messages]
    assert alice_msgs == ["A-1", "A-2"]
    assert bob_msgs == ["B-1"]
    assert "B-1" not in alice_msgs and "A-1" not in bob_msgs, "cross-session bleed detected"


def test_p0_3_history_window_trims(monkeypatch):
    """Conversation history is bounded to the window, not retained/resent forever."""
    monkeypatch.setattr(A, "SESSION_HISTORY_WINDOW", 4)
    s = A.SessionState()
    for i in range(10):
        s.append_message("user", f"m{i}")
    assert len(s.messages) == 4, "history must be trimmed to the window"
    assert [m["content"] for m in s.messages] == ["m6", "m7", "m8", "m9"]


def test_p0_3_registry_isolation_unit():
    reg = A.SessionRegistry()
    a = reg.get_or_create("x")
    b = reg.get_or_create("y")
    assert a is not b
    assert reg.get_or_create("x") is a  # stable per key


# ── P0-5: one real governed swarm endpoint end-to-end ─────────────────────────

def _stub_backend(monkeypatch):
    """Stub the provider so the worker returns a detectable REAL work product (proving
    the governed-LLM worker path ran, not the deterministic _draft template)."""
    def _stub(messages=None, system=None, **k):
        user = messages[-1]["content"] if messages else ""
        return f"REAL_LLM_WORK_PRODUCT :: {user[:40]}"
    monkeypatch.setattr(A, "BACKEND_DISPATCH", {"groq": _stub})


def test_p0_5_requires_admin(monkeypatch):
    _stub_backend(monkeypatch)
    app, _ = _app(monkeypatch)
    r = app.test_client().post("/api/swarm/dispatch", json={"task": "x", "department": "ENG"})
    assert r.status_code in (401, 403), "swarm dispatch must be admin-gated (fail-closed)"


def test_p0_5_governed_swarm_end_to_end(monkeypatch):
    _stub_backend(monkeypatch)
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    app, tok = _app(monkeypatch)
    r = app.test_client().post(
        "/api/swarm/dispatch",
        json={"task": "Draft a friendly product FAQ intro", "departments": ["ENG", "MKT"]},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["ok"] is True
    assert len(body["results"]) == 2

    # (a) actual work product, not a template string
    for res in body["results"]:
        assert res["status"] == "complete"
        assert res["content"].startswith("REAL_LLM_WORK_PRODUCT ::"), \
            "worker returned a template, not governed-LLM output"
        assert "governed local draft" not in res["content"].lower(), \
            "worker fell back to the _draft template"
        # (c) packet was signed + verified per P0-4 (complete is only reachable post-verify)
        assert res["packet_verified"] is True
        assert res["packet_id"]

    # (b) every step shares ONE job-level gov_tx_id
    gov_ids = {res["gov_tx_id"] for res in body["results"]}
    assert len(gov_ids) == 1, f"steps did not share one gov_tx_id: {gov_ids}"
    assert body["single_gov_tx_id"] is True
    assert body["gov_tx_id"] and body["gov_tx_id"].startswith("GTX-")
    assert body["gov_tx_id"] in gov_ids

    # audit trail: the SWARM_DISPATCH_COMPLETE event carries the same single gov_tx_id
    done = [d for et, d in events if et == "SWARM_DISPATCH_COMPLETE"]
    assert done and done[0]["gov_tx_id"] == body["gov_tx_id"]


def test_p0_5_swarm_worker_uses_signed_verified_packet(monkeypatch):
    """Direct proof the receiving side rejects an unsigned/placeholder packet (P0-4/P0-5):
    a legacy-style packet must not be accepted by execute_worker."""
    _stub_backend(monkeypatch)
    from swarm import execute_worker, SwarmDenied
    from orchestration import build_routing_manifest
    from orchestration.handoff_packet import build_handoff_packet
    import dataclasses

    manifest = build_routing_manifest(
        task_intent="t", request_type="chat_inference", modality="text",
        source_trust_class="operator_direct", risk_level="low", input_payload=b"t",
    )
    good = build_handoff_packet(manifest, to_agent="ENG-LEAD", mission="draft",
                                authority_scope="produce_local_draft:x")
    # A tampered / unsigned variant (legacy placeholder) must be refused.
    forged = dataclasses.replace(good, signature_algorithm="SHA256_CHAIN_PLACEHOLDER",
                                 signature_placeholder="SHA256_CHAIN_PLACEHOLDER:deadbeef")
    with pytest.raises(SwarmDenied):
        execute_worker(forged, "ENG")
    # The genuine signed packet is accepted.
    out = execute_worker(good, "ENG")
    assert isinstance(out, str) and out
