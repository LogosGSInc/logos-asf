# -*- coding: utf-8 -*-
"""
test_topology_auth.py — SEC-03 EP-03: authenticate topology endpoints.

The four topology routes must be admin-gated and fail closed:
  /api/agents/departments, /api/agents, /api/agents/<dept>/status, /api/agents/lifecycle
  - no token            -> 401
  - server token unset  -> 503 (fail closed)
  - valid token         -> 200

Regression guards: public routes stay unauthenticated; public UIs do not depend on
unauth topology; no new endpoint is added.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

ADMIN = "admintok_EP03"
TOPOLOGY = [
    "/api/agents/departments",
    "/api/agents",
    "/api/agents/ENG/status",   # ENG is a valid dept code (_normalize_dept)
    "/api/agents/lifecycle",
]
PUBLIC = ["/", "/api/status", "/api/sentinel-health"]


def _client():
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app.test_client()


# ── EP-03: topology is admin-gated, fail closed ──────────────────────────────
@pytest.mark.parametrize("route", TOPOLOGY)
def test_topology_requires_token(monkeypatch, route):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)
    r = _client().get(route)
    assert r.status_code == 401, f"{route} must 401 without a token"


@pytest.mark.parametrize("route", TOPOLOGY)
def test_topology_fails_closed_when_server_token_unset(monkeypatch, route):
    monkeypatch.delenv("ABIGAIL_ADMIN_TOKEN", raising=False)
    r = _client().get(route, headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503, f"{route} must 503 (fail closed) when server token unset"


@pytest.mark.parametrize("route", TOPOLOGY)
def test_topology_allows_valid_token(monkeypatch, route):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)
    r = _client().get(route, headers={"Authorization": f"Bearer {ADMIN}"})
    assert r.status_code == 200, f"{route} must 200 with a valid token"


@pytest.mark.parametrize("route", TOPOLOGY)
def test_topology_wrong_token_denied(monkeypatch, route):
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)
    r = _client().get(route, headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 401


# ── regression: public routes remain unauthenticated ─────────────────────────
@pytest.mark.parametrize("route", PUBLIC)
def test_public_routes_not_auth_gated(monkeypatch, route):
    # Public routes must not be auth-gated. (sentinel-health may 503 when Sentinel is
    # down in pytest — that's a health signal, not an auth gate.)
    monkeypatch.setenv("ABIGAIL_ADMIN_TOKEN", ADMIN)
    r = _client().get(route)
    assert r.status_code not in (401, 403), f"{route} must stay public (got {r.status_code})"


# ── invariant: public UIs do not depend on unauth topology ───────────────────
def test_public_uis_have_no_topology_calls():
    pat = re.compile(r"/api/agents/(departments|lifecycle|[^\"'/]+/status)")
    for name in ("index.html", "dashboard.html", "abigail.html", "abigail.js"):
        f = ROOT / "static" / name
        if f.exists():
            assert not pat.search(f.read_text(encoding="utf-8")), \
                f"public UI {name} must not call topology endpoints"


def test_operator_ui_sends_token_for_topology():
    op = (ROOT / "static" / "operator.html").read_text(encoding="utf-8")
    # operator surface sends the admin token and falls back to labeled mock otherwise
    assert "abigail.adminToken" in op
    assert "renderDeptNav(null, true)" in op


# ── no new endpoint introduced ───────────────────────────────────────────────
def test_route_count_unchanged():
    src = (ROOT / "abigail" / "abigail_hardened_enhanced.py").read_text(encoding="utf-8")
    assert src.count("@flask_app.route(") == 15
