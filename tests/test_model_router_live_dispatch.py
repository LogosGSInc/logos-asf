# -*- coding: utf-8 -*-
"""MR-04: dispatcher execution-gate + governed fallback tests. No real provider calls."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
from model_router import dispatcher as D, provider_capabilities as C  # noqa: E402


def _stub_table():
    return {
        "groq": lambda m, s: "STUB-GROQ",
        "openai": lambda m, s: "STUB-OPENAI",
        "current_backend": lambda m, s: "STUB-CB",
    }


def _key_all(monkeypatch):
    for env in ["GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"]:
        monkeypatch.setenv(env, "k" * 12)


def test_fallback_when_provider_not_live_wired(monkeypatch):
    _key_all(monkeypatch)
    r = D.dispatch("gemini", [], "", approval_state="cleared",
                   cost_state={"approved": True}, subscriber_tier="paid",
                   dispatch_table=_stub_table())
    assert r["dispatch_status"] == "unavailable"
    assert r["reason"] == "provider_not_live_wired"
    assert r["fallback_provider"] in ("groq", "current_backend")


def test_fallback_when_key_missing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = D.dispatch("openai", [], "", approval_state="cleared",
                   cost_state={"approved": True}, subscriber_tier="paid",
                   dispatch_table=_stub_table())
    assert r["dispatch_status"] == "unavailable"
    assert r["reason"] == "key_missing"


def test_fallback_when_tier_disallows(monkeypatch):
    _key_all(monkeypatch)
    r = D.dispatch("openai", [], "", approval_state="cleared",
                   cost_state={"approved": True}, subscriber_tier="free_trial",
                   dispatch_table=_stub_table())
    assert r["dispatch_status"] == "unavailable"
    assert r["reason"] == "tier_not_permitted"


def test_approval_required_blocks_dispatch(monkeypatch):
    _key_all(monkeypatch)
    r = D.dispatch("groq", [], "", approval_state="approval_required",
                   cost_state={"approved": True}, subscriber_tier="paid",
                   dispatch_table=_stub_table())
    assert r["dispatch_status"] == "approval_required"
    assert "text" not in r


def test_fallback_when_cost_ceiling_exceeded(monkeypatch):
    _key_all(monkeypatch)
    r = D.dispatch("groq", [], "", approval_state="cleared",
                   cost_state={"approved": False}, subscriber_tier="paid",
                   dispatch_table=_stub_table())
    assert r["dispatch_status"] == "unavailable"
    assert r["reason"] == "cost_ceiling_exceeded"


def test_fallback_when_provider_unhealthy(monkeypatch):
    _key_all(monkeypatch)
    try:
        C.set_health("openai", "circuit_open")
        r = D.dispatch("openai", [], "", approval_state="cleared",
                       cost_state={"approved": True}, subscriber_tier="paid",
                       dispatch_table=_stub_table())
        assert r["dispatch_status"] == "unavailable"
        assert r["reason"] == "provider_circuit_open"
    finally:
        C.set_health("openai", "available")


def test_execute_when_all_gates_pass(monkeypatch):
    _key_all(monkeypatch)
    r = D.dispatch("openai", [], "", approval_state="cleared",
                   cost_state={"approved": True}, subscriber_tier="paid",
                   dispatch_table=_stub_table())
    assert r["dispatch_status"] == "executed"
    assert r["text"] == "STUB-OPENAI"


def test_adapter_error_returns_governed_fallback(monkeypatch):
    _key_all(monkeypatch)

    def boom(m, s):
        raise RuntimeError("provider exploded")

    table = {"openai": boom, "groq": lambda m, s: "STUB-GROQ", "current_backend": lambda m, s: "cb"}
    r = D.dispatch("openai", [], "", approval_state="cleared",
                   cost_state={"approved": True}, subscriber_tier="paid",
                   dispatch_table=table)
    assert r["dispatch_status"] == "unavailable"
    assert r["reason"].startswith("adapter_error:")


def test_governed_fallback_shape(monkeypatch):
    _key_all(monkeypatch)
    r = D.dispatch("gemini", [], "", approval_state="cleared",
                   cost_state={"approved": True}, subscriber_tier="paid",
                   dispatch_table=_stub_table())
    for field in ("provider_selected", "dispatch_status", "reason",
                  "fallback_provider", "audit_record"):
        assert field in r
    assert r["audit_record"]["provider_selected"] == "gemini"
