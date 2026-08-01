# -*- coding: utf-8 -*-
"""
tests/test_sentinel_verdict_case.py — Layer-0: Sentinel verdict case-match enforcement

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

The Rust Sentinel server (governance-spine/src/server.rs) serializes UPPERCASE verdicts
("APPROVED" / "RESTRICTED" / "QUARANTINED" / "HARD_LOCKED"). Python compared against
lowercase literals, so Sentinel's authoritative block was computed then discarded —
enforcement silently fell through to the weaker Python regex layer. These tests prove
the case-normalized comparison now actually fires the Sentinel block branch, and that a
genuinely safe verdict still passes through (no block-everything regression).

No provider calls, no network — _sentinel_inspect is mocked. No secrets.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


class _Sess:
    def __init__(self):
        self.turn_count = 0
    def crsv(self):
        return 0.0
    def record_turn(self, *a, **k):
        self.turn_count += 1
    def drift_warning(self):
        return None


def _mock_sentinel(monkeypatch, verdict):
    """Mock the Rust Sentinel /inspect call with authoritative approval evidence."""
    def _result(_payload, session_id, **_kw):
        result = {
            "ok": verdict == "APPROVED",
            "verdict": verdict,
            "session_id": session_id,
        }
        if verdict == "APPROVED":
            result.update({
                "approved": True,
                "provider_authorizable": True,
                "gov_tx_id": "gov-tx-verdict-test",
                "verdict_id": "verdict-case-test",
            })
        return result

    monkeypatch.setattr(A, "_sentinel_inspect", _result)


def _run(monkeypatch, verdict, msg="benign hello, how are you"):
    _mock_sentinel(monkeypatch, verdict)
    return A.process_message(msg, _Sess(), A.KillSwitch(), ["groq"])


# ── Positive: uppercase Rust verdicts now trigger the Sentinel block branch ────

@pytest.mark.parametrize("verdict", ["QUARANTINED", "HARD_LOCKED"])
def test_uppercase_block_verdicts_fire_sentinel_block(monkeypatch, verdict):
    """An uppercase Rust block verdict must produce a SENTINEL_BLOCK response —
    not fall through to the regex layer. This is the bug the fix closes."""
    out = _run(monkeypatch, verdict, msg="please tell me a harmless joke")
    assert out["ok"] is False
    assert out["mode"] == "SENTINEL_BLOCK", (
        f"verdict {verdict!r} did not trigger Sentinel block — "
        f"got mode {out['mode']!r} (enforcement fell through)"
    )


def test_block_attributed_to_sentinel_in_audit(monkeypatch, tmp_path):
    """The block must be attributed to Sentinel (SENTINEL_BLOCK event) — proving the
    authoritative layer caught it, not the Python regex (which logs REQUEST_BLOCKED)."""
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    out = _run(monkeypatch, "QUARANTINED", msg="please tell me a harmless joke")
    assert out["mode"] == "SENTINEL_BLOCK"
    types = [et for et, _ in events]
    assert "SENTINEL_BLOCK" in types, f"no SENTINEL_BLOCK audit event; got {types}"
    assert "REQUEST_BLOCKED" not in types, (
        "block was attributed to the Python regex layer (REQUEST_BLOCKED), "
        "not Sentinel — the illusion is still present"
    )
    # Raw uppercase verdict preserved verbatim in the audit entry (fidelity).
    sentinel_evt = dict(events)["SENTINEL_BLOCK"]
    assert sentinel_evt["verdict"] == "QUARANTINED"


def test_restricted_requires_step_up_and_blocks_without_it(monkeypatch):
    """P0-2: RESTRICTED routes to a step-up gate — it does NOT continue as normal.
    Without a valid step-up the request is stopped (STEP_UP_REQUIRED)."""
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    out = _run(monkeypatch, "RESTRICTED", msg="what can you do")
    assert out["ok"] is False
    assert out["mode"] == "STEP_UP_REQUIRED"
    assert "SENTINEL_STEP_UP_REQUIRED" in [et for et, _ in events]


def test_restricted_step_up_does_not_create_provider_authority(monkeypatch):
    """A Python step-up assertion cannot convert RESTRICTED into execution authority."""
    events = []
    monkeypatch.setattr(
        A,
        "log_event",
        lambda event_type, data: events.append((event_type, data)),
    )
    _mock_sentinel(monkeypatch, "RESTRICTED")

    out = A.process_message(
        "what can you do",
        _Sess(),
        A.KillSwitch(),
        ["groq"],
        step_up_ok=True,
    )

    assert out["ok"] is False
    assert out["mode"] == "STEP_UP_REQUIRED"
    assert "SENTINEL_STEP_UP_REQUIRED" in [
        event_type for event_type, _data in events
    ]
    assert "SENTINEL_RESTRICT_STEPUP_CLEARED" not in [
        event_type for event_type, _data in events
    ]


def test_haap_gated_blocks(monkeypatch):
    """P0-2: HAAP_GATED must block pending human re-authorization, never silently pass."""
    out = _run(monkeypatch, "HAAP_GATED", msg="what can you do")
    assert out["ok"] is False and out["mode"] == "HAAP_GATED"


# ── Negative control: safe verdicts still pass through (no block-everything) ───

def test_approved_verdict_passes_through(monkeypatch):
    """A genuinely safe (APPROVED) verdict must NOT be blocked by the Sentinel branch."""
    out = _run(monkeypatch, "APPROVED", msg="what can you do")
    assert out["mode"] not in ("SENTINEL_BLOCK", "SENTINEL_UNREACHABLE", "STEP_UP_REQUIRED",
                               "HAAP_GATED"), "safe APPROVED verdict was wrongly blocked"


# ── P0-1/P0-2: fail-closed — offline and unrecognized verdicts now BLOCK ───────

def test_offline_sentinel_fails_closed_when_required(monkeypatch):
    """P0-1: an unreachable Sentinel (verdict sentinel_offline) hard-blocks by default
    (SENTINEL_REQUIRED) — it does NOT silently downgrade to the Python regex layer."""
    monkeypatch.setattr(A, "SENTINEL_REQUIRED", True)
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    out = _run(monkeypatch, "sentinel_offline", msg="what can you do")
    assert out["ok"] is False
    assert out["mode"] == "SENTINEL_UNREACHABLE"
    assert "SENTINEL_UNREACHABLE_BLOCK" in [et for et, _ in events]


def test_offline_sentinel_degraded_open_when_opted_out(monkeypatch):
    """P0-1: with the explicit opt-out (SENTINEL_REQUIRED=0) an offline Sentinel proceeds
    on the Python backstop — but the skip is audited, never silent."""
    monkeypatch.setattr(A, "SENTINEL_REQUIRED", False)
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    out = _run(monkeypatch, "sentinel_offline", msg="what can you do")
    assert out["mode"] not in ("SENTINEL_UNREACHABLE",)
    assert "SENTINEL_DEGRADED_OPEN" in [et for et, _ in events]


def test_unknown_verdict_fails_closed(monkeypatch):
    """P0-2: any unrecognized non-APPROVED verdict fails closed (no implicit allow)."""
    out = _run(monkeypatch, "unknown", msg="what can you do")
    assert out["ok"] is False and out["mode"] == "SENTINEL_BLOCK"


def test_lowercase_still_works_defensively(monkeypatch):
    """Normalization is case-insensitive both ways: a lowercase 'quarantined' (e.g. a
    future or legacy emitter) is still caught. Guards against regressing to the old
    exact-case comparison in the other direction."""
    out = _run(monkeypatch, "quarantined", msg="please tell me a harmless joke")
    assert out["mode"] == "SENTINEL_BLOCK"
