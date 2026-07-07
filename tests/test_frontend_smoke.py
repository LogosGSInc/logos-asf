# -*- coding: utf-8 -*-
"""
test_frontend_smoke.py — Abigail Command Center frontend smoke (Layer 1).

Servable-HTML smoke via the Flask test client + JS syntax check. No browser
automation (Layer 2 deferred). Enforces the governed-interface rules:
  - the new pages are served (200) with correct content types;
  - the 6-tab IA and brand are present;
  - a data-provenance system is present (badges + helper);
  - NO privileged/destructive action controls in the default DOM;
  - NO raw /api/* endpoint paths surfaced in the page markup (copy);
  - the app JS parses (node --check).
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "static"
sys.path.insert(0, str(ROOT / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402


def _client():
    app = A.build_web_app(A.SessionState(), A.KillSwitch(), ["groq"])
    app.testing = True
    return app.test_client()


# ── served assets ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,ctype", [
    ("/abigail.html", "text/html"),
    ("/abigail.css", "text/css"),
    ("/abigail.js", "javascript"),
])
def test_assets_served(path, ctype):
    r = _client().get(path)
    assert r.status_code == 200
    assert ctype in r.headers.get("Content-Type", "")
    assert len(r.get_data()) > 0


# ── information architecture ─────────────────────────────────────────────────
def test_six_tab_ia_present():
    html = (STATIC / "abigail.html").read_text(encoding="utf-8")
    for tab in ["home", "workspace", "operations", "governance", "observability", "settings"]:
        assert f'data-tab="{tab}"' in html, f"missing tab: {tab}"


def test_brand_is_abigail():
    html = (STATIC / "abigail.html").read_text(encoding="utf-8")
    assert "Abigail" in html
    # the console should not present itself as the old product name
    assert "LOGOS ASF" not in html


# ── provenance system present ────────────────────────────────────────────────
def test_provenance_system_present():
    css = (STATIC / "abigail.css").read_text(encoding="utf-8")
    js = (STATIC / "abigail.js").read_text(encoding="utf-8")
    for kind in ["live", "simulated", "cached", "offline", "local", "remote"]:
        assert f".prov.{kind}" in css, f"missing prov style: {kind}"
    assert "function provBadge" in js
    # briefing must not hardcode a fabricated live count without a badge helper
    assert "provBadge(" in js


# ── attack surface: no privileged controls in the default experience ─────────
def test_no_privileged_controls_in_markup():
    html = (STATIC / "abigail.html").read_text(encoding="utf-8")
    lowered = html.lower()
    for danger in ["kill agent", "restart department", "operator reset",
                   "reload registry", "rollback", "kill switch"]:
        assert danger not in lowered, f"privileged control leaked into default DOM: {danger}"


def test_no_raw_api_paths_in_page_copy():
    # API paths belong in abigail.js (the client), never surfaced in the HTML copy.
    html = (STATIC / "abigail.html").read_text(encoding="utf-8")
    assert "/api/" not in html


# ── advanced mode + confirm/reason are reveal-only scaffolding ───────────────
def test_advanced_mode_and_reason_modal_scaffolding():
    html = (STATIC / "abigail.html").read_text(encoding="utf-8")
    js = (STATIC / "abigail.js").read_text(encoding="utf-8")
    assert 'id="advToggle"' in html and 'id="modalReason"' in html
    # advanced mode reveals only; grants nothing (documented + reason required)
    assert "grants nothing" in js.lower()
    assert "reason is REQUIRED" in js or "reason is required" in js.lower()


# ── JS parses ────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_app_js_syntax_ok():
    r = subprocess.run(["node", "--check", str(STATIC / "abigail.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
