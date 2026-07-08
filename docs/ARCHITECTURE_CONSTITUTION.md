# Metatron / Abigail — Architecture Constitution

**Dated:** 2026-07-07 · **Status:** Living constitutional document (slow-changing)

> Naming note: the product is referred to here as **Metatron (formerly Abigail)**.
> Code identifiers today use **Abigail / CP-00**; no code rename is implied by this
> document. Where this constitution describes a future-state (e.g., the canonical
> Contract Envelope, Ed25519 signing, `gov_tx_id` through contracts), those items
> are marked **DIRECTIONAL** in Appendix B — the constitution must itself obey the
> truthful-provenance rule it sets.

This document defines the constitutional rules by which Metatron is allowed to
evolve. It consolidates the governing invariants already established across doctrine
drafts, CP-00 architecture decisions, security hardening (SEC-03), model-router work
(MR-04/MR-05), UI provenance work, and communication-protocol verification.

---

## Purpose

Metatron is a governed assistant operating system built as a **supervisory control
plane, not a swarm of sovereign peers**. Its purpose is to translate human intent
into bounded machine action while preserving governance, auditability, separation
of concerns, and human authority over execution.

This constitution exists to **freeze the slow-changing architectural rules** before
the runtime, registry, and UI layers expand further. Every future feature, registry
change, connector, skill, route, or contributor decision should be evaluated against
this document before implementation.

---

## Layer Model

Metatron is organized into **five layers**:

1. **Presentation** — the operator-facing shell: Home, Workspace, Governance,
   Observability, and cockpit-style views.
2. **Governance** — Sentinel, HAAP, approval gates (MM-03), cost controls, and audit
   controls that determine *whether* work may proceed.
3. **Execution** — chat, governed routing, dispatch, and bounded worker execution
   paths that act only *after* governance allows them.
4. **Knowledge** — skills, references, policies, evaluations, and other governed
   knowledge artifacts that improve execution *quality* without granting authority.
5. **Infrastructure** — providers, Docker, registries, secrets, networking, and
   storage that *supply capability* but do not *decide permission*.

**Core separation rule:** Infrastructure provides capability; Governance authorizes
capability; Execution consumes authorized capability; Knowledge improves execution
quality; Presentation reveals state and accepts human instruction.

---

## Layer 1 — Authority

CP-00 is the **sole constitutional authority**. Agents are workers, not sovereign
actors.

- No agent may authorize itself or another agent.
- All execution authority originates from CP-00.
- Department leads, specialist agents, and sub-agents are execution personas or
  workers — **not brokers**.
- Authorization must be an explicit policy decision, not a hard-coded assumption or
  implied control flow.
- Any change that allows a worker, department lead, registry entry, or infrastructure
  component to behave as an independent authorizer is **unconstitutional** and must
  be rejected.

## Layer 2 — Communication

Agents never communicate directly as peers. All coordination occurs through
**structured JSON contracts brokered by CP-00** (or its explicitly authorized
supervisory identity).

- Workers never hold peer references as an execution primitive.
- Workers do not establish autonomous conversations with other workers.
- Every handoff must be contract-shaped and brokered.
- Any agent-to-agent relay that attempts delegated authorization by assertion must
  be blocked **before** execution proceeds.

This architecture rejects informal message-passing between agents in favor of
governed contracts, because contracts preserve traceability, explicit routing,
bounded payloads, and brokered authority.

## Layer 3 — Governance

Governance always precedes execution. Sentinel, HAAP, approval gates, and cost
controls evaluate whether work may proceed **before** skills, routing, or provider
execution occur.

- No capability layer may bypass `process_message` (or its governing equivalent).
- No new unauthenticated provider path may be introduced.
- Skills, prompts, routing preferences, or model-selection logic may **never**
  override governance decisions.
- Defense-in-depth re-checks are preferred over single-point trust wherever approval
  state, cost state, or route eligibility matter.
- Public-facing UI and operator surfaces must not overclaim runtime status or
  fabricate live behavior.

**Controlling principle:** policy decides *whether* action is allowed; capability
affects only *how* allowed work is carried out.

## Layer 4 — Knowledge

Skills are **governed knowledge artifacts, not permission artifacts**. They are
advisory, versioned, auditable, scoped, and progressively loaded.

- Skills may influence execution quality, structure, and consistency, but **never
  execution authority**.
- Skills must be scoped by department, role, or task class — not loaded
  indiscriminately.
- Skills use **progressive disclosure**: lightweight metadata first, deeper
  instructions loaded only when matched.
- Skills carry stable identifiers and versions in audit records once the skill
  registry matures.
- Skills, references, policies, and evaluations are versioned and treated as a
  governed subsystem, not ad hoc prompt fragments.
- Knowledge changes should receive their own auditable lifecycle so that activation,
  deprecation, and experimental use are governed rather than implicit.

## Layer 5 — Observability

Every governed action should be traceable through a durable transaction spine.
**`gov_tx_id`** is the preferred correlation identifier for governed work because it
allows incident reconstruction across screening, approval, routing, dispatch, and
completion.

- Every governed action receives a transaction identifier.
- Audit records should identify approval state, router decision, skill
  identity/version (when applicable), and execution outcome.
- UI widgets must declare provenance — `LIVE`, `SIMULATED`, `OFFLINE`, `LOCAL`,
  `REMOTE`, `CACHED` — rather than forcing the operator to infer it.
- Audit-safe metadata is preferred to raw prompt retention wherever possible.

The architectural direction converges toward a **single governed transaction model**
spanning chat, dispatch, contracts, and UI observability.

---

## Contract Spine

Metatron's differentiator is not merely message passing between agents; it is
**governed contract exchange**. Existing contract concepts already include structured
routing and handoff objects, payload hashes, and prior-packet linkage — pointing
toward a canonical envelope model.

A future canonical **Contract Envelope** should be capable of carrying:

```
ContractEnvelope
├── gov_tx_id
├── manifest_id
├── packet_id
├── packet_hash
├── previous_packet_hash
├── origin
├── destination
├── authority_level
├── approval_state
├── skill_id
├── skill_version
├── skill_hash
├── router_decision
├── cost_decision
├── sentinel_verdict
├── timestamp
├── payload
└── signature
```

This envelope is **not yet fully implemented end to end** (DIRECTIONAL), but it is
the correct constitutional direction because it unifies governance, knowledge,
routing, audit, and cryptographic authenticity into one transaction model. Every
feature discussed fits into it: Skills → `skill_id`/`skill_hash`; Registry →
`origin`/`destination`; UI → provenance; Audit → `gov_tx_id`; Ed25519 →
`signature`; Cost Governor → `cost_decision`.

---

## Infrastructure Boundaries

Infrastructure supplies execution substrate but **never constitutional judgment**.
Providers, containers, registries, secret stores, networking, and storage are
subordinate to governance and must not create alternate authority paths.

- Registry shipping must not create new implicit routing authority.
- Topology and control-plane endpoints must be authenticated before registry-era
  runtime expansion.
- Secrets management, IAM least privilege, environment separation, and image hygiene
  remain part of the production gate for AWS deployment.
- Infrastructure state may **inform** governance, but may not **replace** it.

---

## Acceptance Invariants

Preserved by tests, reviews, and audit criteria:

1. CP-00 remains the sole broker and constitutional authority.
2. Supervisory allow-lists exclude department leads and worker identities.
3. YAML relationship fields (`supervises`, `reports_to`) are descriptive only and do
   not create executable routing authority.
4. No public or worker-callable path may target another agent directly.
5. Governance gates remain upstream of routing, skills, and provider dispatch.
6. Provenance labeling remains truthful in both UI and runtime reporting.
7. Knowledge artifacts remain advisory unless explicitly elevated through governed
   policy.

---

## Roadmap Ordering

The constitutional layer changes slowly; runtime and presentation evolve rapidly.
Freeze the rules first, then build.

1. **Foundation** — preserve SEC-03 hardening, governed routing (MR-04/MR-05),
   skills discipline, and CP-00 verification.
2. **Constitutional hardening** — finish residual verification (code-inert metadata
   checks), propagate `gov_tx_id` through the contract flow, replace placeholder
   signing with real Ed25519 where required, ratify this constitution and the
   Contract Envelope.
3. **Runtime expansion** — close topology authentication (EP-03), then introduce the
   Control Plane Registry and container-aware runtime features **under the preserved
   invariants**.
4. **Experience** — evolve UI (P2), Mission page, Operator Cockpit, and browser
   automation only **after** runtime truth and provenance are ready to be exposed
   honestly.

---

## Change Standard

Every material change must answer these questions **before** approval:

1. Does it preserve CP-00 as the sole constitutional authority?
2. Does it preserve brokered contracts and forbid peer-to-peer agent execution?
3. Does governance still precede execution?
4. Does it preserve truthful provenance and auditable correlation?
5. Does it enlarge capability without silently enlarging authority?

If the answer to any is **no**, the change must not proceed without a constitutional
revision (recorded in the Amendments log below).

---

## Closing Principle

> **Metatron is allowed to become more capable, but not less governed.**

The system must grow by adding bounded capability under preserved authority,
preserved contracts, preserved auditability, and preserved human control.

---

## Appendix A — Current Enforcement Map (verified 2026-07-07)

Each invariant tied to where it is enforced today (from the CP-00 protocol
verification and SEC-03/SKILLS-01 work). Line numbers are indicative.

| Invariant | Enforced by | Locus |
|---|---|---|
| CP-00 sole broker | `AUTHORIZED_SUPERVISORS = {"abigail","abigail_cp00","abigail_supervisor"}`; `SignedHandoffPacket.from_agent` must be in set (raises `ValueError`) | `abigail/orchestration/schemas.py` |
| No agent-to-agent primitive | worker `_draft` is a pure string fn; `execute_worker` requires `SignedHandoffPacket` + `manifest_id` (`SwarmDenied`); "cannot self-route or self-approve" | `abigail/swarm/local_executor.py` |
| Contracts structured / hash-chained / audit-safe | `RoutingManifest`, `SignedHandoffPacket` (`payload_hash`, `previous_packet_hash`, `input_hash`, `audit_safe=True`) | `abigail/orchestration/schemas.py` |
| A2A relay hard-block | `_detects_a2a_relay` → HAAP Layer 1a `HARD_STOP` (before Sentinel/HAAP) | `abigail/abigail_hardened_enhanced.py` |
| `supervises`/`reports_to` code-inert | referenced in **0** `.py` files (present only in agent YAML); worker resolution is by department code | `resolve_department_worker` / `dispatch_department` |
| Governance precedes execution | order: kill-switch → A2A → Sentinel → HAAP → MM-03 → UX-01 → cost → router/dispatch | `process_message` + `api_chat` |
| Approval fails closed | `_resolve_approval_meta` → `GOVERNANCE_UNAVAILABLE_FAIL_CLOSED` (GOV-01) | `abigail/abigail_hardened_enhanced.py` |
| Skills advisory-only | bounded excerpt appended to system prompt after gates; changes no gate/authority/routing (chat P4, dispatch P4b-2a) | `_router_dispatch` region / `api_agents_dispatch` |
| Skills scoped + progressive disclosure | metadata-only `build_index`; `select_skill` department-scoped; path-contained body load | `abigail/skills_lib/discovery.py` |
| `gov_tx_id` correlation | minted per chat/dispatch request; on Sentinel/HAAP/approval/cost/router/skill/turn events | `process_message`, `api_chat`, `api_agents_dispatch` |
| Truthful UI provenance | `LIVE/SIMULATED/OFFLINE/LOCAL/REMOTE/CACHED` badges; LIVE only for named endpoints | `static/dashboard.html`, `static/abigail.*` |
| No unauthenticated provider path / privileged route | admin-gated dispatch/spawn/kill/restart/audit-tail; static path-traversal closed (EP-01); Sentinel loopback + token (DOCK-01/02) | runtime + `governance-spine` |

## Appendix B — Status Ledger (enforced vs directional)

**Enforced today** (test-locked): Layers 1–4 authority/communication/governance/
knowledge invariants; A2A block; skills advisory-only; `gov_tx_id` on chat &
dispatch; UI provenance; SEC-03 blocker fixes.

**Directional (not yet fully implemented):**
- `gov_tx_id` threaded **through the contract flow** (manifests/packets still use
  `manifest_id`/`packet_id`; correlation gap — see verification F1).
- **Real Ed25519 signing** (contracts use `SHA256_CHAIN_PLACEHOLDER` — F2 / SWARM-02).
- **Canonical Contract Envelope** (concepts exist; single unified envelope not built).
- **Control Plane Registry** in-container + **EP-03** topology-route authentication
  (dispatch is inert in-container until the curated registry ships behind closed EP-03).

## Amendments

| Date | Change | Rationale |
|---|---|---|
| 2026-07-07 | Initial ratification | Consolidate established invariants before registry/runtime expansion. |
