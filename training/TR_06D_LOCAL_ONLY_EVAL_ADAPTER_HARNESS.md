# TR-06D: Local-Only Evaluation Adapter Harness

**Version**: 1.0.0  
**Status**: Implemented (deterministic stub execution only — no real inference)  
**Authority**: LOGOS Governance Systems Inc.  
**Effective Date**: 2026-06-27  
**Requires**: TR-06C (live_eval_interface.py, LIVE_EVALUATION_PLAN.schema.json)  
**Not implemented here**: Real model inference, local model runtimes, provider execution, model training, model promotion, deployment, TR-07

---

## What TR-06D Creates

1. **`training/LIVE_EVALUATION_EXECUTION_REPORT.schema.json`** — typed contract for the result of executing a live eval plan against a stub adapter.
2. **`training/local_eval_adapter_harness.py`** — execution plumbing with deterministic stub adapter, blocked-provider gate, report builder, and save/summarize API.
3. **`training/tests/test_local_eval_adapter_harness.py`** — 104-test suite covering adapter blocking, stub behavior, report invariants, and module purity.
4. **`training/TR_06D_LOCAL_ONLY_EVAL_ADAPTER_HARNESS.md`** — this document.

TR-06D provides the harness shape. It proves the adapter interface, execution record format, and blocked-provider posture before any real local model connector exists.

---

## Architecture Position

```
TR-06A Metadata Evaluation Harness
  ↓
TR-06B Metadata Evaluation Fixtures
  ↓
TR-06C Live Behavioral Eval Interface (plans, disabled executor)
  ↓
TR-06D Local-Only Adapter Harness (this)   ← stub execution only
  ↓
[future: operator-approved local model adapter]  ← real local inference, separate phase
  ↓
TR-07 Shadow/Canary                              ← NOT started here
```

---

## What TR-06D Is and Is Not

| Is | Is Not |
|---|---|
| Execution plumbing for TR-06C plans | Real model inference |
| Deterministic stub adapter execution path | Local model runtime execution (Ollama, vLLM, llama.cpp) |
| Typed execution report layer | Provider execution |
| Hard block against real provider/model adapters | Model training |
| Bridge between TR-06C plans and future real adapters | Model promotion |
| | Deployment |
| | TR-07 shadow/canary |

---

## Deterministic Stub Adapter

The stub adapter (`TR06D_STUB_ADAPTER_001`) produces fixed synthetic responses keyed on `(live_eval_case_id, case_category)`. It does not load, call, or simulate any real model.

**Every stub response carries the disclaimer:**
```
DETERMINISTIC_STUB_OUTPUT_NOT_MODEL_BEHAVIOR
```

This disclaimer is required in every `case_result.disclaimer` field and is enforced by `validate_execution_report`. Its purpose is to prevent any downstream system from interpreting stub results as evidence of actual model behavior.

### Stub result map

| `case_category` | Result |
|---|---|
| `constitutional_fidelity` | `stub_pass` — governance rails confirmed active |
| `haap_refusal_behavior` | `stub_pass` — HAAP-pattern refusal confirmed |
| `routing_correctness` | `stub_pass` — intent labeled, no capability inflation |
| `audit_safe_json_ir_output` | `stub_pass` — JSON-shaped output, no leak |
| `store1_govmem_boundary_preservation` | `stub_pass` — no Store 1 write confirmed |
| `promotion_blocking_invariants` | `stub_block` if "promotion" in prompt, else `stub_pass` |
| Any other category | `not_evaluated` |

Stub responses are deterministic: same `(case_id, category, response_text)` always produces the same `stub_response_hash`.

---

## Blocked Provider and Runtime Adapters

`assert_real_adapter_blocked(adapter_config)` raises `LocalEvalAdapterBlockedError` if the adapter config's serialized JSON contains any blocked keyword or references a non-stub adapter type.

**Blocked keywords (substring match against serialized config):**
`openai`, `anthropic`, `gemini`, `groq`, `xai`, `huggingface`, `ollama`, `vllm`, `llama_cpp`, `llama.cpp`, `together`, `mistral`, `cohere`, `replicate`, `bedrock`, `azure_openai`, `gpt`, `claude`, `http://`, `https://`, `localhost:`, `127.0.0.1`, `0.0.0.0`, `subprocess`

**Blocked adapter types:** any `adapter_type` other than `"deterministic_stub"`.

`execute_plan_with_stub_adapter` calls `assert_real_adapter_blocked` on every adapter before execution. A plan using a real provider adapter will be rejected before any case runs.

---

## Execution Report Schema

`LIVE_EVALUATION_EXECUTION_REPORT.schema.json` (draft 2020-12) defines 20 required fields with the following hard constants:

| Field | Value in TR-06D |
|---|---|
| `real_model_inference_performed` | const `false` |
| `provider_calls_performed` | const `false` |
| `model_weights_loaded` | const `false` |
| `promotion_blocked` | const `true` |
| `promotion_decision_emitted` | const `false` |
| `operator_review_required` | const `true` |
| `requires_live_inference` | const `true` (plans come from TR-06C) |
| `adapter_type` | enum: `deterministic_stub`, `blocked_provider`, `blocked_local_runtime` |
| `execution_status` | enum: `completed_stub_execution`, `blocked`, `failed_validation` |

**Execution report ID:** `XR-<sha256[:16]>`, deterministic for the same `(plan_id, sorted case result hashes)`.

**Per-case result fields:** `live_eval_case_id`, `case_category`, `result`, `stub_response_hash`, `rubric_reference`, `disclaimer`, `notes`.

**Per-case result enum:** `stub_pass`, `stub_fail`, `stub_block`, `not_evaluated`, `blocked`.

---

## Public API

```python
from training.local_eval_adapter_harness import (
    build_deterministic_stub_adapter,
    validate_plan_for_stub_execution,
    execute_plan_with_stub_adapter,
    build_execution_report,
    validate_execution_report,
    save_execution_report,
    summarize_execution_report,
    assert_real_adapter_blocked,
    LocalEvalAdapterBlockedError,
    LocalEvalPlanRejectedError,
    LocalEvalReportValidationError,
)
from training.live_eval_interface import (
    build_default_cases_for_candidate,
    build_live_eval_plan,
    load_live_eval_plan,
)

# Build and execute a plan
cases = build_default_cases_for_candidate("MA-abc123")
plan = build_live_eval_plan("MA-abc123", cases)

adapter = build_deterministic_stub_adapter()     # no model loaded
report = execute_plan_with_stub_adapter(plan, adapter=adapter, out_dir="/tmp/tr06d")
# writes /tmp/tr06d/live_evaluation_execution_report.json
# writes /tmp/tr06d/checksums.sha256

# Summarize
summary = summarize_execution_report(report)
# {
#   "execution_status": "completed_stub_execution",
#   "adapter_type": "deterministic_stub",
#   "by_result": {"stub_pass": 5, "not_evaluated": 1},
#   "real_model_inference_performed": False,
#   "promotion_blocked": True,
#   ...
# }

# Load a plan and run against stub
plan = load_live_eval_plan("/tmp/lp_abc.json")
report = execute_plan_with_stub_adapter(plan)

# Assert a config is blocked (real adapter check)
try:
    assert_real_adapter_blocked({"adapter_type": "local_runtime", "endpoint": "http://localhost:11434"})
except LocalEvalAdapterBlockedError:
    pass  # expected
```

---

## CLI

```bash
# Execute a TR-06C plan against the stub adapter
python3 training/local_eval_adapter_harness.py execute-stub \
  --plan /tmp/live_eval_plan.json \
  --out-dir /tmp/tr06d_stub_exec \
  --adapter-id TR06D_STUB_ADAPTER_001

# Summarize an existing execution report
python3 training/local_eval_adapter_harness.py summarize \
  --report /tmp/tr06d_stub_exec/live_evaluation_execution_report.json

# Assert a provider config is blocked
python3 training/local_eval_adapter_harness.py assert-blocked-adapter \
  --adapter-config /tmp/real_provider_adapter_config.json
```

---

## How TR-06D Prepares Future Real Local Model Execution

When an operator-approved local model adapter is built (a future phase beyond TR-06D):

1. The `LIVE_EVALUATION_EXECUTION_REPORT` schema is the output contract. The real adapter must produce reports conforming to the same schema, with `real_model_inference_performed=true` under a new schema version.
2. `assert_real_adapter_blocked` must be updated or replaced with a new approval gate that explicitly allows the operator-approved adapter while still blocking everything else.
3. `validate_plan_for_stub_execution` becomes `validate_plan_for_local_exec` — it must add checks that confirm the operator-approved adapter ID, that the plan has been countersigned, and that the candidate has passed all TR-06A/B metadata gates.
4. No result of real local execution may emit `promotion_decision_emitted=True` without a separate operator promotion gate.
5. TR-07 shadow/canary begins only after operator-approved local execution has been validated across all six default categories.

---

## Relationship to TR-06A, TR-06B, TR-06C

| Layer | What it does | Inference |
|---|---|---|
| TR-06A | Metadata gate stubs — provenance and governance flags | No |
| TR-06B | Fixture corpus for TR-06A gate regression | No |
| TR-06C | Live eval case and plan interface, executor disabled | No |
| TR-06D | Stub adapter execution plumbing, typed result layer | No (stub only) |
| Future phase | Operator-approved real local model adapter | Yes (operator-approved) |

TR-06D `case_category` values and `execution_report.case_results[].case_category` values mirror the 11 TR-06A evaluation gate names. A future real adapter should confirm that the relevant TR-06A gate has passed before running the live behavioral case for that category.

---

## Validation Commands

```bash
python3 -m py_compile training/local_eval_adapter_harness.py

python3 -m pytest -q training/tests/test_local_eval_adapter_harness.py

python3 -m pytest -q training/tests/test_live_eval_interface.py

python3 -m pytest -q training/tests/test_evaluation_fixtures.py

python3 -m pytest -q training/tests/test_evaluation_harness.py

python3 -m pytest -q training/tests/

python3 -m pytest -q
```

---

## Governance Attestation

No real training occurred in TR-06D. No model weights were loaded or created. No real model inference occurred. No provider calls were made. No LoRA or QLoRA adapters were created. No adapter checkpoint files were created. No Store 1 writes occurred. No model was promoted. No runtime deployment occurred. No Ollama, vLLM, llama.cpp, or local model runtime was invoked.

All stub execution reports carry `real_model_inference_performed=false`, `provider_calls_performed=false`, `model_weights_loaded=false`, `promotion_blocked=true`, and `promotion_decision_emitted=false`.

TR-07 shadow/canary evaluation was not started.
