---
name: incident-runbook-writer
description: Draft an incident-response runbook for a described failure scenario — detection, triage, mitigation, comms, and postmortem prompts. Advisory only; produces the runbook, executes nothing. Trigger on "write a runbook", "incident plan for X outage", "how do we respond if Y fails".
department: OPS
department_id: DEPT-OPS
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_scenario
  - draft_runbook_text
forbidden_actions:
  - execute_commands_or_shell
  - restart_kill_or_deploy
  - modify_files
  - grant_authority
  - expose_secrets
inputs:
  - a description of the service and the failure/incident scenario
outputs:
  - a structured runbook (detect → triage → mitigate → communicate → recover → postmortem) as text
activation_examples:
  - "write a runbook for a database outage"
  - "incident plan if the API goes down"
  - "how should we respond to a Sentinel failure"
negative_activation_examples:
  - "restart the service now"
  - "run the mitigation commands"
  - "kill the agent"
  - "reset the session"
---

## Purpose
Draft a clear, text-only incident-response runbook for a described scenario so
on-call humans have a governed plan. It never executes operational actions.

## When to Use
- A failure/incident scenario is described and the user wants a response runbook.

## When Not to Use
- The user wants operational actions **performed** (restart/kill/deploy) — refuse; advisory only.
- No scenario is provided.

## Inputs
- Service + scenario description in the request. Nothing read from disk/network; nothing executed.

## Outputs
- Runbook sections: detection signals, triage steps, mitigation options (as guidance),
  comms/escalation, recovery, and postmortem prompts. Commands appear as *suggested, human-run* text only.

## Governance Rules
- **Advisory only.** Never executes commands, restarts, kills, deploys, or edits files.
- Operational actions remain gated by existing Abigail governance (admin auth, MM-03, Sentinel).
- Default plan/review mode; suggested commands are for a human operator, not auto-run.
- Never expose or request secrets/credentials; never include live tokens in the runbook.

## Procedure
1. Model the scenario: blast radius, detection signals, dependencies.
2. Draft triage → mitigation → comms → recovery → postmortem.
3. Mark steps that require operator authority/approval before execution.

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log a safe summary (scenario label) only.

## Tests
- The runbook includes detection, mitigation, and escalation for the scenario.
- A "restart/kill/deploy now" request is declined; skill stays advisory.
