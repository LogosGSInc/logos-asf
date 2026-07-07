# -*- coding: utf-8 -*-
"""
test_mr04_chat_dispatch_hardening.py — MR-04 chat dispatch hardening & verification.

Proves the /api/chat governed dispatch (MR-04 governed_route_and_dispatch, wired
via MR-05 _router_dispatch inside process_message):
  - inherits every gate — Sentinel, HAAP, MM-03 approval, SEC-02 cost — which all
    block BEFORE the MR-04 dispatcher is ever called;
  - derives the approval state from real approval_meta (RTR-05), not a literal;
  - stamps a single gov_tx_id across gate audit events and router metadata;
  - is reachable only through the approved governance path (structural no-bypass);
  - still works on the happy path with a stubbed provider — no live provider calls.
"""
import ast
import sys
from pathlib import Path

import pytest

RUNTIME = Path(__file__).parent.parent / "abigail" / "abigail_hardened_enhanced.py"
sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────
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


def _mode(monkeypatch, m):
    monkeypatch.setenv("ABIGAIL_MOE_ROUTER_MODE", str(m))


def _stub_env(monkeypatch, verdict="unknown"):
    """No network; detectable active backend; spy on the MR-04 dispatcher."""
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": True, "verdict": verdict, "approved": True})
    monkeypatch.setattr(A, "try_grounded_answer", lambda *a, **k: None)
    calls = {"backend": 0, "router": 0}

    def _fake_backend(messages=None, system=None, **k):
        calls["backend"] += 1
        return "STUB-ACTIVE"

    monkeypatch.setitem(A.BACKEND_DISPATCH, "groq", _fake_backend)
    return calls


def _spy_router(monkeypatch, calls, result=None):
    def _spy(*a, **k):
        calls["router"] += 1
        return result or {"provider_selected": "groq", "dispatch_status": "executed",
                          "text": "STUB-ROUTED", "reason": "all_gates_passed",
                          "route_request_type": "normal_chat"}
    monkeypatch.setattr(A, "_governed_route_and_dispatch", _spy)


# ── gate inheritance: each gate blocks before the MR-04 dispatcher ────────────
def test_sentinel_block_before_router_dispatch(monkeypatch):
    calls = _stub_env(monkeypatch, verdict="quarantined")
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)
    out = A.process_message("malicious", _Sess(), A.KillSwitch(), ["groq"])
    assert out["mode"] == "SENTINEL_BLOCK"
    assert calls["router"] == 0        # MR-04 dispatcher never reached
    assert calls["backend"] == 0


def test_haap_block_before_router_dispatch(monkeypatch):
    calls = _stub_env(monkeypatch)
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)

    def _raise(*a, **k):
        raise A.HAAPViolation("HAAP block for test")

    monkeypatch.setattr(A, "haap_gate", _raise)
    out = A.process_message("injection", _Sess(), A.KillSwitch(), ["groq"])
    assert out["mode"] == "BLOCKED"
    assert calls["router"] == 0
    assert calls["backend"] == 0


def test_mm03_approval_required_before_router_dispatch(monkeypatch):
    calls = _stub_env(monkeypatch)
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)
    meta = {"human_approval_required": True, "risk_level": "high",
            "manifest_id": "M-1", "command_style_signal": False}
    out = A.process_message("plan my week", _Sess(), A.KillSwitch(), ["groq"],
                            approval_meta=meta)
    assert out["mode"] == "APPROVAL_REQUIRED"
    assert calls["router"] == 0
    assert calls["backend"] == 0


def test_cost_block_prevents_router_dispatch(monkeypatch):
    calls = _stub_env(monkeypatch)
    _mode(monkeypatch, 2)
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "1")
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", "0")   # zero budget → cost re-check fails

    # cost-aware dispatcher spy: mirrors the real MR-04 dispatcher, which blocks on
    # an unapproved cost state BEFORE routing/executing any provider.
    def _spy(*a, **k):
        calls["router"] += 1
        if not (k.get("cost_state") or {}).get("approved"):
            return {"provider_selected": None, "dispatch_status": "blocked",
                    "reason": "cost_gate_blocked", "routed": False}
        return {"provider_selected": "groq", "dispatch_status": "executed",
                "text": "STUB-ROUTED", "reason": "ok"}
    monkeypatch.setattr(A, "_governed_route_and_dispatch", _spy)

    # cost_state None → _router_dispatch re-checks the deterministic cost gate
    out = A.process_message("expensive", _Sess(), A.KillSwitch(), ["groq"])
    assert out["router"]["dispatch_status"] == "blocked"
    assert out["router"]["live_dispatch"] is False
    assert calls["backend"] == 0        # NO provider dispatch — not even the fallback


# ── RTR-05: approval state is derived, not hardcoded ─────────────────────────
def test_approval_state_is_derived_not_hardcoded(monkeypatch):
    """If approval_meta would block, _router_dispatch must NOT dispatch (and must
    not call any provider), proving the state is derived from approval_meta."""
    calls = _stub_env(monkeypatch)
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)
    meta = {"human_approval_required": True}
    text, rmeta = A._router_dispatch(
        "x", _Sess(), ["groq"], "sys", {"selected_provider": "groq"}, 5,
        cost_state={"approved": True}, approval_meta=meta, gov_tx_id="TX123")
    assert rmeta["dispatch_status"] == "approval_required"
    assert rmeta["live_dispatch"] is False
    assert calls["router"] == 0        # dispatcher NOT called
    assert calls["backend"] == 0       # no provider call at all


def test_cleared_approval_allows_dispatch(monkeypatch):
    calls = _stub_env(monkeypatch)
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)
    text, rmeta = A._router_dispatch(
        "x", _Sess(), ["groq"], "sys", {"selected_provider": "groq"}, 5,
        cost_state={"approved": True}, approval_meta=None, gov_tx_id="TX123")
    assert rmeta["dispatch_status"] == "executed"
    assert calls["router"] == 1


# ── gov_tx_id propagation ────────────────────────────────────────────────────
def test_gov_tx_id_in_router_metadata_and_events(monkeypatch):
    calls = _stub_env(monkeypatch)
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)
    events = []
    monkeypatch.setattr(A, "log_event", lambda ev, p=None: events.append((ev, p or {})))
    out = A.process_message("compose a poem", _Sess(), A.KillSwitch(), ["groq"])
    tx = out["router"]["gov_tx_id"]
    assert tx and isinstance(tx, str)
    # the same gov_tx_id appears on the dispatch + completion audit events
    live = [p for ev, p in events if ev == "ROUTER_LIVE_DISPATCH"]
    done = [p for ev, p in events if ev == "TURN_COMPLETE"]
    assert live and live[0]["gov_tx_id"] == tx
    assert done and done[0]["gov_tx_id"] == tx


def test_gov_tx_id_on_sentinel_block_event(monkeypatch):
    calls = _stub_env(monkeypatch, verdict="hard_locked")
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)
    events = []
    monkeypatch.setattr(A, "log_event", lambda ev, p=None: events.append((ev, p or {})))
    A.process_message("bad", _Sess(), A.KillSwitch(), ["groq"])
    blk = [p for ev, p in events if ev == "SENTINEL_BLOCK"]
    assert blk and "gov_tx_id" in blk[0]


# ── happy path (stubbed provider, no live call) ──────────────────────────────
def test_happy_path_executes_via_stubbed_dispatcher(monkeypatch):
    calls = _stub_env(monkeypatch)
    _spy_router(monkeypatch, calls)
    _mode(monkeypatch, 2)
    out = A.process_message("compose a poem", _Sess(), A.KillSwitch(), ["groq"])
    assert out["text"] == "STUB-ROUTED"
    assert out["router"]["dispatch_status"] == "executed"
    assert calls["router"] == 1


# ── structural no-bypass: protect the trust boundary ─────────────────────────
def _callers_of(tree, target):
    """Return the set of enclosing function names that contain a direct call to
    `target` (by bare name)."""
    callers = set()

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == target and self.stack:
                callers.add(self.stack[-1])
            self.generic_visit(node)

    V().visit(tree)
    return callers


def test_no_bypass_governed_dispatch_only_via_router_dispatch():
    """_governed_route_and_dispatch must be invoked ONLY from _router_dispatch.
    If a future caller is added, this fails until it is explicitly recognized as
    passing through the designated governance wrapper."""
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    APPROVED = {"_router_dispatch"}
    callers = _callers_of(tree, "_governed_route_and_dispatch")
    assert callers <= APPROVED, (
        f"Unrecognized caller(s) of _governed_route_and_dispatch: {callers - APPROVED}. "
        "MR-04 dispatch must only be reached through the governed _router_dispatch path."
    )


def test_no_bypass_router_dispatch_only_via_process_message():
    """_router_dispatch must be invoked ONLY from process_message."""
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    APPROVED = {"process_message"}
    callers = _callers_of(tree, "_router_dispatch")
    assert callers <= APPROVED, (
        f"Unrecognized caller(s) of _router_dispatch: {callers - APPROVED}. "
        "Chat dispatch must not bypass process_message."
    )
