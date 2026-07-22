# -*- coding: utf-8 -*-
"""
dispatcher.py — MR-04 governed live provider dispatch.

Three gates, in order:
  - Approval gate (upstream): IF the request may proceed.
  - Model router (upstream):  WHICH provider/model is best within the approved boundary.
  - Dispatcher (here):        WHETHER the chosen provider can actually execute —
                              live-wired? keyed? tier-permitted? cost-approved? approval-cleared?

If any dispatcher check fails, a governed fallback is returned (never a crash):
  {provider_selected, dispatch_status, reason, fallback_provider, audit_record}.

No secret values are ever emitted. Tests inject a dispatch_table so no real calls occur.
"""
from orchestration.audit import now_utc

from . import provider_capabilities as caps
from .live_adapters import get_live_dispatch


_SAFE_FALLBACK_ORDER = ["groq", "current_backend", "local"]


def _card_value(card, key, default=None):
    """Read router cards consistently whether returned as dicts or models."""
    if isinstance(card, dict):
        return card.get(key, default)
    return getattr(card, key, default)


def _audit(provider, status, reason, fallback, subscriber_tier):
    return {
        "provider_selected": provider,
        "dispatch_status": status,
        "reason": reason,
        "fallback_provider": fallback,
        "subscriber_tier": subscriber_tier,
        "at": now_utc(),
    }


def _pick_fallback(subscriber_tier, dispatch_table, exclude=None):
    """Deterministically choose a safe, live, keyed, tier-permitted fallback."""
    exclude = exclude or set()
    for p in _SAFE_FALLBACK_ORDER:
        if p in exclude:
            continue
        if p in dispatch_table and caps.tier_permits(subscriber_tier, p) and caps.key_present(p):
            return p
    # last resort: any live, permitted, keyed provider
    for p in sorted(dispatch_table):
        if p in exclude:
            continue
        if caps.tier_permits(subscriber_tier, p) and caps.key_present(p):
            return p
    return None


def _fallback(provider, reason, subscriber_tier, dispatch_table):
    fb = _pick_fallback(subscriber_tier, dispatch_table, exclude={provider})
    rec = _audit(provider, "unavailable", reason, fb, subscriber_tier)
    return {
        "provider_selected": provider,
        "dispatch_status": "unavailable",
        "reason": reason,
        "fallback_provider": fb,
        "audit_record": rec,
    }


def dispatch(provider, messages, system, *, approval_state, cost_state,
             subscriber_tier="paid", dispatch_table=None):
    """Execution gate. approval_state: 'cleared' | 'approval_required'.
    cost_state: {'approved': bool, ...}. Returns a governed result dict."""
    table = dispatch_table if dispatch_table is not None else get_live_dispatch()
    cost_state = cost_state or {"approved": False}

    # 1) live-wired?
    if provider not in table:
        return _fallback(provider, "provider_not_live_wired", subscriber_tier, table)
    # 2) key present?
    if not caps.key_present(provider):
        return _fallback(provider, "key_missing", subscriber_tier, table)
    # 3) subscriber tier permits?
    if not caps.tier_permits(subscriber_tier, provider):
        return _fallback(provider, "tier_not_permitted", subscriber_tier, table)
    # 4) provider health?
    if caps.health(provider) != "available":
        return _fallback(provider, f"provider_{caps.health(provider)}", subscriber_tier, table)
    # 5) approval cleared? (final defense-in-depth check — approval decided upstream)
    if approval_state != "cleared":
        rec = _audit(provider, "approval_required", "approval_not_cleared", None, subscriber_tier)
        return {"provider_selected": provider, "dispatch_status": "approval_required",
                "reason": "approval_not_cleared", "fallback_provider": None, "audit_record": rec}
    # 6) cost approved?
    if not cost_state.get("approved"):
        return _fallback(provider, "cost_ceiling_exceeded", subscriber_tier, table)

    # all gates passed → execute the live adapter
    try:
        text = table[provider](messages, system)
        rec = _audit(provider, "executed", "all_gates_passed", None, subscriber_tier)
        return {"provider_selected": provider, "dispatch_status": "executed",
                "text": text, "fallback_provider": None, "audit_record": rec}
    except Exception as exc:  # adapter failure → governed fallback, never crash
        return _fallback(provider, f"adapter_error:{type(exc).__name__}", subscriber_tier, table)


def governed_route_selection(text, *, drs_score=5, approval_state, cost_state,
                              subscriber_tier="paid", route_fn=None,
                              dispatch_table=None):
    """Select and validate a live provider without executing it.

    This is the required pre-execution boundary for Sentinel capability
    authorization. It performs approval, cost, routing, live-wiring, key,
    tier, and health checks, then returns the selected provider. No model
    adapter is called.
    """
    table = dispatch_table if dispatch_table is not None else get_live_dispatch()
    cost_state = cost_state or {"approved": False}

    if approval_state != "cleared":
        rec = _audit(
            None,
            "approval_required",
            "approval_gate_blocked",
            None,
            subscriber_tier,
        )
        return {
            "provider_selected": None,
            "selection_status": "approval_required",
            "reason": "approval_gate_blocked",
            "fallback_provider": None,
            "audit_record": rec,
            "routed": False,
        }

    if not cost_state.get("approved"):
        rec = _audit(
            None,
            "blocked",
            "cost_gate_blocked",
            None,
            subscriber_tier,
        )
        return {
            "provider_selected": None,
            "selection_status": "blocked",
            "reason": "cost_gate_blocked",
            "fallback_provider": None,
            "audit_record": rec,
            "routed": False,
        }

    if route_fn is None:
        from .router import route_request as route_fn

    card = route_fn(text, drs_score, [], None)
    provider = _card_value(card, "selected_provider", "current_backend")

    if provider not in table:
        rec = _audit(
            provider,
            "unavailable",
            "provider_not_live_wired",
            None,
            subscriber_tier,
        )
        return {
            "provider_selected": provider,
            "selection_status": "unavailable",
            "reason": "provider_not_live_wired",
            "fallback_provider": None,
            "audit_record": rec,
            "routed": True,
            "route_request_type": _card_value(card, "request_type"),
        }

    if not caps.key_present(provider):
        rec = _audit(
            provider,
            "unavailable",
            "key_missing",
            None,
            subscriber_tier,
        )
        return {
            "provider_selected": provider,
            "selection_status": "unavailable",
            "reason": "key_missing",
            "fallback_provider": None,
            "audit_record": rec,
            "routed": True,
            "route_request_type": _card_value(card, "request_type"),
        }

    if not caps.tier_permits(subscriber_tier, provider):
        rec = _audit(
            provider,
            "unavailable",
            "tier_not_permitted",
            None,
            subscriber_tier,
        )
        return {
            "provider_selected": provider,
            "selection_status": "unavailable",
            "reason": "tier_not_permitted",
            "fallback_provider": None,
            "audit_record": rec,
            "routed": True,
            "route_request_type": _card_value(card, "request_type"),
        }

    provider_health = caps.health(provider)
    if provider_health != "available":
        reason = f"provider_{provider_health}"
        rec = _audit(
            provider,
            "unavailable",
            reason,
            None,
            subscriber_tier,
        )
        return {
            "provider_selected": provider,
            "selection_status": "unavailable",
            "reason": reason,
            "fallback_provider": None,
            "audit_record": rec,
            "routed": True,
            "route_request_type": _card_value(card, "request_type"),
        }

    rec = _audit(
        provider,
        "selected",
        "all_selection_gates_passed",
        None,
        subscriber_tier,
    )
    return {
        "provider_selected": provider,
        "selection_status": "selected",
        "reason": "all_selection_gates_passed",
        "fallback_provider": None,
        "audit_record": rec,
        "routed": True,
        "route_request_type": _card_value(card, "request_type"),
    }


def governed_route_and_dispatch(text, *, drs_score=5, approval_state, cost_state,
                                subscriber_tier="paid", route_fn=None,
                                dispatch_table=None, messages=None, system=""):
    """Enforce ordering: approval gate → cost gate → model router → dispatcher.
    The router is NOT consulted until approval is cleared and cost is approved."""
    # approval gate FIRST — router never runs for un-approved requests
    if approval_state != "cleared":
        rec = _audit(None, "approval_required", "approval_gate_blocked", None, subscriber_tier)
        return {"provider_selected": None, "dispatch_status": "approval_required",
                "reason": "approval_gate_blocked", "fallback_provider": None,
                "audit_record": rec, "routed": False}
    # cost gate BEFORE router — no routing/selection for un-budgeted paid work
    if not (cost_state or {}).get("approved"):
        rec = _audit(None, "blocked", "cost_gate_blocked", None, subscriber_tier)
        return {"provider_selected": None, "dispatch_status": "blocked",
                "reason": "cost_gate_blocked", "fallback_provider": None,
                "audit_record": rec, "routed": False}
    # capability gate — router selects best provider within approved boundary
    if route_fn is None:
        from .router import route_request as route_fn  # lazy
    card = route_fn(text, drs_score, [], None)
    provider = _card_value(card, "selected_provider", "current_backend")
    # execution gate
    result = dispatch(provider, messages or [{"role": "user", "content": text}], system,
                      approval_state="cleared", cost_state=cost_state,
                      subscriber_tier=subscriber_tier, dispatch_table=dispatch_table)
    result["routed"] = True
    result["route_request_type"] = _card_value(card, "request_type")
    return result
