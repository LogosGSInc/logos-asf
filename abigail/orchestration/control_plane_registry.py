# -*- coding: utf-8 -*-
"""
control_plane_registry.py — LOGOS Governance Systems Inc. — Abigail CP-00 Curated Control Plane Registry

The governed registry that exposes Skills to Operations *safely*. It is the new
governed registry — NOT the old swarm registry (abigail/swarm/registry.py), which
tracks activation state and can activate/resolve workers for execution.

Contract (fail-closed, enforced here and by tests):
  - authenticated      — you cannot read a worker description without a valid token;
                         the ONLY public entry point for reading is authenticate().
  - curated            — descriptors are registered then sealed; after seal() the
                         catalogue is frozen and cannot be added to or altered.
  - immutable metadata — WorkerDescriptor is a frozen dataclass of tuples; nothing
                         about a worker can be mutated once registered.
  - no executable routing — there is NO method anywhere that dispatches, routes,
                         invokes, activates, resolves, or selects a worker. The
                         registry only DESCRIBES workers.
  - broker remains authoritative — dispatch happens exclusively through the broker
                         (handoff_packet / runtime_bridge). The registry never
                         dispatches and holds no callables, endpoints, or targets.

No provider calls. No network calls. No secrets stored. Truth-in-labeling: health
and availability default to "unknown" — the registry never claims a liveness it has
not been given.
"""
import dataclasses
import hmac
import os

from .schemas import VALID_RISK_LEVELS
from .capabilities import all_capability_profiles


# ── Governed descriptive enumerations (metadata only — never authority) ────────

# Descriptive lifecycle mirror. These label a worker; they do NOT grant execution.
LIFECYCLE_STATES = frozenset({
    "authored", "dormant", "active_dryrun", "active_sandboxed_local",
    "deprecated", "retired",
})
HEALTH_STATES        = frozenset({"unknown", "healthy", "degraded", "unavailable"})
AVAILABILITY_STATES  = frozenset({"unknown", "available", "unavailable"})
GOVERNANCE_STATUSES  = frozenset({"governed", "restricted", "quarantined"})

# Verbs a control-plane *registry* must never expose. A registry that could do any
# of these would be a dispatcher, not a description. Enforced by test.
FORBIDDEN_REGISTRY_CAPABILITIES = frozenset({
    "dispatch", "route", "execute", "invoke", "activate", "run", "handoff",
    "select", "resolve", "spawn", "call", "set_state", "can_execute", "deploy",
})

CONTROL_PLANE_VERSION = "1.0.0"


class ControlPlaneAuthError(PermissionError):
    """Raised when a caller is not authorized to read the control plane registry."""


# ── WorkerDescriptor — immutable curated metadata ──────────────────────────────

@dataclasses.dataclass(frozen=True)
class WorkerDescriptor:
    """
    Immutable descriptive record for one governed worker class.

    Carries identity, version, declared lifecycle/health/availability, capabilities,
    and governance posture — and deliberately NO endpoint, callable, or routing
    target. It describes a worker; it cannot be used to reach one.
    """
    worker_class: str
    display_name: str
    description: str
    version: str
    lifecycle_state: str
    governance_status: str
    modalities_supported: tuple
    allowed_request_types: tuple
    max_risk_level: str
    requires_human_approval: bool
    forbidden_tasks: tuple
    cost_class: str
    health: str = "unknown"
    availability: str = "unknown"

    def __post_init__(self):
        if not self.worker_class.strip():
            raise ValueError("worker_class must be non-empty")
        if self.lifecycle_state not in LIFECYCLE_STATES:
            raise ValueError(
                f"invalid lifecycle_state {self.lifecycle_state!r}; "
                f"must be one of {sorted(LIFECYCLE_STATES)}"
            )
        if self.governance_status not in GOVERNANCE_STATUSES:
            raise ValueError(
                f"invalid governance_status {self.governance_status!r}; "
                f"must be one of {sorted(GOVERNANCE_STATUSES)}"
            )
        if self.health not in HEALTH_STATES:
            raise ValueError(f"invalid health {self.health!r}; must be one of {sorted(HEALTH_STATES)}")
        if self.availability not in AVAILABILITY_STATES:
            raise ValueError(
                f"invalid availability {self.availability!r}; must be one of {sorted(AVAILABILITY_STATES)}"
            )
        if self.max_risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"invalid max_risk_level {self.max_risk_level!r}")
        # Enforce tuple (hashable, immutable) storage even if lists are passed in.
        object.__setattr__(self, "modalities_supported", tuple(self.modalities_supported))
        object.__setattr__(self, "allowed_request_types", tuple(self.allowed_request_types))
        object.__setattr__(self, "forbidden_tasks", tuple(self.forbidden_tasks))

    def to_public_dict(self) -> dict:
        """Audit-safe, JSON-serializable view for Operations (UI P2). Lists, not tuples."""
        return {
            "worker_class": self.worker_class,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "lifecycle_state": self.lifecycle_state,
            "governance_status": self.governance_status,
            "modalities_supported": list(self.modalities_supported),
            "allowed_request_types": list(self.allowed_request_types),
            "max_risk_level": self.max_risk_level,
            "requires_human_approval": self.requires_human_approval,
            "forbidden_tasks": list(self.forbidden_tasks),
            "cost_class": self.cost_class,
            "health": self.health,
            "availability": self.availability,
        }


# ── AuthorizedReader — the only surface that can read the catalogue ────────────

class _AuthorizedReader:
    """
    Read-only capability handle returned by ControlPlaneRegistry.authenticate().

    Exposes description queries only. It cannot mutate the registry and has no
    dispatch/route/execute surface — obtaining a reader authorizes reading, never
    acting on, the workers it describes.
    """
    __slots__ = ("_descriptors",)

    def __init__(self, descriptors: tuple):
        # descriptors is an already-frozen tuple of frozen WorkerDescriptors
        self._descriptors = descriptors

    def list_workers(self) -> tuple:
        return self._descriptors

    def describe(self, worker_class: str) -> WorkerDescriptor:
        for d in self._descriptors:
            if d.worker_class == worker_class:
                return d
        raise KeyError(
            f"no worker descriptor for {worker_class!r}; "
            f"known: {sorted(d.worker_class for d in self._descriptors)}"
        )

    def snapshot(self) -> dict:
        """Audit-safe snapshot for Operations. This is what UI P2 renders."""
        return {
            "governed_by": "abigail.cp00",
            "control_plane_version": CONTROL_PLANE_VERSION,
            "sealed": True,
            "worker_count": len(self._descriptors),
            "workers": [d.to_public_dict() for d in self._descriptors],
        }


# ── ControlPlaneRegistry ───────────────────────────────────────────────────────

class ControlPlaneRegistry:
    """
    Curated, sealed, authenticated, description-only registry of governed workers.

    Lifecycle: register(...) one or more descriptors during curation, then seal().
    After sealing, the catalogue is immutable and readable only via authenticate().
    """

    def __init__(self, access_token: str = None):
        # Optional injected server token (mainly for tests). When not injected,
        # authenticate() resolves the token from the environment, fail-closed.
        self._access_token = (access_token or "").strip() or None
        self._descriptors = {}
        self._sealed = False

    # -- curation (pre-seal only) ----------------------------------------------
    def register(self, descriptor: WorkerDescriptor) -> None:
        if self._sealed:
            raise ValueError("registry is sealed; curated metadata is immutable and cannot be added to")
        if not isinstance(descriptor, WorkerDescriptor):
            raise TypeError("register() accepts WorkerDescriptor only")
        if descriptor.worker_class in self._descriptors:
            raise ValueError(f"duplicate worker_class {descriptor.worker_class!r} in registry")
        self._descriptors[descriptor.worker_class] = descriptor

    def seal(self) -> "ControlPlaneRegistry":
        if self._sealed:
            raise ValueError("registry is already sealed")
        self._sealed = True
        return self

    @property
    def is_sealed(self) -> bool:
        return self._sealed

    # -- authenticated reading (post-seal only) --------------------------------
    def _server_token(self) -> str:
        return (
            os.environ.get("ABIGAIL_CONTROL_PLANE_TOKEN", "").strip()
            or os.environ.get("ABIGAIL_ADMIN_TOKEN", "").strip()
            or (self._access_token or "")
        )

    def authenticate(self, token: str) -> _AuthorizedReader:
        """
        Exchange a valid token for a read-only reader. Fail-closed:
          - unsealed registry            -> refuse (curation not finished)
          - no server token configured   -> refuse (misconfiguration)
          - missing / mismatched token   -> refuse
        Never reveals token contents or closeness.
        """
        if not self._sealed:
            raise ControlPlaneAuthError("control plane registry is not sealed; reads are refused")
        server_token = self._server_token()
        if not server_token:
            raise ControlPlaneAuthError("control plane access not configured: server token missing")
        client_token = (token or "").strip()
        if not client_token or not hmac.compare_digest(client_token, server_token):
            raise ControlPlaneAuthError("valid control plane access token required")
        # Freeze the read view: a tuple of frozen descriptors, stable ordering.
        descriptors = tuple(self._descriptors[k] for k in sorted(self._descriptors))
        return _AuthorizedReader(descriptors)


# ── Default curated registry (curated from the governed capability profiles) ────

def _describe_worker(worker_class: str) -> str:
    return worker_class.replace("_", " ").strip().capitalize() + " (governed worker class)"


def _display_name(worker_class: str) -> str:
    return worker_class.replace("_", " ").title()


def build_default_control_plane_registry(access_token: str = None) -> ControlPlaneRegistry:
    """
    Build and SEAL the default control plane registry, curated from the same
    capability profiles the broker uses to govern routing — one source of truth.

    lifecycle_state is "authored" and health/availability are "unknown" this sprint:
    the registry describes what exists; live status wiring is UI P2 / future work.
    """
    reg = ControlPlaneRegistry(access_token=access_token)
    for worker_class, profile in sorted(all_capability_profiles().items()):
        reg.register(WorkerDescriptor(
            worker_class=worker_class,
            display_name=_display_name(worker_class),
            description=_describe_worker(worker_class),
            version=CONTROL_PLANE_VERSION,
            lifecycle_state="authored",
            governance_status="governed",
            modalities_supported=tuple(profile.modalities_supported),
            allowed_request_types=tuple(profile.allowed_request_types),
            max_risk_level=profile.max_risk_level,
            requires_human_approval=profile.requires_human_approval,
            forbidden_tasks=tuple(profile.forbidden_tasks),
            cost_class=profile.cost_class,
            health="unknown",
            availability="unknown",
        ))
    return reg.seal()
