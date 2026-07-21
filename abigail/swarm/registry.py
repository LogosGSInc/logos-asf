# -*- coding: utf-8 -*-
"""
registry.py — AG-01 governed swarm registry.

Loads authored agent definitions and tracks explicit runtime *activation state*.
Authored != active: every agent starts DORMANT. Only ACTIVE_DRYRUN or
ACTIVE_SANDBOXED_LOCAL may execute; production/autonomous/external modes are refused.
No provider calls, no network. Truth-in-labeling: capability_label() reports only the
verified local state, never "live autonomous".
"""
import dataclasses
from pathlib import Path

import yaml

_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


class ActivationState:
    DORMANT = "dormant"
    ACTIVE_DRYRUN = "active_dryrun"
    ACTIVE_SANDBOXED_LOCAL = "active_sandboxed_local"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETE = "complete"


_ACTIVATABLE = frozenset({ActivationState.ACTIVE_DRYRUN, ActivationState.ACTIVE_SANDBOXED_LOCAL})

# Modes that must never be selectable via activate() — AG-01 is local-only.
FORBIDDEN_MODES = frozenset({
    "production_autonomous", "unbounded_autonomy", "external_action",
    "network_recon", "send_email", "publish", "ad_spend", "cloud_deploy",
})

# Demo department code -> authored-agent department prefix (agents use EX-01/EN-01/...).
_DEPARTMENT_ALIASES = {
    "EXE": "EX", "ENG": "EN", "PRD": "PRD", "MKT": "MKT", "REV": "REV",
    "LGL": "LGL", "FIN": "FIN", "SEC": "SEC", "GRC": "GRC", "OPS": "OPS",
    "DAT": "DAT", "QA": "QA", "RI": "RI", "TKR": "TKR",
    # HR has no authored department in the registry -> resolves to a synthetic handle.
}


@dataclasses.dataclass
class AgentRecord:
    agent_id: str
    name: str
    department: str          # raw YAML department, e.g. "GRC-01"
    authored: bool           # True when loaded from an `agent:` root (not a stub)
    activation_state: str = ActivationState.DORMANT


class SwarmRegistry:
    """Loads authored agents and governs their activation state."""

    def __init__(self, agents_dir=None):
        self._dir = Path(agents_dir) if agents_dir else _AGENTS_DIR
        self._agents = {}
        self._load()

    def _load(self):
        if not self._dir.is_dir():
            return
        for yf in sorted(self._dir.rglob("*.yaml")):
            try:
                data = yaml.safe_load(yf.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            node = data.get("agent")               # authored + activatable
            authored = node is not None
            if node is None:
                node = data.get("inactive_agent_stub")   # dormant stub only
            if not isinstance(node, dict):
                continue
            aid = node.get("id") or node.get("agent_id")
            if not aid:
                continue
            self._agents[aid] = AgentRecord(
                agent_id=aid,
                name=node.get("name", aid),
                department=str(node.get("department") or "UNKNOWN"),
                authored=authored,
                activation_state=ActivationState.DORMANT,
            )

    # ── introspection ──────────────────────────────────────────────────────
    def all_agents(self):
        return dict(self._agents)

    def get(self, agent_id):
        return self._agents.get(agent_id)

    def state(self, agent_id):
        rec = self._agents.get(agent_id)
        return rec.activation_state if rec else None

    def authored_count(self):
        return sum(1 for a in self._agents.values() if a.authored)

    def dept_prefix(self, dept_code):
        return _DEPARTMENT_ALIASES.get((dept_code or "").upper(), (dept_code or "").upper())

    def agents_in_department(self, dept_code):
        pref = self.dept_prefix(dept_code)
        return sorted(
            a.agent_id for a in self._agents.values()
            if a.authored and a.department.upper().startswith(pref + "-")
        )

    def resolve_department_worker(self, dept_code):
        """Return (worker_id, backed_by_authored_agent). Departments with no authored
        agent resolve to an explicit synthetic handle flagged as not-authored."""
        ids = self.agents_in_department(dept_code)
        if ids:
            return ids[0], True
        return f"{(dept_code or '').upper()}-LEAD", False

    # ── governance ─────────────────────────────────────────────────────────
    def activate(self, agent_id, mode):
        """Move an agent to a local activation mode. Refuses forbidden/unknown modes."""
        if mode in FORBIDDEN_MODES:
            raise ValueError(f"forbidden activation mode: {mode!r} (AG-01 is local-only)")
        if mode not in _ACTIVATABLE:
            raise ValueError(f"activation mode must be one of {sorted(_ACTIVATABLE)}, got {mode!r}")
        rec = self._agents.get(agent_id)
        if rec is None:
            # synthetic department handle (e.g. HR-LEAD) — allowed, flagged not-authored
            rec = AgentRecord(agent_id=agent_id, name=agent_id,
                              department="SYNTHETIC", authored=False)
            self._agents[agent_id] = rec
        rec.activation_state = mode
        return rec.activation_state

    def set_state(self, agent_id, state):
        rec = self._agents.get(agent_id)
        if rec:
            rec.activation_state = state

    def can_execute(self, agent_id):
        rec = self._agents.get(agent_id)
        return bool(rec and rec.activation_state in _ACTIVATABLE)

    def capability_label(self):
        """Honest capability descriptor — maps only to verified local state."""
        activated = [a for a in self._agents.values() if a.activation_state in _ACTIVATABLE]
        return {
            "authored_agents": self.authored_count(),
            "activated_local": len(activated),
            "verified_state": (
                "authored/active_local_bounded" if activated else "authored/dormant"
            ),
            "autonomous": False,
            "external_actions_enabled": False,
        }
