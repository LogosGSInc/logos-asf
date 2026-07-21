# -*- coding: utf-8 -*-
"""
provider_capabilities.py — MR-04 provider capability registry.

Static capability matrix + health + key-presence + subscriber-tier eligibility.
Pure data / env reads only — no provider calls, no network, no secret values printed
(only key *presence* is exposed).
"""
import os

# ── static capability matrix ────────────────────────────────────────────────
# cost_per_1k is a coarse relative estimate for gating, not billing truth.
CAPABILITIES = {
    "groq": {
        "strengths": ["fast_scout", "low_risk_classification", "quick_summary"],
        "modalities": ["text"], "context_window": 128000, "max_output_tokens": 2048,
        "tool_support": False, "structured_output": False,
        "latency_profile": "very_fast", "cost_per_1k": 0.0, "key_env": "GROQ_API_KEY",
    },
    "anthropic": {
        "strengths": ["careful_reasoning", "policy_review", "critic", "high_stakes"],
        "modalities": ["text"], "context_window": 200000, "max_output_tokens": 2048,
        "tool_support": True, "structured_output": True,
        "latency_profile": "normal", "cost_per_1k": 0.009, "key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "strengths": ["structured_reasoning", "tool_control", "code_plan", "json_schema"],
        "modalities": ["text"], "context_window": 128000, "max_output_tokens": 2048,
        "tool_support": True, "structured_output": True,
        "latency_profile": "normal", "cost_per_1k": 0.01, "key_env": "OPENAI_API_KEY",
    },
    "xai": {
        "strengths": ["social_terrain", "realtime_narrative", "x_search"],
        "modalities": ["text"], "context_window": 131072, "max_output_tokens": 2048,
        "tool_support": True, "structured_output": True,
        "latency_profile": "normal", "cost_per_1k": 0.01, "key_env": "XAI_API_KEY",
    },
    "perplexity": {
        "strengths": ["web_grounded", "freshness"],
        "modalities": ["text"], "context_window": 32000, "max_output_tokens": 2048,
        "tool_support": False, "structured_output": False,
        "latency_profile": "normal", "cost_per_1k": 0.005, "key_env": "PERPLEXITY_API_KEY",
    },
    "ollama": {
        "strengths": ["local", "privacy"],
        "modalities": ["text"], "context_window": 8192, "max_output_tokens": 2048,
        "tool_support": False, "structured_output": False,
        "latency_profile": "variable", "cost_per_1k": 0.0, "key_env": None,
    },
    "local": {
        "strengths": ["privacy_firewall", "sensitive_summary"],
        "modalities": ["text"], "context_window": 8192, "max_output_tokens": 2048,
        "tool_support": False, "structured_output": False,
        "latency_profile": "variable", "cost_per_1k": 0.0, "key_env": None,
    },
    "gemini": {
        "strengths": ["long_context", "multimodal"],
        "modalities": ["text", "image", "pdf"], "context_window": 1000000,
        "max_output_tokens": 2048, "tool_support": True, "structured_output": True,
        "latency_profile": "normal", "cost_per_1k": 0.007, "key_env": "GEMINI_API_KEY",
    },
    "current_backend": {
        "strengths": ["existing_runtime_fallback"],
        "modalities": ["text"], "context_window": 128000, "max_output_tokens": 2048,
        "tool_support": False, "structured_output": False,
        "latency_profile": "normal", "cost_per_1k": 0.0, "key_env": None,
    },
}

# ── subscriber tiers → permitted providers ──────────────────────────────────
TIER_PROVIDERS = {
    "free_trial": {"groq", "current_backend", "local", "ollama"},
    "paid": {"groq", "anthropic", "openai", "xai", "perplexity", "current_backend", "local", "ollama"},
    "pro_business": {"groq", "anthropic", "openai", "xai", "perplexity", "gemini",
                     "current_backend", "local", "ollama"},
    "sensitive_governed": {"local", "current_backend"},
}

# ── coarse cost ceilings (relative) per tier ────────────────────────────────
TIER_COST_CEILING = {
    "free_trial": 0.0,          # free/local providers only
    "paid": 0.02,
    "pro_business": 0.05,
    "sensitive_governed": 0.0,
}

_VALID_HEALTH = frozenset({"available", "degraded", "unavailable", "circuit_open"})
# Static default health; a live health-probe layer is future work (see doc).
_HEALTH = {p: "available" for p in CAPABILITIES}


def capability(provider):
    return CAPABILITIES.get(provider)


def health(provider):
    return _HEALTH.get(provider, "unavailable")


def set_health(provider, status):
    if status not in _VALID_HEALTH:
        raise ValueError(f"invalid health status: {status!r}")
    _HEALTH[provider] = status


def key_present(provider):
    """True if the provider needs no key (local) or its key env var is set & nonempty."""
    cap = CAPABILITIES.get(provider)
    if cap is None:
        return False
    env = cap.get("key_env")
    if env is None:
        return True
    return bool(os.environ.get(env, "").strip())


def tier_permits(subscriber_tier, provider):
    return provider in TIER_PROVIDERS.get(subscriber_tier, set())


def cost_ceiling(subscriber_tier):
    return TIER_COST_CEILING.get(subscriber_tier, 0.0)


def eligible_providers(subscriber_tier):
    """Providers permitted by tier AND keyed AND healthy."""
    return sorted(
        p for p in TIER_PROVIDERS.get(subscriber_tier, set())
        if key_present(p) and health(p) == "available"
    )


def registry_snapshot(subscriber_tier="paid"):
    """Audit-safe snapshot — key *presence* only, never values."""
    return {
        p: {
            "strengths": c["strengths"],
            "health": health(p),
            "key_present": key_present(p),
            "tier_permitted": tier_permits(subscriber_tier, p),
            "cost_per_1k": c["cost_per_1k"],
        }
        for p, c in CAPABILITIES.items()
    }
