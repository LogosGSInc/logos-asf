from typing import Callable

_SAFE_FIELDS = frozenset({
    "card_id", "request_type", "risk_level", "data_sensitivity",
    "freshness_required", "tool_required", "latency_need", "cost_ceiling",
    "output_contract", "selected_provider", "fallback_provider",
    "review_required", "reviewer_provider", "swarm_recommended",
    "swarm_parent", "swarm_children", "memory_policy",
    "reason_for_route", "blocked_reason",
})


def safe_route_fields(card: dict) -> dict:
    """Return only audit-safe fields. Never includes raw prompt text."""
    return {k: v for k, v in card.items() if k in _SAFE_FIELDS}


def log_model_route_card(card: dict, log_fn: Callable) -> None:
    """Emit MODEL_ROUTE_CARD via Abigail's log_event. Caller supplies log_fn."""
    log_fn("MODEL_ROUTE_CARD", safe_route_fields(card))
