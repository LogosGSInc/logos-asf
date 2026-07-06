# -*- coding: utf-8 -*-
"""
test_sentinel_client_auth.py — SEC-03 DOCK-02 (Abigail side).

Abigail must authenticate to the Sentinel governance control plane: the /inspect
call carries the X-Sentinel-Token header (value from SENTINEL_ADMIN_TOKEN), the
/health call does NOT, and the token value is never written to the audit log.

No live server, no network: httpx is monkeypatched.
"""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

TOKEN = "TESTTOK_sentinel_123"


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_inspect_sends_x_sentinel_token(monkeypatch):
    monkeypatch.setenv("SENTINEL_ADMIN_TOKEN", TOKEN)
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _Resp({"ok": True, "verdict": "unknown", "approved": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = A._sentinel_inspect("hello world", "sess-1")
    assert out["ok"] is True
    assert seen["headers"].get("X-Sentinel-Token") == TOKEN
    assert seen["url"].endswith("/inspect")


def test_inspect_sends_no_token_header_when_unset(monkeypatch):
    monkeypatch.delenv("SENTINEL_ADMIN_TOKEN", raising=False)
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["headers"] = headers or {}
        return _Resp({"ok": True, "verdict": "unknown"})

    monkeypatch.setattr(httpx, "post", fake_post)
    A._sentinel_inspect("hi", "s")
    # no empty/None token leaked as a header when not configured
    assert "X-Sentinel-Token" not in seen["headers"]


def test_health_does_not_send_token(monkeypatch):
    monkeypatch.setenv("SENTINEL_ADMIN_TOKEN", TOKEN)
    seen = {}

    def fake_get(url, timeout=None, headers=None):
        seen["headers"] = headers or {}
        return _Resp({"ok": True, "service": "sentinel-overwatch"})

    monkeypatch.setattr(httpx, "get", fake_get)
    out = A._sentinel_health()
    assert out["ok"] is True
    assert "X-Sentinel-Token" not in seen["headers"]


def test_inspect_error_never_logs_token(monkeypatch):
    monkeypatch.setenv("SENTINEL_ADMIN_TOKEN", TOKEN)

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(httpx, "post", boom)
    logs = []
    monkeypatch.setattr(A, "log_event", lambda ev, payload=None: logs.append((ev, payload)))
    out = A._sentinel_inspect("hi", "s")
    # fail-soft: degrades, does not crash
    assert out["approved"] is False
    assert out["verdict"] == "sentinel_offline"
    # the token must never appear in any audit payload
    assert TOKEN not in str(logs)
