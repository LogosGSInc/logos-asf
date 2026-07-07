# -*- coding: utf-8 -*-
"""
test_skills_library.py — SKILLS-01 P2 (author-only) lint & governance tests.

Validates the first-party minimum skills library WITHOUT any loader or runtime
wiring (deferred). Enforces the doctrine so nothing drifts before discovery is built:
  - every SKILL.md has required frontmatter + body sections and is token-light;
  - every skill is first-party licensed and department-scoped;
  - every skill is ADVISORY — allowed_actions contain no write/execute/deploy verbs;
  - negative activation examples exist (reduce false triggers);
  - NO scripts/ and no executable payloads exist in the library;
  - the manifest is schema+example only (no hand-authored truth manifest), the
    example validates against the schema, and it carries metadata only (no bodies).
"""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
SKILLS = ROOT / "skills"

REQUIRED_FRONTMATTER = [
    "name", "description", "department", "authority_level", "risk_level",
    "allowed_actions", "forbidden_actions", "inputs", "outputs",
    "activation_examples", "negative_activation_examples",
]
REQUIRED_SECTIONS = [
    "Purpose", "When to Use", "When Not to Use", "Inputs", "Outputs",
    "Governance Rules", "Procedure", "Audit Requirements", "Tests",
]
# Leading-verb forms that would make an allowed_action non-advisory. Matched
# against the FIRST token of a verb_object action (e.g. "modify_files" -> "modify"),
# so nouns like "..._commit_message_text" don't false-positive.
DANGEROUS_VERBS = {"write", "execute", "run", "deploy", "commit", "push", "kill",
                   "restart", "reset", "install", "fetch", "modify", "delete",
                   "scan", "exploit", "grant", "stage"}
DEPT_TO_ID = {"ENG": "DEPT-ENG", "SEC": "DEPT-SEC", "OPS": "DEPT-OPS", "GRC": "DEPT-GRC"}


def _skill_files():
    return sorted(SKILLS.rglob("SKILL.md"))


def _parse(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, f"{path}: missing YAML frontmatter block"
    fm = yaml.safe_load(m.group(1))
    return fm, m.group(2), text


def test_library_present():
    files = _skill_files()
    assert len(files) == 10, f"expected 10 skills, found {len(files)}"


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_frontmatter_complete(path):
    fm, _, text = _parse(path)
    for field in REQUIRED_FRONTMATTER:
        assert field in fm, f"{path}: missing frontmatter '{field}'"
    assert len(text.splitlines()) <= 500, f"{path}: over 500 lines (token budget)"
    assert isinstance(fm["description"], str) and len(fm["description"]) <= 600


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_body_sections_present(path):
    _, body, _ = _parse(path)
    for sec in REQUIRED_SECTIONS:
        assert re.search(r"^##\s+" + re.escape(sec) + r"\s*$", body, re.M), \
            f"{path}: missing body section '## {sec}'"


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_first_party_and_license(path):
    fm, _, _ = _parse(path)
    assert fm.get("source") == "first-party", f"{path}: must be source: first-party"
    assert fm.get("license"), f"{path}: license required"


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_department_scoped(path):
    fm, _, _ = _parse(path)
    dept = path.relative_to(SKILLS).parts[0]           # skills/<DEPT>/<skill>/SKILL.md
    assert fm["department"] == dept, f"{path}: department '{fm['department']}' != folder '{dept}'"
    assert fm.get("department_id") == DEPT_TO_ID.get(dept), f"{path}: department_id mismatch"


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_advisory_only_no_dangerous_allowed_actions(path):
    fm, _, _ = _parse(path)
    assert fm["authority_level"] == "advisory", f"{path}: must be advisory"
    assert fm["risk_level"] in ("low", "medium", "high")
    for act in fm["allowed_actions"]:
        lead = str(act).lower().split("_")[0]   # verb_object → verb
        assert lead not in DANGEROUS_VERBS, \
            f"{path}: allowed_action '{act}' has privileged leading verb '{lead}'"


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: str(p.relative_to(SKILLS)))
def test_negative_activation_present(path):
    fm, _, _ = _parse(path)
    neg = fm.get("negative_activation_examples")
    assert isinstance(neg, list) and len(neg) >= 1, f"{path}: needs negative_activation_examples"
    pos = fm.get("activation_examples")
    assert isinstance(pos, list) and len(pos) >= 1, f"{path}: needs activation_examples"


def test_no_scripts_or_executables_in_library():
    # No scripts/ dirs and nothing executable / no shebangs — skills are inert data.
    assert not list(SKILLS.rglob("scripts")), "no scripts/ dirs allowed in the minimum library"
    for f in SKILLS.rglob("*"):
        if f.is_file():
            assert not (f.stat().st_mode & 0o111), f"{f}: unexpected executable bit"
            if f.suffix.lower() in (".sh", ".py", ".js", ".rb", ".bash"):
                pytest.fail(f"{f}: no runnable scripts permitted in P2")


# ── manifest: schema + example only (no hand-authored truth manifest) ────────
def test_no_real_manifest_committed():
    assert not (SKILLS / "manifest.json").exists(), \
        "real manifest.json must be generated later, never hand-authored in P2"
    assert (SKILLS / "manifest.schema.json").exists()
    assert (SKILLS / "manifest.example.json").exists()


def test_manifest_example_validates_against_schema():
    schema = json.loads((SKILLS / "manifest.schema.json").read_text())
    example = json.loads((SKILLS / "manifest.example.json").read_text())
    entry_schema = schema["definitions"]["skillEntry"]
    allowed_keys = set(entry_schema["properties"].keys())
    required_keys = set(entry_schema["required"])
    assert example["version"] == 1
    for e in example["skills"]:
        keys = set(e.keys())
        # additionalProperties:false → metadata only, NO body keys leak in
        assert keys <= allowed_keys, f"manifest entry has non-metadata keys: {keys - allowed_keys}"
        assert required_keys <= keys, f"manifest entry missing required: {required_keys - keys}"
        assert e["authority_level"] == "advisory"
        assert e["risk_level"] in ("low", "medium", "high")
        assert re.match(r"^skills/[A-Z]{2,4}/[a-z0-9-]+/SKILL\.md$", e["path"])
        # a real referenced skill file exists
        assert (ROOT / e["path"]).exists(), f"manifest path points to a real skill: {e['path']}"
        # no body content smuggled into the manifest
        for banned in ("procedure", "purpose", "body", "governance_rules"):
            assert banned not in keys
