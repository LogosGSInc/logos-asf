# -*- coding: utf-8 -*-
"""
routing_manifest.py — LOGOS Governance Systems Inc. — Abigail CP-00 Routing Manifest Builder

Deterministic builder for RoutingManifest. Abigail calls this before any worker handoff.
human_approval_required is computed automatically from risk_level, request_type, and
required_tools — it cannot be overridden to False when governance rules require True.

No provider calls. No network calls. No raw prompts stored. No secrets.
"""
import dataclasses

from .schemas import (
    RoutingManifest, Budget,
    HIGH_RISK_LEVELS, HUMAN_APPROVAL_REQUEST_TYPES, HUMAN_APPROVAL_TOOLS,
)
from .audit import canonical_hash, hash_input, now_utc, new_manifest_id


def _requires_human_approval(
    risk_level: str,
    request_type: str,
    required_tools: list,
) -> bool:
    return (
        risk_level in HIGH_RISK_LEVELS
        or request_type in HUMAN_APPROVAL_REQUEST_TYPES
        or any(t in HUMAN_APPROVAL_TOOLS for t in required_tools)
    )


def build_routing_manifest(
    task_intent: str,
    request_type: str,
    modality: str,
    source_trust_class: str,
    data_sensitivity: str = "internal",
    risk_level: str = "low",
    doctrine_sensitivity: str = "standard",
    command_style_signal: bool = False,
    required_capabilities: list = None,
    allowed_worker_classes: list = None,
    forbidden_worker_classes: list = None,
    required_tools: list = None,
    forbidden_tools: list = None,
    budget: Budget = None,
    fallback_chain: list = None,
    termination_condition: str = "task_complete_or_max_steps_reached",
    input_payload: bytes = b"",
    policy_refs: list = None,
    supervisor: str = "abigail",
    gov_tx_id: str = "",
) -> RoutingManifest:
    """
    Build a governed RoutingManifest. Computes human_approval_required automatically.
    Stores SHA-256 of input_payload as input_hash — no raw content stored.
    Raises ValueError if any invariant would be violated.

    gov_tx_id: single governance transaction ID for end-to-end correlation. Leave
    empty to mint a fresh one (the common case — one manifest opens the transaction);
    pass an existing id to attach this manifest to a transaction already in flight.
    """
    required_tools = list(required_tools or [])
    forbidden_tools = list(forbidden_tools or [])
    fallback_chain = list(fallback_chain or [])

    auto_approval = _requires_human_approval(risk_level, request_type, required_tools)

    if budget is None:
        budget = Budget(max_steps=10, max_tokens_estimate=4096)

    return RoutingManifest(
        manifest_id=new_manifest_id(),
        created_at=now_utc(),
        supervisor=supervisor,
        task_intent=task_intent,
        request_type=request_type,
        modality=modality,
        source_trust_class=source_trust_class,
        data_sensitivity=data_sensitivity,
        risk_level=risk_level,
        doctrine_sensitivity=doctrine_sensitivity,
        command_style_signal=command_style_signal,
        required_capabilities=list(required_capabilities or []),
        allowed_worker_classes=list(allowed_worker_classes or []),
        forbidden_worker_classes=list(forbidden_worker_classes or []),
        required_tools=required_tools,
        forbidden_tools=forbidden_tools,
        budget=budget,
        fallback_chain=fallback_chain,
        termination_condition=termination_condition,
        human_approval_required=auto_approval,
        input_hash=hash_input(input_payload),
        policy_refs=list(policy_refs or []),
        audit_safe=True,
        gov_tx_id=gov_tx_id,
    )


def to_audit_dict(manifest: RoutingManifest) -> dict:
    """Recursively convert manifest to a plain dict for canonical hashing or logging."""
    return dataclasses.asdict(manifest)


def manifest_hash(manifest: RoutingManifest) -> str:
    """SHA-256 over canonical JSON of the manifest audit dict."""
    return canonical_hash(to_audit_dict(manifest))
