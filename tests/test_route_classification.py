# -*- coding: utf-8 -*-
"""
test_route_classification.py — router-wrapper-realignment D4.

Asserts:
  1. The full tests/route_corpus.jsonl corpus classifies as expected.
  2. classify_route is pure (no network/provider imports reachable from it).
  3. Soft quarantine: a blocked/quarantined turn does not poison a later
     LOCAL_STATUS/LOCAL_TESTING_GUIDANCE turn in the same session.
  4. The D3 stage enum exists and is used on blocked responses.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402
from model_router import classify as C  # noqa: E402

CORPUS_PATH = Path(__file__).parent / "route_corpus.jsonl"


def _load_corpus():
    rows = []
    with open(CORPUS_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


CORPUS = _load_corpus()


def test_corpus_file_has_all_15_verification_prompts():
    assert len(CORPUS) == 15


@pytest.mark.parametrize("row", CORPUS, ids=[r["prompt"][:40] for r in CORPUS])
def test_corpus_classification(row):
    route = C.classify_route(row["prompt"], None)
    assert route.intent_class == row["expected"], (
        f"{row['prompt']!r}: expected {row['expected']}, got {route.intent_class}"
    )


def test_classify_route_is_pure_no_network_no_provider_call():
    """classify.py imports nothing network- or Flask-shaped — only stdlib
    plus its pure sibling modules (schemas, sensitivity)."""
    import ast
    import inspect
    import model_router.classify as mod

    tree = ast.parse(inspect.getsource(mod))
    banned = {"httpx", "requests", "socket", "flask"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(n.name.split(".")[0].lower() for n in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())
    assert not (imported & banned), f"classify.py must stay network/Flask-free: found {imported & banned}"


def test_classify_route_deterministic():
    for row in CORPUS:
        a = C.classify_route(row["prompt"], None)
        b = C.classify_route(row["prompt"], None)
        assert a.intent_class == b.intent_class


def test_unknown_high_risk_never_assigned_for_lack_of_signal():
    """UNKNOWN_HIGH_RISK is reserved for a detected-but-unresolvable action
    verb — never a default for plain ambiguous chat."""
    for prompt in ["hello", "what's up", "tell me a joke", "I'm not sure what I need",
                   "can you help me think through something"]:
        route = C.classify_route(prompt, None)
        assert route.intent_class != C.UNKNOWN_HIGH_RISK


# ── Session/session-state doubles (mirrors tests/test_public_response_calibration.py) ──
class _Sess:
    def __init__(self):
        self.turn_count = 0
        self.cumulative_drs = 0
        self.messages = []
        self.flags = []
        self.sentinel_session_id = "conv_test_route_classification"

    def crsv(self):
        return 0.0

    def record_turn(self, *a, **k):
        self.turn_count += 1

    def append_message(self, role, content):
        self.messages.append({"role": role, "content": content})

    def drift_warning(self):
        return None


def test_local_status_never_touches_sentinel_or_ensure_session_started(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("LOCAL_STATUS must not touch Sentinel")

    monkeypatch.setattr(A, "_ensure_session_started", _boom)
    monkeypatch.setattr(A, "_sentinel_inspect", _boom)

    out = A.process_message(
        "what is your current runtime status", _Sess(), A.KillSwitch(), ["groq"]
    )
    assert out["ok"] is True
    assert out["mode"] == "LOCAL_STATUS"
    assert out["intent_class"] == "LOCAL_STATUS"
    assert out["governance"]["provider_execution_required"] is False


def test_local_testing_guidance_never_touches_sentinel(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("LOCAL_TESTING_GUIDANCE must not touch Sentinel")

    monkeypatch.setattr(A, "_ensure_session_started", _boom)
    monkeypatch.setattr(A, "_sentinel_inspect", _boom)

    out = A.process_message(
        "how can i test your current state and capability status",
        _Sess(), A.KillSwitch(), ["groq"],
    )
    assert out["ok"] is True
    assert out["mode"] == "LOCAL_TESTING_GUIDANCE"
    assert len(out["checklist"]) > 0


def test_soft_quarantine_does_not_poison_later_local_status_turn(monkeypatch):
    """D3: one blocked prompt must not poison subsequent benign prompts.
    LOCAL_STATUS/LOCAL_TESTING_GUIDANCE remain available unless a hard lock
    (kill switch) is set — not a Sentinel-side quarantine on this session."""
    monkeypatch.setattr(A, "_ensure_session_started", lambda _s: True)
    monkeypatch.setattr(
        A,
        "_sentinel_inspect",
        lambda *a, **kw: {"ok": True, "verdict": "quarantined", "session_id": "x"},
    )

    sess = _Sess()
    kill = A.KillSwitch()

    blocked = A.process_message("some risky content", sess, kill, ["groq"])
    assert blocked["ok"] is False
    assert blocked["governance"]["stage"] == A.STAGE_SESSION_QUARANTINED
    assert blocked["recovery"]["action"] == "POST /api/session/reset"

    recovered = A.process_message(
        "what is your current runtime status", sess, kill, ["groq"]
    )
    assert recovered["ok"] is True
    assert recovered["mode"] == "LOCAL_STATUS"


def test_hard_lock_kill_switch_still_blocks_local_lanes():
    """The one hard lock (kill switch) still blocks even LOCAL_STATUS —
    soft quarantine only exempts Sentinel-side session state, not this."""
    kill = A.KillSwitch()
    kill.activate(principal="test")
    out = A.process_message(
        "what is your current runtime status", _Sess(), kill, ["groq"]
    )
    assert out["ok"] is False
    assert out["mode"] == "KILL_SWITCH"


# ── D3 stage enum ────────────────────────────────────────────────────────────
_EXPECTED_STAGES = {
    "route_card_missing", "ingress_blocked", "research_denied",
    "provider_unavailable", "capability_not_issued",
    "outbound_review_missing", "outbound_review_blocked",
    "audit_write_failed", "session_quarantined",
}


def test_stage_enum_constants_present():
    actual = {
        A.STAGE_ROUTE_CARD_MISSING, A.STAGE_INGRESS_BLOCKED,
        A.STAGE_RESEARCH_DENIED, A.STAGE_PROVIDER_UNAVAILABLE,
        A.STAGE_CAPABILITY_NOT_ISSUED, A.STAGE_OUTBOUND_REVIEW_MISSING,
        A.STAGE_OUTBOUND_REVIEW_BLOCKED, A.STAGE_AUDIT_WRITE_FAILED,
        A.STAGE_SESSION_QUARANTINED,
    }
    assert actual == _EXPECTED_STAGES


def test_governed_provider_error_carries_stage():
    exc = A.GovernedProviderError("x", stage=A.STAGE_OUTBOUND_REVIEW_BLOCKED)
    assert exc.stage == A.STAGE_OUTBOUND_REVIEW_BLOCKED

    default_exc = A.GovernedProviderError("x")
    assert default_exc.stage == A.STAGE_CAPABILITY_NOT_ISSUED


def test_governed_execution_block_response_carries_stage(monkeypatch):
    monkeypatch.setattr(A, "_ensure_session_started", lambda _s: True)
    monkeypatch.setattr(
        A,
        "_sentinel_inspect",
        lambda *a, **kw: {
            "ok": True, "verdict": "approved", "provider_authorizable": True,
            "gov_tx_id": "tx1", "verdict_id": "v1", "session_id": "x",
        },
    )

    def _boom_dispatch(*a, **kw):
        raise A.GovernedProviderError(
            "outbound rejected", stage=A.STAGE_OUTBOUND_REVIEW_BLOCKED
        )

    monkeypatch.setattr(A, "_moe_dispatch", _boom_dispatch)

    out = A.process_message(
        "what's a good name for a governance product", _Sess(), A.KillSwitch(), ["groq"]
    )
    assert out["ok"] is False
    assert out["mode"] == "PROVIDER_EXECUTION_BLOCKED"
    assert out["governance"]["stage"] == A.STAGE_OUTBOUND_REVIEW_BLOCKED
    assert "recovery" in out


def test_plan_only_response_states_no_execution_occurred(monkeypatch):
    monkeypatch.setattr(A, "_ensure_session_started", lambda _s: True)
    monkeypatch.setattr(
        A,
        "_sentinel_inspect",
        lambda *a, **kw: {
            "ok": True, "verdict": "approved", "provider_authorizable": True,
            "gov_tx_id": "tx1", "verdict_id": "v1", "session_id": "x",
        },
    )
    monkeypatch.setattr(
        A,
        "_moe_dispatch",
        lambda raw, session, active_backend, system, score, **kw: (
            "Here is your plan.", {"router_mode": "0", "selected_provider": "groq"},
            {"capability_id": "cap1"},
        ),
    )

    out = A.process_message(
        "plan and outline a personal assistant agent for me to review",
        _Sess(), A.KillSwitch(), ["groq"],
    )
    assert out["ok"] is True
    assert out["intent_class"] == "PLAN_ONLY"
    assert "no tools or connectors were activated" in out["text"]
    assert out["governance"]["plan_only"] is True
    assert out["governance"]["tools_activated"] is False
    assert out["governance"]["department_dispatched"] is False
