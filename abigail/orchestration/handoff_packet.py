# -*- coding: utf-8 -*-
"""
handoff_packet.py — LOGOS Governance Systems Inc. — Abigail CP-00 Signed Handoff Packet Builder

Scoped worker handoff packets with hash-chain integrity.
from_agent must be an authorized supervisor (Abigail or Abigail-authorized role).
payload_hash covers canonical packet content — excludes hash/signature fields.
signature_algorithm is SHA256_CHAIN_PLACEHOLDER until real ED25519 signing is implemented.

Workers receive bounded scoped packets, not free-form transcript sprawl.
No worker may expand its own authority — enforced in SignedHandoffPacket.__post_init__.
No provider calls. No network calls. No secrets.
"""
import dataclasses

from .schemas import SignedHandoffPacket, Budget, RoutingManifest
from .audit import canonical_json, sha256_hex, now_utc, new_packet_id

# Fields included in the canonical payload hash.
# Excludes: payload_hash, previous_packet_hash, signature_*, audit_safe.
_CANONICAL_PAYLOAD_FIELDS = (
    "packet_id", "manifest_id", "created_at", "from_agent", "to_agent",
    "mission", "constraints", "authority_scope", "allowed_tools",
    "forbidden_tools", "allowed_outputs", "forbidden_outputs",
    "evidence_requirements", "budget", "stop_conditions",
    "fallback_on_failure", "input_refs",
)

_DEFAULT_FORBIDDEN_TOOLS = ["shell", "bash", "file_write", "network", "http_request", "deploy"]
_DEFAULT_STOP_CONDITIONS  = ["task_complete", "max_steps_reached", "supervisor_abort", "error"]


def build_handoff_packet(
    manifest: RoutingManifest,
    to_agent: str,
    mission: str,
    authority_scope: str,
    from_agent: str = "abigail",
    constraints: dict = None,
    allowed_tools: list = None,
    forbidden_tools: list = None,
    allowed_outputs: list = None,
    forbidden_outputs: list = None,
    evidence_requirements: list = None,
    budget: Budget = None,
    stop_conditions: list = None,
    fallback_on_failure: str = "return_to_supervisor",
    input_refs: list = None,
    previous_packet_hash: str = None,
) -> SignedHandoffPacket:
    """
    Build a scoped signed handoff packet from an approved RoutingManifest.

    payload_hash is deterministic SHA-256 over canonical content fields.
    signature_placeholder contains algorithm tag + hash prefix — real signing is future work.
    """
    if budget is None:
        budget = manifest.budget
    budget_dict = dataclasses.asdict(budget)

    packet_id  = new_packet_id()
    created_at = now_utc()
    ftools     = list(forbidden_tools or _DEFAULT_FORBIDDEN_TOOLS)
    stops      = list(stop_conditions or _DEFAULT_STOP_CONDITIONS)
    constraints_val = dict(constraints or {})

    canonical_content = {
        "packet_id":            packet_id,
        "manifest_id":          manifest.manifest_id,
        "created_at":           created_at,
        "from_agent":           from_agent,
        "to_agent":             to_agent,
        "mission":              mission,
        "constraints":          constraints_val,
        "authority_scope":      authority_scope,
        "allowed_tools":        list(allowed_tools or []),
        "forbidden_tools":      ftools,
        "allowed_outputs":      list(allowed_outputs or []),
        "forbidden_outputs":    list(forbidden_outputs or []),
        "evidence_requirements": list(evidence_requirements or []),
        "budget":               budget_dict,
        "stop_conditions":      stops,
        "fallback_on_failure":  fallback_on_failure,
        "input_refs":           list(input_refs or []),
    }
    payload_hash      = sha256_hex(canonical_json(canonical_content))
    sig_placeholder   = f"SHA256_CHAIN_PLACEHOLDER:{payload_hash[:16]}"

    return SignedHandoffPacket(
        packet_id=packet_id,
        manifest_id=manifest.manifest_id,
        created_at=created_at,
        from_agent=from_agent,
        to_agent=to_agent,
        mission=mission,
        constraints=constraints_val,
        authority_scope=authority_scope,
        allowed_tools=list(allowed_tools or []),
        forbidden_tools=ftools,
        allowed_outputs=list(allowed_outputs or []),
        forbidden_outputs=list(forbidden_outputs or []),
        evidence_requirements=list(evidence_requirements or []),
        budget=budget,
        stop_conditions=stops,
        fallback_on_failure=fallback_on_failure,
        input_refs=list(input_refs or []),
        payload_hash=payload_hash,
        previous_packet_hash=previous_packet_hash,
        signature_algorithm="SHA256_CHAIN_PLACEHOLDER",
        signature_public_key_ref="",
        signature_placeholder=sig_placeholder,
        audit_safe=True,
    )


def packet_canonical_payload_dict(packet: SignedHandoffPacket) -> dict:
    """Return the dict used to compute payload_hash — useful for verification tests."""
    raw = dataclasses.asdict(packet)
    budget_dict = dataclasses.asdict(packet.budget)
    return {
        "packet_id":            raw["packet_id"],
        "manifest_id":          raw["manifest_id"],
        "created_at":           raw["created_at"],
        "from_agent":           raw["from_agent"],
        "to_agent":             raw["to_agent"],
        "mission":              raw["mission"],
        "constraints":          raw["constraints"],
        "authority_scope":      raw["authority_scope"],
        "allowed_tools":        raw["allowed_tools"],
        "forbidden_tools":      raw["forbidden_tools"],
        "allowed_outputs":      raw["allowed_outputs"],
        "forbidden_outputs":    raw["forbidden_outputs"],
        "evidence_requirements": raw["evidence_requirements"],
        "budget":               budget_dict,
        "stop_conditions":      raw["stop_conditions"],
        "fallback_on_failure":  raw["fallback_on_failure"],
        "input_refs":           raw["input_refs"],
    }
