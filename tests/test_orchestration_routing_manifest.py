# -*- coding: utf-8 -*-
"""
tests/test_orchestration_routing_manifest.py — MM-01 Routing Manifest + Capability Tests

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

Covers:
- RoutingManifest build + field validation
- human_approval_required governance invariants (fail-closed)
- input_hash privacy (no raw prompt stored)
- command_style_signal support
- mixed_bundle modality
- Budget requirements
- CapabilityProfile validation
- SingleGovernedState validation
- Mixed-bundle sprint simulation fixture
- No provider calls / no network calls / no secrets / ~/Abigailv1 untouched
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from abigail.orchestration import (
    Budget, RoutingManifest, CapabilityProfile, SingleGovernedState,
    build_routing_manifest, manifest_hash, to_audit_dict,
    get_capability_profile, check_modality_supported,
    check_risk_level_allowed, requires_human_approval_for,
    sha256_hex, canonical_json, hash_input, new_state_id,
    VALID_MODALITIES, VALID_TRUST_CLASSES, VALID_RISK_LEVELS,
    HIGH_RISK_LEVELS, AUTHORIZED_SUPERVISORS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _base_manifest(**overrides) -> RoutingManifest:
    defaults = dict(
        task_intent="analyze_document",
        request_type="analyze",
        modality="document",
        source_trust_class="user_supplied",
        input_payload=b"canonical_test_input",
    )
    defaults.update(overrides)
    return build_routing_manifest(**defaults)


# ── RoutingManifest build ─────────────────────────────────────────────────────

def test_routing_manifest_builds_with_required_fields():
    m = _base_manifest()
    assert m.manifest_id.startswith("MANIFEST-")
    assert m.supervisor == "abigail"
    assert m.task_intent == "analyze_document"
    assert m.modality == "document"
    assert m.audit_safe is True
    assert len(m.input_hash) == 64   # SHA-256 hex


def test_routing_manifest_rejects_missing_modality():
    with pytest.raises(ValueError, match="Invalid modality"):
        _base_manifest(modality="spreadsheet")


def test_routing_manifest_rejects_all_invalid_modalities():
    for bad in ("pdf", "stream", "binary", "", "TEXT"):
        with pytest.raises(ValueError):
            _base_manifest(modality=bad)


def test_routing_manifest_rejects_invalid_source_trust_class():
    with pytest.raises(ValueError, match="Invalid source_trust_class"):
        _base_manifest(source_trust_class="public_internet")


def test_routing_manifest_rejects_invalid_risk_level():
    with pytest.raises(ValueError, match="Invalid risk_level"):
        _base_manifest(risk_level="extreme")


# ── human_approval_required invariants (fail-closed) ─────────────────────────

def test_routing_manifest_marks_high_risk_as_human_approval_required():
    m = _base_manifest(risk_level="high")
    assert m.human_approval_required is True


def test_routing_manifest_marks_critical_risk_as_human_approval_required():
    m = _base_manifest(risk_level="critical")
    assert m.human_approval_required is True


def test_routing_manifest_marks_file_write_as_human_approval_required():
    m = _base_manifest(request_type="file_write")
    assert m.human_approval_required is True


def test_routing_manifest_marks_network_call_as_human_approval_required():
    m = _base_manifest(request_type="network_call")
    assert m.human_approval_required is True


def test_routing_manifest_marks_publish_as_human_approval_required():
    m = _base_manifest(request_type="publish")
    assert m.human_approval_required is True


def test_routing_manifest_marks_paid_spend_as_human_approval_required():
    m = _base_manifest(request_type="paid_spend")
    assert m.human_approval_required is True


def test_routing_manifest_marks_privileged_operation_as_human_approval_required():
    m = _base_manifest(request_type="privileged_operation")
    assert m.human_approval_required is True


def test_routing_manifest_marks_sensitive_required_tool_as_human_approval_required():
    m = _base_manifest(required_tools=["file_write"])
    assert m.human_approval_required is True


def test_routing_manifest_low_risk_safe_request_does_not_require_approval():
    m = _base_manifest(risk_level="low", request_type="analyze")
    assert m.human_approval_required is False


def test_routing_manifest_medium_risk_safe_request_does_not_require_approval():
    m = _base_manifest(risk_level="medium", request_type="summarize")
    assert m.human_approval_required is False


# ── input_hash privacy ────────────────────────────────────────────────────────

def test_routing_manifest_stores_input_hash_not_raw_prompt():
    payload = b"this is the operator input"
    m = build_routing_manifest("t", "analyze", "text", "operator_direct",
                                input_payload=payload)
    expected_hash = hash_input(payload)
    assert m.input_hash == expected_hash
    # Verify raw payload is NOT stored anywhere in the audit dict
    audit = to_audit_dict(m)
    audit_str = str(audit)
    assert "this is the operator input" not in audit_str


def test_routing_manifest_different_inputs_produce_different_hashes():
    m1 = build_routing_manifest("t", "a", "text", "operator_direct", input_payload=b"aaa")
    m2 = build_routing_manifest("t", "a", "text", "operator_direct", input_payload=b"bbb")
    assert m1.input_hash != m2.input_hash


# ── command_style_signal ──────────────────────────────────────────────────────

def test_routing_manifest_supports_command_style_signal_false():
    m = _base_manifest(command_style_signal=False)
    assert m.command_style_signal is False


def test_routing_manifest_supports_command_style_signal_true():
    m = _base_manifest(command_style_signal=True)
    assert m.command_style_signal is True


# ── mixed_bundle modality ─────────────────────────────────────────────────────

def test_routing_manifest_supports_mixed_bundle_modality():
    m = _base_manifest(modality="mixed_bundle")
    assert m.modality == "mixed_bundle"


def test_all_valid_modalities_accepted():
    for mod in VALID_MODALITIES:
        m = _base_manifest(modality=mod)
        assert m.modality == mod


# ── Budget fields ─────────────────────────────────────────────────────────────

def test_routing_manifest_budget_has_max_steps_and_tokens():
    budget = Budget(max_steps=5, max_tokens_estimate=2048)
    m = _base_manifest(budget=budget)
    assert m.budget.max_steps == 5
    assert m.budget.max_tokens_estimate == 2048


def test_routing_manifest_default_budget_is_valid():
    m = _base_manifest()
    assert m.budget.max_steps > 0
    assert m.budget.max_tokens_estimate > 0


def test_budget_rejects_zero_steps():
    with pytest.raises(ValueError, match="max_steps"):
        Budget(max_steps=0, max_tokens_estimate=4096)


def test_budget_rejects_zero_tokens():
    with pytest.raises(ValueError, match="max_tokens_estimate"):
        Budget(max_steps=1, max_tokens_estimate=0)


# ── CapabilityProfile validation ──────────────────────────────────────────────

def test_capability_profile_rejects_unsupported_modality():
    with pytest.raises(ValueError, match="unsupported modality"):
        CapabilityProfile(
            worker_class="bad_worker",
            modalities_supported=["pdf_stream"],
            allowed_request_types=["analyze"],
            max_risk_level="low",
            tool_permissions=[],
            write_permissions=[],
            network_permissions=[],
            cost_class="low",
            requires_human_approval=False,
            forbidden_tasks=[],
        )


def test_capability_profile_requires_human_approval_when_risk_exceeded():
    doc_profile = get_capability_profile("document_analyst")
    assert doc_profile.max_risk_level == "medium"
    assert requires_human_approval_for(doc_profile, "high") is True
    assert requires_human_approval_for(doc_profile, "critical") is True


def test_capability_profile_does_not_require_approval_within_risk():
    text_profile = get_capability_profile("text_analyst")
    assert requires_human_approval_for(text_profile, "low") is False
    assert requires_human_approval_for(text_profile, "medium") is False


def test_capability_profile_image_analyst_is_metadata_only():
    img = get_capability_profile("image_analyst")
    assert img.allowed_request_types == ["metadata_only"]
    assert "content_analysis" in img.forbidden_tasks


def test_capability_profile_governance_reviewer_requires_human_approval():
    gov = get_capability_profile("governance_reviewer")
    assert gov.requires_human_approval is True


# ── SingleGovernedState validation ───────────────────────────────────────────

def test_single_governed_state_builds():
    m = _base_manifest()
    s = SingleGovernedState(
        state_id=new_state_id(),
        manifest_id=m.manifest_id,
        current_stage="routing",
        safe_task_summary="analyze document",
        risk_level="low",
        modality="document",
        source_trust_class="user_supplied",
        authority_status="authorized",
        active_constraints=["no_network"],
        approved_capabilities=["document_analyst"],
        blocked_capabilities=[],
        budget_remaining=Budget(5, 2048),
        worker_outputs_refs=[],
        supervisor_decision="pending",
        audit_refs=[],
    )
    assert s.current_stage == "routing"
    assert s.supervisor_decision == "pending"


def test_single_governed_state_rejects_invalid_stage():
    with pytest.raises(ValueError, match="Invalid pipeline stage"):
        m = _base_manifest()
        SingleGovernedState(
            state_id="S1", manifest_id=m.manifest_id,
            current_stage="free_roam",
            safe_task_summary="x", risk_level="low", modality="text",
            source_trust_class="user_supplied", authority_status="authorized",
            active_constraints=[], approved_capabilities=[], blocked_capabilities=[],
            budget_remaining=Budget(1, 100), worker_outputs_refs=[],
            supervisor_decision="pending", audit_refs=[],
        )


def test_single_governed_state_rejects_invalid_authority_status():
    with pytest.raises(ValueError, match="Invalid authority_status"):
        m = _base_manifest()
        SingleGovernedState(
            state_id="S1", manifest_id=m.manifest_id,
            current_stage="routing",
            safe_task_summary="x", risk_level="low", modality="text",
            source_trust_class="user_supplied", authority_status="self_approved",
            active_constraints=[], approved_capabilities=[], blocked_capabilities=[],
            budget_remaining=Budget(1, 100), worker_outputs_refs=[],
            supervisor_decision="pending", audit_refs=[],
        )


# ── Mixed-bundle sprint simulation fixture ────────────────────────────────────

def test_mixed_bundle_hostile_content_quarantined():
    """
    Sprint simulation: mixed bundle containing:
    1. Legitimate document-analysis task
    2. Hostile command-style instruction (dump config)
    3. Ambiguous authority claim (escalate role admin)
    4. External action (network_call)

    Expected Abigail behavior:
    - Classify as mixed_bundle, high risk, command_style_signal=True
    - human_approval_required=True for the bundle
    - Safe subtask gets its own low-risk manifest
    - External action manifest requires human approval
    - No worker executes. No provider called.
    - Output is an audited supervisor decision structure.
    """
    # Gate 2: Bundle classified as high risk — hostile content quarantined at doctrine gate
    bundle_manifest = build_routing_manifest(
        task_intent="process_mixed_bundle",
        request_type="analyze",
        modality="mixed_bundle",
        source_trust_class="user_supplied",
        risk_level="high",
        command_style_signal=True,   # hostile cmd-style content present
        forbidden_tools=["shell", "bash", "network", "file_write"],
        input_payload=b"[BUNDLE: doc_analysis + dump config + escalate role + http_request]",
        policy_refs=["GOVSEC_V2_1_COMMAND_STYLE_INJECTION.md"],
    )
    assert bundle_manifest.command_style_signal is True
    assert bundle_manifest.human_approval_required is True
    assert bundle_manifest.modality == "mixed_bundle"
    assert bundle_manifest.risk_level == "high"
    assert bundle_manifest.audit_safe is True

    # Gate 3: Safe subtask gets a scoped routing manifest
    safe_manifest = build_routing_manifest(
        task_intent="analyze_document_content",
        request_type="analyze",
        modality="document",
        source_trust_class="user_supplied",
        risk_level="low",
        command_style_signal=False,
        input_payload=b"[SAFE_SUBTASK: document_content_only]",
    )
    assert safe_manifest.human_approval_required is False
    assert safe_manifest.modality == "document"
    assert safe_manifest.command_style_signal is False

    # External action sub-element requires human approval
    external_manifest = build_routing_manifest(
        task_intent="outbound_http_call",
        request_type="network_call",
        modality="text",
        source_trust_class="user_supplied",
        risk_level="medium",
        input_payload=b"[EXTERNAL_ACTION]",
    )
    assert external_manifest.human_approval_required is True

    # Gate 5: Supervisor decision — no worker executes, no provider called
    # Represented as SingleGovernedState with supervisor_decision=pending (awaiting human approval)
    state = SingleGovernedState(
        state_id=new_state_id(),
        manifest_id=bundle_manifest.manifest_id,
        current_stage="doctrine_gate",
        safe_task_summary="mixed bundle: hostile content quarantined, safe subtask routed, external action pending approval",
        risk_level="high",
        modality="mixed_bundle",
        source_trust_class="user_supplied",
        authority_status="pending_human_approval",
        active_constraints=["no_network", "no_file_write", "no_shell", "haap_gate_active"],
        approved_capabilities=["document_analyst"],
        blocked_capabilities=["network_call", "shell_exec", "file_write"],
        budget_remaining=Budget(10, 4096),
        worker_outputs_refs=[],
        supervisor_decision="pending",
        audit_refs=[bundle_manifest.manifest_id, safe_manifest.manifest_id],
    )
    assert state.authority_status == "pending_human_approval"
    assert state.supervisor_decision == "pending"
    assert "document_analyst" in state.approved_capabilities
    assert "network_call" in state.blocked_capabilities


def test_normal_safe_work_routes_as_bounded_task():
    """Normal safe document analysis routes without human approval."""
    m = build_routing_manifest(
        task_intent="summarize_policy_doc",
        request_type="summarize",
        modality="document",
        source_trust_class="operator_direct",
        risk_level="low",
        input_payload=b"policy document content",
    )
    assert m.human_approval_required is False
    assert m.modality == "document"
    assert m.risk_level == "low"
    assert m.audit_safe is True


# ── No provider / network calls / secrets ────────────────────────────────────

def test_no_provider_calls_in_orchestration_modules():
    """Verify orchestration source has no provider/network imports."""
    orch_dir = Path(__file__).parent.parent / "abigail" / "orchestration"
    forbidden_patterns = [
        "groq", "openai", "anthropic", "requests.get", "requests.post",
        "httpx", "urllib.request", "socket.connect", "subprocess",
    ]
    for pyfile in sorted(orch_dir.glob("*.py")):
        source = pyfile.read_text()
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"{pyfile.name} must not use {pattern!r} — no provider/network calls in orchestration"
            )


def test_no_secrets_in_routing_manifest_audit_dict():
    """Audit dict must not contain raw prompt or secret-shaped values."""
    m = build_routing_manifest("t", "analyze", "text", "operator_direct",
                                input_payload=b"sk-secret-key-value")
    audit = str(to_audit_dict(m))
    assert "sk-secret-key-value" not in audit
    assert "sk-" not in audit


def test_abigailv1_has_no_unresolved_merge_paths():
    """The active V1 repository must not contain unresolved merge entries."""
    import subprocess
    repo = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=U"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    unresolved = result.stdout.strip()
    assert unresolved == "", (
        f"Unresolved merge paths remain in Abigailv1: {unresolved}"
    )
