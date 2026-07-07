# -*- coding: utf-8 -*-
"""
discovery.py — SKILLS-01 P3 read-only skill discovery.

Responsibilities (all read-only, deterministic, offline):
  - build_index()      : metadata-only index of skills (name/description/department/
                         authority_level/risk_level/path) — the discovery surface.
  - load_skill_body()  : return a skill's markdown body under STRICT path containment
                         (only files named SKILL.md inside skills/). Never scripts/.
  - select_skill()     : department-scoped trigger match with negative-trigger
                         suppression; returns metadata-only for the chosen skill or None.
  - emit_manifest()    : optional helper to write a metadata-only manifest to an
                         explicit destination (for human inspection); NEVER writes a
                         committed skills/manifest.json.

No execution, no network, no file mutation of the library, no authority. Uses
yaml.safe_load only.
"""
import json
import os
import re
from pathlib import Path

import yaml

# skills/ lives at the repo root: abigail/skills_lib/discovery.py -> ../../skills
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
_ROOT = SKILLS_DIR.parent

# metadata surfaced by discovery (mirrors manifest.schema.json skillEntry)
_META_FIELDS = ("name", "description", "department", "authority_level", "risk_level", "path")

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
_STOPWORDS = {"this", "the", "a", "an", "for", "me", "my", "to", "of", "and",
              "in", "on", "is", "it", "you", "your", "please", "can", "with", "what"}


def _read(path):
    """Return (frontmatter_dict, body_str) for a SKILL.md, or (None, None) on failure."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except Exception:
        return None, None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, None
    try:
        fm = yaml.safe_load(m.group(1))
    except Exception:
        return None, None
    if not isinstance(fm, dict):
        return None, None
    return fm, m.group(2)


def _public_meta(fm, path):
    """Project frontmatter to the metadata-only index entry (no body/triggers)."""
    rel = Path(path).resolve().relative_to(_ROOT).as_posix()
    return {
        "name": fm.get("name"),
        "description": fm.get("description"),
        "department": fm.get("department"),
        "authority_level": fm.get("authority_level"),
        "risk_level": fm.get("risk_level"),
        "path": rel,
    }


def _skill_files():
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(SKILLS_DIR.rglob("SKILL.md"))


def build_index():
    """Return the metadata-only discovery index (deterministic order). No bodies,
    no activation/negative examples — only the manifest field set."""
    out = []
    for path in _skill_files():
        fm, _ = _read(path)
        if fm is None:
            continue
        out.append(_public_meta(fm, path))
    out.sort(key=lambda e: (e.get("department") or "", e.get("name") or ""))
    return out


def _contained(candidate):
    """True iff `candidate` resolves to a real file strictly inside SKILLS_DIR."""
    root = os.path.realpath(SKILLS_DIR)
    cand = os.path.realpath(candidate)
    try:
        if cand != root and os.path.commonpath([root, cand]) != root:
            return False
    except ValueError:
        return False
    return os.path.isfile(cand)


def load_skill_body(path):
    """Return the markdown body of a skill, or None if the path escapes skills/,
    is not a regular SKILL.md file, or cannot be read. Rejects traversal, absolute
    escapes, and any non-SKILL.md target (so scripts/ can never be read here)."""
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = _ROOT / p
    if os.path.basename(str(p)) != "SKILL.md":
        return None
    if not _contained(p):
        return None
    _, body = _read(p)
    return body


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", str(s).lower())) - _STOPWORDS


def select_skill(department, text, index=None):
    """Department-scoped selection. Returns the metadata-only entry of the best
    trigger match, or None. Negative-trigger suppression wins over any match.

    Read-only and deterministic. `index` is accepted for symmetry but selection
    re-reads frontmatter (activation/negative examples are not part of the public
    index). Only metadata is ever returned to the caller.
    """
    if not department or not text:
        return None
    tl = str(text).lower()
    ttok = _tokens(text)
    best = None
    best_score = 0
    for path in _skill_files():
        fm, _ = _read(path)
        if fm is None or fm.get("department") != department:
            continue
        negatives = fm.get("negative_activation_examples") or []
        if any(isinstance(n, str) and n.lower() in tl for n in negatives):
            continue  # suppressed
        pool = _tokens(str(fm.get("name", "")).replace("-", " "))
        for ex in (fm.get("activation_examples") or []):
            pool |= _tokens(ex)
        score = len(ttok & pool)
        if score > best_score:
            best_score = score
            best = _public_meta(fm, path)
    return best


def emit_manifest(dest, generated="unstamped"):
    """Write a metadata-only manifest to an EXPLICIT destination for inspection.
    Never writes skills/manifest.json (the committed truth manifest is prohibited).
    Caller supplies `generated` (e.g. an ISO timestamp) — this module stamps nothing."""
    dest = Path(dest)
    if dest.resolve() == (SKILLS_DIR / "manifest.json").resolve():
        raise ValueError("refusing to write a committed skills/manifest.json")
    payload = {"version": 1, "generated": generated, "skills": build_index()}
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest
