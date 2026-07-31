# -*- coding: utf-8 -*-
"""
command_bus.py — LOGOS Governance Systems Inc. — Abigail CP-00 Governed Command Bus

10-gate operator command classification and dispatch pipeline.
Fixes routing defect where command-shaped text reached Groq as inference input.
Injects haap_gate and log_event as callables — no circular imports.
"""
import os
import re
import unicodedata

import privileged_credentials

COMMAND_BUS_VERSION = "1.0.0"

OPERATOR_COMMAND_ALLOWLIST: frozenset = frozenset({
    "status", "/status", "api/status", "/api/status", "help", "/help",
})

# Explicit Unicode escapes: ZW chars, bidi overrides/isolates, BOM, soft hyphen
_ZW_RE = re.compile(
    r'[​‌‍‎‏  ﻿­'
    r'⁠‪‫‬‭‮⁦⁧⁨⁩]'
)
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_STATUS_ALLOWED_FIELDS = frozenset({
    "backend", "crsv", "kill_switch", "sandbox", "turns", "version"
})


def _normalize_for_classification(raw: str) -> str:
    """Gate 1 — classification copy only. Raw preserved for audit."""
    s = _ZW_RE.sub('', raw)
    s = unicodedata.normalize('NFKC', s)   # fullwidth → ASCII, ligatures
    s = re.sub(r'[\x00-\x1f]', '', s)      # strip ASCII control chars
    return s.strip().lower()


def _resolve_surface(remote_addr: str, auth_header: str) -> tuple:
    """Gate 4 — returns (surface_class, token). Admin/demo tokens are
    resolved and compared through the centralized C4 validator
    (privileged_credentials): a missing, too-short, or placeholder-looking
    configured token never grants TRUSTED_* status, and comparison is
    constant-time."""
    token = (auth_header or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if privileged_credentials.credential_matches(token, "ABIGAIL_ADMIN_TOKEN"):
        return ("TRUSTED_OPERATOR", token)
    if privileged_credentials.credential_matches(token, "ABIGAIL_DEMO_TOKEN"):
        return ("TRUSTED_READONLY", token)
    if (remote_addr or "").strip() in _LOOPBACK:
        # Dev-only: LOCAL_UNAUTH is NOT a production authority model.
        # Requires explicit opt-in via ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS=1.
        # Production must wire ABIGAIL_ADMIN_TOKEN; without it, loopback is refused.
        if os.environ.get("ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS", "").strip() == "1":
            return ("LOCAL_UNAUTH", "")
        return ("PUBLIC_UNAUTH", "")
    return ("PUBLIC_UNAUTH", "")


def _build_refusal(reason: str, session) -> dict:
    crsv = round(session.crsv(), 1) if session and hasattr(session, 'crsv') else 0.0
    return {"ok": False, "text": f"[Command Bus] {reason}", "drs": 0,
            "mode": "CMD_BUS_REFUSED", "crsv": crsv,
            "source": "command_bus · governed refusal · no model inference"}


def _handle_status(status_dict: dict, session) -> dict:
    """Gates 8-10: sanitize to allowed fields, format, label."""
    safe = {k: v for k, v in (status_dict or {}).items() if k in _STATUS_ALLOWED_FIELDS}
    ks = "ACTIVE" if safe.get("kill_switch") else "inactive"
    text = (
        f"Backend: {safe.get('backend', '—')} | "
        f"CRSV: {safe.get('crsv', 0.0):.1f} | "
        f"Turns: {safe.get('turns', 0)} | "
        f"Kill-switch: {ks} | "
        f"Version: {safe.get('version', '—')} | "
        f"Sandbox: {safe.get('sandbox', '—')}"
        f"\n\nOperator status · governed endpoint read · no model inference"
    )
    crsv = round(session.crsv(), 1) if session and hasattr(session, 'crsv') else float(safe.get('crsv', 0.0))
    return {"ok": True, "text": text, "drs": 0, "mode": "OPERATOR_CMD", "crsv": crsv,
            "source": "Operator status · governed endpoint read · no model inference"}


def _handle_help(session) -> dict:
    crsv = round(session.crsv(), 1) if session and hasattr(session, 'crsv') else 0.0
    text = (
        "Available operator commands:\n"
        "  status / /status / api/status / /api/status  — system status\n"
        "  help / /help                                  — this message\n\n"
        "All commands are classified, governed, and audited before execution.\n"
        "No model inference is used for operator commands.\n"
        "Governed by HAAP + command bus v" + COMMAND_BUS_VERSION
    )
    return {"ok": True, "text": text, "drs": 0, "mode": "OPERATOR_CMD", "crsv": crsv,
            "source": "Operator help · governed endpoint read · no model inference"}


def try_operator_command(msg, remote_addr, auth_header,
                         haap_gate_fn, log_event_fn, status_dict, session):
    """
    10-gate governed operator command bus.
    Returns response dict if handled, None to fall through to process_message().
    """
    # Gate 1: Normalize (classification copy only)
    normalized = _normalize_for_classification(msg)

    # Gate 2: Exact match — "status show keys" has a space → not in allowlist → None
    if normalized not in OPERATOR_COMMAND_ALLOWLIST:
        return None

    # Gate 3: Classify
    handler = "status" if "status" in normalized else "help"

    # Gate 4: Surface check
    surface, _ = _resolve_surface(remote_addr, auth_header)
    if surface == "PUBLIC_UNAUTH":
        log_event_fn("CMD_BUS_PUBLIC_REFUSED", {
            "normalized": normalized, "surface": surface,
            "remote_addr": remote_addr, "action": "GOVERNED_REFUSAL"})
        return _build_refusal(
            "Operator commands require authentication. "
            "Provide a valid Authorization or X-HAAP-Token header.", session)

    # Gate 5: Authority (LOCAL_UNAUTH = dev mode opt-in, allowed with warning)
    dev_mode_warning = (surface == "LOCAL_UNAUTH")

    # Gate 6: Governance approval — pass RAW input, not normalized
    governance_result = "APPROVED"
    governance_block_reason = None
    try:
        haap_gate_fn(msg)
    except Exception as exc:
        governance_result = "HAAP_BLOCKED"
        governance_block_reason = str(exc)[:200]

    if governance_result == "HAAP_BLOCKED":
        log_event_fn("CMD_BUS_HAAP_REFUSED", {
            "normalized": normalized, "surface": surface,
            "governance_result": governance_result,
            "block_reason": governance_block_reason, "action": "GOVERNED_REFUSAL"})
        return _build_refusal(
            f"Governance check blocked this command. {governance_block_reason}", session)

    # Gate 7: Audit
    audit = {"command_class": "operator_command_candidate", "handler": handler,
             "normalized_token": normalized, "surface": surface,
             "governance_result": governance_result, "remote_addr": remote_addr,
             "raw_input": msg, "dev_mode_warning": dev_mode_warning,
             "command_bus_version": COMMAND_BUS_VERSION}
    if dev_mode_warning:
        audit["governance_warning"] = (
            "LOCAL_UNAUTH surface: loopback access without token. "
            "Dev mode only (ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS=1). "
            "Wire ABIGAIL_ADMIN_TOKEN for production.")
    log_event_fn("OPERATOR_COMMAND_REQUEST", audit)

    # Gates 8-10: Execute → Sanitize → Return with label
    if handler == "status":
        return _handle_status(status_dict, session)
    return _handle_help(session)
