from typing import Callable

_SAFE_PROVIDER_FIELDS = frozenset({
    "envelope_id",
    "route_card_id",
    "selected_provider",
    "request_type",
    "data_sensitivity",
    "output_contract",
    "dry_run",
    "redaction_applied",
    "blocked_reason",
})


def safe_provider_fields(envelope: dict) -> dict:
    """Return only audit-safe fields. Never logs messages_summary or system_policy_summary."""
    return {k: v for k, v in envelope.items() if k in _SAFE_PROVIDER_FIELDS}


def log_provider_dry_run_card(envelope: dict, log_fn: Callable) -> None:
    """Emit PROVIDER_DRY_RUN_CARD via Abigail's log_event. Caller supplies log_fn."""
    log_fn("PROVIDER_DRY_RUN_CARD", safe_provider_fields(envelope))
