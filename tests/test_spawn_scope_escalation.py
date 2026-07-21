# -*- coding: utf-8 -*-
"""
tests/test_spawn_scope_escalation.py — Bucket 2 Slice A: reject caller-side scope escalation

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

/api/agents/spawn previously let a request body override the agent's agency_level,
permitted_resources, and drs_ceiling with no bound (except drs_ceiling>60). Slice A makes
the agent definition — or the interim ceiling, since 0/125 YAMLs declare scope yet — the
authority: a body value that EXCEEDS it is a scope-escalation attempt and is REJECTED
(not clamped) and audited as SCOPE_ESCALATION_REJECTED. Within-bounds requests are unchanged.

Spawn is admin-gated, so all requests here carry a valid admin token; these tests exercise
the SCOPE layer, not the auth layer. No Docker — spawn_agent_container is stubbed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


_ADMIN = "spawn-scope-admin-token"
_AUTH = {"Authorization": "Bearer " + _ADMIN}


class _SpawnRecorder:
    def __init__(self): self.calls = []
    def __call__(self, dept_id=None, task_prompt=None, agency_level=None,
                 permitted=None, drs_ceiling=None, extra_env=None):
        self.calls.append({"dept_id": dept_id, "agency_level": agency_level,
                           "permitted": permitted, "drs_ceiling": drs_ceiling})
        return {"ok": True, "output": "spawned (stub)", "exit_code": 0}


def _app(monkeypatch, agent_def=None):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    rec = _SpawnRecorder()
    monkeypatch.setattr(A, "spawn_agent_container", rec)
    # 0/125 YAMLs declare scope today -> default to an empty def (interim ceilings apply).
    monkeypatch.setattr(A, "_get_yaml_agent", lambda _id: dict(agent_def or {}))
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app.test_client(), rec


_TASK = "summarize the weekly engineering status"


def _spawn(c, **scope):
    body = {"dept_id": "DEPT-ENG", "task": _TASK}
    body.update(scope)
    return c.post("/api/agents/spawn", json=body, headers=_AUTH)


# ── escalation is REJECTED (not clamped) and no container is spawned ───────────

def test_agency_level_escalation_rejected(monkeypatch):
    c, rec = _app(monkeypatch)
    r = _spawn(c, agency_level=3)          # interim ceiling is 2
    assert r.status_code == 403
    body = r.get_json()
    assert body["reason"] == "SCOPE_ESCALATION"
    assert any(v["field"] == "agency_level" and v["requested"] == 3 and v["allowed"] == 2
               for v in body["violations"])
    assert rec.calls == [], "escalation was clamped-and-run instead of rejected"


def test_drs_ceiling_escalation_rejected(monkeypatch):
    c, rec = _app(monkeypatch)
    r = _spawn(c, drs_ceiling=60)          # interim ceiling is 40
    assert r.status_code == 403
    assert r.get_json()["reason"] == "SCOPE_ESCALATION"
    assert rec.calls == []


def test_permitted_resources_escalation_rejected(monkeypatch):
    c, rec = _app(monkeypatch)
    r = _spawn(c, permitted_resources=["/workspace", "/etc", "/root"])
    assert r.status_code == 403
    v = [v for v in r.get_json()["violations"] if v["field"] == "permitted_resources"][0]
    assert set(v["disallowed"]) == {"/etc", "/root"}
    assert rec.calls == []


def test_non_integer_scope_value_rejected(monkeypatch):
    c, rec = _app(monkeypatch)
    r = _spawn(c, agency_level="admin")    # unparseable -> treated as escalation/invalid
    assert r.status_code == 403
    assert rec.calls == []


# ── rejection is audited with request-vs-allowed detail ────────────────────────

def test_escalation_is_audited_with_detail(monkeypatch):
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    c, rec = _app(monkeypatch)
    _spawn(c, agency_level=5, drs_ceiling=99)
    rejected = [d for et, d in events if et == "SCOPE_ESCALATION_REJECTED"]
    assert rejected, "no SCOPE_ESCALATION_REJECTED audit event emitted"
    fields = {v["field"] for v in rejected[0]["violations"]}
    assert {"agency_level", "drs_ceiling"} <= fields
    # detail carries requested vs allowed
    al = [v for v in rejected[0]["violations"] if v["field"] == "agency_level"][0]
    assert al["requested"] == 5 and al["allowed"] == 2


# ── within-bounds requests are unchanged (no regression) ───────────────────────

def test_no_scope_body_succeeds_with_defaults(monkeypatch):
    c, rec = _app(monkeypatch)
    r = _spawn(c)                          # no scope fields supplied
    assert r.status_code == 200
    assert len(rec.calls) == 1
    assert rec.calls[0]["agency_level"] == 2
    assert rec.calls[0]["drs_ceiling"] == 40
    assert rec.calls[0]["permitted"] == ["/workspace"]


def test_explicit_within_bounds_succeeds(monkeypatch):
    c, rec = _app(monkeypatch)
    r = _spawn(c, agency_level=1, drs_ceiling=40, permitted_resources=["/workspace"])
    assert r.status_code == 200
    assert len(rec.calls) == 1
    assert rec.calls[0]["agency_level"] == 1   # a LOWER request is honored


def test_definition_ceiling_is_authoritative(monkeypatch):
    """Forward-compatible with Slice C: if the definition declares a higher ceiling,
    a matching request is allowed (definition, not interim default, is the bound)."""
    c, rec = _app(monkeypatch, agent_def={"agency_level": 3, "drs_ceiling": 55})
    r = _spawn(c, agency_level=3, drs_ceiling=55)
    assert r.status_code == 200
    assert rec.calls[0]["agency_level"] == 3
