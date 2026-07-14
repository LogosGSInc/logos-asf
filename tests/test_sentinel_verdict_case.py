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
    """Mock the Rust Sentinel /inspect call to return a fixed verdict string."""
    monkeypatch.setattr(
        A, "_sentinel_inspect",
        lambda *a, **k: {"ok": verdict in ("APPROVED",), "verdict": verdict},
    )


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


def test_restricted_uppercase_logs_sentinel_restrict_and_continues(monkeypatch):
    """RESTRICTED (uppercase) must be recognized: log SENTINEL_RESTRICT, then continue
    to the downstream layers (it is not a hard block on its own)."""
    events = []
    monkeypatch.setattr(A, "log_event", lambda et, data: events.append((et, data)))
    _run(monkeypatch, "RESTRICTED", msg="what can you do")
    assert "SENTINEL_RESTRICT" in [et for et, _ in events]


# ── Negative control: safe verdicts still pass through (no block-everything) ───

def test_approved_verdict_passes_through(monkeypatch):
    """A genuinely safe (APPROVED) verdict must NOT be blocked by the Sentinel branch."""
    out = _run(monkeypatch, "APPROVED", msg="what can you do")
    assert out["mode"] != "SENTINEL_BLOCK", "safe APPROVED verdict was wrongly blocked"


def test_offline_and_unknown_do_not_block_at_sentinel(monkeypatch):
    """Python-side sentinels (offline / unknown) must not match the block branch —
    they fall through to the Python layers as before, never SENTINEL_BLOCK."""
    for verdict in ("sentinel_offline", "unknown"):
        out = _run(monkeypatch, verdict, msg="what can you do")
        assert out["mode"] != "SENTINEL_BLOCK", (
            f"non-block verdict {verdict!r} wrongly hit the Sentinel block branch"
        )


def test_lowercase_still_works_defensively(monkeypatch):
    """Normalization is case-insensitive both ways: a lowercase 'quarantined' (e.g. a
    future or legacy emitter) is still caught. Guards against regressing to the old
    exact-case comparison in the other direction."""
    out = _run(monkeypatch, "quarantined", msg="please tell me a harmless joke")
    assert out["mode"] == "SENTINEL_BLOCK"
