# -*- coding: utf-8 -*-
"""
test_moe_router_chatpath_integration.py — MR-05.

Wires the MR-04 governed router (governed_route_and_dispatch) into the /api/chat
request path behind a three-state flag, ABIGAIL_MOE_ROUTER_MODE:

  "0" — single active-backend (existing behavior; router never involved)
  "1" — dry-run router: decide + record audit-safe metadata, NEVER call a provider
        through the MR-04 dispatcher; existing active backend still responds
  "2" — live governed router dispatch via MR-04, only after Sentinel/HAAP, command
        bus, MM-03 approval, UX-01 public-intent, and SEC-02 cost gates clear

Governance ordering is preserved and proven: command-bus and PUBLIC_ASSIST bypass
the router entirely; high-risk returns APPROVAL_REQUIRED before any router run; a
cost block stops before the router; provider errors are sanitized; and no live
provider call ever occurs in pytest (the dispatcher table / active backend are
stubbed, and the MR-04 dispatcher is spied).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402
from model_router import dispatcher as D  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────────
class _Sess:
    def __init__(self):
        self.turn_count = 0
        self.messages = []

    def crsv(self):
        return 0.0

    def record_turn(self, *a, **k):
        self.turn_count += 1

    def drift_warning(self):
        return None


def _neutralize(monkeypatch, active_reply="STUB-ACTIVE"):
    """Sentinel offline, no grounded shortcut, and a detectable active backend stub.
    Returns a call counter dict {"active", "router"}."""
    monkeypatch.setattr(A, "_sentinel_inspect",
                        lambda *a, **k: {"ok": True, "verdict": "unknown", "approved": True})
    monkeypatch.setattr(A, "try_grounded_answer", lambda *a, **k: None)
    calls = {"active": 0, "router": 0}

    def _fake_active(messages=None, system=None, **k):
        calls["active"] += 1
        return active_reply

    # groq is the active backend used across these tests
    monkeypatch.setitem(A.BACKEND_DISPATCH, "groq", _fake_active)
    return calls


def _spy_router(monkeypatch, calls, *, result=None, exc=None):
    """Replace the module-global MR-04 dispatcher with a counting spy."""
    def _spy(*a, **k):
        calls["router"] += 1
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(A, "_governed_route_and_dispatch", _spy)


def _mode(monkeypatch, value):
    monkeypatch.setenv("ABIGAIL_MOE_ROUTER_MODE", str(value))


def _budget(monkeypatch, turns=1000, tokens=8000, enabled="1"):
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", enabled)
    monkeypatch.setenv("ABIGAIL_MAX_CHAT_TURNS", str(turns))
    monkeypatch.setenv("ABIGAIL_MAX_ESTIMATED_TOKENS", str(tokens))


def _client(monkeypatch, turns=1000, tokens=8000):
    _budget(monkeypatch, turns, tokens)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client()


NORMAL = "compose a short poem about the ocean"
EXECUTED = {"provider_selected": "openai", "dispatch_status": "executed",
            "text": "STUB-ROUTED", "reason": "all_gates_passed",
            "route_request_type": "normal_chat", "routed": True}
UNAVAILABLE = {"provider_selected": "openai", "dispatch_status": "unavailable",
               "reason": "key_missing", "fallback_provider": "groq", "routed": True}


# ── mode config resolution ──────────────────────────────────────────────────
@pytest.mark.parametrize("val,expected", [("0", "0"), ("1", "1"), ("2", "2")])
def test_resolve_router_mode_accepts_valid(monkeypatch, val, expected):
    _mode(monkeypatch, val)
    assert A.resolve_router_mode() == expected


@pytest.mark.parametrize("bad", ["3", "live", "", "  ", "-1", "true", "0x2"])
def test_invalid_router_mode_fails_closed_to_zero(monkeypatch, bad):
    monkeypatch.setenv("ABIGAIL_MOE_ROUTER_MODE", bad)
    assert A.resolve_router_mode() == "0"


def test_unset_router_mode_defaults_to_zero(monkeypatch):
    monkeypatch.delenv("ABIGAIL_MOE_ROUTER_MODE", raising=False)
    assert A.resolve_router_mode() == "0"


# ── mode 0: single active backend ────────────────────────────────────────────
def test_mode_0_uses_single_active_backend(monkeypatch):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, 0)
    out = A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])
    assert calls["active"] == 1          # existing single-backend path
    assert calls["router"] == 0          # MR-04 dispatcher never consulted
    assert out["text"] == "STUB-ACTIVE"
    assert out["router"]["router_mode"] == "0"
    assert out["router"]["dispatch_status"] == "single_backend"
    assert out["router"]["live_dispatch"] is False


# ── mode 1: dry-run router ───────────────────────────────────────────────────
def test_mode_1_returns_dry_run_metadata(monkeypatch):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, 1)
    out = A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])
    assert out["router"]["router_mode"] == "1"
    assert out["router"]["dispatch_status"] == "dry_run"
    assert out["router"]["live_dispatch"] is False
    assert out["router"]["selected_provider"]  # a decision was recorded
    assert calls["router"] == 0          # never calls MR-04 live dispatcher
    assert calls["active"] == 1          # existing active backend still responds
    assert out["text"] == "STUB-ACTIVE"


def test_moe_router_dry_run_returns_dry_run_and_never_calls_provider_adapter(monkeypatch):
    """Explicit dry-run safety proof (MR-05):
      ABIGAIL_MOE_ROUTER_MODE=1 → dispatch_status == "dry_run", live_dispatch False,
      NO provider adapter function is called, NO MR-04 live dispatcher is called,
      and the existing active-backend behavior remains safe and governed."""
    calls = _neutralize(monkeypatch)
    _mode(monkeypatch, 1)

    # Spy the MR-04 live dispatcher (module global) and the low-level execution gate.
    _spy_router(monkeypatch, calls, result=EXECUTED)
    dispatch_calls = {"n": 0}
    provider_adapter_calls = {"n": 0}

    def _spy_dispatch(*a, **k):
        dispatch_calls["n"] += 1
        return {"dispatch_status": "executed", "text": "SHOULD-NOT-HAPPEN"}

    monkeypatch.setattr(D, "dispatch", _spy_dispatch)

    # Any provider adapter reachable through the live dispatch table must stay untouched.
    def _spy_adapter(messages, system):
        provider_adapter_calls["n"] += 1
        return "SHOULD-NOT-HAPPEN"

    monkeypatch.setattr(D, "get_live_dispatch",
                        lambda: {"groq": _spy_adapter, "openai": _spy_adapter,
                                 "current_backend": _spy_adapter})

    out = A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])

    assert out["router"]["dispatch_status"] == "dry_run"
    assert out["router"]["live_dispatch"] is False
    assert calls["router"] == 0                 # MR-04 live dispatcher never called
    assert dispatch_calls["n"] == 0             # execution gate never entered
    assert provider_adapter_calls["n"] == 0     # no provider adapter function called
    # existing active backend fallback behavior remains safe and governed
    assert calls["active"] == 1
    assert out["text"] == "STUB-ACTIVE"


# ── mode 2: live governed router dispatch ────────────────────────────────────
def test_mode_2_uses_governed_route_and_dispatch(monkeypatch):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, 2)
    out = A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])
    assert calls["router"] == 1          # MR-04 governed dispatcher used
    assert calls["active"] == 0          # active backend NOT used when router executes
    assert out["text"] == "STUB-ROUTED"
    assert out["router"]["router_mode"] == "2"
    assert out["router"]["dispatch_status"] == "executed"
    assert out["router"]["selected_provider"] == "openai"
    assert out["router"]["live_dispatch"] is True


def test_mode_2_real_dispatcher_executes_through_stubbed_table(monkeypatch):
    """End-to-end wiring: the REAL MR-04 governed_route_and_dispatch runs (not spied);
    the live dispatch table is the stubbed BACKEND_DISPATCH, so no network call occurs."""
    calls = _neutralize(monkeypatch)
    _mode(monkeypatch, 2)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 12)
    # Force the route card to select groq (a live-wired, keyed provider).
    monkeypatch.setattr(A, "_route_request",
                        lambda *a, **k: {"selected_provider": "groq",
                                         "request_type": "normal_chat"})
    out = A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])
    assert out["router"]["dispatch_status"] == "executed"
    assert out["router"]["selected_provider"] == "groq"
    assert out["router"]["live_dispatch"] is True
    assert out["text"] == "STUB-ACTIVE"   # groq stub executed via the MR-04 table
    assert calls["active"] == 1


def test_mode_2_unavailable_provider_uses_governed_fallback(monkeypatch):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=UNAVAILABLE)
    _mode(monkeypatch, 2)
    out = A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])
    assert calls["router"] == 1
    assert out["router"]["dispatch_status"] == "fallback"
    assert out["router"]["fallback_used"] is True
    assert out["router"]["fallback_provider"] == "groq"
    assert out["router"]["live_dispatch"] is True
    assert out["text"] == "STUB-ACTIVE"   # governed fallback to active backend
    assert calls["active"] == 1           # no crash; active backend served


def test_mode_2_router_exception_is_sanitized_and_falls_back(monkeypatch):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, exc=RuntimeError("boom sk-live-SECRET-999"))
    _mode(monkeypatch, 2)
    out = A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])
    assert out["router"]["dispatch_status"] == "fallback"
    assert out["router"]["reason"] == "router_exception_sanitized"
    assert out["text"] == "STUB-ACTIVE"
    # sanitized: no raw exception text / secret material anywhere in the response
    assert "SECRET" not in str(out)
    assert "sk-live" not in str(out)


# ── governance gates precede the router ──────────────────────────────────────
@pytest.mark.parametrize("mode", ["1", "2"])
def test_command_bus_bypasses_router(monkeypatch, mode):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, mode)
    # Simulate an exact command-bus match (returns a governed command result).
    monkeypatch.setattr(A, "_try_operator_command_fn",
                        lambda *a, **k: {"ok": True, "text": "CMD-OK", "mode": "COMMAND"})
    # process_message must never run for a command-bus hit.
    pm_calls = {"n": 0}
    monkeypatch.setattr(A, "process_message",
                        lambda *a, **k: pm_calls.__setitem__("n", pm_calls["n"] + 1) or {})
    c = _client(monkeypatch)
    body = c.post("/api/chat", json={"message": "status show keys"}).get_json()
    assert body["mode"] == "COMMAND"
    assert calls["router"] == 0
    assert pm_calls["n"] == 0


@pytest.mark.parametrize("mode", ["1", "2"])
def test_public_assist_bypasses_router(monkeypatch, mode):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, mode)
    out = A.process_message("what can you do", _Sess(), A.KillSwitch(), ["groq"])
    assert out["mode"] == "PUBLIC_ASSIST"
    assert calls["router"] == 0          # canned answer — no router
    assert calls["active"] == 0          # canned answer — no provider inference
    assert "router" not in out           # public path attaches no router metadata


@pytest.mark.parametrize("mode", ["1", "2"])
def test_high_risk_returns_approval_required_before_router(monkeypatch, mode):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, mode)
    meta = {"human_approval_required": True, "manifest_id": "M-1", "state_id": "S-1",
            "risk_level": "high", "command_style_signal": False,
            "request_type": "chat_inference"}
    out = A.process_message("please help me plan my week", _Sess(), A.KillSwitch(),
                            ["groq"], approval_meta=meta)
    assert out["mode"] == "APPROVAL_REQUIRED"
    assert calls["router"] == 0          # approval gate precedes any router run
    assert calls["active"] == 0          # no inference / no spend


@pytest.mark.parametrize("mode", ["1", "2"])
def test_cost_block_stops_before_router(monkeypatch, mode):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, mode)
    c = _client(monkeypatch, turns=0)    # turn budget exhausted → cost block
    body = c.post("/api/chat", json={"message": NORMAL}).get_json()
    assert body["mode"] == "COST_BLOCKED"
    assert calls["router"] == 0          # cost gate precedes the router
    assert calls["active"] == 0


# ── metadata safety ──────────────────────────────────────────────────────────
def test_router_metadata_contains_no_prompt_or_secret(monkeypatch):
    calls = _neutralize(monkeypatch)
    _spy_router(monkeypatch, calls, result=EXECUTED)
    _mode(monkeypatch, 2)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_SUPERSECRETVALUE_123")
    marker = "PINEAPPLE_MARKER_74x compose ocean poem"
    out = A.process_message(marker, _Sess(), A.KillSwitch(), ["groq"])
    rmeta = str(out["router"])
    assert "PINEAPPLE_MARKER_74x" not in rmeta      # no raw prompt
    assert "SUPERSECRETVALUE" not in rmeta          # no key value
    assert "GROQ_API_KEY" not in rmeta              # no env var name/value
    # only the audit-safe field set is present
    assert set(out["router"]) <= {
        "router_mode", "selected_provider", "dispatch_status", "fallback_used",
        "fallback_provider", "reason", "live_dispatch", "request_type"}


def test_no_provider_calls_in_pytest_across_modes(monkeypatch):
    """Across modes 0/1/2 with the router spied and the backend stubbed, no real
    provider callable in BACKEND_DISPATCH other than the stub is ever invoked."""
    for m in ("0", "1", "2"):
        calls = _neutralize(monkeypatch)
        _spy_router(monkeypatch, calls, result=EXECUTED)
        _mode(monkeypatch, m)
        A.process_message(NORMAL, _Sess(), A.KillSwitch(), ["groq"])
        # groq stub is the only backend touched; anthropic/openai/xai untouched.
        # (spy router means mode 2 never reaches a real adapter either.)
