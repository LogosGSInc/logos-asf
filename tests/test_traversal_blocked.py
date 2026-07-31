# -*- coding: utf-8 -*-
"""
test_traversal_blocked.py — F1 boundary closure, Phase 1.

The catch-all static route (`/<path:filename>` in build_web_app) joins the
request path onto STATIC_DIR with plain os.path.join and never checks the
resolved path stays inside STATIC_DIR. Confirmed against a live Flask
3.1.3 / Werkzeug 3.1.7 instance at /app/static depth: several encodings of
`../` escape the static root and read arbitrary files (repo secrets,
/etc/passwd) back through the HTTP response body.

This file is the red baseline: the LEAK_VECTORS all currently return 200
with file content instead of 404. It must go green once static_files()
resolves the joined path and rejects anything outside STATIC_DIR.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


@pytest.fixture
def client():
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app.test_client()


# Currently leak file content (200) — must 404 once the static route
# contains the resolved path to STATIC_DIR.
LEAK_VECTORS = [
    "/../.abigail.env",
    "/../.env",
    "/../.abigail.env.bak.20260721_155014",
    "/%2e%2e%2f.abigail.env",
    "/..%2f.abigail.env",
    "/./../.abigail.env",
    "/../../etc/passwd",
    "/%2e%2e/%2e%2e/etc/passwd",
]

# Already 404 today — asserted so the fix doesn't become over-broad and
# start rejecting requests Werkzeug/Flask already normalize or refuse.
ALREADY_BLOCKED_VECTORS = [
    "/....//.abigail.env",
    "/..%252f.abigail.env",
    "/..%5c.abigail.env",
    "/static/../../.abigail.env",
]


@pytest.mark.parametrize("path", LEAK_VECTORS)
def test_traversal_blocked(client, path):
    resp = client.get(path)
    assert resp.status_code == 404, f"{path} returned {resp.status_code}, expected 404"
    body = resp.data
    assert b"GROQ_API_KEY" not in body
    assert b"root:" not in body


@pytest.mark.parametrize("path", ALREADY_BLOCKED_VECTORS)
def test_traversal_already_blocked_stays_blocked(client, path):
    resp = client.get(path)
    assert resp.status_code == 404, f"{path} returned {resp.status_code}, expected 404"


def test_static_control_still_served(client):
    resp = client.get("/abigail.html")
    assert resp.status_code == 200
    assert b"GROQ_API_KEY" not in resp.data
    assert b"root:" not in resp.data
