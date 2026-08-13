# GovSec canonical envelope contracts

Status: contract implementation and adversarial tests. Pipeline and capability
wiring intentionally follow in a separate change.

## Trust boundary

The external runtime supplies raw model context and a raw tool call. A trusted
adapter must derive the principal, normalized resource, tool name and active
signed-policy identity. Callers must never be allowed to assert those authority
fields directly.

## Model-context envelope

`logos.model-context.v1` binds one model run to:

- principal, session and run identifiers;
- provider and model identifiers;
- signed policy version and policy hash;
- the exact provider-bound context-payload hash;
- the exact assembled system-prompt hash;
- the ordered tool-schema hash;
- the injected workspace/bootstrap manifest hash;
- ordered, source-labelled text segments;
- attachment identifiers, types, sizes and content hashes.

Every segment has a contiguous ordinal. External user content, prior
conversation, tool results, attachments, hook and runtime injections, and
compaction summaries are all explicitly selected for Sentinel inspection on
every run. This prevents model-produced or imported text from bypassing the
ingress scan merely because it appears in history.

`context_hash` is SHA-256 over deterministic canonical JSON excluding the
`context_hash` field itself. Mutation, reordering or rebinding changes the hash.

## Action envelope

`logos.action.v1` binds one proposed tool call to:

- tool name and full JSON arguments;
- normalized resource kind and locator;
- trusted principal, session, run and tool-call identifiers;
- signed policy version and policy hash;
- the approved `context_hash` that caused the action;
- a deterministic `action_hash` excluding only itself.

JSON object keys are sorted before hashing, so semantically identical argument
objects have the same digest regardless of insertion order. Arrays retain order.

The strict baseline classifier:

- denies unknown tools;
- denies path traversal, credential access and protected system writes;
- denies destructive shell, privilege escalation and downloaded-code piping;
- denies browser script evaluation;
- requires explicit authorization for ordinary shell, filesystem mutation and
  browser interaction;
- permits only non-sensitive reads at the contract-classification layer.

This classifier is a minimum fail-closed gate, not the signed constitution. The
constitution can be stricter but cannot turn a structural contract failure into
an approval.

## Limits

- 4,096 context segments;
- 256 KiB per segment;
- 4 MiB total context text;
- 128 attachments;
- 256 KiB canonical action arguments;
- JSON nesting depth of 32.

Missing, malformed, oversized or hash-mismatched envelopes fail closed.

## Contract tests

`tests/envelope_contracts.rs` fixes one golden digest for each schema and tests
mutation, reordering, context rebinding, malformed digests, attachment binding,
unknown tools, destructive shell, downloaded-code piping, protected writes,
credential reads, path traversal and browser script execution.

## Next wiring step

1. Store `context_hash` in the final approved verdict.
2. Add `context_hash` to `ProviderAuthorizationRequest`, `Decision`,
   `CapabilityToken` and presented capability binding.
3. Evaluate `ActionEnvelope` at the OpenClaw `before_tool_call` boundary.
4. Bind both `context_hash` and `action_hash` into a single-use tool capability.
5. Write terminal outcomes to an immutable append-only audit sink.

Hashes prove binding and tamper detection. They do not make an in-memory or
ordinary file log immutable.
