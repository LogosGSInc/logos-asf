# -*- coding: utf-8 -*-
"""
test_skills_discovery.py — SKILLS-01 P3 read-only discovery tests.

Proves the loader/indexer is clean before any runtime wiring (P4):
  - index is metadata-only (no bodies, no activation/negative triggers);
  - load_skill_body is path-contained (rejects traversal/absolute/non-SKILL.md);
  - department-scoped selection with negative-trigger suppression;
  - deterministic; no exec/subprocess/network; yaml.safe_load only;
  - no committed manifest.json; emit_manifest writes metadata-only to an explicit dest.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "abigail"))
from skills_lib import discovery as D  # noqa: E402

META_FIELDS = {"name", "description", "department", "authority_level", "risk_level", "path"}


# ── index is metadata-only ────────────────────────────────────────────────────
def test_index_has_ten_metadata_only_entries():
    idx = D.build_index()
    assert len(idx) == 10
    for e in idx:
        assert set(e.keys()) == META_FIELDS, f"non-metadata keys: {set(e.keys()) - META_FIELDS}"
        assert e["authority_level"] == "advisory"
        assert e["risk_level"] in ("low", "medium", "high")
        assert e["path"].startswith("skills/") and e["path"].endswith("/SKILL.md")
        assert (ROOT / e["path"]).exists()


def test_index_never_exposes_body_or_triggers():
    for e in D.build_index():
        for banned in ("activation_examples", "negative_activation_examples",
                       "allowed_actions", "procedure", "body", "inputs", "outputs"):
            assert banned not in e


def test_index_is_deterministic():
    assert D.build_index() == D.build_index()


# ── path containment ──────────────────────────────────────────────────────────
def test_load_body_valid():
    body = D.load_skill_body("skills/ENG/code-reviewer/SKILL.md")
    assert body and "## Purpose" in body and "## Governance Rules" in body


@pytest.mark.parametrize("bad", [
    "skills/ENG/code-reviewer/../../../../etc/passwd",
    "/etc/passwd",
    "skills/../abigail/abigail_hardened_enhanced.py",
    "skills/ENG/code-reviewer/scripts/run.sh",   # non-SKILL.md / would-be script
    "skills/ENG/code-reviewer/README.md",
    "",
])
def test_load_body_rejects_escapes_and_non_skill(bad):
    assert D.load_skill_body(bad) is None


# ── department-scoped selection + negative suppression ───────────────────────
def test_select_matches_in_department():
    sel = D.select_skill("ENG", "please review this diff for bugs")
    assert sel is not None and sel["name"] == "code-reviewer"
    assert set(sel.keys()) == META_FIELDS   # selection returns metadata only


def test_select_respects_department_scope():
    # ENG-style request in SEC department → no SEC skill matches
    assert D.select_skill("SEC", "write a commit message") is None


def test_select_negative_trigger_suppresses():
    # "commit this for me" is a negative example for ENG skills → suppressed
    assert D.select_skill("ENG", "commit this for me") is None


def test_select_none_without_department_or_text():
    assert D.select_skill(None, "review this") is None
    assert D.select_skill("ENG", "") is None


# ── safety: no exec / no network / safe_load only ────────────────────────────
def test_module_source_is_read_only_safe():
    src = (ROOT / "abigail" / "skills_lib" / "discovery.py").read_text(encoding="utf-8")
    for banned in ["exec(", "eval(", "subprocess", "os.system", "popen",
                   "requests.", "httpx", "urllib", "socket"]:
        assert banned not in src, f"discovery.py must not contain '{banned}'"
    assert "yaml.safe_load" in src
    assert "yaml.load(" not in src   # never the unsafe loader


# ── manifest: no committed truth; emit is metadata-only + refuses skills/ ─────
def test_no_committed_manifest_json():
    assert not (ROOT / "skills" / "manifest.json").exists()


def test_emit_manifest_metadata_only(tmp_path):
    dest = tmp_path / "manifest.json"
    D.emit_manifest(dest, generated="TEST")
    data = json.loads(dest.read_text())
    assert data["version"] == 1 and data["generated"] == "TEST"
    for e in data["skills"]:
        assert set(e.keys()) == META_FIELDS
    # schema example (committed) still validates shape-wise against what we emit
    assert len(data["skills"]) == 10


def test_emit_manifest_refuses_committed_path():
    with pytest.raises(ValueError):
        D.emit_manifest(D.SKILLS_DIR / "manifest.json")
