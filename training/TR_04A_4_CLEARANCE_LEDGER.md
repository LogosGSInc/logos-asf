# TR-04A.4: Source Clearance Ledger

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-26  
**Requires**: TR-04A.3 (source_registry.py)  
**Not implemented here**: Real Ed25519 signing (TR-04A.5), AWS S3 Object Lock, synthetic_doctrine.py (TR-04A.5), TR-05

---

## What TR-04A.4 Does

`training/clearance_ledger.py` is the local append-only decision ledger for
training source clearance. It records every transition in a source's approval
status — nomination, REG-01 review, LGL-01 review, EA-00 batch review, HP
approval, rejection, block, or archive — as a SHA-256 hash-chained entry.

The ledger enforces a tamper-evident audit trail: changing any field in any
prior entry, reordering entries, or splicing entries invalidates the chain.

**This is a local file-based ledger.** AWS S3 Object Lock (WORM infrastructure)
is a future deployment concern and is not implemented here.

---

## Hash Chain Design

Every ledger entry includes two hash fields:

```
previous_entry_hash  — SHA-256 of the preceding entry (or 0×64 for genesis)
entry_hash           — SHA-256 of the current entry, excluding entry_hash
                       and signature_value
```

The `entry_hash` is computed over the canonical JSON of the entry with keys
sorted and no whitespace — identical to `hash_entry(entry)`. It covers
`previous_entry_hash`, so any change to any field in any prior entry cascades
forward and breaks validation.

**Tamper detection guarantees:**

| Attack | Detection |
|--------|-----------|
| Mutate any field (e.g. `decision_reason`) | `entry_hash` mismatch at that entry |
| Mutate `previous_entry_hash` directly | `entry_hash` mismatch (field is covered) + chain mismatch |
| Reorder entries | `previous_entry_hash` mismatch at the first displaced entry |
| Remove an entry | `previous_entry_hash` mismatch at the entry that followed it |
| Insert a forged entry | `previous_entry_hash` mismatch at the entry after it |

`validate_ledger()` stops and reports the first failing entry, including its
index, entry ID, and the specific check that failed.

---

## Ed25519 Signature Fields

Every entry carries three signature fields:

```json
"signature_status":        "unsigned_local",
"signature_algorithm":     "ed25519_placeholder",
"signature_public_key_id": null,
"signature_value":         null
```

These are **interface placeholders only**. No private keys are generated or
used in TR-04A.4. The hash chain operates independently of signing.

Real Ed25519 signing is TR-04A.5 (synthetic_doctrine.py is also TR-04A.5).

`signature_value` is excluded from `entry_hash` computation so that adding a
signature to an existing entry does not break the chain.

---

## Clearance State Machine

The ledger tracks decisions that correspond to the source registry clearance
pipeline:

```
nominate        → draft
reg01_clear     → reg01 gate passed
reg01_reject    → reg01 gate denied
lgl01_clear     → lgl01 gate passed
lgl01_reject    → lgl01 gate denied
ea00_batch      → EA-00 architecture batch approved
hp_approve      → Human Principal final approval
hp_reject       → Human Principal denial
block           → Emergency or permanent block
archive         → Source retired/sunset
restore         → Re-entry after archive (requires new HP approval)
```

For clearance purposes, `hp_approve`, `reg01_clear`, `lgl01_clear`, and
`ea00_batch` are **approval-type** decisions. `block`, `hp_reject`,
`reg01_reject`, `lgl01_reject`, and `archive` are **blocking** decisions.

A blocking decision with a timestamp ≥ the most recent approval supersedes
that approval. A new approval after a block restores clearance.

---

## REG-01, LGL-01, EA-00, and HP Decision Relationship

Each ledger entry records the gate statuses at the time of the decision:

```json
"reg01_status":       "approved",
"lgl01_status":       "approved",
"hp_decision_status": "approved"
```

The ledger does not enforce gate sequencing — that is the source registry's
concern. The ledger is a neutral audit record: it records what was decided and
by whom, independent of whether all upstream gates were satisfied.

Human Principal decisions (`actor_role: "human_principal"`, `actor_id: "DWS-001"`)
carry the highest authority. An HP block overrides any prior state.

---

## Source Registry Bridge

`source_registry.assert_source_allowed_with_ledger(source_id, requested_use,
registry_path=None, ledger_path=None)` adds an optional second gate:

```
Gate 1 (TR-04A.3): registry_status == approved, use in allowed_uses, HP gate passed
Gate 2 (TR-04A.4): ledger contains valid approval entry, not superseded by block
```

If `ledger_path` is `None`, the function behaves identically to
`assert_source_allowed` — no existing tests need to change.

**The dry-run trainer (TR-04) does not require a ledger yet.** That bridge
comes after TR-04A.4 validation is proven. Making the ledger mandatory for
`dry_run_trainer.py` is the TR-04B gate upgrade.

---

## Public API

```python
from clearance_ledger import (
    create_empty_ledger,          # create_empty_ledger(authority) → dict
    load_ledger,                  # load_ledger(path) → dict
    save_ledger,                  # save_ledger(ledger, path)
    append_decision,              # append_decision(ledger, decision) → entry
    validate_ledger,              # validate_ledger(ledger) → {"valid": True, ...}
    hash_entry,                   # hash_entry(entry) → hex64
    find_entries_for_source,      # find_entries_for_source(ledger, source_id) → list
    assert_clearance_entry_exists,# assert_clearance_entry_exists(ledger, source_id) → entry
    summarize_ledger,             # summarize_ledger(ledger) → audit-safe dict
)

from source_registry import (
    assert_source_allowed_with_ledger,  # two-gate check (registry + ledger)
)
```

---

## Validation Commands

```bash
python3 -m py_compile training/clearance_ledger.py training/source_registry.py

python3 -m pytest -q training/tests/test_clearance_ledger.py

python3 -m pytest -q training/tests/test_source_registry.py

python3 -m pytest -q training/tests/test_dry_run_trainer.py

python3 -m pytest -q
```

---

## What Is Not Implemented

**Real Ed25519 signing**: `signature_value` is null for all entries. The
signing interface is defined (`signature_algorithm`, `signature_public_key_id`,
`signature_value`) but no private key is generated or used. Real signing is
TR-04A.5.

**AWS S3 Object Lock / WORM**: The ledger is a local JSON file. Immutability
in production will require S3 Object Lock or equivalent WORM storage. That is
future infrastructure, not a code deliverable.

**synthetic_doctrine.py**: Not implemented. That is TR-04A.5.

**TR-05 — Model registry and lineage**: Not started.

---

## Governance Attestation

No real training occurred in this phase. TR-04A.4 adds an audit ledger layer
only. All TR-04 governance invariants (`training_allowed: false`, etc.) remain
unchanged. The dry-run trainer continues to operate without a required ledger
path until TR-04B is upgraded.
