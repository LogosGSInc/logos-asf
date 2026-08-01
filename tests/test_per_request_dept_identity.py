# -*- coding: utf-8 -*-
"""
tests/test_per_request_dept_identity.py — Gate 2: department identity travels
per-request to Sentinel, not fixed at process start (F-GM-005).

Before this gate, governance-spine/src/pipeline.rs read GOVMEM_DEPARTMENT_ID
once from the environment at process construction. Every request through one
Sentinel process was attributed to the same department (or none) regardless
of which department actually sent it — should_block's per-department drift
threshold was unreachable from any real request.

These tests exercise the Python side: /api/chat resolves and validates
department_id, then forwards it to _sentinel_inspect (which now sends it in
the /inspect JSON body — see FINDINGS.md: DEPT_THRESHOLD_CLIENT_SELECTABLE
for the Rust-side behavior this enables, and governance-spine/src/govmem.rs's
registry_tests::should_block_threshold_is_department_selectable for the
Rust-side proof). No real Sentinel process runs during these tests —
_sentinel_inspect is monkeypatched, same convention as
tests/test_session_boundary.py and tests/test_durable_session_governance_a1.py.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


def _active_codes():
    reg = json.loads(Path("departments/registry.json").read_text())
    return sorted(d["code"] for d in reg["departments"] if d["status"] == "active")


ACTIVE_CODES = _active_codes()


def _client(monkeypatch, captured=None):
    """A /api/chat test client with Sentinel calls stubbed out.

    If `captured` is given, each _sentinel_inspect call appends its
    (payload, session_id, department_id, agent_id) args to it.
    """
    monkeypatch.setattr(A, "_ensure_session_started", lambda _session: True)

    def _fake_inspect(payload, session_id, department_id=None, agent_id=None):
        if captured is not None:
            captured.append({
                "payload": payload, "session_id": session_id,
                "department_id": department_id, "agent_id": agent_id,
            })
        return {"ok": True, "verdict": "approved", "approved": True,
                "gov_tx_id": "GTX-test", "verdict_id": "VID-test",
                "provider_authorizable": False}

    monkeypatch.setattr(A, "_sentinel_inspect", _fake_inspect)

    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client()


def test_two_departments_attributed_distinctly(monkeypatch):
    """Two requests naming different departments must reach Sentinel with
    distinct department_id values — not both collapse onto the same thing."""
    captured = []
    c = _client(monkeypatch, captured)

    c.post("/api/chat", json={"message": "test", "department_id": "LGL"},
           headers={"X-Session-ID": "gate2-test-lgl"})
    c.post("/api/chat", json={"message": "test", "department_id": "ENG"},
           headers={"X-Session-ID": "gate2-test-eng"})

    assert len(captured) == 2
    assert captured[0]["department_id"] == "LGL"
    assert captured[1]["department_id"] == "ENG"
    assert captured[0]["department_id"] != captured[1]["department_id"]


def test_unknown_department_rejected(monkeypatch):
    """An unknown department code must be rejected before Sentinel is ever called."""
    captured = []
    c = _client(monkeypatch, captured)

    r = c.post("/api/chat", json={"message": "test", "department_id": "BOGUS"},
               headers={"X-Session-ID": "gate2-test-bogus"})

    assert r.status_code == 400, f"Unknown dept should be rejected, got {r.status_code}: {r.data}"
    data = r.get_json()
    assert data["mode"] == "DEPT_REJECTED"
    assert not captured, "Sentinel must never be called for a rejected department"


def test_absent_department_id_forwarded_as_none(monkeypatch):
    """A request with no department_id must forward None to Sentinel — never
    a made-up default. (The env var this used to silently fall back to,
    GOVMEM_DEPARTMENT_ID, no longer exists on the Rust side as of this gate —
    see governance-spine/src/pipeline.rs.)"""
    captured = []
    c = _client(monkeypatch, captured)

    r = c.post("/api/chat", json={"message": "test"},
               headers={"X-Session-ID": "gate2-test-no-dept"})

    assert r.status_code == 200
    assert len(captured) == 1
    assert captured[0]["department_id"] is None


@pytest.mark.parametrize("code", ACTIVE_CODES)
def test_all_active_departments_accepted(monkeypatch, code):
    """Every active registry department must be accepted and forwarded verbatim."""
    captured = []
    c = _client(monkeypatch, captured)

    r = c.post("/api/chat", json={"message": "test", "department_id": code},
               headers={"X-Session-ID": f"gate2-test-{code.lower()}"})

    assert r.status_code == 200, f"Active department {code} should be accepted, got {r.status_code}: {r.data}"
    assert captured[0]["department_id"] == code


def test_department_id_is_case_and_whitespace_normalized(monkeypatch):
    captured = []
    c = _client(monkeypatch, captured)

    c.post("/api/chat", json={"message": "test", "department_id": " lgl "},
           headers={"X-Session-ID": "gate2-test-normalize"})

    assert captured[0]["department_id"] == "LGL"


def test_agent_id_forwarded_as_metadata(monkeypatch):
    """agent_id is optional per-request metadata, not validated against a
    registry (no such registry exists yet) — just forwarded as given."""
    captured = []
    c = _client(monkeypatch, captured)

    c.post("/api/chat", json={"message": "test", "agent_id": "LGL-01"},
           headers={"X-Session-ID": "gate2-test-agent"})

    assert captured[0]["agent_id"] == "LGL-01"


def test_should_block_department_selectable_end_to_end_marker():
    """This Python suite can't drive the Rust should_block threshold
    directly — that's proven in governance-spine/src/govmem.rs's
    registry_tests::should_block_threshold_is_department_selectable (run via
    `cargo test`). This is a pointer, not a duplicate: if that Rust test's
    name changes, this one should be updated to match, so the two don't
    silently drift apart the way the department lists did pre-Gate-1."""
    rust_src = Path("governance-spine/src/govmem.rs").read_text()
    assert "fn should_block_threshold_is_department_selectable" in rust_src
