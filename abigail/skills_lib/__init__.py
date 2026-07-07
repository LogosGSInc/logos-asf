# -*- coding: utf-8 -*-
"""
skills_lib — read-only discovery for the Abigail first-party skill library.

SKILLS-01 P3. READ-ONLY: scans skills/**/SKILL.md, builds a metadata-only index,
loads bounded skill bodies under strict path containment, and selects a
department-scoped skill by trigger match with negative-trigger suppression.

Invariant: skills are ADVISORY DATA ONLY. This package never executes scripts,
never makes network calls, never mutates files, and never grants authority. No
runtime dispatch wiring lives here (that is P4, separately approved).
"""
from .discovery import (
    build_index,
    load_skill_body,
    select_skill,
    emit_manifest,
    library_version,
    SKILLS_DIR,
)

__all__ = ["build_index", "load_skill_body", "select_skill", "emit_manifest",
           "library_version", "SKILLS_DIR"]
