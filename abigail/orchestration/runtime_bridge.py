# -*- coding: utf-8 -*-
"""
runtime_bridge.py — LOGOS Governance Systems Inc. — Abigail CP-00 MM-02 Shadow Runtime Bridge

Builds an audit-safe shadow orchestration context before Groq inference.
Does not alter inference dispatch. Does not store raw message text.
Does not call external services. Fails soft on any exception.

request_metadata is treated as untrusted input: modality and risk_level are
validated against VALID_MODALITIES and VALID_RISK_LEVELS before use.

Shadow mode: RoutingManifest + SingleGovernedState are created for every normal
chat turn. Workers are not executed. Groq dispatch is unchanged.
"""
import dataclasses
import re
from typing import Optional

from .schemas import SingleGovernedState, VALID_MODALITIES, VALID_RISK_LEVELS
from .audit import new_state_id
from .routing_manifest import build_routing_manifest

BRIDGE_VERSION = "1.0.0"

# CMD_STYLE_INJECTION quick-check patterns (mirrors SENT-CMD-001–006).
# Local to avoid circular imports with abigail_hardened_enhanced.py.
_CMD_SIGNAL_RE = re.compile(
    r'(?i)('
    r'dump.{0,10}(config|env|key|secret|token|credential)'
    r'|/api/(admin|internal|secret|debug|config|raw|v\d)'
    r'|(show|reveal|print|echo|expose|list).{0,20}(key|token|secret|route|config)'
    r'|(role|grant|escalate).{0,15}(admin|root|operator|superuser)'
    r'|(tool|function|call|invoke|execute|run).{0,20}(shell|bash|system|exec|eval)'
    r'|(bypass|skip|ignore).{0,20}(auth|governance|gate|haap|sentinel)'
    r')'
)

# Patterns to redact from safe_task_summary before storage
_SECRET_RE = re.compile(
    r'(?i)(sk-[A-Za-z0-9]{8,}|gsk_[A-Za-z0-9]{8,}'
    r'|Bearer\s+[A-Za-z0-9._-]{8,}|api[_-]key\s*[:=]\s*\S+)'
)

_SAFE_SUMMARY_MAX = 120
_DEFAULT_MODALITY = "text"
_DEFAULT_RISK_LEVEL = "low"
_DEFAULT_SOURCE_TRUST = "user_supplied"


@dataclasses.dataclass(frozen=True)
class ShadowOrchestrationContext:
    """Audit-safe shadow orchestration context. Holds no raw message content."""
    routing_manifest: object          # RoutingManifest
    governed_state: object            # SingleGovernedState
    response_metadata: dict           # audit-safe subset for response JSON attachment
    orchestration_mode: str           # always "shadow" in MM-02


def _safe_summary(message: str) -> str:
    """Deterministic truncation + secret-pattern redaction. No model inference."""
    s = _SECRET_RE.sub('[REDACTED]', message)
    if len(s) > _SAFE_SUMMARY_MAX:
        s = s[:_SAFE_SUMMARY_MAX] + '...'
    return s


def _validate_modality(raw) -> str:
    if isinstance(raw, str) and raw in VALID_MODALITIES:
        return raw
    return _DEFAULT_MODALITY


def _validate_risk_level(raw) -> str:
    if isinstance(raw, str) and raw in VALID_RISK_LEVELS:
        return raw
    return _DEFAULT_RISK_LEVEL


def build_shadow_orchestration_context(
    message: str,
    mode: str,
    session,
    active_backend,
    request_metadata: Optional[dict] = None,
) -> Optional[ShadowOrchestrationContext]:
    """
    Build an audit-safe shadow orchestration context before Groq inference.

    Returns None on any failure — callers must handle None (fail-soft).
    Does not store raw message text. Does not call Groq or external services.
    Does not execute worker agents.

    For exact allowlisted operator commands, call the command bus first and
    skip this function if it returns a handled response.
    """
    try:
        meta = dict(request_metadata or {})

        # Validate untrusted request_metadata fields against allowlists
        modality = _validate_modality(meta.get("modality"))
        risk_from_meta = _validate_risk_level(meta.get("risk_level"))

        # CMD_STYLE_INJECTION signal detection (local pattern, no HAAP dependency)
        cmd_signal = bool(_CMD_SIGNAL_RE.search(message))

        # Risk escalation: CMD_STYLE_INJECTION detected → escalate to high
        risk_level = "high" if cmd_signal else risk_from_meta

        manifest = build_routing_manifest(
            task_intent=f"chat_inference:{mode or 'default'}",
            request_type="chat_inference",
            modality=modality,
            source_trust_class=_DEFAULT_SOURCE_TRUST,
            risk_level=risk_level,
            command_style_signal=cmd_signal,
            input_payload=message.strip().encode('utf-8'),
        )

        # Authority and decision depend on whether human approval is needed
        if manifest.human_approval_required:
            authority_status = "pending_human_approval"
            supervisor_decision = "pending"
        else:
            authority_status = "authorized"
            supervisor_decision = "approved"

        state = SingleGovernedState(
            state_id=new_state_id(),
            manifest_id=manifest.manifest_id,
            current_stage="routing",
            safe_task_summary=_safe_summary(message),
            risk_level=manifest.risk_level,
            modality=manifest.modality,
            source_trust_class=manifest.source_trust_class,
            authority_status=authority_status,
            active_constraints=["no_worker_execution", "shadow_mode"],
            approved_capabilities=["llm_inference"],
            blocked_capabilities=[],
            budget_remaining=manifest.budget,
            worker_outputs_refs=[],
            supervisor_decision=supervisor_decision,
            audit_refs=[manifest.manifest_id],
        )

        response_metadata = {
            "manifest_id": manifest.manifest_id,
            "state_id": state.state_id,
            "modality": manifest.modality,
            "risk_level": manifest.risk_level,
            "source_trust_class": manifest.source_trust_class,
            "human_approval_required": manifest.human_approval_required,
            "command_style_signal": manifest.command_style_signal,
            "max_steps": manifest.budget.max_steps,
            "max_tokens_estimate": manifest.budget.max_tokens_estimate,
            "orchestration_mode": "shadow",
        }

        return ShadowOrchestrationContext(
            routing_manifest=manifest,
            governed_state=state,
            response_metadata=response_metadata,
            orchestration_mode="shadow",
        )
    except Exception:
        return None


def approval_gate_blocks(response_metadata) -> bool:
    """MM-03: enforced approval gate predicate. Returns True when a shadow context's
    audit-safe metadata indicates human approval is required before any action, worker,
    tool, outbound call, or provider spend may proceed. Reusable by every future dispatch
    path — the single source of truth for 'must Abigail stop and escalate?'."""
    return bool(response_metadata and response_metadata.get("human_approval_required"))
