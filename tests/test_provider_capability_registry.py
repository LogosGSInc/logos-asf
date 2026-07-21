# -*- coding: utf-8 -*-
"""MR-04: provider capability registry tests. No provider calls, no secret values."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
from model_router import provider_capabilities as C  # noqa: E402


def test_capability_matrix_has_core_providers():
    for p in ["groq", "anthropic", "openai", "xai", "local", "current_backend"]:
        cap = C.capability(p)
        assert cap is not None
        assert "strengths" in cap and "context_window" in cap and "key_env" in cap


def test_key_present_reflects_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")
    assert C.key_present("openai") is True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert C.key_present("openai") is False
    # keyless local providers are always "present"
    assert C.key_present("local") is True
    assert C.key_present("ollama") is True


def test_tier_eligibility():
    assert C.tier_permits("free_trial", "groq") is True
    assert C.tier_permits("free_trial", "openai") is False
    assert C.tier_permits("paid", "openai") is True
    assert C.tier_permits("paid", "xai") is True
    assert C.tier_permits("sensitive_governed", "openai") is False
    assert C.tier_permits("sensitive_governed", "local") is True


def test_eligible_providers_free_tier_is_groq_only(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    elig = C.eligible_providers("free_trial")
    # free tier permits only local/free providers; paid providers excluded
    assert "groq" in elig
    assert "openai" not in elig and "anthropic" not in elig and "xai" not in elig


def test_eligible_providers_paid_includes_the_four(monkeypatch):
    for env in ["GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"]:
        monkeypatch.setenv(env, "k" * 12)
    elig = set(C.eligible_providers("paid"))
    assert {"groq", "anthropic", "openai", "xai"} <= elig


def test_health_states():
    assert C.health("groq") == "available"
    with pytest.raises(ValueError):
        C.set_health("groq", "on_fire")
    try:
        C.set_health("groq", "degraded")
        assert C.health("groq") == "degraded"
    finally:
        C.set_health("groq", "available")


def test_registry_snapshot_exposes_presence_not_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    snap = C.registry_snapshot("paid")
    assert snap["openai"]["key_present"] is True
    # the snapshot must not contain the secret value anywhere
    assert "sk-super-secret-value" not in str(snap)
