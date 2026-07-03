# -*- coding: utf-8 -*-
"""
capabilities.py — LOGOS Governance Systems Inc. — Abigail CP-00 Worker Capability Profiles

Default capability profiles for known worker classes.
Abigail uses these during routing to enforce capability, modality, risk, and approval boundaries.

image/audio/video workers are metadata-only this sprint — no content analysis.
No provider calls. No network calls. No secrets.
"""
from .schemas import (
    CapabilityProfile, VALID_MODALITIES, VALID_RISK_LEVELS,
    HIGH_RISK_LEVELS, _RISK_ORDER,
)

_PROFILES: dict[str, CapabilityProfile] = {}


def _register(**kwargs) -> CapabilityProfile:
    p = CapabilityProfile(**kwargs)
    _PROFILES[p.worker_class] = p
    return p


TEXT_ANALYST = _register(
    worker_class="text_analyst",
    modalities_supported=["text"],
    allowed_request_types=["analyze", "summarize", "classify", "review"],
    max_risk_level="medium",
    tool_permissions=[],
    write_permissions=[],
    network_permissions=[],
    cost_class="low",
    requires_human_approval=False,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy", "publish"],
)

DOCUMENT_ANALYST = _register(
    worker_class="document_analyst",
    modalities_supported=["document", "text"],
    allowed_request_types=["analyze", "summarize", "classify", "extract"],
    max_risk_level="medium",
    tool_permissions=["read_document"],
    write_permissions=[],
    network_permissions=[],
    cost_class="medium",
    requires_human_approval=False,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy", "publish"],
)

# Metadata-only this sprint — no image content analysis
IMAGE_ANALYST = _register(
    worker_class="image_analyst",
    modalities_supported=["image"],
    allowed_request_types=["metadata_only"],
    max_risk_level="low",
    tool_permissions=[],
    write_permissions=[],
    network_permissions=[],
    cost_class="medium",
    requires_human_approval=False,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy",
                     "content_analysis", "transcription", "publish"],
)

# Metadata-only this sprint — no audio transcription
AUDIO_ANALYST = _register(
    worker_class="audio_analyst",
    modalities_supported=["audio"],
    allowed_request_types=["metadata_only"],
    max_risk_level="low",
    tool_permissions=[],
    write_permissions=[],
    network_permissions=[],
    cost_class="high",
    requires_human_approval=True,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy",
                     "transcription", "content_analysis", "publish"],
)

CODE_REVIEWER = _register(
    worker_class="code_reviewer",
    modalities_supported=["text", "document"],
    allowed_request_types=["review", "analyze", "classify"],
    max_risk_level="medium",
    tool_permissions=["read_file"],
    write_permissions=[],
    network_permissions=[],
    cost_class="medium",
    requires_human_approval=False,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy", "publish"],
)

SECURITY_REVIEWER = _register(
    worker_class="security_reviewer",
    modalities_supported=["text", "document"],
    allowed_request_types=["review", "analyze", "classify", "threat_model"],
    max_risk_level="high",
    tool_permissions=["read_file"],
    write_permissions=[],
    network_permissions=[],
    cost_class="medium",
    requires_human_approval=True,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy",
                     "run_scan", "publish"],
)

RESEARCH_INTELLIGENCE = _register(
    worker_class="research_intelligence",
    modalities_supported=["text", "document"],
    allowed_request_types=["research", "summarize", "analyze"],
    max_risk_level="medium",
    tool_permissions=["read_document"],
    write_permissions=[],
    network_permissions=[],   # no live search in this sprint
    cost_class="medium",
    requires_human_approval=False,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy",
                     "live_search", "publish"],
)

MARKETING_DRAFT = _register(
    worker_class="marketing_draft",
    modalities_supported=["text"],
    allowed_request_types=["draft", "review"],
    max_risk_level="low",
    tool_permissions=[],
    write_permissions=[],
    network_permissions=[],
    cost_class="low",
    requires_human_approval=False,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy", "publish"],
)

GOVERNANCE_REVIEWER = _register(
    worker_class="governance_reviewer",
    modalities_supported=["text", "document"],
    allowed_request_types=["review", "audit", "classify", "compliance_check"],
    max_risk_level="high",
    tool_permissions=["read_document", "read_policy"],
    write_permissions=[],
    network_permissions=[],
    cost_class="medium",
    requires_human_approval=True,
    forbidden_tasks=["execute_code", "write_file", "send_message", "deploy",
                     "modify_policy", "publish"],
)


# ── Capability query helpers ──────────────────────────────────────────────────

def get_capability_profile(worker_class: str) -> CapabilityProfile:
    if worker_class not in _PROFILES:
        raise KeyError(
            f"No capability profile for worker class {worker_class!r}. "
            f"Known classes: {sorted(_PROFILES)}"
        )
    return _PROFILES[worker_class]


def check_modality_supported(profile: CapabilityProfile, modality: str) -> bool:
    return modality in profile.modalities_supported


def check_risk_level_allowed(profile: CapabilityProfile, risk_level: str) -> bool:
    return _RISK_ORDER.index(risk_level) <= _RISK_ORDER.index(profile.max_risk_level)


def requires_human_approval_for(profile: CapabilityProfile, risk_level: str) -> bool:
    """True if this profile+risk combination requires human approval."""
    if profile.requires_human_approval:
        return True
    if not check_risk_level_allowed(profile, risk_level):
        return True
    return False
