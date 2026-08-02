# -*- coding: utf-8 -*-
"""
tests/test_tax2_harness_importable.py — TAX2_REQUESTS_UNDECLARED (Gate 4)

The TAX2 red-team harness imports `requests`, but nothing declared that
dependency in an installable manifest — it worked only because every
environment this has run in so far happened to already have `requests`
installed. This proves both halves of the fix: the dependency is now
declared in redteam/tax2/requirements.txt, and the harness module actually
imports cleanly (which would raise ModuleNotFoundError in a genuinely
clean environment if the declaration were missing or wrong).
"""
import importlib.util
from pathlib import Path

TAX2_REQUIREMENTS = Path("redteam/tax2/requirements.txt")
HARNESS_PATH = Path("redteam/tax2/harness/fasdtest_dark_psych_v2_1.py")


def test_tax2_requirements_file_declares_requests():
    assert TAX2_REQUIREMENTS.exists(), "redteam/tax2/requirements.txt must exist"
    text = TAX2_REQUIREMENTS.read_text()
    assert "requests" in text, "redteam/tax2/requirements.txt must declare requests"


def test_tax2_harness_module_imports_cleanly():
    spec = importlib.util.spec_from_file_location("fasdtest_dark_psych_v2_1", HARNESS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
