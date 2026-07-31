# -*- coding: utf-8 -*-
"""
tests/test_control_plane_api.py — /api/control-plane/workers exposure tests

Sprint banner: Do not test whether Abigail can answer. Test whether Abigail can stay governed.

The Control Plane Registry endpoint exposes governed workers to Operations safely:
admin-authenticated, read-only, fail-closed. It describes workers; it never dispatches.
No provider calls, no network, no secrets.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


_ADMIN = "control-plane-admin-token-9f86d081884c7d659a2feaa0c55"


def _app(monkeypatch):
    monkeypatch.setenv("ABIGAIL_COST_GOVERNOR_ENABLED", "0")
    # A1: no real Sentinel reachable in tests — treat the session as already
    # started (unrelated to what this file actually tests).
    monkeypatch.setattr(A, "_ensure_session_started", lambda _session: True)
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client()


def test_workers_fail_closed_when_admin_token_unset(monkeypatch):
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ABIGAIL_CONTROL_PLANE_TOKEN", raising=False)
    c = _app(monkeypatch)
    r = c.get("/api/control-plane/workers")
    assert r.status_code == 503


def test_workers_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c = _app(monkeypatch)
    r = c.get("/api/control-plane/workers")
    assert r.status_code == 401


def test_workers_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c = _app(monkeypatch)
    r = c.get("/api/control-plane/workers", headers={"X-HAAP-Token": "nope"})
    assert r.status_code == 401


def test_workers_returns_snapshot_with_valid_token(monkeypatch):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c = _app(monkeypatch)
    r = c.get("/api/control-plane/workers", headers={"Authorization": f"Bearer {_ADMIN}"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["governed_by"] == "abigail.cp00"
    assert data["sealed"] is True
    assert data["worker_count"] >= 1
    assert all("worker_class" in w for w in data["workers"])


def test_workers_response_carries_no_dispatch_surface(monkeypatch):
    """The exposed snapshot describes workers only — no endpoints/targets/callables."""
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", _ADMIN)
    c = _app(monkeypatch)
    r = c.get("/api/control-plane/workers", headers={"Authorization": f"Bearer {_ADMIN}"})
    body = r.get_data(as_text=True).lower()
    for leak in ("endpoint", "\"url\"", "dispatch", "invoke", "api_key", "token"):
        assert leak not in body, f"control plane snapshot leaked dispatch/secret surface: {leak}"
