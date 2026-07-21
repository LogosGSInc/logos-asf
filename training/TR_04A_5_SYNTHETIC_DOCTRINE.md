# TR-04A.5: Synthetic Doctrine Generator

**Version**: 1.0.0  
**Status**: Implemented  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Requires**: TR-04A.3 (source_registry.py), TR-04A.4 (clearance_ledger.py)  
**Not implemented here**: Real Ed25519 signing (future TR-04A.4 hardening), AWS S3 Object Lock, TR-05

---

## What TR-04A.5 Does

`training/synthetic_doctrine.py` is a deterministic local-only synthetic
instruction example generator that is seeded **only from approved Lane 1
LOGOS-owned doctrine sources**. It requires both the Training Source Registry
(TR-04A.3) and the Clearance Ledger (TR-04A.4) to clear before any record is
produced.

Every generated record is labeled `synthetic_origin=true` and
`training_allowed=false`. Generated examples are **candidates only** — they
require operator review before any SFT use. No real training occurs here.

---

## Owned Data Only

All synthetic records are generated from governed templates derived from
LOGOS-owned doctrine. The generator **does not**:

- Call any external LLM, API, or provider SDK
- Ingest Common Pile, Common Crawl, RedPajama, Stack Exchange, PMC, NIST, or
  any remote corpus
- Make any network call
- Access any file outside the repository's training directory

The templates encode representative instruction patterns for each category
(routing, refusal, clarification, tool approval, etc.) without exposing:

- Raw red-team vectors or attack payloads
- Private governance thresholds
- Secrets, credentials, API keys, or personal data
- Real user transcripts

---

## Allowed Source IDs

Only Lane 1 approved doctrine sources whose `allowed_uses` includes
`"synthetic_seed"` may be used:

| Source ID | Name | Allowed for synthetic_seed |
|-----------|------|--------------------------|
| L1-001 | Buildspec Volumes I, II, III | Yes |
| L1-003 | Agent Position Specs JSON IR | Yes |
| L1-005 | HAAP Constitutional Bounds | Yes |
| L1-006 | Volume III Amendment Layer | Yes |

**Why is L1-004 excluded?** L1-004 (Sentinel Red Team Results and AARs) has
`allowed_uses: ["rag", "evaluation_reference"]`. It does not include
`"synthetic_seed"`. The registry clearance state machine enforces this: any
attempt to generate from L1-004 with `synthetic_seed` fails at the registry
gate with `SourceNotAllowedError`.

**Why is L1-007 not a generation source?** L1-007 (Synthetic Instruction Data)
is the **output** registry entry for generator batches. Its `allowed_uses` are
`["sft_candidate", "evaluation_reference"]` — it does not have `"synthetic_seed"`
because it is what the generator produces, not what it reads from.

**L2-L7 sources are never eligible** — they are either pending, blocked, or
restricted to `rag` and `evaluation_reference` uses.

---

## prompt_hash and generation_agent_id

Each record carries two audit-replay fields:

**`prompt_hash`**: SHA-256[:32] of `"{prompt_template_id}:{input}"`. This is
stable across runs for the same template and input. Changing the template
content changes the hash. This enables exact audit replay of any record.

**`generation_agent_id`**: The identifier of the automated process that ran
the generator (default: `SYNTH_DOCTRINE_LOCAL_001`). It is embedded in every
record and also drives `record_id` derivation. Two batches run with different
agent IDs on the same source and limit will produce identical `prompt_hash`
values but different `record_id` values.

**`record_id`**: `"SR-" + SHA-256(source_id:agent_id:template_id:index)[:16]`.
Stable for identical inputs; changes when any of the four inputs change.

---

## Registry + Ledger Gating

The generator enforces a two-gate check before producing any record:

**Gate 1 — Source Registry (TR-04A.3)**  
`assert_source_allowed(source_id, "synthetic_seed", registry_path)` must pass:
- Source exists in the registry
- `registry_status == "approved"`
- `"synthetic_seed"` is in `allowed_uses`
- `sha256_manifest` is present
- `hp_decision_status` is `"approved"` or `"not_required"`

**Gate 2 — Clearance Ledger (TR-04A.4)**  
The ledger must contain at least one approval-type decision (`hp_approve`,
`reg01_clear`, `lgl01_clear`, or `ea00_batch`) for the source that has not
been superseded by a later `block`, `hp_reject`, `reg01_reject`,
`lgl01_reject`, or `archive` decision. The ledger's SHA-256 hash chain must
be intact.

If either gate fails, the generator exits with nonzero status and produces
no output files. The clearance ledger path is **mandatory** — there is no
bypass (unlike the dry-run trainer's `allow_unregistered_source_for_tests`,
which is a test-only trainer-side bypass and does not exist in this generator).

---

## Synthetic Categories

The generator produces examples across eight instruction categories:

| Category | What it models |
|----------|---------------|
| `user_request_to_abigail_route_decision` | User query → Abigail routing decision |
| `user_request_to_sentinel_overwatch_posture` | Operator request → Sentinel posture update |
| `unsafe_request_to_governed_refusal_with_haap_citation` | Prohibited request → HAAP-cited refusal |
| `ambiguous_request_to_clarification_or_safe_best_effort` | Ambiguous input → clarification prompt |
| `tool_request_to_approval_gate` | Elevated tool use → approval gate issuance |
| `operator_directive_to_ea00_acknowledgment_and_routing` | EA-00 directive → acknowledgment and queue |
| `dataset_manifest_to_accept_or_reject_explanation` | Dataset manifest → accept/reject with reason |
| `provider_route_request_to_audit_safe_envelope` | Provider route request → audit envelope |

Records cycle through categories deterministically. With a limit of 8 (one
cycle), each category appears exactly once. With a limit of 16 (two cycles),
each appears twice with its second template variant.

---

## Generated Examples Are Candidates Only

Generated records carry hard governance labels enforced at both code and schema
level:

```json
{
  "training_allowed": false,
  "operator_review_required": true,
  "store1_write_allowed": false,
  "runtime_deployment_allowed": false,
  "model_promotion_allowed": false,
  "external_calls_allowed": false
}
```

These constants are `const` values in `SYNTHETIC_DOCTRINE_RECORD.schema.json`.
They cannot be overridden by any CLI argument or programmatic call.

Operator review is required before any SFT use. The generated JSONL is written
as a candidate batch to an explicit `out_dir` outside the repository. No record
is promoted to Store 1 or any training dataset without a separate operator
review gate.

---

## No Real Training

TR-04A.5 performs no real training. It does not:

- Create or modify model weights
- Create LoRA or QLoRA adapters
- Submit a training job to any infrastructure
- Upload data to any external system
- Write to Store 1
- Deploy to the runtime
- Promote any model to the registry
- Call any external provider SDK

TR-05 (Model Registry and Lineage) was not started here.

---

## Output Artifacts

All artifacts are written to `--out-dir` (which must be outside the repository).

| File | Description |
|------|-------------|
| `synthetic_records.jsonl` | One synthetic record per line (compact JSON) |
| `synthetic_manifest.json` | Metadata: generator version, agent ID, source ID, ledger entry ID, record count, governance flags |
| `checksums.sha256` | SHA-256 checksums of the JSONL and manifest files |

---

## CLI Commands

```bash
# Generate 8 records from L1-001 with the fixture ledger
python3 training/synthetic_doctrine.py \
  --source-id L1-001 \
  --clearance-ledger training/tests/fixtures/clearance_ledger_valid_fixture.json \
  --out-dir /tmp/synthetic_demo \
  --limit 8 \
  --generation-agent-id SYNTH_DOCTRINE_LOCAL_001

# Generate 8 records from L1-006 with a production ledger
python3 training/synthetic_doctrine.py \
  --source-id L1-006 \
  --clearance-ledger /path/to/production_clearance_ledger.json \
  --out-dir /tmp/synthetic_l1006 \
  --limit 8 \
  --generation-agent-id SYNTH_DOCTRINE_LOCAL_001
```

---

## Validation Commands

```bash
python3 -m py_compile training/synthetic_doctrine.py

python3 -m pytest -q training/tests/test_synthetic_doctrine.py

python3 -m pytest -q training/tests/

python3 -m pytest -q
```

---

## Schema

`training/SYNTHETIC_DOCTRINE_RECORD.schema.json` — JSON Schema draft 2020-12

`$id`: `logos-asf:training:synthetic-doctrine-record:v1.0.0`

Required fields (15): `record_id`, `schema_version`, `created_at`,
`synthetic_origin`, `source_id`, `source_registry_version`,
`clearance_ledger_entry_id`, `generation_agent_id`, `prompt_template_id`,
`prompt_hash`, `category`, `input`, `desired_output`, `governance_labels`,
`audit_metadata`.

---

## Governance Attestation

No real training occurred in TR-04A.5. All generated records carry
`training_allowed: false` and `operator_review_required: true`. No model
weights were created. No Store 1 writes occurred. No external calls were made.
Operator review is required before any SFT use of generated candidates.
TR-05 was not started.
