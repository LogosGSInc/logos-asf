# -*- coding: utf-8 -*-
"""AG-01: swarm registry activation tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
from swarm import SwarmRegistry, ActivationState, FORBIDDEN_MODES  # noqa: E402


def test_registry_loads_authored_agents_dormant():
    r = SwarmRegistry()
    assert r.authored_count() >= 12
    # every authored agent starts dormant
    for rec in r.all_agents().values():
        assert rec.activation_state == ActivationState.DORMANT


def test_dormant_agents_cannot_execute():
    r = SwarmRegistry()
    wid, authored = r.resolve_department_worker("EXE")
    assert authored is True
    assert r.can_execute(wid) is False  # dormant


def test_activation_enables_execution():
    r = SwarmRegistry()
    wid, _ = r.resolve_department_worker("EXE")
    r.activate(wid, ActivationState.ACTIVE_DRYRUN)
    assert r.can_execute(wid) is True
    assert r.state(wid) == ActivationState.ACTIVE_DRYRUN


@pytest.mark.parametrize("mode", sorted(FORBIDDEN_MODES))
def test_forbidden_activation_modes_refused(mode):
    r = SwarmRegistry()
    wid, _ = r.resolve_department_worker("SEC")
    with pytest.raises(ValueError):
        r.activate(wid, mode)


def test_unknown_activation_mode_refused():
    r = SwarmRegistry()
    wid, _ = r.resolve_department_worker("SEC")
    with pytest.raises(ValueError):
        r.activate(wid, "turbo")


def test_department_resolution_authored_vs_synthetic():
    r = SwarmRegistry()
    _, exe_authored = r.resolve_department_worker("EXE")
    _, hr_authored = r.resolve_department_worker("HR")
    assert exe_authored is True          # EX-01 agents exist
    assert hr_authored is False          # no authored HR department -> synthetic handle


def test_capability_label_is_honest():
    r = SwarmRegistry()
    label = r.capability_label()
    assert label["autonomous"] is False
    assert label["external_actions_enabled"] is False
    assert label["verified_state"] == "authored/dormant"
    wid, _ = r.resolve_department_worker("EXE")
    r.activate(wid, ActivationState.ACTIVE_SANDBOXED_LOCAL)
    assert r.capability_label()["verified_state"] == "authored/active_local_bounded"
    assert r.capability_label()["autonomous"] is False
