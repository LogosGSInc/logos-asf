import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "abigail"))
import abigail_hardened_enhanced as A  # noqa: E402

REGISTRY_PATH = Path("departments/registry.json")

def load_registry():
    return json.loads(REGISTRY_PATH.read_text())

def active_codes(registry):
    return {
        d["code"]
        for d in registry["departments"]
        if d["status"] == "active"
    }

def test_registry_exists():
    assert REGISTRY_PATH.exists(), "departments/registry.json must exist"

def test_active_count():
    r = load_registry()
    active = [d for d in r["departments"] if d["status"] == "active"]
    assert len(active) == 14, f"Expected 14 active departments, got {len(active)}"

def test_total_count():
    r = load_registry()
    assert len(r["departments"]) == 16, \
        f"Expected 16 total records (14 active + 1 stub + 1 ghost), got {len(r['departments'])}"

def test_hr_not_in_active():
    r = load_registry()
    codes = active_codes(r)
    assert "HR" not in codes, "HR is a ghost — must not appear in active departments"

def test_tkr_not_runtime_loadable():
    r = load_registry()
    tkr = next(d for d in r["departments"] if d["code"] == "TKR")
    assert tkr["status"] == "inactive_stub"
    assert tkr["runtime_loadable"] is False

def test_valid_depts_matches_registry():
    """VALID_DEPTS in abigail_hardened_enhanced.py must equal active registry codes.

    Gate 1 makes VALID_DEPTS a registry-driven frozenset (built from
    departments/registry.json at import time), not a literal — so there is no
    hardcoded set for a source-text regex to extract. This asserts the real
    runtime value directly by importing the module, the same pattern already
    used by tests/test_control_plane_api.py etc.
    """
    r = load_registry()
    expected = active_codes(r)
    assert set(A.VALID_DEPTS) == expected, \
        f"VALID_DEPTS mismatch.\nIn code: {sorted(A.VALID_DEPTS)}\nIn registry: {sorted(expected)}"

def test_govmem_rs_matches_registry():
    """govmem.rs must load department configs from the registry, not a hardcoded list.

    Cross-language runtime introspection isn't available from a Python test, so
    this checks the mechanism structurally: GovMem::new() calls a loader that
    reads departments/registry.json and filters on status == "active", and the
    old hardcoded dept_ids vec is gone. The actual runtime equivalence (loaded
    department set == active registry codes) is verified in Rust itself by
    governance-spine/src/govmem.rs::registry_tests (see `cargo test registry_tests`),
    since only Rust can execute Rust's dynamic loader.
    """
    src = Path("governance-spine/src/govmem.rs").read_text()
    assert "fn load_dept_configs_from_registry" in src, \
        "govmem.rs must load department configs via a registry-reading function"
    assert "registry.json" in src, \
        "govmem.rs must reference departments/registry.json"
    assert re.search(r'"active"', src), \
        "load_dept_configs_from_registry must filter on status == \"active\""
    assert "let dept_ids = vec![" not in src, \
        "hardcoded dept_ids vec must be gone"
    assert re.search(r'department_configs:\s*load_dept_configs_from_registry\(\)', src), \
        "GovMem's constructor must build department_configs via load_dept_configs_from_registry() " \
        "(Gate 3: GovMem::new() delegates to new_with_sessions(), which is where this now lives)"

def test_asf_departments_matches_registry():
    """ASF_DEPARTMENTS in abigail_hardened_enhanced.py must equal active registry codes.

    Gate 1 makes ASF_DEPARTMENTS a registry-driven list comprehension, not a
    literal — so there is no hardcoded "id":"DEPT-XXX" text for a source-text
    regex to extract. This asserts the real runtime value directly.
    """
    r = load_registry()
    expected = active_codes(r)
    found_codes = {d["id"] for d in A.ASF_DEPARTMENTS}
    assert found_codes == expected, \
        f"ASF_DEPARTMENTS mismatch.\nIn code: {sorted(found_codes)}\nIn registry: {sorted(expected)}"

def test_no_hardcoded_dept_lists():
    """No file outside departments/registry.json should contain a hardcoded dept list."""
    patterns = [
        # The old VALID_DEPTS literal (post-repoint it reads from registry)
        r'VALID_DEPTS\s*=\s*\{"EXE"',
        # The old govmem.rs vec literal
        r'\("EXE",\s*0\.6\)',
        # The old ASF_DEPARTMENTS literal
        r'"id"\s*:\s*"DEPT-ENG"',
    ]
    files_to_check = [
        "abigail/abigail_hardened_enhanced.py",
        "governance-spine/src/govmem.rs",
    ]
    for f in files_to_check:
        src = Path(f).read_text()
        for pat in patterns:
            assert not re.search(pat, src), \
                f"Hardcoded department list found in {f}: pattern {pat!r}"

def test_sc_and_sec_both_present():
    """OD-3: SC and SEC are distinct departments, both must be active."""
    r = load_registry()
    codes = active_codes(r)
    assert "SC" in codes, "SC (Security and Governance, SC-01) must be in active departments"
    assert "SEC" in codes, "SEC (Security Governance, SEC-01) must be in active departments"

def test_registry_spec_paths_exist():
    """Every active department's spec_path must exist on the filesystem."""
    r = load_registry()
    missing = []
    for d in r["departments"]:
        if d["status"] == "active" and d.get("spec_path"):
            p = Path(d["spec_path"])
            if not p.exists():
                missing.append(str(p))
    assert not missing, f"Missing spec files: {missing}"
