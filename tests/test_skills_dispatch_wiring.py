# -*- coding: utf-8 -*-
"""
test_skills_dispatch_wiring.py — SKILLS-01 P4b-2a agent-dispatch advisory wiring.

Dispatch-path parity with the chat wiring. Inert in production until an agent
registry ships (agents/ not shipped); here the agent_def is stubbed so the wiring
is fully exercised. Proves the same invariant:

  A skill may influence WORDING after governance approval, but never WHETHER
  EXECUTION IS ALLOWED.

No live provider calls (backend stubbed).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

ADMIN = "admintok_P4b2a"
REVIEW = "please review this diff for bugs"


def _setup(monkeypatch, verdict="unknown", dept="EN-01"):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "1")
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", "1000")
    monkeypatch.setenv("ABIGAIL_MAX_ESTIMATED_TOKENS", "8000")
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": True, "verdict": verdict, "approved": True})
    monkeypatch.setattr(A, "_get_yaml_agent",
                        lambda aid: {"name": "Bezalel", "department": dept,
                                     "system_prompt": "You are an engineering agent."})
    cap = {"system": None, "backend": 0}

    def _fake(messages=None, system=None, **k):
        cap["backend"] += 1
        cap["system"] = system
        return "STUB"

    monkeypatch.setitem(A.BACKEND_DISPATCH, "groq", _fake)
    events = []
    monkeypatch.setattr(A, "log_event", lambda ev, p=None: events.append((ev, p or {})))
    return cap, events


def _client():
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app.test_client()


def _auth():
    return {"Authorization": f"Bearer {ADMIN}"}


def _post(c, body, headers=None):
    return c.post("/api/agents/dispatch", json=body, headers=headers or {})


def _activated(events):
    return [p for ev, p in events if ev == "SKILL_ACTIVATED"]


# ── activation on dispatch ────────────────────────────────────────────────────
def test_dispatch_activates_department_skill(monkeypatch):
    cap, events = _setup(monkeypatch, dept="EN-01")   # EN-01 → ENG
    c = _client()
    body = _post(c, {"agent_id": "EN-01-MA", "task": REVIEW}, _auth()).get_json()
    assert body["ok"] is True
    assert body["selected_skill"] == "code-reviewer"
    assert "[ADVISORY SKILL: code-reviewer" in cap["system"]
    assert "## Purpose" in cap["system"] and "## Governance Rules" in cap["system"]
    act = _activated(events)
    assert act and act[0]["skill"] == "code-reviewer"
    assert act[0]["agent_id"] == "EN-01-MA" and act[0]["gov_tx_id"]
    assert act[0]["path"] == "skills/ENG/code-reviewer/SKILL.md"


def test_dispatch_excerpt_is_bounded(monkeypatch):
    cap, _ = _setup(monkeypatch)
    _post(_client(), {"agent_id": "EN-01-MA", "task": REVIEW}, _auth())
    for excluded in ("## When to Use", "## Procedure", "## Tests", "## Inputs", "## Audit Requirements"):
        assert excluded not in cap["system"]


def test_dispatch_unmapped_department_no_skill(monkeypatch):
    cap, events = _setup(monkeypatch, dept="MKT-01")   # no skills for MKT
    body = _post(_client(), {"agent_id": "MKT-01", "task": REVIEW}, _auth()).get_json()
    assert "selected_skill" not in body
    assert "[ADVISORY SKILL" not in (cap["system"] or "")
    assert not _activated(events)


# ── invariant: skill never changes the execution decision ────────────────────
def test_unauth_dispatch_no_skill_no_execution(monkeypatch):
    cap, events = _setup(monkeypatch)
    body = _post(_client(), {"agent_id": "EN-01-MA", "task": REVIEW})  # no token
    assert body.status_code == 401
    assert cap["backend"] == 0 and not _activated(events)


def test_sentinel_block_before_skill(monkeypatch):
    cap, events = _setup(monkeypatch, verdict="quarantined")
    r = _post(_client(), {"agent_id": "EN-01-MA", "task": REVIEW}, _auth())
    assert r.status_code == 403
    assert cap["backend"] == 0 and not _activated(events)


def test_approval_required_before_skill(monkeypatch):
    cap, events = _setup(monkeypatch)
    body = _post(_client(), {"agent_id": "EN-01-MA", "task": REVIEW, "risk_level": "high"},
                 _auth()).get_json()
    assert body.get("mode") == "APPROVAL_REQUIRED"
    assert cap["backend"] == 0 and not _activated(events)


def test_cost_block_before_skill(monkeypatch):
    cap, events = _setup(monkeypatch)
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", "0")   # zero budget
    body = _post(_client(), {"agent_id": "EN-01-MA", "task": REVIEW}, _auth()).get_json()
    assert body.get("mode") == "COST_BLOCKED"
    assert cap["backend"] == 0 and not _activated(events)


def test_skill_activated_never_logs_body_on_dispatch(monkeypatch):
    _, events = _setup(monkeypatch)
    _post(_client(), {"agent_id": "EN-01-MA", "task": REVIEW}, _auth())
    act = _activated(events)
    assert act
    assert set(act[0].keys()) == {"gov_tx_id", "skill", "department", "path", "agent_id"}
    assert "Purpose" not in str(act[0]) and "##" not in str(act[0])


# ── dept map correctness ──────────────────────────────────────────────────────
def test_dept_map_only_four_skill_departments():
    assert A._AGENT_DEPT_TO_SKILL == {"EN-01": "ENG", "SEC-01": "SEC", "OPS-01": "OPS", "GRC-01": "GRC"}
