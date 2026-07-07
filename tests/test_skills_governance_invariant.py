# -*- coding: utf-8 -*-
"""
test_skills_governance_invariant.py — SKILLS-01 P4 tripwires + the core invariant.

KEY INVARIANT:
  A skill may influence WORDING after governance approval, but it must never
  influence WHETHER EXECUTION IS ALLOWED.

Tripwires verified here:
  - import guard fails soft to NO SKILL (chat still works, no crash);
  - selection needs an explicit department; invalid department → no skill;
  - SKILL_ACTIVATED never logs the skill body;
  - blocked requests (Sentinel / approval / cost) never activate a skill;
  - the dispatch route has no skill wiring;
  - Dockerfile untouched.
No live provider calls.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

RUNTIME = ROOT / "abigail" / "abigail_hardened_enhanced.py"
REVIEW = "please review this diff for bugs"


class _Sess:
    def __init__(self):
        self.turn_count = 0
        self.messages = []
    def crsv(self): return 0.0
    def record_turn(self, *a, **k): self.turn_count += 1
    def drift_warning(self): return None


def _setup(monkeypatch, verdict="unknown", mode="0"):
    monkeypatch.setenv("ABIGAIL_MOE_ROUTER_MODE", mode)
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": True, "verdict": verdict, "approved": True})
    monkeypatch.setattr(A, "try_grounded_answer", lambda *a, **k: None)
    cap = {"system": None, "backend": 0}
    def _fake(messages=None, system=None, **k):
        cap["backend"] += 1; cap["system"] = system; return "STUB"
    monkeypatch.setitem(A.BACKEND_DISPATCH, "groq", _fake)
    events = []
    monkeypatch.setattr(A, "log_event", lambda ev, p=None: events.append((ev, p or {})))
    return cap, events


def _activated(events):
    return [p for ev, p in events if ev == "SKILL_ACTIVATED"]


# ── tripwire: import guard fails soft to NO SKILL, never blocks chat ─────────
def test_import_guard_fail_soft_no_skill(monkeypatch):
    cap, events = _setup(monkeypatch)
    monkeypatch.setattr(A, "_SKILLS_OK", False)     # simulate skills_lib unavailable
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    assert out["ok"] is True and cap["backend"] == 1          # chat still works
    assert "[ADVISORY SKILL" not in (cap["system"] or "")
    assert not _activated(events)


def test_selection_error_fails_soft(monkeypatch):
    cap, events = _setup(monkeypatch)
    def _boom(*a, **k): raise RuntimeError("discovery blew up")
    monkeypatch.setattr(A, "_select_skill", _boom)
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    assert out["ok"] is True and cap["backend"] == 1          # never blocks chat
    assert not _activated(events)
    assert any(ev == "SKILL_SELECT_ERROR" for ev, _ in events)


# ── tripwire: explicit department required; invalid → no skill ───────────────
def test_invalid_department_value_no_skill(monkeypatch):
    cap, _ = _setup(monkeypatch)
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "1")
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", "1000")
    monkeypatch.setenv("ABIGAIL_MAX_ESTIMATED_TOKENS", "8000")
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"]); app.testing = True
    body = app.test_client().post("/api/chat",
        json={"message": REVIEW, "department": "engineering"}).get_json()  # lowercase/invalid
    assert "selected_skill" not in body.get("router", {})
    assert "[ADVISORY SKILL" not in (cap["system"] or "")


# ── tripwire: SKILL_ACTIVATED never logs the body ────────────────────────────
def test_skill_activated_never_logs_body(monkeypatch):
    _, events = _setup(monkeypatch)
    A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    act = _activated(events)
    assert act, "skill should have activated"
    payload = act[0]
    assert set(payload.keys()) == {"gov_tx_id", "skill", "department", "path"}
    blob = str(payload)
    for body_marker in ("## Purpose", "## Governance Rules", "Advisory only", "Procedure"):
        assert body_marker not in blob     # no body content in the audit event


# ── tripwire: blocked requests never activate a skill ────────────────────────
def test_sentinel_block_before_skill(monkeypatch):
    cap, events = _setup(monkeypatch, verdict="quarantined")
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    assert out["mode"] == "SENTINEL_BLOCK"
    assert cap["backend"] == 0 and not _activated(events)


# ── tripwire: dispatch route has no skill wiring; Dockerfile untouched ───────
def test_dispatch_route_has_no_skill_wiring():
    src = RUNTIME.read_text(encoding="utf-8")
    m = re.search(r"def api_agents_dispatch\(.*?\n(.*?)\n    @flask_app\.route", src, re.S)
    assert m, "could not isolate dispatch route"
    route_body = m.group(1)
    for banned in ("_select_skill", "SKILL_ACTIVATED", "_skill_excerpt"):
        assert banned not in route_body, f"dispatch route must not wire skills: {banned}"


def test_dockerfile_ships_skills_but_not_agents():
    # P4b-1: skills library + module are shipped; agent registry is NOT (P4b-2 / DOCK-03).
    df = (ROOT / "abigail" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY skills /app/skills" in df
    assert "COPY abigail/skills_lib /app/skills_lib" in df
    assert "COPY agents" not in df, "agent registry must not be shipped yet (P4b-2/DOCK-03)"


# ══════════════════════════════════════════════════════════════════════════════
# KEY INVARIANT: a skill changes wording, never the execution decision.
# ══════════════════════════════════════════════════════════════════════════════
def test_skill_changes_wording_not_execution_decision(monkeypatch):
    # (a) ALLOWED request: with vs without a skill → identical execution decision;
    #     the ONLY difference is the system prompt wording.
    cap1, _ = _setup(monkeypatch)
    out_no = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"])          # no dept
    sys_no, disp_no, be_no = cap1["system"], out_no["router"]["dispatch_status"], cap1["backend"]

    cap2, _ = _setup(monkeypatch)
    out_sk = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    sys_sk, disp_sk, be_sk = cap2["system"], out_sk["router"]["dispatch_status"], cap2["backend"]

    assert disp_no == disp_sk == "single_backend"      # SAME execution decision
    assert be_no == be_sk == 1                          # both executed once
    assert "[ADVISORY SKILL" not in sys_no and "[ADVISORY SKILL" in sys_sk  # only wording differs


def test_skill_cannot_unblock_denied_request(monkeypatch):
    # (b) DENIED request (approval required): adding a skill must NOT unblock it.
    cap, events = _setup(monkeypatch)
    meta = {"human_approval_required": True, "risk_level": "high"}
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"],
                            approval_meta=meta, department="ENG")
    assert out["mode"] == "APPROVAL_REQUIRED"           # still denied
    assert cap["backend"] == 0                          # no execution
    assert not _activated(events)                       # skill never even selected
