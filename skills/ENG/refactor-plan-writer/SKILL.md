---
name: refactor-plan-writer
description: Produce a step-by-step, low-risk refactor plan for supplied code — ordered changes, risks, and verification per step. Advisory only; plans, does not refactor. Trigger on "plan a refactor", "how should I restructure this", "break this change into safe steps".
department: ENG
department_id: DEPT-ENG
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_code
  - produce_ordered_refactor_plan
  - identify_risks_and_verification
forbidden_actions:
  - modify_files
  - execute_code_or_shell
  - commit_or_deploy
  - grant_authority
  - expose_secrets
inputs:
  - code excerpt and the refactor goal
outputs:
  - an ordered, incremental refactor plan with per-step risk and verification
activation_examples:
  - "plan a refactor for this module"
  - "break this into safe steps"
  - "how do I restructure this without breaking it"
negative_activation_examples:
  - "do the refactor"
  - "apply these changes"
  - "deploy the refactor"
  - "disable the tests"
---

## Purpose
Give an ordered, incremental refactor plan for supplied code so each step is small,
reversible, and independently verifiable. Planning only — a human executes.

## When to Use
- Code is provided and the user wants a safe sequence of changes toward a goal.

## When Not to Use
- The user wants the refactor **performed** (advisory only).
- No code or no goal is provided.

## Inputs
- Code excerpt + stated refactor goal. Nothing read from disk/network.

## Outputs
- Numbered steps, each with: the change, why it's safe, and how to verify before the next step.
- Explicit rollback note per risky step.

## Governance Rules
- **Advisory only.** Never edits files, runs code, commits, or deploys.
- Abigail backend gates (Sentinel, HAAP, MM-03, SEC-02 cost, audit) remain authoritative.
- Default plan/review mode; execution requires existing Abigail governance approval.
- Never expose or request secrets/credentials/env values.

## Procedure
1. Understand current structure and the goal from the supplied code.
2. Decompose into the smallest safe, ordered steps (behavior-preserving first).
3. For each step: risk, verification (tests/checks), and rollback.
4. Call out steps that need human/security review.

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log a safe summary (step count) only.

## Tests
- The plan's first steps are behavior-preserving and each has a verification.
- A request to "do it"/"apply" is declined; skill stays advisory.
