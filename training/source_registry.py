"""
LOGOS ASF — TR-04A.3 Training Source Registry Validator v1.0.0
LOGOS Governance Systems Inc.

Machine-enforceable validator for SOURCE_REGISTRY.schema.json and
source_registry_seed.json. Implements the clearance state machine that
gates all TR-04B dry-run training inputs.

No source may enter TR-04B unless:
  - It exists in this registry (registry presence)
  - registry_status == "approved"
  - The requested use is listed in allowed_uses
  - sha256_manifest is present and non-empty
  - hp_decision_status is "approved" or "not_required"
  - A clearance ledger entry exists (TR-04A.4, not implemented here)

clearance_ledger.json and Ed25519 signing are TR-04A.4/TR-04A.5 and are
not implemented in this module.
"""
import json
from pathlib import Path

# Default registry — training/source_registry_seed.json relative to this file
_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent / "source_registry_seed.json"

# ── controlled value sets (mirrors SOURCE_REGISTRY.schema.json) ───────────────

VALID_REGISTRY_STATUSES = frozenset({
    "draft", "reg01_pending", "lgl01_pending", "ea00_pending", "hp_pending",
    "approved", "rejected", "archived", "blocked",
})
VALID_ALLOWED_USES = frozenset({
    "rag", "sft_candidate", "synthetic_seed",
    "evaluation_reference", "pretraining_candidate",
})
VALID_CLEARANCE_STATUSES = frozenset({
    "not_required", "pending", "approved", "rejected", "blocked",
})
VALID_PII_RISKS       = frozenset({"none", "low", "medium", "high", "blocked"})
VALID_COPYRIGHT_RISKS = frozenset({"none", "low", "medium", "high", "blocked", "uncertain"})
VALID_DRIFT_RISKS     = frozenset({"low", "medium", "high", "blocked"})
VALID_LANES           = frozenset({1, 2, 3, 4, 5, 6, 7})

USABLE_STATUSES  = frozenset({"approved"})
TERMINAL_STATUSES = frozenset({"rejected", "archived", "blocked"})
PENDING_STATUSES  = frozenset({
    "draft", "reg01_pending", "lgl01_pending", "ea00_pending", "hp_pending",
})

# Clearance values that satisfy a gate
PASSED_CLEARANCE = frozenset({"approved", "not_required"})

REQUIRED_TOP_LEVEL_FIELDS = frozenset({
    "registry_id", "version", "effective_date", "classification",
    "authority", "constitutional_constraint", "entries",
})
REQUIRED_ENTRY_FIELDS = frozenset({
    "source_id", "source_name", "source_type", "lane", "license_family",
    "commercial_use_allowed", "requires_attribution", "sharealike_risk",
    "no_derivatives_risk", "pii_risk", "copyright_risk", "registry_status",
    "allowed_uses", "reg01_status", "lgl01_status", "hp_decision_status",
    "hp_decision_timestamp", "license_evidence_uri", "license_checked_at",
    "license_checked_by", "component_whitelist", "drift_risk_level",
    "requires_operator_approval", "sha256_manifest", "govmem_namespace", "notes",
})


# ── exceptions ────────────────────────────────────────────────────────────────

class SourceRegistryError(Exception):
    """Base class for all source registry errors."""

class SourceNotFoundError(SourceRegistryError):
    """Raised when a source_id is not present in the registry."""

class SourceNotAllowedError(SourceRegistryError):
    """Raised when a source is registered but not cleared for the requested use."""

class SourceBlockedError(SourceRegistryError):
    """Raised when a source is permanently blocked, rejected, or archived."""

class RegistryValidationError(SourceRegistryError):
    """Raised when the registry document itself is malformed or inconsistent."""


# ── registry class ────────────────────────────────────────────────────────────

class SourceRegistry:
    """
    Loads and validates a source registry JSON document, then enforces
    the clearance state machine for TR-04B pipeline gating.
    """

    def __init__(self, registry_path=None):
        self._path = Path(registry_path) if registry_path else _DEFAULT_REGISTRY_PATH
        self._data = None
        self._entries = None  # dict keyed by source_id

    def _ensure_loaded(self):
        if self._data is None:
            self.load()

    def load(self):
        if not self._path.exists():
            raise RegistryValidationError(
                f"Registry file not found: {self._path}"
            )
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RegistryValidationError(
                f"Registry file is not valid JSON: {e}"
            )
        # Index entries by source_id for O(1) lookup
        raw_entries = self._data.get("entries", [])
        self._entries = {}
        for entry in raw_entries:
            sid = entry.get("source_id")
            if sid:
                self._entries[sid] = entry
        return self

    # ── validation ────────────────────────────────────────────────────────────

    def validate_registry(self) -> dict:
        """
        Full structural and invariant validation of the registry document.
        Returns a summary dict on success. Raises RegistryValidationError on failure.
        """
        self._ensure_loaded()
        errors = []

        # Top-level required fields
        for field in sorted(REQUIRED_TOP_LEVEL_FIELDS):
            if field not in self._data:
                errors.append(f"missing top-level field: {field!r}")

        entries = self._data.get("entries", [])
        if not isinstance(entries, list) or len(entries) == 0:
            errors.append("entries must be a non-empty array")
            if errors:
                raise RegistryValidationError(
                    "Registry validation failed:\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )

        seen_ids: set = set()
        for i, entry in enumerate(entries):
            eid = entry.get("source_id", f"<entry[{i}]>")

            # Required fields
            for field in sorted(REQUIRED_ENTRY_FIELDS):
                if field not in entry:
                    errors.append(f"{eid}: missing required field {field!r}")

            # Unique source_id
            if eid in seen_ids:
                errors.append(f"duplicate source_id: {eid!r}")
            seen_ids.add(eid)

            # Lane / source_id prefix consistency
            lane = entry.get("lane")
            if isinstance(lane, int):
                if lane not in VALID_LANES:
                    errors.append(f"{eid}: invalid lane value {lane}")
                expected_prefix = f"L{lane}-"
                if not eid.startswith(expected_prefix):
                    errors.append(
                        f"{eid}: source_id prefix does not match lane {lane} "
                        f"(expected prefix {expected_prefix!r})"
                    )

            # Controlled enum: registry_status
            reg_status = entry.get("registry_status")
            if reg_status and reg_status not in VALID_REGISTRY_STATUSES:
                errors.append(f"{eid}: invalid registry_status {reg_status!r}")

            # Controlled enum: allowed_uses
            for use in entry.get("allowed_uses", []):
                if use not in VALID_ALLOWED_USES:
                    errors.append(f"{eid}: invalid allowed_use {use!r}")

            # Controlled enum: clearance statuses
            for clearance_field in ("reg01_status", "lgl01_status", "hp_decision_status"):
                val = entry.get(clearance_field)
                if val and val not in VALID_CLEARANCE_STATUSES:
                    errors.append(f"{eid}: invalid {clearance_field} {val!r}")

            # Controlled enum: risk levels
            for risk_field, valid_set in (
                ("pii_risk",       VALID_PII_RISKS),
                ("copyright_risk", VALID_COPYRIGHT_RISKS),
                ("drift_risk_level", VALID_DRIFT_RISKS),
            ):
                val = entry.get(risk_field)
                if val and val not in valid_set:
                    errors.append(f"{eid}: invalid {risk_field} {val!r}")

            # Approved entries: clearance gates must be satisfied
            if reg_status == "approved":
                for clearance_field in ("reg01_status", "lgl01_status", "hp_decision_status"):
                    val = entry.get(clearance_field, "")
                    if val not in PASSED_CLEARANCE:
                        errors.append(
                            f"{eid}: registry_status=approved but "
                            f"{clearance_field}={val!r} (must be approved or not_required)"
                        )
                if entry.get("hp_decision_status") == "approved":
                    if not entry.get("hp_decision_timestamp"):
                        errors.append(
                            f"{eid}: hp_decision_status=approved but "
                            "hp_decision_timestamp is null or missing"
                        )

            # Blocked entries: allowed_uses must be empty
            if reg_status == "blocked":
                if entry.get("allowed_uses"):
                    errors.append(
                        f"{eid}: blocked source must have allowed_uses=[]"
                    )

            # Synthetic sources must declare synthetic_origin=true
            if entry.get("source_type") == "synthetic_instruction_data":
                if entry.get("synthetic_origin") is not True:
                    errors.append(
                        f"{eid}: source_type=synthetic_instruction_data "
                        "requires synthetic_origin=true"
                    )

        if errors:
            raise RegistryValidationError(
                f"Registry validation failed with {len(errors)} error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        return {
            "valid": True,
            "entry_count": len(entries),
            "unique_ids": len(seen_ids),
        }

    # ── public API ────────────────────────────────────────────────────────────

    def get_source(self, source_id: str) -> dict:
        """Return the registry entry for source_id. Raises SourceNotFoundError if absent."""
        self._ensure_loaded()
        entry = self._entries.get(source_id)
        if entry is None:
            raise SourceNotFoundError(
                f"Source {source_id!r} is not registered in the training source "
                "registry. All training sources must be registered before use."
            )
        return entry

    def list_sources(self, status: str = None, lane: int = None) -> list:
        """Return registry entries, optionally filtered by status and/or lane."""
        self._ensure_loaded()
        results = list(self._entries.values())
        if status is not None:
            results = [e for e in results if e.get("registry_status") == status]
        if lane is not None:
            results = [e for e in results if e.get("lane") == lane]
        return results

    def assert_source_allowed(self, source_id: str, requested_use: str) -> dict:
        """
        Assert that source_id is cleared for requested_use.

        Clearance state machine:
          BLOCKED/REJECTED/ARCHIVED → SourceBlockedError (permanently closed)
          PENDING (any sub-status)  → SourceNotAllowedError (clearance incomplete)
          APPROVED but use absent   → SourceNotAllowedError (use not declared)
          APPROVED but HP not done  → SourceNotAllowedError (HP gate not passed)
          APPROVED, use allowed     → returns clearance record dict

        Raises:
          SourceNotFoundError   if source_id is unknown
          SourceBlockedError    if source is permanently blocked/rejected/archived
          SourceNotAllowedError if clearance is incomplete or use is disallowed
        """
        # 1. Validate requested_use
        if requested_use not in VALID_ALLOWED_USES:
            raise SourceNotAllowedError(
                f"requested_use={requested_use!r} is not a recognized use. "
                f"Valid values: {sorted(VALID_ALLOWED_USES)}"
            )

        # 2. Source must exist
        entry = self.get_source(source_id)
        reg_status = entry.get("registry_status", "")
        source_name = entry.get("source_name", "")

        # 3. Permanently terminal statuses
        if reg_status == "blocked":
            raise SourceBlockedError(
                f"Source {source_id!r} ({source_name!r}) is BLOCKED. "
                "It may not be used for any training pipeline purpose."
            )
        if reg_status in ("rejected", "archived"):
            raise SourceBlockedError(
                f"Source {source_id!r} ({source_name!r}) has "
                f"registry_status={reg_status!r} and may not be used."
            )

        # 4. Pending clearance states
        if reg_status in PENDING_STATUSES:
            raise SourceNotAllowedError(
                f"Source {source_id!r} ({source_name!r}) has "
                f"registry_status={reg_status!r}. Clearance is not complete. "
                "This source may not enter TR-04B until all gates are passed."
            )

        # 5. Must be explicitly approved
        if reg_status != "approved":
            raise SourceNotAllowedError(
                f"Source {source_id!r} has registry_status={reg_status!r}. "
                "Only approved sources may enter TR-04B."
            )

        # 6. Requested use must be declared in allowed_uses
        allowed = entry.get("allowed_uses", [])
        if requested_use not in allowed:
            raise SourceNotAllowedError(
                f"Source {source_id!r} ({source_name!r}) does not permit "
                f"requested_use={requested_use!r}. "
                f"Allowed uses for this source: {allowed}"
            )

        # 7. sha256_manifest must be present and non-empty
        sha_manifest = entry.get("sha256_manifest", "")
        if not sha_manifest:
            raise SourceNotAllowedError(
                f"Source {source_id!r} has no sha256_manifest. "
                "A content hash or sentinel is required before the source "
                "can enter TR-04B."
            )

        # 8. HP decision gate
        hp_status = entry.get("hp_decision_status", "")
        if hp_status not in PASSED_CLEARANCE:
            raise SourceNotAllowedError(
                f"Source {source_id!r} has hp_decision_status={hp_status!r}. "
                "hp_decision_status must be 'approved' or 'not_required'."
            )
        if hp_status == "approved" and not entry.get("hp_decision_timestamp"):
            raise SourceNotAllowedError(
                f"Source {source_id!r} has hp_decision_status=approved but "
                "hp_decision_timestamp is null. HP approval timestamp is required."
            )

        # All gates passed
        return {
            "source_id":      source_id,
            "source_name":    source_name,
            "requested_use":  requested_use,
            "registry_status": reg_status,
            "cleared":        True,
            "sha256_manifest": sha_manifest,
        }

    def build_registry_summary(self) -> dict:
        """Return an audit-safe summary of registry state. No raw source content."""
        self._ensure_loaded()
        entries = list(self._entries.values())

        by_status: dict = {}
        for e in entries:
            s = e.get("registry_status", "unknown")
            by_status.setdefault(s, []).append(e["source_id"])

        return {
            "registry_id":    self._data.get("registry_id"),
            "version":        self._data.get("version"),
            "effective_date": self._data.get("effective_date"),
            "total_entries":  len(entries),
            "approved_count": sum(1 for e in entries
                                  if e.get("registry_status") == "approved"),
            "pending_count":  sum(1 for e in entries
                                  if e.get("registry_status") in PENDING_STATUSES),
            "blocked_count":  sum(1 for e in entries
                                  if e.get("registry_status") == "blocked"),
            "rejected_count": sum(1 for e in entries
                                  if e.get("registry_status") == "rejected"),
            "by_status": {
                status: {"count": len(ids), "source_ids": sorted(ids)}
                for status, ids in sorted(by_status.items())
            },
        }


# ── module-level convenience functions ────────────────────────────────────────

def get_source(source_id: str, registry_path=None) -> dict:
    return SourceRegistry(registry_path).load().get_source(source_id)


def list_sources(status: str = None, lane: int = None, registry_path=None) -> list:
    return SourceRegistry(registry_path).load().list_sources(status=status, lane=lane)


def validate_registry(registry_path=None) -> dict:
    return SourceRegistry(registry_path).load().validate_registry()


def assert_source_allowed(source_id: str, requested_use: str,
                           registry_path=None) -> dict:
    return SourceRegistry(registry_path).load().assert_source_allowed(
        source_id, requested_use
    )


def build_registry_summary(registry_path=None) -> dict:
    return SourceRegistry(registry_path).load().build_registry_summary()
