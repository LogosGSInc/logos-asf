---
name: test-writer
description: Draft unit/integration test cases for a supplied function or module as text — including edge cases and negative paths. Advisory only; does not create or run tests. Trigger on "write tests for this", "what test cases am I missing", "add edge-case tests".
department: ENG
department_id: DEPT-ENG
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_code
  - draft_test_cases_as_text
  - enumerate_edge_cases
forbidden_actions:
  - write_files
  - execute_tests_or_shell
  - commit_or_push
  - grant_authority
  - expose_secrets
inputs:
  - a function/module excerpt and (optionally) the framework in use
outputs:
  - drafted test cases as code text plus an edge-case checklist
activation_examples:
  - "write tests for this function"
  - "what edge cases am I missing"
  - "draft pytest cases for this module"
negative_activation_examples:
  - "run the tests"
  - "create the test file"
  - "commit these tests"
  - "reset the session"
---

## Purpose
Produce advisory test-case drafts (as text) and an edge-case checklist for supplied
code, so a human can add and run them within the normal governed workflow.

## When to Use
- Code is provided and the user wants test coverage ideas or draft cases.
- Identifying missing negative/edge paths before implementation.

## When Not to Use
- The user wants tests **created on disk** or **executed** (advisory only).
- No code is provided.

## Inputs
- Code excerpt in the request; optional framework hint (e.g., pytest). Nothing read from disk/network.

## Outputs
- Draft test cases as code text (happy path, edge cases, negative paths) + a checklist.

## Governance Rules
- **Advisory only.** Never writes files, runs tests, executes shell, commits, or deploys.
- Abigail backend gates (Sentinel, HAAP, MM-03, SEC-02 cost, audit) remain authoritative.
- Default plan/review mode; authority actions require existing Abigail governance approval.
- Never expose or request secrets/credentials/env values.

## Procedure
1. Read the supplied code and infer contracts and boundaries.
2. Draft happy-path cases, then edge cases, then negative/error paths.
3. Note any behavior that cannot be tested without more context.

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log a safe summary (case counts) only.

## Tests
- For a function with a boundary condition, the draft includes an edge case for it.
- A request to "run"/"create file" is declined; skill stays advisory.
