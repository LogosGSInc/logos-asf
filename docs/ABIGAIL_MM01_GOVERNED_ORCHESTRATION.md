# Abigail MM-01: Governed Orchestration Manifests and Signed Handoff Packets

**Document ID:** ABIGAIL_MM01_GOVERNED_ORCHESTRATION
**Version:** 1.0
**Date:** 2026-07-03
**Status:** ACTIVE
**Classification:** Internal Governance Doctrine

---

> **Sprint banner:** Do not test whether Abigail can answer. Test whether Abigail can stay governed.

---

## 1. Purpose

MM-01 creates the deterministic governance primitives for Abigail's multi-agent and multimodal routing. It does not execute real sub-agents, call providers, or process real media content. It defines the contracts, boundaries, and audit structures that all future worker-agent integration must satisfy.

**MM-01 does not test whether Abigail can answer more impressively; it tests whether Abigail can remain governed under ambiguity, adversarial input, modality uncertainty, authority confusion, and bounded execution pressure.**

---

## 2. Why Abigail Is Supervisor-Arbiter

Abigail is not a participant in a worker swarm. Abigail is the constitutional supervisor-arbiter of LOGOS Governance Systems' agentic system.

Abigail exclusively owns:

| Responsibility | Worker may do this? |
|---|---|
| Intent resolution | No |
| Doctrine screening | No |
| Modality decomposition | No |
| Capability selection | No |
| Routing manifest creation | No |
| Arbitration and fallback activation | No |
| Audit log merge | No |
| Final response approval | No |
| Termination authority | No |

Workers are narrow executors. They receive scoped handoff packets, execute within bounded constraints, and return outputs as references. They may not self-expand authority, self-route, self-approve, or write final policy.

---

## 3. Five Governed Gates

Every request processed through Abigail's orchestration layer passes five gates in sequence.

```
Input (raw)
    │
    ▼
Gate 1: INPUT CLASSIFICATION
        Classify modality, source trust, data sensitivity,
        command-style risk, authority claims, task intent,
        and task type. Produce structured classification.
    │
    ▼
Gate 2: DOCTRINE AND SAFETY GATE
        Apply HAAP, Sentinel, OverWatch, GovSec, command-bus doctrine,
        and Cost Governor constraints. Block or quarantine hostile content
        before any routing or tool execution.
    │
    ▼
Gate 3: ROUTING MANIFEST
        Build a deterministic, audit-safe RoutingManifest:
        modality, risk class, trust class, data sensitivity,
        allowed/forbidden tools, fallback chain, budget,
        termination condition, human-approval requirement.
        No worker receives a handoff without a manifest.
    │
    ▼
Gate 4: BOUNDED WORKER EXECUTION
        Issue a scoped SignedHandoffPacket to each worker.
        Workers receive least-privilege authority only.
        Budget, tools, outputs, and stop conditions are explicit.
        No free-form transcript sprawl.
        [This sprint: contract defined only. No real worker execution.]
    │
    ▼
Gate 5: AUDITED MERGE AND FINAL JUDGMENT
        Abigail owns arbitration, merge, fallback activation,
        final response approval, and termination.
        Workers may not self-terminate in ways that bypass audit.
```

---

## 4. RoutingManifest

**Module:** `abigail/orchestration/routing_manifest.py`
**Schema:** `abigail/orchestration/schemas.py`

A RoutingManifest is an audit-safe deterministic record created at Gate 3, before any worker handoff.

### Required fields

| Field | Type | Notes |
|---|---|---|
| `manifest_id` | str | Unique ID, `MANIFEST-<hex>` |
| `created_at` | str | ISO-8601 UTC |
| `supervisor` | str | Always `"abigail"` or authorized role |
| `task_intent` | str | Human-readable intent label |
| `request_type` | str | Functional request category |
| `modality` | str | One of: `text`, `document`, `image`, `audio`, `video`, `mixed_bundle`, `unknown` |
| `source_trust_class` | str | One of: `operator_direct`, `user_supplied`, `uploaded_file`, `rag_retrieved`, `web_retrieved`, `tool_returned`, `agent_returned`, `untrusted_external` |
| `data_sensitivity` | str | e.g. `internal`, `confidential`, `public` |
| `risk_level` | str | One of: `low`, `medium`, `high`, `critical` |
| `doctrine_sensitivity` | str | Doctrine context label |
| `command_style_signal` | bool | True if CMD_STYLE_INJECTION signals present (GovSec V2.1) |
| `required_capabilities` | list | Worker capability classes required |
| `allowed_worker_classes` | list | Explicitly permitted workers |
| `forbidden_worker_classes` | list | Explicitly blocked workers |
| `required_tools` | list | Tools worker must have access to |
| `forbidden_tools` | list | Tools worker must not use |
| `budget` | Budget | `max_steps`, `max_tokens_estimate`, optional wall time + cost |
| `fallback_chain` | list | Ordered fallback workers |
| `termination_condition` | str | Explicit, non-empty |
| `human_approval_required` | bool | Auto-computed; see approval rules below |
| `input_hash` | str | SHA-256 of canonical input — raw prompt never stored |
| `policy_refs` | list | GovSec/HAAP/Sentinel doctrine references |
| `audit_safe` | bool | Always True — no raw user content in this record |

### Human approval rules (fail-closed)

`human_approval_required` is computed automatically. It cannot be overridden to `False` when governance rules require `True`.

| Condition | Result |
|---|---|
| `risk_level` in `{high, critical}` | `True` |
| `request_type` in `{file_write, network_call, publish, paid_spend, privileged_operation, external_action, deploy, send_email, send_message, write_db}` | `True` |
| Any `required_tools` entry in `{file_write, network, http_request, shell, bash, deploy, publish, send_email, send_message, write_db}` | `True` |
| All other cases | `False` |

---

## 5. SignedHandoffPacket

**Module:** `abigail/orchestration/handoff_packet.py`
**Schema:** `abigail/orchestration/schemas.py`

A SignedHandoffPacket is the scoped worker instruction issued at Gate 4.

### Required fields

| Field | Type | Notes |
|---|---|---|
| `packet_id` | str | Unique ID, `PACKET-<hex>` |
| `manifest_id` | str | Links to RoutingManifest |
| `created_at` | str | ISO-8601 UTC |
| `from_agent` | str | Must be in `{abigail, abigail_cp00, abigail_supervisor}` |
| `to_agent` | str | Target worker class |
| `mission` | str | Non-empty scoped task description |
| `constraints` | dict | Additional constraints for this worker |
| `authority_scope` | str | Explicit, non-empty, least-privilege |
| `allowed_tools` | list | Default empty — no tools unless explicitly listed |
| `forbidden_tools` | list | Defaults: shell, bash, file_write, network, http_request, deploy |
| `allowed_outputs` | list | Permitted output types |
| `forbidden_outputs` | list | Prohibited output types |
| `evidence_requirements` | list | What the worker must return as evidence |
| `budget` | Budget | Inherited from manifest unless overridden |
| `stop_conditions` | list | Non-empty; at minimum: task_complete, max_steps_reached |
| `fallback_on_failure` | str | Default: `return_to_supervisor` |
| `input_refs` | list | References to input objects (no raw content) |
| `payload_hash` | str | SHA-256 over canonical content fields |
| `previous_packet_hash` | str | For chain-of-custody linking (optional) |
| `signature_algorithm` | str | `SHA256_CHAIN_PLACEHOLDER` until real ED25519 implemented |
| `signature_public_key_ref` | str | Empty until real signing implemented |
| `signature_placeholder` | str | `SHA256_CHAIN_PLACEHOLDER:<hash_prefix>` |
| `audit_safe` | bool | Always True |

### payload_hash canonical content

The `payload_hash` is computed over these fields only (excludes hash and signature fields):

`packet_id`, `manifest_id`, `created_at`, `from_agent`, `to_agent`, `mission`, `constraints`, `authority_scope`, `allowed_tools`, `forbidden_tools`, `allowed_outputs`, `forbidden_outputs`, `evidence_requirements`, `budget`, `stop_conditions`, `fallback_on_failure`, `input_refs`

Canonical JSON: sorted keys, no extra whitespace, UTF-8 encoded.

### Signing status

Real cryptographic signing (ED25519) is future work. Current sprint: deterministic SHA-256 chain + placeholder fields. No private key material is generated or stored.

---

## 6. CapabilityProfile

**Module:** `abigail/orchestration/capabilities.py`

Each worker class has a capability profile declaring what it can and cannot do. Abigail uses profiles at Gate 3 to select appropriate workers.

### Default profiles

| Worker class | Max risk | Modalities | Human approval |
|---|---|---|---|
| `text_analyst` | medium | text | No |
| `document_analyst` | medium | document, text | No |
| `image_analyst` | low | image (metadata only) | No |
| `audio_analyst` | low | audio (metadata only) | Yes |
| `code_reviewer` | medium | text, document | No |
| `security_reviewer` | high | text, document | Yes |
| `research_intelligence` | medium | text, document | No |
| `marketing_draft` | low | text | No |
| `governance_reviewer` | high | text, document | Yes |

### Capability query helpers

- `get_capability_profile(worker_class)` — retrieve profile, raises `KeyError` for unknown class
- `check_modality_supported(profile, modality)` — bool
- `check_risk_level_allowed(profile, risk_level)` — bool (respects risk order)
- `requires_human_approval_for(profile, risk_level)` — bool (fails toward True)

---

## 7. Multimodal as a Security Boundary

Modality is a security classification, not just a content type.

| Modality | Sprint status | Risk notes |
|---|---|---|
| `text` | Full routing | Standard Sentinel/HAAP applies |
| `document` | Full routing | File-read permissions scoped to document_analyst |
| `image` | Metadata only | No content analysis this sprint |
| `audio` | Metadata only | No transcription this sprint; always requires human approval |
| `video` | Not implemented | Route to `unknown` with human approval |
| `mixed_bundle` | Routing + quarantine | `command_style_signal` checked; hostile sub-elements quarantined |
| `unknown` | Requires human approval | Conservative fallback |

**Mixed-bundle handling:** When a request contains mixed modalities or mixed trust levels, Abigail classifies the bundle, quarantines hostile sub-elements at Gate 2, and builds separate routing manifests for safe subtasks. No sub-element bypasses doctrine screening.

---

## 8. Command-Style Injection Integration

MM-01 integrates GovSec V2.1 CMD_STYLE_INJECTION doctrine directly into the RoutingManifest schema.

`command_style_signal=True` in a RoutingManifest means:
- CMD_STYLE_INJECTION signals were detected in the input at Gate 2
- The manifest is flagged for elevated audit scrutiny
- The routing and worker selection must account for possible adversarial command-shaped content
- Risk escalation (typically to `high`) is expected

See: `docs/GOVSEC_V2_1_COMMAND_STYLE_INJECTION.md`

---

## 9. Cost Governor Integration

The `Budget` dataclass provides the Cost Governor integration surface:

- `max_steps` — hard step limit per worker invocation
- `max_tokens_estimate` — estimated token budget for the task
- `max_wall_seconds` — optional wall-clock timeout
- `max_cost_usd_estimate` — optional cost ceiling (no billing service called in this sprint)

Budget constraints are embedded in both RoutingManifest and SignedHandoffPacket. Workers receive the budget in their scoped packet. Workers may not modify their own budget.

---

## 10. DEP.KEYSTONE Evidence Reference Integration

The `input_refs` and `evidence_requirements` fields in SignedHandoffPacket are designed to support DEP.KEYSTONE supply-chain evidence attachment without rerunning DEP.KEYSTONE during this sprint.

Future pattern:
```python
packet = build_handoff_packet(
    manifest,
    input_refs=["dep_keystone://training/dep_keystone_ingress.py@5cdfee1"],
    evidence_requirements=["dep_keystone_provenance", "sbom_sha256"],
)
```

---

## 11. Supervisor-Only Merge and Termination

Workers may not:
- Alter their own mission, authority_scope, budget, or stop_conditions
- Issue handoff packets to other workers
- Self-approve their own outputs as final responses
- Self-terminate in ways that bypass the audit trail
- Write final governance policy

Abigail alone activates fallback chains, performs output arbitration, and approves final responses. This constraint is enforced structurally: only `AUTHORIZED_SUPERVISORS` may set `from_agent` in a SignedHandoffPacket.

---

## 12. Failure Modes

| Failure | Expected behavior |
|---|---|
| Invalid modality | ValueError at build time — no manifest created |
| Invalid risk_level | ValueError at build time |
| human_approval_required=False for high risk | ValueError at build time — fail closed |
| Unauthorized from_agent in packet | ValueError at build time |
| Empty authority_scope | ValueError at build time |
| Empty stop_conditions | ValueError at build time |
| CMD_STYLE_INJECTION signal detected | command_style_signal=True, risk escalated, human approval required |
| mixed_bundle with hostile sub-element | Quarantine at Gate 2; safe subtasks get separate manifests |
| Worker exceeds budget | Supervisor activates fallback_chain |
| Worker self-expands authority | Packet construction fails — from_agent check |

---

## 13. Acceptance Tests

Test suite: `tests/test_orchestration_routing_manifest.py`, `tests/test_orchestration_handoff_packet.py`

| Assertion | Test |
|---|---|
| Abigail is supervisor-arbiter | `test_abigail_supervisor_arbiter_is_authorized` |
| Worker packets cannot self-expand authority | `test_worker_cannot_self_issue_packet` |
| Routing manifest exists before handoff packet | `test_routing_manifest_exists_before_handoff_packet` |
| SingleGovernedState does not require transcript replay | `test_single_governed_state_builds` |
| High-risk tasks require human approval | `test_routing_manifest_marks_high_risk_as_human_approval_required` |
| External action requires human approval | `test_high_risk_external_action_requires_human_approval` |
| Mixed-bundle hostile content quarantined | `test_mixed_bundle_hostile_content_quarantined` |
| Normal safe work routes as bounded task | `test_normal_safe_work_routes_as_bounded_task` |
| No provider calls | `test_no_provider_calls_in_orchestration_modules` |
| No network calls | `test_no_provider_or_network_calls_in_handoff_packet_module` |
| ~/Abigailv1 remains untouched | `test_abigailv1_not_modified` |
| input_hash instead of raw prompt | `test_routing_manifest_stores_input_hash_not_raw_prompt` |
| payload_hash is stable and sensitive | `test_handoff_packet_stable_hash_for_canonical_equivalent_content` |

---

## 14. What This Sprint Does Not Do

- **Does not execute real sub-agents.** Worker execution contracts are defined; no worker runs.
- **Does not call providers.** No Groq, OpenAI, Anthropic, or other inference calls.
- **Does not process real image, audio, or video content.** Multimodal routing is metadata-only.
- **Does not implement real cryptographic signing.** ED25519 signing is future work; SHA-256 chain placeholders are used.
- **Does not integrate a live Cost Governor billing service.** Budget fields are present; no billing API is called.
- **Does not rerun DEP.KEYSTONE.** Evidence reference slots are defined for future attachment.
- **Does not contain external citations as authoritative doctrine.** All doctrine references are internal LOGOS/GovSec/HAAP/Sentinel documents. External standards (NIST, OWASP, etc.) are reference targets for later verification only.

---

## 15. Version History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-07-03 | Initial MM-01: RoutingManifest, SignedHandoffPacket, CapabilityProfile, SingleGovernedState, 5-gate pipeline, mixed-bundle fixture, 61 tests |
