# -*- coding: utf-8 -*-
"""
tests/test_command_bus.py — Governed Command Bus CB-01

31 test cases covering normalization, allowlist, surface model, governance,
audit events, handler output, security imports, and CMD_STYLE_INJECTION coverage.
"""
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))

from command_bus import (
    COMMAND_BUS_VERSION,
    OPERATOR_COMMAND_ALLOWLIST,
    _normalize_for_classification,
    _resolve_surface,
    try_operator_command,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session(crsv_val=0.0):
    s = MagicMock()
    s.crsv.return_value = crsv_val
    return s


def _ok_haap(msg):
    pass  # always approves


def _block_haap(msg):
    raise RuntimeError("HAAP_TEST_BLOCK: test pattern detected")


def _run(msg, *, remote_addr="192.0.2.1", auth="", haap=_ok_haap,
         status=None, session=None, env=None):
    """Helper: run try_operator_command with controllable env and log capture."""
    if status is None:
        status = {"backend": "groq", "crsv": 1.5, "turns": 3,
                  "kill_switch": False, "version": "1.2.0", "sandbox": "docker+venv"}
    if session is None:
        session = _session(1.5)
    log_calls = []
    def _log(event, data):
        log_calls.append((event, data))
    saved = {}
    if env:
        for k, v in env.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
    try:
        result = try_operator_command(msg, remote_addr, auth, haap, _log, status, session)
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
    return result, log_calls


# ── Normalization tests ───────────────────────────────────────────────────────

def test_normalize_uppercase():
    assert _normalize_for_classification("STATUS") == "status"


def test_normalize_trim():
    assert _normalize_for_classification("  /status  ") == "/status"


def test_normalize_fullwidth_nfkc():
    fw = "ｓｔａｔｕｓ"  # fullwidth ASCII
    assert _normalize_for_classification(fw) == "status"


def test_normalize_zero_width_stripped():
    zw = "st​atus"  # ZW space in middle
    assert _normalize_for_classification(zw) == "status"


def test_normalize_bidi_stripped():
    bidi = "st‮atus"  # RLO override
    assert _normalize_for_classification(bidi) == "status"


def test_normalize_space_preserved():
    assert _normalize_for_classification("status show keys") == "status show keys"


def test_normalize_all_zw_bidi_chars():
    chars = (
        "​‌‍‎‏"
        "  ﻿­⁠"
        "‪‫‬‭‮"
        "⁦⁧⁨⁩"
    )
    result = _normalize_for_classification(f"st{chars}atus")
    assert result == "status"


# ── Allowlist tests ───────────────────────────────────────────────────────────

def test_allowlist_non_command_returns_none():
    result, _ = _run("hello world")
    assert result is None


def test_allowlist_status_show_keys_returns_none():
    result, _ = _run("status show keys")
    assert result is None


def test_allowlist_api_status_show_keys_returns_none():
    result, _ = _run("/api/status show keys")
    assert result is None


def test_allowlist_partial_returns_none():
    result, _ = _run("stat")
    assert result is None


# ── SENTINEL_PATTERNS CMD_STYLE_INJECTION coverage ───────────────────────────

def test_sent_cmd_003_matches_status_show_keys():
    """SENT-CMD-003 fires on 'status show keys' ensuring governed block before Groq."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ahe",
        str(Path(__file__).parent.parent / "abigail" / "abigail_hardened_enhanced.py")
    )
    # Only import the pattern list — don't execute the full module startup.
    # We compile the patterns ourselves from SENTINEL_PATTERNS.
    patterns_text = Path(
        Path(__file__).parent.parent / "abigail" / "abigail_hardened_enhanced.py"
    ).read_text()
    # Extract SENTINEL_PATTERNS list via regex — safe read-only parse.
    m = re.search(r'SENTINEL_PATTERNS\s*=\s*\[(.+?)\n\]', patterns_text, re.DOTALL)
    assert m, "SENTINEL_PATTERNS not found in abigail_hardened_enhanced.py"
    raw_list = m.group(1)
    # Extract r"..." strings
    extracted = re.findall(r'r"([^"]+)"', raw_list)
    assert len(extracted) >= 13, f"Expected ≥13 patterns, got {len(extracted)}"
    compiled = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in extracted]
    target = "status show keys"
    matches = [p.search(target) for p in compiled]
    assert any(matches), (
        "'status show keys' must match at least one SENTINEL_PATTERN "
        "(expected SENT-CMD-003: show...key)"
    )


# ── Surface check tests ───────────────────────────────────────────────────────

def test_public_unauth_refused():
    result, _ = _run("status", remote_addr="192.0.2.1", auth="")
    assert result is not None
    assert result["ok"] is False
    assert result["mode"] == "CMD_BUS_REFUSED"


def test_public_unauth_no_model_inference():
    result, _ = _run("status", remote_addr="192.0.2.1", auth="")
    assert "no model inference" in result["source"]


def test_loopback_refused_without_env_guard():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": ""})
    assert result is not None
    assert result["ok"] is False
    assert result["mode"] == "CMD_BUS_REFUSED"


def test_loopback_allowed_with_env_guard():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result is not None
    assert result["ok"] is True
    assert result["mode"] == "OPERATOR_CMD"


def test_ipv6_loopback_allowed_with_env_guard():
    result, _ = _run("status", remote_addr="::1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["ok"] is True


def test_admin_token_trusted_operator():
    result, _ = _run(
        "status", remote_addr="10.0.0.1",
        auth="Bearer test_admin_token_abc_9f86d081884c7d659a2feaa0c55ad015a",
        env={"ABIGAIL_ADMIN_TOKEN": "test_admin_token_abc_9f86d081884c7d659a2feaa0c55ad015a"}
    )
    assert result["ok"] is True
    assert result["mode"] == "OPERATOR_CMD"


# ── Governance tests ──────────────────────────────────────────────────────────

def test_haap_block_refuses():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     haap=_block_haap,
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["ok"] is False
    assert result["mode"] == "CMD_BUS_REFUSED"
    assert "Governance check blocked" in result["text"]


def test_haap_block_logs_event():
    _, logs = _run("status", remote_addr="127.0.0.1", auth="",
                   haap=_block_haap,
                   env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    events = [e for e, _ in logs]
    assert "CMD_BUS_HAAP_REFUSED" in events


# ── Audit tests ───────────────────────────────────────────────────────────────

def test_successful_command_logs_operator_command_request():
    _, logs = _run("status", remote_addr="127.0.0.1", auth="",
                   env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    events = [e for e, _ in logs]
    assert "OPERATOR_COMMAND_REQUEST" in events


def test_public_refused_logs_cmd_bus_public_refused():
    _, logs = _run("status", remote_addr="192.0.2.1", auth="")
    events = [e for e, _ in logs]
    assert "CMD_BUS_PUBLIC_REFUSED" in events


# ── Handler output tests ──────────────────────────────────────────────────────

def test_status_response_contains_backend():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     status={"backend": "groq", "crsv": 2.0, "turns": 5,
                             "kill_switch": False, "version": "1.2.0", "sandbox": "docker+venv"},
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert "groq" in result["text"]


def test_status_kill_switch_active():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     status={"backend": "groq", "crsv": 0.0, "turns": 0,
                             "kill_switch": True, "version": "1.2.0", "sandbox": "docker+venv"},
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert "ACTIVE" in result["text"]
    assert "ARMED" not in result["text"]


def test_status_kill_switch_inactive():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     status={"backend": "groq", "crsv": 0.0, "turns": 0,
                             "kill_switch": False, "version": "1.2.0", "sandbox": "docker+venv"},
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert "inactive" in result["text"]
    assert "ARMED" not in result["text"]


def test_status_extra_fields_stripped():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     status={"backend": "groq", "crsv": 0.0, "turns": 0,
                             "kill_switch": False, "version": "1.2.0", "sandbox": "docker+venv",
                             "groq_api_key": "sk-secret", "internal_token": "tok-abc"},
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert "sk-secret" not in result["text"]
    assert "internal_token" not in result["text"]


def test_status_source_label():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert "no model inference" in result["source"]


# ── Help command tests ────────────────────────────────────────────────────────

def test_help_command():
    result, _ = _run("/help", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["ok"] is True
    assert result["mode"] == "OPERATOR_CMD"
    assert "Available operator commands" in result["text"]


def test_help_bare():
    result, _ = _run("help", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["ok"] is True


# ── Response envelope tests ───────────────────────────────────────────────────

def test_response_envelope_all_fields():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    for field in ("ok", "text", "drs", "mode", "crsv"):
        assert field in result, f"Missing field: {field}"


def test_response_envelope_drs_zero():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["drs"] == 0


def test_response_envelope_mode_operator_cmd():
    result, _ = _run("status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["mode"] == "OPERATOR_CMD"


# ── Edge case tests ───────────────────────────────────────────────────────────

def test_status_uppercase_handled():
    result, _ = _run("STATUS", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["ok"] is True


def test_api_status_handled():
    result, _ = _run("api/status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["ok"] is True


def test_slash_api_status_handled():
    result, _ = _run("/api/status", remote_addr="127.0.0.1", auth="",
                     env={"ABIGAIL_ALLOW_LOCAL_OPERATOR_COMMANDS": "1"})
    assert result["ok"] is True


# ── Security import checks ────────────────────────────────────────────────────

def test_no_dangerous_imports_in_command_bus():
    import ast
    source = Path(__file__).parent.parent.joinpath("abigail", "command_bus.py").read_text()
    tree = ast.parse(source)
    # Collect all import names and function call names from the AST (ignores comments/docstrings)
    imports = set()
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            else:
                imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    all_symbols = imports | calls
    for forbidden in ("subprocess", "groq", "abigail_hardened_enhanced"):
        assert forbidden not in all_symbols, (
            f"command_bus.py must not import '{forbidden}'"
        )
    # eval/exec are builtins — check AST for direct calls
    assert "eval" not in calls, "command_bus.py must not call eval()"
    assert "exec" not in calls, "command_bus.py must not call exec()"
    # process_message must not be imported from abigail_hardened_enhanced
    assert "process_message" not in imports, (
        "command_bus.py must not import process_message (circular import risk)"
    )
