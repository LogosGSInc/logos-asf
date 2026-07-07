---
name: dependency-risk-reviewer
description: Review a supplied dependency manifest (requirements.txt, package.json, Cargo.toml, etc.) for risk signals — unpinned versions, undeclared/transitive reliance, abandoned or high-CVE-history packages, license concerns. Advisory only; no network calls. Trigger on "review my dependencies", "is this package risky", "check this requirements file".
department: SEC
department_id: DEPT-SEC
authority_level: advisory
risk_level: low
source: first-party
license: proprietary
allowed_actions:
  - read_provided_manifest
  - flag_risk_signals_from_text
  - suggest_pinning_and_review_actions
forbidden_actions:
  - fetch_from_network
  - install_packages
  - execute_code_or_shell
  - modify_files
  - grant_authority
inputs:
  - a dependency manifest pasted into the request
outputs:
  - a per-dependency risk table (signal, severity, suggested action) as text
activation_examples:
  - "review these dependencies for risk"
  - "is anything in this requirements file risky"
  - "check this package.json for supply-chain issues"
negative_activation_examples:
  - "install these packages"
  - "run npm audit"
  - "upgrade and deploy"
  - "fetch the latest versions"
---

## Purpose
Advisory, offline review of a supplied dependency manifest for risk signals a human
should investigate. Reasons only over provided text — **makes no network calls** and
does not fetch live CVE data (it flags what to check, not authoritative CVE verdicts).

## When to Use
- A manifest is pasted and the user wants risk signals and hardening suggestions.

## When Not to Use
- The user wants packages **installed/upgraded**, or a live audit performed (advisory only).
- No manifest is provided.

## Inputs
- Manifest text (requirements.txt / package.json / Cargo.toml / etc.). Nothing fetched.

## Outputs
- Per-dependency signals: unpinned/loose ranges, undeclared-but-imported, known-abandonment
  or heavy-CVE-history reputation (as *check-this* flags, not verdicts), license concerns.
- Suggested actions (pin, add explicit dep, request SEC review). No changes applied.

## Governance Rules
- **Advisory only, offline.** Never fetches, installs, upgrades, executes, or edits files.
- CVE/abandonment notes are **advisory flags for human verification**, never authoritative claims.
- Abigail backend gates (Sentinel, HAAP, MM-03, SEC-02 cost, audit) remain authoritative.
- Never expose or request secrets/credentials/registry tokens.

## Procedure
1. Parse the manifest; list each dependency and its version constraint.
2. Flag unpinned/loose versions and (if code is also provided) undeclared-but-imported packages.
3. Note reputation/license concerns as *verify* flags; suggest pinning and SEC review.

## Audit Requirements
- Record activation with gov_tx_id, skill, department; log a safe summary (flag counts) only.

## Tests
- An unpinned dependency is flagged with a pinning suggestion.
- An "install"/"npm audit"/"fetch" request is declined (no network, no install).
