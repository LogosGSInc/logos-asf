# -*- coding: utf-8 -*-
"""
abigail.orchestration — LOGOS Governance Systems Inc. — MM-01 Governed Orchestration

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

Public API for Abigail's deterministic routing and handoff primitives.
No provider calls. No real worker execution. No secrets.
"""
from .schemas import (
    Budget,
    RoutingManifest,
    SignedHandoffPacket,
    CapabilityProfile,
    SingleGovernedState,
    VALID_MODALITIES,
    VALID_TRUST_CLASSES,
    VALID_RISK_LEVELS,
    HIGH_RISK_LEVELS,
    VALID_PIPELINE_STAGES,
    AUTHORIZED_SUPERVISORS,
    HUMAN_APPROVAL_REQUEST_TYPES,
    HUMAN_APPROVAL_TOOLS,
)
from .audit import (
    canonical_json,
    sha256_hex,
    canonical_hash,
    hash_input,
    now_utc,
    new_manifest_id,
    new_packet_id,
    new_state_id,
)
from .routing_manifest import build_routing_manifest, to_audit_dict, manifest_hash
from .handoff_packet import build_handoff_packet, packet_canonical_payload_dict
from .runtime_bridge import (
    ShadowOrchestrationContext,
    build_shadow_orchestration_context,
    BRIDGE_VERSION,
)
from .capabilities import (
    get_capability_profile,
    check_modality_supported,
    check_risk_level_allowed,
    requires_human_approval_for,
)

__all__ = [
    "Budget",
    "RoutingManifest",
    "SignedHandoffPacket",
    "CapabilityProfile",
    "SingleGovernedState",
    "VALID_MODALITIES",
    "VALID_TRUST_CLASSES",
    "VALID_RISK_LEVELS",
    "HIGH_RISK_LEVELS",
    "VALID_PIPELINE_STAGES",
    "AUTHORIZED_SUPERVISORS",
    "HUMAN_APPROVAL_REQUEST_TYPES",
    "HUMAN_APPROVAL_TOOLS",
    "canonical_json",
    "sha256_hex",
    "canonical_hash",
    "hash_input",
    "now_utc",
    "new_manifest_id",
    "new_packet_id",
    "new_state_id",
    "build_routing_manifest",
    "to_audit_dict",
    "manifest_hash",
    "build_handoff_packet",
    "packet_canonical_payload_dict",
    "ShadowOrchestrationContext",
    "build_shadow_orchestration_context",
    "BRIDGE_VERSION",
    "get_capability_profile",
    "check_modality_supported",
    "check_risk_level_allowed",
    "requires_human_approval_for",
]
