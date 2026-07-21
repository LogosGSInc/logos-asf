from __future__ import annotations
from typing import Optional
from .base import BaseProviderAdapter
from ..envelopes import ProviderRequestEnvelope, ProviderResponseEnvelope

_SENSITIVE_LEVELS = frozenset({"user_private", "confidential", "regulated", "sacred_doctrinal"})


class DryRunProviderAdapter(BaseProviderAdapter):
    def __init__(self, provider_name: str = "dry_run"):
        self.provider_name = provider_name

    def supports(self, route_card: dict) -> bool:
        return True  # accepts any route in dry-run mode

    def build_request(
        self,
        route_card: dict,
        session=None,
        tacit_card: Optional[dict] = None,
    ) -> ProviderRequestEnvelope:
        sensitivity = route_card.get("data_sensitivity", "public")
        blocked     = route_card.get("blocked_reason")

        # Count only — never include message content
        msg_count = len(getattr(session, "messages", [])) if session else 0
        messages_summary = f"[{msg_count} prior turn(s) — content not included]"

        # Policy metadata only — never include full system prompt text
        system_summary = (
            f"HAAP-governed; sensitivity={sensitivity}; "
            f"review_required={route_card.get('review_required', False)}; dry_run=True"
        )

        redaction = sensitivity in _SENSITIVE_LEVELS

        return ProviderRequestEnvelope(
            route_card_id=route_card.get("card_id", ""),
            selected_provider=route_card.get("selected_provider", "current_backend"),
            model_hint=None,
            request_type=route_card.get("request_type", "normal_chat"),
            data_sensitivity=sensitivity,
            output_contract=route_card.get("output_contract", "freeform"),
            tool_required=route_card.get("tool_required", "none"),
            review_required=bool(route_card.get("review_required", False)),
            messages_summary=messages_summary,
            system_policy_summary=system_summary,
            redaction_applied=redaction,
            dry_run=True,
            blocked_reason=blocked,
        )

    def execute(self, request_envelope: ProviderRequestEnvelope) -> ProviderResponseEnvelope:
        if request_envelope.blocked_reason:
            return ProviderResponseEnvelope(
                envelope_id=request_envelope.envelope_id,
                provider=request_envelope.selected_provider,
                dry_run=True,
                output_text="",
                error=f"blocked:{request_envelope.blocked_reason}",
                safety_flags=["route_blocked"],
            )
        return ProviderResponseEnvelope(
            envelope_id=request_envelope.envelope_id,
            provider=request_envelope.selected_provider,
            dry_run=True,
            output_text=(
                f"[DRY_RUN] No provider call made. "
                f"Would route to: {request_envelope.selected_provider} "
                f"for {request_envelope.request_type} "
                f"({request_envelope.output_contract})"
            ),
        )

    def normalize_response(self, raw_response) -> ProviderResponseEnvelope:
        if isinstance(raw_response, ProviderResponseEnvelope):
            return raw_response
        return ProviderResponseEnvelope(
            provider=self.provider_name,
            dry_run=True,
            output_text="[DRY_RUN]",
        )
