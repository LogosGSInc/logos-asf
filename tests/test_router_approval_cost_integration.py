# -*- coding: utf-8 -*-
"""MR-04: ordering — approval gate → cost gate → model router → dispatcher.
The router must NOT run until approval is cleared and cost is approved."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
from model_router import dispatcher as D  # noqa: E402


def _stub_table():
    return {"groq": lambda m, s: "STUB-GROQ", "openai": lambda m, s: "STUB-OPENAI",
            "current_backend": lambda m, s: "STUB-CB"}


class _Card:
    def __init__(self, provider="groq", request_type="normal_chat"):
        self.selected_provider = provider
        self.request_type = request_type


def test_router_not_run_before_approval_gate(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    calls = {"router": 0}

    def spy_route(*a, **k):
        calls["router"] += 1
        return _Card()

    r = D.governed_route_and_dispatch(
        "do something risky", approval_state="approval_required",
        cost_state={"approved": True}, subscriber_tier="paid",
        route_fn=spy_route, dispatch_table=_stub_table())
    assert r["dispatch_status"] == "approval_required"
    assert r["routed"] is False
    assert calls["router"] == 0            # router never consulted


def test_router_not_run_before_cost_gate(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    calls = {"router": 0}

    def spy_route(*a, **k):
        calls["router"] += 1
        return _Card()

    r = D.governed_route_and_dispatch(
        "expensive paid task", approval_state="cleared",
        cost_state={"approved": False}, subscriber_tier="paid",
        route_fn=spy_route, dispatch_table=_stub_table())
    assert r["dispatch_status"] == "blocked"
    assert r["reason"] == "cost_gate_blocked"
    assert r["routed"] is False
    assert calls["router"] == 0            # cost gate precedes router


def test_router_runs_and_dispatches_when_gates_pass(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    calls = {"router": 0}

    def spy_route(*a, **k):
        calls["router"] += 1
        return _Card(provider="groq", request_type="normal_chat")

    r = D.governed_route_and_dispatch(
        "simple fast question", approval_state="cleared",
        cost_state={"approved": True}, subscriber_tier="paid",
        route_fn=spy_route, dispatch_table=_stub_table())
    assert calls["router"] == 1            # router consulted only after gates pass
    assert r["routed"] is True
    assert r["dispatch_status"] == "executed"
    assert r["text"] == "STUB-GROQ"
    assert r["route_request_type"] == "normal_chat"


def test_router_selection_honored_by_dispatcher(monkeypatch):
    # router picks openai; dispatcher executes it when tier/key/cost allow
    for env in ["GROQ_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.setenv(env, "k" * 12)
    r = D.governed_route_and_dispatch(
        "code planning task", approval_state="cleared",
        cost_state={"approved": True}, subscriber_tier="paid",
        route_fn=lambda *a, **k: _Card(provider="openai", request_type="technical_task"),
        dispatch_table=_stub_table())
    assert r["provider_selected"] == "openai"
    assert r["dispatch_status"] == "executed"
