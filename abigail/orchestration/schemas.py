# -*- coding: utf-8 -*-
"""
schemas.py — LOGOS Governance Systems Inc. — Abigail CP-00 Orchestration Schemas

Core data structures for governed orchestration:
  - Budget
  - RoutingManifest     — audit-safe deterministic routing record
  - SignedHandoffPacket — scoped worker handoff with hash-chain integrity
  - CapabilityProfile   — worker capability declaration
  - SingleGovernedState — shared structured orchestration state (no transcript replay)

All classes validate on construction and fail closed on invalid inputs.
No provider calls. No network calls. No secrets stored.

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.
"""
from dataclasses import dataclass, field
from typing import Optional

from .audit import new_gov_tx_id


# ── Governed enumerations ─────────────────────────────────────────────────────

VALID_MODALITIES = frozenset({
    "text", "document", "image", "audio", "video", "mixed_bundle", "unknown",
})

VALID_TRUST_CLASSES = frozenset({
    "operator_direct", "user_supplied", "uploaded_file",
    "rag_retrieved", "web_retrieved", "tool_returned",
    "agent_returned", "untrusted_external",
})

VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
HIGH_RISK_LEVELS  = frozenset({"high", "critical"})
_RISK_ORDER       = ["low", "medium", "high", "critical"]

VALID_PIPELINE_STAGES = frozenset({
    "input_classification", "doctrine_gate", "routing",
    "worker_execution", "merge_judgment",
})

AUTHORIZED_SUPERVISORS = frozenset({
    "abigail", "abigail_cp00", "abigail_supervisor",
})

# Request types that always require human approval — fail closed
HUMAN_APPROVAL_REQUEST_TYPES = frozenset({
    "file_write", "network_call", "publish", "paid_spend",
    "privileged_operation", "external_action", "deploy",
    "send_email", "send_message", "write_db",
})

# Tools that always require human approval — fail closed
HUMAN_APPROVAL_TOOLS = frozenset({
    "file_write", "network", "http_request", "shell", "bash",
    "deploy", "publish", "send_email", "send_message", "write_db",
})


# ── Budget ────────────────────────────────────────────────────────────────────

@dataclass
class Budget:
    """Execution budget for a governed task or worker."""
    max_steps: int
    max_tokens_estimate: int
    max_wall_seconds: Optional[int] = None
    max_cost_usd_estimate: Optional[float] = None

    def __post_init__(self):
        if self.max_steps <= 0:
            raise ValueError(f"Budget.max_steps must be > 0, got {self.max_steps}")
        if self.max_tokens_estimate <= 0:
            raise ValueError(f"Budget.max_tokens_estimate must be > 0, got {self.max_tokens_estimate}")


# ── RoutingManifest ───────────────────────────────────────────────────────────

@dataclass
class RoutingManifest:
    """
    Audit-safe deterministic routing record created before any worker handoff.

    Rules (enforced in __post_init__):
    - modality must be in VALID_MODALITIES
    - source_trust_class must be in VALID_TRUST_CLASSES
    - risk_level must be in VALID_RISK_LEVELS
    - human_approval_required must be True for high/critical risk,
      external actions, file writes, network calls, publishing, paid spend
    - input_hash is a SHA-256 of canonical input material — no raw prompt stored
    - termination_condition must be non-empty
    - audit_safe is always True — no raw user prompt in this record
    """
    manifest_id: str
    created_at: str
    supervisor: str
    task_intent: str
    request_type: str
    modality: str
    source_trust_class: str
    data_sensitivity: str
    risk_level: str
    doctrine_sensitivity: str
    command_style_signal: bool
    required_capabilities: list
    allowed_worker_classes: list
    forbidden_worker_classes: list
    required_tools: list
    forbidden_tools: list
    budget: Budget
    fallback_chain: list
    termination_condition: str
    human_approval_required: bool
    input_hash: str
    policy_refs: list
    audit_safe: bool = True
    # Single governance transaction ID. The manifest is the ORIGIN of a governance
    # transaction: if none is supplied, one is minted here and threaded, unchanged,
    # into every downstream handoff packet, governed state, and audit record.
    gov_tx_id: str = ""

    def __post_init__(self):
        if not self.gov_tx_id.strip():
            self.gov_tx_id = new_gov_tx_id()
        if self.modality not in VALID_MODALITIES:
            raise ValueError(
                f"Invalid modality: {self.modality!r}. "
                f"Must be one of: {sorted(VALID_MODALITIES)}"
            )
        if self.source_trust_class not in VALID_TRUST_CLASSES:
            raise ValueError(
                f"Invalid source_trust_class: {self.source_trust_class!r}. "
                f"Must be one of: {sorted(VALID_TRUST_CLASSES)}"
            )
        if self.risk_level not in VALID_RISK_LEVELS:
            raise ValueError(
                f"Invalid risk_level: {self.risk_level!r}. "
                f"Must be one of: {sorted(VALID_RISK_LEVELS)}"
            )
        if not self.termination_condition.strip():
            raise ValueError("termination_condition must be a non-empty string")
        if not self.input_hash.strip():
            raise ValueError("input_hash must be non-empty (supply SHA-256 of canonical input)")
        if not self.manifest_id.strip():
            raise ValueError("manifest_id must be non-empty")
        if not self.supervisor.strip():
            raise ValueError("supervisor must be non-empty")
        # Fail closed: human approval required for high/critical risk
        if self.risk_level in HIGH_RISK_LEVELS and not self.human_approval_required:
            raise ValueError(
                f"human_approval_required must be True when risk_level={self.risk_level!r}"
            )
        # Fail closed: human approval required for sensitive request types
        if self.request_type in HUMAN_APPROVAL_REQUEST_TYPES and not self.human_approval_required:
            raise ValueError(
                f"human_approval_required must be True for request_type={self.request_type!r}"
            )
        # Fail closed: human approval required when sensitive tools are required
        approval_tools = [t for t in self.required_tools if t in HUMAN_APPROVAL_TOOLS]
        if approval_tools and not self.human_approval_required:
            raise ValueError(
                f"human_approval_required must be True when required_tools includes "
                f"sensitive tools: {approval_tools!r}"
            )


# ── SignedHandoffPacket ───────────────────────────────────────────────────────

@dataclass
class SignedHandoffPacket:
    """
    Scoped worker handoff packet with hash-chain integrity.

    Rules (enforced in __post_init__):
    - from_agent must be in AUTHORIZED_SUPERVISORS
    - authority_scope must be explicit and non-empty
    - mission must be non-empty
    - stop_conditions must be non-empty
    - payload_hash is SHA-256 over canonical packet content (excludes hash/sig fields)
    - signature_algorithm is SHA256_CHAIN_PLACEHOLDER or ED25519_PLACEHOLDER until real signing
    - No worker may expand its own authority — validated at construction
    - audit_safe is always True
    """
    packet_id: str
    manifest_id: str
    created_at: str
    from_agent: str
    to_agent: str
    mission: str
    constraints: dict
    authority_scope: str
    allowed_tools: list
    forbidden_tools: list
    allowed_outputs: list
    forbidden_outputs: list
    evidence_requirements: list
    budget: Budget
    stop_conditions: list
    fallback_on_failure: str
    input_refs: list
    payload_hash: str
    previous_packet_hash: Optional[str]
    signature_algorithm: str
    signature_public_key_ref: str
    signature_placeholder: str
    audit_safe: bool = True
    # Copied verbatim from the originating RoutingManifest — the builder threads it
    # and it is covered by payload_hash, so any tampering breaks hash-chain integrity.
    gov_tx_id: str = ""

    def __post_init__(self):
        if self.from_agent not in AUTHORIZED_SUPERVISORS:
            raise ValueError(
                f"from_agent {self.from_agent!r} is not an authorized supervisor. "
                f"Authorized: {sorted(AUTHORIZED_SUPERVISORS)}"
            )
        if not self.manifest_id.strip():
            raise ValueError("manifest_id must be non-empty")
        if not self.authority_scope.strip():
            raise ValueError(
                "authority_scope must be explicit and non-empty. "
                "Workers receive least-privilege scoped authority only."
            )
        if not self.mission.strip():
            raise ValueError("mission must be non-empty")
        if not self.stop_conditions:
            raise ValueError("stop_conditions must be non-empty — workers must have termination boundaries")
        if not self.payload_hash.strip():
            raise ValueError("payload_hash must be non-empty")
        if not self.signature_algorithm.strip():
            raise ValueError("signature_algorithm must be set (use SHA256_CHAIN_PLACEHOLDER if real signing not yet implemented)")


# ── CapabilityProfile ─────────────────────────────────────────────────────────

@dataclass
class CapabilityProfile:
    """
    Declares what a worker class can and cannot do.
    Used by Abigail during routing to enforce capability boundaries.
    """
    worker_class: str
    modalities_supported: list
    allowed_request_types: list
    max_risk_level: str
    tool_permissions: list
    write_permissions: list
    network_permissions: list
    cost_class: str
    requires_human_approval: bool
    forbidden_tasks: list

    def __post_init__(self):
        for m in self.modalities_supported:
            if m not in VALID_MODALITIES:
                raise ValueError(
                    f"CapabilityProfile {self.worker_class!r}: "
                    f"unsupported modality {m!r}. Must be one of {sorted(VALID_MODALITIES)}"
                )
        if self.max_risk_level not in VALID_RISK_LEVELS:
            raise ValueError(
                f"CapabilityProfile {self.worker_class!r}: "
                f"invalid max_risk_level {self.max_risk_level!r}"
            )
        if not self.worker_class.strip():
            raise ValueError("worker_class must be non-empty")


# ── SingleGovernedState ───────────────────────────────────────────────────────

_VALID_AUTHORITY_STATUSES  = frozenset({"authorized", "pending_human_approval", "blocked"})
_VALID_SUPERVISOR_DECISIONS = frozenset({"pending", "approved", "rejected", "escalated"})


@dataclass
class SingleGovernedState:
    """
    Shared structured orchestration state across a governed pipeline run.

    Does not require full transcript replay — structured fields only.
    worker_outputs_refs and audit_refs are reference pointers, not raw content.
    """
    state_id: str
    manifest_id: str
    current_stage: str
    safe_task_summary: str
    risk_level: str
    modality: str
    source_trust_class: str
    authority_status: str
    active_constraints: list
    approved_capabilities: list
    blocked_capabilities: list
    budget_remaining: Budget
    worker_outputs_refs: list
    supervisor_decision: str
    audit_refs: list
    # Copied verbatim from the manifest that opened this transaction — correlates
    # this state with its manifest, handoff packets, and audit records.
    gov_tx_id: str = ""

    def __post_init__(self):
        if self.current_stage not in VALID_PIPELINE_STAGES:
            raise ValueError(
                f"Invalid pipeline stage: {self.current_stage!r}. "
                f"Must be one of: {sorted(VALID_PIPELINE_STAGES)}"
            )
        if self.risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"Invalid risk_level: {self.risk_level!r}")
        if self.modality not in VALID_MODALITIES:
            raise ValueError(f"Invalid modality: {self.modality!r}")
        if self.source_trust_class not in VALID_TRUST_CLASSES:
            raise ValueError(f"Invalid source_trust_class: {self.source_trust_class!r}")
        if self.authority_status not in _VALID_AUTHORITY_STATUSES:
            raise ValueError(
                f"Invalid authority_status: {self.authority_status!r}. "
                f"Must be one of: {sorted(_VALID_AUTHORITY_STATUSES)}"
            )
        if self.supervisor_decision not in _VALID_SUPERVISOR_DECISIONS:
            raise ValueError(
                f"Invalid supervisor_decision: {self.supervisor_decision!r}. "
                f"Must be one of: {sorted(_VALID_SUPERVISOR_DECISIONS)}"
            )
        if not self.state_id.strip():
            raise ValueError("state_id must be non-empty")
        if not self.manifest_id.strip():
            raise ValueError("manifest_id must be non-empty")
