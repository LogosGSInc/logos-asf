# -*- coding: utf-8 -*-
"""
test_skills_chat_wiring.py — SKILLS-01 P4 chat-only advisory wiring.

Proves skills are injected as ADVISORY CONTEXT ONLY, and never change governance:
  - explicit department + trigger match → a BOUNDED excerpt (Purpose + Governance
    Rules only) is appended to the system prompt; SKILL_ACTIVATED logged with
    gov_tx_id/skill/department/path; router metadata carries selected_skill;
  - no department / no match / negative trigger → nothing injected, no event;
  - selection runs only AFTER gates — a blocked request never activates a skill;
  - skill text never flips approval / cost / routing authority;
  - no live provider calls (backend stubbed).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


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


def _setup(monkeypatch, mode="0"):
    monkeypatch.setenv("ABIGAIL_MOE_ROUTER_MODE", mode)
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": True, "verdict": "unknown", "approved": True})
    monkeypatch.setattr(A, "try_grounded_answer", lambda *a, **k: None)
    cap = {"system": None, "backend": 0}

    def _fake_backend(messages=None, system=None, **k):
        cap["backend"] += 1
        cap["system"] = system
        return "STUB"

    monkeypatch.setitem(A.BACKEND_DISPATCH, "groq", _fake_backend)
    events = []
    monkeypatch.setattr(A, "log_event", lambda ev, p=None: events.append((ev, p or {})))
    return cap, events


REVIEW = "please review this diff for bugs"


# ── activation ────────────────────────────────────────────────────────────────
def test_skill_injected_with_department_and_match(monkeypatch):
    cap, events = _setup(monkeypatch)
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    # bounded excerpt appended to the system prompt actually sent to dispatch
    assert "[ADVISORY SKILL: code-reviewer" in cap["system"]
    assert "## Purpose" in cap["system"] and "## Governance Rules" in cap["system"]
    # metadata + audit
    assert out["router"]["selected_skill"] == "code-reviewer"
    act = [p for ev, p in events if ev == "SKILL_ACTIVATED"]
    assert act and act[0]["skill"] == "code-reviewer"
    assert act[0]["department"] == "ENG"
    assert act[0]["path"] == "skills/ENG/code-reviewer/SKILL.md"
    assert act[0]["gov_tx_id"]


def test_injection_is_bounded_excerpt_not_whole_body(monkeypatch):
    cap, _ = _setup(monkeypatch)
    A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    sys_prompt = cap["system"]
    # excerpt = Purpose + Governance Rules ONLY; other sections must NOT appear
    for excluded in ("## When to Use", "## Procedure", "## Audit Requirements", "## Tests", "## Inputs"):
        assert excluded not in sys_prompt, f"whole-body leak: {excluded}"


# ── non-activation ────────────────────────────────────────────────────────────
def test_no_department_no_skill(monkeypatch):
    cap, events = _setup(monkeypatch)
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"])  # department=None
    assert "[ADVISORY SKILL" not in (cap["system"] or "")
    assert "selected_skill" not in out.get("router", {})
    assert not [p for ev, p in events if ev == "SKILL_ACTIVATED"]


def test_negative_trigger_no_skill(monkeypatch):
    cap, events = _setup(monkeypatch)
    A.process_message("commit this for me", _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    assert "[ADVISORY SKILL" not in (cap["system"] or "")
    assert not [p for ev, p in events if ev == "SKILL_ACTIVATED"]


def test_wrong_department_no_skill(monkeypatch):
    cap, events = _setup(monkeypatch)
    A.process_message("write a commit message", _Sess(), A.KillSwitch(), ["groq"], department="SEC")
    assert "[ADVISORY SKILL" not in (cap["system"] or "")
    assert not [p for ev, p in events if ev == "SKILL_ACTIVATED"]


# ── governance precedence: skill never runs before/instead of gates ──────────
def test_approval_required_blocks_before_skill(monkeypatch):
    cap, events = _setup(monkeypatch)
    meta = {"human_approval_required": True, "risk_level": "high"}
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"],
                            approval_meta=meta, department="ENG")
    assert out["mode"] == "APPROVAL_REQUIRED"
    assert cap["backend"] == 0                       # no dispatch
    assert not [p for ev, p in events if ev == "SKILL_ACTIVATED"]  # skill never reached


def test_skill_does_not_change_routing_authority(monkeypatch):
    # mode 0 + skill present → dispatch stays single_backend (skill changed nothing)
    cap, _ = _setup(monkeypatch, mode="0")
    out = A.process_message(REVIEW, _Sess(), A.KillSwitch(), ["groq"], department="ENG")
    assert out["router"]["dispatch_status"] == "single_backend"
    assert out["router"]["selected_skill"] == "code-reviewer"
    assert cap["backend"] == 1


# ── api_chat integration + cost gate still authoritative ─────────────────────
def _client(monkeypatch, turns=1000):
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "1")
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", str(turns))
    monkeypatch.setenv("ABIGAIL_MAX_ESTIMATED_TOKENS", "8000")
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app.test_client()


def test_api_chat_department_activates_skill(monkeypatch):
    cap, _ = _setup(monkeypatch)
    c = _client(monkeypatch)
    body = c.post("/api/chat", json={"message": REVIEW, "department": "ENG"}).get_json()
    assert body["router"]["selected_skill"] == "code-reviewer"
    assert "[ADVISORY SKILL: code-reviewer" in cap["system"]


def test_cost_block_still_authoritative_with_department(monkeypatch):
    cap, events = _setup(monkeypatch)
    c = _client(monkeypatch, turns=0)   # zero budget
    body = c.post("/api/chat", json={"message": REVIEW, "department": "ENG"}).get_json()
    assert body["mode"] == "COST_BLOCKED"
    assert cap["backend"] == 0
    assert not [p for ev, p in events if ev == "SKILL_ACTIVATED"]
