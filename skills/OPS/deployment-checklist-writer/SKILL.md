---
name: deployment-checklist-writer
description: Draft a pre-deploy and post-deploy checklist for a described release — gates, health checks, rollback, and sign-offs. Advisory only; produces the checklist, deploys nothing. Trigger on "deployment checklist for X", "what should I verify before shipping", "pre-flight for this release".
department: OPS
department_id: DEPT-OPS
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_release_context
  - draft_checklist_text
forbidden_actions:
  - deploy_or_release
  - execute_commands_or_shell
  - modify_files
  - grant_authority
  - expose_secrets
inputs:
  - a description of the release/change and target environment
outputs:
  - pre-deploy, deploy, and post-deploy checklists with rollback and sign-off items, as text
activation_examples:
  - "deployment checklist for this release"
  - "what to verify before shipping this"
  - "pre-flight checklist for the container update"
negative_activation_examples:
  - "deploy it now"
  - "run the release"
  - "push to production"
  - "give me the deploy key"
---

## Purpose
Draft a text-only, governed deployment checklist (pre/deploy/post + rollback +
sign-offs) for a described release so a human runs the actual deploy under governance.

## When to Use
- A release/change is described and the user wants a verification checklist.

## When Not to Use
- The user wants the deploy **performed** (advisory only — refuse and point to governance).
- No release context is provided.

## Inputs
- Release/change description + target environment. Nothing read from disk/network; nothing deployed.

## Outputs
- Pre-deploy gates (tests, security, approvals), deploy steps (as human-run guidance),
  post-deploy health checks, rollback plan, and required sign-offs.

## Governance Rules
- **Advisory only.** Never deploys, releases, executes commands, or edits files.
- Deployment remains gated by existing Abigail governance and the SEC-03 release gate
  (TLS/ACM, secrets manager, IAM, etc. for AWS) — the checklist must reference, never bypass, these.
- Default plan/review mode; sign-offs and actions require existing governance approval.
- Never expose or request secrets/credentials/deploy tokens.

## Procedure
1. Capture release scope, environment, and risk.
2. Draft pre-deploy gates → deploy steps (human-run) → post-deploy checks → rollback → sign-offs.
3. Flag any gate that maps to an open SEC-03/AWS release-gate item.

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log a safe summary (release label) only.

## Tests
- The checklist includes rollback and at least one required sign-off.
- A "deploy now"/"push to prod" request is declined; skill stays advisory.
