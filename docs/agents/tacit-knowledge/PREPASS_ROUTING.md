# Tacit Swarm Pre-Pass Routing
**Status:** DOCTRINE_ONLY — runtime activation not authorized (see ACTIVATION_PHASES.md)  
**Classification:** INTERNAL — ARCHITECTURE  
**Owner:** CP-00 (Abigail Constitutional Authority)  
**Phase:** Tacit Swarm Phase 1

---

## Purpose

The Tacit Swarm Pre-Pass is a lightweight, always-on interpretive layer that Abigail invokes before planning any response. It is not a full reconnaissance run. It is the first interpretive lens — a small, bounded inference pass that helps Abigail understand what the user is actually asking, what prior doctrine or context matters, and what constraints apply before she speaks.

The pre-pass produces a single `Tacit Context Card` (see `TACIT_CONTEXT_CARD.schema.json`). That card is ephemeral and governs Abigail's response planning for exactly one turn. It does not mutate Store 1, does not train Abigail, and does not persist across sessions unless explicitly authorized as Store 2 evidence.

---

## Request Flow

```
User Request
  → Sentinel / OverWatch / HAAP-X gate    [BLOCKING — always first]
  → Tacit Swarm Pre-Pass                  [interpretive, bounded, ephemeral]
      → Tacit Context Card produced
  → Abigail Response Planner              [uses card as framing context]
      → optional: department/agent routing
      → optional: external lookup (if card authorizes and scope permits)
  → Governed Response
```

Sentinel/OverWatch/HAAP-X remain authoritative. The pre-pass runs only on requests that clear the gate. The card cannot override a governance verdict.

---

## When the Pre-Pass Runs

Every request that clears the Sentinel gate and reaches Abigail's response planning layer triggers a pre-pass. There are no exceptions by request type. The pre-pass is tiered:

| Request Class | Pre-Pass Tier | Agents Invoked |
|---|---|---|
| `simple_chat` | Minimal | TKR Director (classify-only mode) |
| `technical_task` | Lightweight | TKR Director + TKR-02 (if artifact context needed) |
| `job_request` | Standard | TKR Director + EIR Director + EIR-01 (lookup authorization required) |
| `security_task` | Lightweight | TKR Director + TKR-02 (no EIR without operator scope) |
| `mission_spiritual` | Minimal | TKR Director (classify-only mode) |
| `operational` | Lightweight | TKR Director |
| `recovery_related` | Minimal | TKR Director (classify-only mode, no elicitation) |
| `memory_query` | Lightweight | TKR Director (doctrine/memory reference pass only) |

---

## Pre-Pass Constraints

### What the pre-pass MUST do
- Classify the request type
- Identify what the user is actually asking (tacit interpretation)
- Note what prior doctrine, context, or constraints matter
- Flag hidden assumptions Abigail might miss
- Set the memory policy for the turn
- Identify which agents are allowed and forbidden for this turn

### What the pre-pass MUST NOT do
- Conduct human elicitation or structured interviews (requires TKR-01, always operator-authorized)
- Mine files, repos, or artifacts beyond what is already in scope (requires TKR-02 authorization)
- Execute external OSINT, live web search, or job lookups without EIR-01 authorization
- Mutate Store 1
- Persist the Tacit Context Card to long-term memory without explicit Store 2 authorization
- Override a Sentinel/OverWatch/HAAP-X verdict
- Expand agent invocation beyond the tier defined for the request class

### Latency Contract
The pre-pass must complete in one inference pass. No multi-step chains, no tool calls, no recursive sub-agent expansion during the pre-pass itself. Estimated max latency: **< 500ms** (single LLM call with structured output). If the pre-pass cannot complete within the budget, it returns a minimal card with `confidence: 0.0` and `escalation_required: true`.

---

## Request Class Behavior Detail

### simple_chat
**Examples:** "What is 2+2?", "Good morning", "Explain photosynthesis."

Pre-pass questions:
- What is the user really asking?
- Is this casual, factual, or clarification-seeking?
- What should Abigail avoid overcomplicating?
- Any hidden doctrine or constraint that applies?

Agent invocation: TKR Director only. No sub-agents. No external lookup. Card is minimal.

---

### job_request
**Examples:** "Find me remote Python jobs", "What jobs fit my veteran/recovery background?", "Help me target senior roles in security."

Pre-pass questions:
- What does the user actually want from this job search?
- What prior constraints apply (work style, income target, recovery considerations, veteran path, clearance)?
- What work type, mission alignment, or technical stack is implied?
- What current-data lookup is needed (live listings)?
- What should be verified before recommending anything?

Agent invocation: TKR Director frames the request. EIR Director determines if a live lookup is warranted. EIR-01 is authorized for public job board lookup when request requires current data.

**Critical constraint:** Tacit agents classify and frame. They do not invent job listings. Live job data must come from a current authorized source (EIR-01 external lookup). If no live source is available, the card flags `missing_scope: live_job_data_required`.

---

### technical_task
**Examples:** Repo changes, code review, architecture design, debugging.

Pre-pass questions:
- What is the technical ask and scope?
- What repo context, prior doctrine, or governance constraint applies?
- What should Abigail avoid patching that she wasn't asked to touch?
- Are there any governance or Store 1 boundaries relevant to this task?

Agent invocation: TKR Director. TKR-02 allowed if artifact/file context is explicitly in scope. No EIR unless external research is part of the task.

---

### security_task
**Examples:** Red-team review, vulnerability triage, governance audit, HAAP-X analysis.

Pre-pass questions:
- What is the security objective and authorized scope?
- What governance layer is relevant (Sentinel, OverWatch, HAAP-X)?
- What should Abigail not escalate or mutate without explicit operator authorization?
- Is this defensive (governance) or offensive (red-team)?

Agent invocation: TKR Director + TKR-02. No EIR agents. No external lookup unless operator-scoped.

---

### mission_spiritual
**Examples:** Covenant interpretation, Proverbs 31 reflection, mission planning, identity and calling.

Pre-pass questions:
- What is the spiritual or mission context?
- What doctrine, covenant, or identity theme applies?
- What should Abigail affirm, not overanalyze?
- Is this a pastoral moment, a planning moment, or a discernment moment?

Agent invocation: TKR Director only. No research, no external lookup, no sub-agents.

---

## Escalation

If the pre-pass cannot classify the request with confidence ≥ 0.60, or if the request scope implies collection, external OSINT, or memory mutation that is not pre-authorized, the card sets:

```json
{
  "escalation_required": true,
  "missing_scope": ["<what is missing>"],
  "recommended_route": "operator_clarification"
}
```

Abigail presents the scope gap to the operator before proceeding. She does not guess into missing authorization.

---

## Memory Policy

| Policy Value | Meaning |
|---|---|
| `ephemeral` | Card is used for this turn only; not persisted |
| `log_only` | Card metadata logged to audit trail; not stored in GovMem |
| `store2_eligible` | Card qualifies for Store 2 analysis batch; requires separate GovMem authorization |
| `store1_blocked` | Explicitly marks that no Store 1 promotion is allowed for this turn |

Default for all pre-pass turns: **`ephemeral` + `store1_blocked`**.

Store 2 eligibility must be separately authorized. Store 1 promotion is never initiated from the pre-pass.
