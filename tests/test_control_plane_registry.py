# -*- coding: utf-8 -*-
"""
tests/test_control_plane_registry.py — Curated Control Plane Registry contract tests

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

The registry exposes Skills to Operations safely. These tests enforce its contract:
  - authenticated       — no read without a valid token; fail-closed
  - curated             — register then seal; sealed catalogue cannot change
  - immutable metadata  — descriptors are frozen; nothing mutates after registration
  - no executable routing — no dispatch/route/execute/activate/resolve surface at all
  - broker remains authoritative — the registry describes workers, never reaches them
"""
import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from abigail.orchestration import (
    ControlPlaneRegistry,
    WorkerDescriptor,
    ControlPlaneAuthError,
    build_default_control_plane_registry,
    all_capability_profiles,
    FORBIDDEN_REGISTRY_CAPABILITIES,
    LIFECYCLE_STATES,
)
import abigail.orchestration.control_plane_registry as cpr_module


_TOKEN = "test-control-plane-token-123"


def _descriptor(worker_class="text_analyst", **kw):
    defaults = dict(
        worker_class=worker_class,
        display_name="Text Analyst",
        description="desc",
        version="1.0.0",
        lifecycle_state="authored",
        governance_status="governed",
        modalities_supported=["text"],
        allowed_request_types=["analyze"],
        max_risk_level="medium",
        requires_human_approval=False,
        forbidden_tasks=["execute_code"],
        cost_class="low",
    )
    defaults.update(kw)
    return WorkerDescriptor(**defaults)


def _sealed_registry(token=_TOKEN):
    reg = ControlPlaneRegistry(access_token=token)
    reg.register(_descriptor("text_analyst"))
    reg.register(_descriptor("code_reviewer", display_name="Code Reviewer"))
    return reg.seal()


# ── authenticated ─────────────────────────────────────────────────────────────

def test_valid_token_returns_reader():
    reg = _sealed_registry()
    reader = reg.authenticate(_TOKEN)
    assert len(reader.list_workers()) == 2


def test_wrong_token_is_refused():
    reg = _sealed_registry()
    with pytest.raises(ControlPlaneAuthError):
        reg.authenticate("wrong-token")


def test_empty_token_is_refused():
    reg = _sealed_registry()
    with pytest.raises(ControlPlaneAuthError):
        reg.authenticate("")


def test_missing_server_token_fails_closed(monkeypatch):
    monkeypatch.delenv("ABIGAIL_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    reg = ControlPlaneRegistry(access_token=None)
    reg.register(_descriptor())
    reg.seal()
    with pytest.raises(ControlPlaneAuthError):
        reg.authenticate("anything")


def test_unsealed_registry_refuses_reads():
    reg = ControlPlaneRegistry(access_token=_TOKEN)
    reg.register(_descriptor())
    with pytest.raises(ControlPlaneAuthError):
        reg.authenticate(_TOKEN)  # not sealed yet — curation incomplete


def test_env_token_authenticates(monkeypatch):
    monkeypatch.setenv("ABIGAIL_CONTROL_PLANE_TOKEN", "env-token-xyz")
    reg = ControlPlaneRegistry(access_token=None)
    reg.register(_descriptor())
    reg.seal()
    assert reg.authenticate("env-token-xyz").list_workers()


# ── curated ─────────────────────────────────────────────────────────────────

def test_register_after_seal_is_refused():
    reg = _sealed_registry()
    with pytest.raises(ValueError, match="sealed"):
        reg.register(_descriptor("marketing_draft"))


def test_duplicate_worker_class_is_refused():
    reg = ControlPlaneRegistry(access_token=_TOKEN)
    reg.register(_descriptor("text_analyst"))
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(_descriptor("text_analyst"))


def test_double_seal_is_refused():
    reg = _sealed_registry()
    with pytest.raises(ValueError, match="already sealed"):
        reg.seal()


def test_register_rejects_non_descriptor():
    reg = ControlPlaneRegistry(access_token=_TOKEN)
    with pytest.raises(TypeError):
        reg.register({"worker_class": "x"})


# ── immutable metadata ────────────────────────────────────────────────────────

def test_descriptor_is_frozen():
    d = _descriptor()
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.max_risk_level = "critical"


def test_descriptor_coerces_lists_to_tuples():
    d = _descriptor(modalities_supported=["text", "document"])
    assert isinstance(d.modalities_supported, tuple)
    assert isinstance(d.forbidden_tasks, tuple)


def test_reader_list_is_immutable_tuple():
    reg = _sealed_registry()
    reader = reg.authenticate(_TOKEN)
    assert isinstance(reader.list_workers(), tuple)


def test_descriptor_validates_lifecycle_state():
    with pytest.raises(ValueError, match="lifecycle_state"):
        _descriptor(lifecycle_state="live_autonomous")


def test_descriptor_validates_governance_and_health():
    with pytest.raises(ValueError, match="governance_status"):
        _descriptor(governance_status="ungoverned")
    with pytest.raises(ValueError, match="health"):
        _descriptor(health="great")


# ── no executable routing / never dispatches ───────────────────────────────────

def _public_callables(obj):
    return [n for n in dir(obj)
            if not n.startswith("_") and callable(getattr(obj, n, None))]


def test_no_dispatch_verbs_in_public_api():
    """No public method name may contain a dispatch/route/execute-style verb."""
    reg = _sealed_registry()
    reader = reg.authenticate(_TOKEN)
    surfaces = _public_callables(reg) + _public_callables(reader) + _public_callables(_descriptor())
    for name in surfaces:
        tokens = set(name.split("_"))
        offending = tokens & FORBIDDEN_REGISTRY_CAPABILITIES
        assert not offending, f"registry surface {name!r} exposes forbidden capability {offending}"


def test_descriptor_holds_no_callable_and_no_endpoint():
    """A descriptor describes a worker — it must not carry a way to reach one."""
    d = _descriptor()
    for f in dataclasses.fields(d):
        val = getattr(d, f.name)
        assert not callable(val), f"descriptor field {f.name} is callable — that is a dispatch surface"
        assert "endpoint" not in f.name and "url" not in f.name and "target" not in f.name


def test_registry_module_does_not_import_dispatch_layers():
    """The registry must not depend on the broker/executor — it only describes.
    Inspects actual import statements (docstrings may name them as non-goals)."""
    import ast
    tree = ast.parse(Path(cpr_module.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)
    joined = " ".join(imported)
    for forbidden in ("handoff_packet", "runtime_bridge", "local_executor",
                      "swarm", "job_spec", "call_groq"):
        assert forbidden not in joined, f"registry imports dispatch layer {forbidden!r}"


# ── reader queries + Operations snapshot (UI P2 seam) ──────────────────────────

def test_describe_returns_descriptor():
    reg = _sealed_registry()
    reader = reg.authenticate(_TOKEN)
    d = reader.describe("text_analyst")
    assert d.worker_class == "text_analyst"


def test_describe_unknown_raises():
    reg = _sealed_registry()
    reader = reg.authenticate(_TOKEN)
    with pytest.raises(KeyError):
        reader.describe("nonexistent_worker")


def test_snapshot_shape_for_ui():
    reg = _sealed_registry()
    reader = reg.authenticate(_TOKEN)
    snap = reader.snapshot()
    assert snap["governed_by"] == "abigail.cp00"
    assert snap["sealed"] is True
    assert snap["worker_count"] == 2
    w = snap["workers"][0]
    for key in ("worker_class", "version", "lifecycle_state", "health",
                "availability", "governance_status", "max_risk_level",
                "requires_human_approval", "modalities_supported"):
        assert key in w


def test_snapshot_is_json_serializable():
    import json
    reg = _sealed_registry()
    snap = reg.authenticate(_TOKEN).snapshot()
    json.loads(json.dumps(snap))  # must not raise


# ── default curated registry (from capability profiles) ────────────────────────

def test_default_registry_describes_all_governed_workers():
    reg = build_default_control_plane_registry(access_token=_TOKEN)
    assert reg.is_sealed
    reader = reg.authenticate(_TOKEN)
    described = {d.worker_class for d in reader.list_workers()}
    assert described == set(all_capability_profiles().keys())


def test_default_registry_governance_matches_profiles():
    reg = build_default_control_plane_registry(access_token=_TOKEN)
    reader = reg.authenticate(_TOKEN)
    for d in reader.list_workers():
        profile = all_capability_profiles()[d.worker_class]
        assert d.max_risk_level == profile.max_risk_level
        assert d.requires_human_approval == profile.requires_human_approval


def test_default_registry_truth_in_labeling():
    """No fabricated liveness — health/availability are unknown until probed."""
    reg = build_default_control_plane_registry(access_token=_TOKEN)
    reader = reg.authenticate(_TOKEN)
    for d in reader.list_workers():
        assert d.health == "unknown"
        assert d.availability == "unknown"
        assert d.lifecycle_state in LIFECYCLE_STATES
