---
name: git-commit-writer
description: Draft a clear, conventional commit message from a supplied diff or change summary. Advisory only — outputs message text; does not stage, commit, or push. Trigger on "write a commit message", "summarize this diff as a commit", "conventional commit for this".
department: ENG
department_id: DEPT-ENG
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_diff_or_summary
  - draft_commit_message_text
forbidden_actions:
  - run_git
  - stage_commit_or_push
  - modify_files
  - grant_authority
  - expose_secrets
inputs:
  - a diff or a plain-language summary of the change
outputs:
  - a drafted commit message (subject + body) as text
activation_examples:
  - "write a commit message for this diff"
  - "conventional commit for these changes"
  - "summarize this change as a commit"
negative_activation_examples:
  - "commit this"
  - "push to main"
  - "git reset --hard"
  - "give me the repo token"
---

## Purpose
Turn a supplied diff/summary into a well-formed commit message (subject + body) as
text. The human performs the actual git action within the normal workflow.

## When to Use
- A change is described or diffed and the user wants a commit message drafted.

## When Not to Use
- The user wants the commit **performed** or **pushed** (advisory only — never runs git).
- No change is provided.

## Inputs
- Diff or change summary in the request. Nothing read from disk/network.

## Outputs
- Commit message text: concise imperative subject, wrapped body explaining what/why.

## Governance Rules
- **Advisory only.** Never runs git, stages, commits, pushes, or edits files.
- Abigail backend gates (Sentinel, HAAP, MM-03, SEC-02 cost, audit) remain authoritative.
- Default plan/review mode; any git/authority action goes through existing governance.
- Never include secrets, tokens, or credentials in the message; never request them.

## Procedure
1. Read the diff/summary; identify the primary change and its rationale.
2. Draft an imperative subject (<~72 chars) and a body covering what and why.
3. Flag if the change appears to mix unrelated concerns (suggest splitting).

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log only that a message was drafted.

## Tests
- Given a diff, the drafted subject is imperative and scoped to the change.
- A request to "commit"/"push" is declined; skill stays advisory.
