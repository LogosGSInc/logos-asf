# -*- coding: utf-8 -*-
"""
test_static_path_traversal.py — EP-01 regression (SEC-03 Critical).

The static-file route (`/<path:filename>`) must not allow unauthenticated path
traversal / arbitrary file read. The original defect served
`open(os.path.join(STATIC_DIR, filename))` with no containment, so
`GET /../../../../etc/passwd` (raw PATH_INFO) returned 200 and leaked the file —
which would expose ~/.abigail.env (provider keys + admin/demo tokens).

These tests exercise BOTH layers:
  1. the explicit containment helper `_safe_static_relpath` (unit), and
  2. the live WSGI route with a RAW PATH_INFO carrying `..` (integration) —
     ordinary clients normalize `..`, so we inject PATH_INFO via
     `environ_overrides`, reproducing the `curl --path-as-is` exploit exactly.

No network, no secrets, no provider calls.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

REPO_STATIC = os.path.realpath(str(Path(__file__).parent.parent / "static"))


def _client():
    ks = A.KillSwitch()
    sess = A.SessionState()
    app = A.build_web_app(sess, ks, ["groq"])
    app.testing = True
    return app.test_client()


def _raw_get(client, raw_path):
    """Issue a GET whose PATH_INFO is `raw_path` verbatim (bypassing client-side
    `..` normalization) — this is the `curl --path-as-is` attack surface."""
    return client.get("/", environ_overrides={"PATH_INFO": raw_path,
                                              "RAW_URI": raw_path})


# ── unit: containment helper ─────────────────────────────────────────────────
def test_helper_allows_real_asset():
    assert A._safe_static_relpath(REPO_STATIC, "index.html") == "index.html"
    assert A._safe_static_relpath(REPO_STATIC, "dashboard.html") == "dashboard.html"


@pytest.mark.parametrize("bad", [
    "../../../../etc/passwd",
    "../../etc/passwd",
    "..",
    "../abigail/abigail_hardened_enhanced.py",   # escape to source tree
    "subdir/../../etc/passwd",
    "/etc/passwd",                                # absolute
    "/etc/shadow",
    "",                                           # empty
    "./../../etc/hostname",
])
def test_helper_rejects_traversal_and_absolute(bad):
    assert A._safe_static_relpath(REPO_STATIC, bad) is None


def test_helper_rejects_nonexistent_within_root():
    assert A._safe_static_relpath(REPO_STATIC, "does_not_exist.html") is None


def test_helper_rejects_directory_itself():
    # the root dir is not a file
    assert A._safe_static_relpath(REPO_STATIC, ".") is None


# ── integration: live route with raw traversal PATH_INFO ─────────────────────
@pytest.mark.parametrize("raw", [
    "/../../../../etc/passwd",
    "/../../../../etc/hostname",
    "/../../etc/passwd",
    "/../abigail/abigail_hardened_enhanced.py",
    "/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd",   # encoded variant
    "/..%2f..%2f..%2fetc%2fpasswd",
])
def test_route_blocks_traversal_raw_pathinfo(raw):
    c = _client()
    r = _raw_get(c, raw)
    assert r.status_code == 404, f"traversal not blocked for {raw!r}"
    body = r.get_data(as_text=True)
    assert "root:" not in body           # /etc/passwd content never leaks
    assert "def build_web_app" not in body  # source content never leaks


def test_route_blocks_absolute_path():
    c = _client()
    r = _raw_get(c, "/etc/passwd")
    # absolute PATH_INFO resolves to the abs file only if traversal allowed;
    # containment + send_from_directory must refuse.
    assert r.status_code == 404
    assert "root:" not in r.get_data(as_text=True)


# ── functional regression: legit assets still served ─────────────────────────
@pytest.mark.parametrize("asset,ctype_frag", [
    ("dashboard.html", "text/html"),
    ("operator.html", "text/html"),
])
def test_legit_static_asset_still_served(asset, ctype_frag):
    c = _client()
    r = c.get("/" + asset)
    assert r.status_code == 200
    assert ctype_frag in r.headers.get("Content-Type", "")
    assert len(r.get_data()) > 0


def test_index_still_served():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    assert len(r.get_data()) > 0


def test_unknown_asset_returns_404():
    c = _client()
    assert c.get("/nope.css").status_code == 404
