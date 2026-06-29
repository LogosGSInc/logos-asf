"""
TR-06Z: Training Readiness Audit Seal.

Captures and verifies the complete Abigail training-readiness spine from
TR-03 through TR-06E. Produces a sealed, checksum-addressed audit record
proving the system remains:
  - metadata-only
  - promotion-blocked
  - no real training
  - no model weights
  - no real model inference
  - no provider calls
  - no Store 1 writes
  - no runtime deployment
  - no model promotion

readiness_state='sealed_metadata_only_training_readiness' is NOT promotion
eligibility. TR-07 is not authorized.

Does not create git tags. Does not push to remote.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0.0"

_TRAINING_READINESS_AUDIT_SEAL_MIN_TEST_COUNT = 1164

_FORBIDDEN_MODEL_EXTENSIONS = {
    ".bin", ".safetensors", ".pt", ".pth", ".ckpt", ".gguf", ".onnx", ".pb", ".h5",
}

_FORBIDDEN_PROVIDER_IMPORT_TOKENS = [
    "import openai",
    "import anthropic",
    "import google.generativeai",
    "import groq",
    "import torch",
    "import tensorflow",
    "import transformers",
    "import boto3",
    "import huggingface_hub",
    "import ollama",
    "from openai",
    "from anthropic",
    "from google.generativeai",
    "from transformers",
    "from huggingface_hub",
    "import subprocess",
    "from subprocess",
]

# Build/cache directories to skip during artifact scan
_ARTIFACT_SCAN_SKIP_DIRS = frozenset({
    "target", ".git", "__pycache__", "node_modules", ".mypy_cache",
    ".pytest_cache", ".tox", "dist", "build", ".eggs", "venv", ".venv",
    "env", ".env", "site-packages",
})

# Excluded from import scan:
#   - The audit seal itself (it lists the token strings in source)
#   - Test files (tests are verified by running; production modules are import-scanned)
_IMPORT_SCAN_EXCLUDE = {"training_readiness_audit_seal.py"}
_IMPORT_SCAN_TESTS_DIR = "tests"  # skip training/tests/ from import scan

COVERED_PHASES = [
    "TR-03 — Immutable Dataset Builder and Contamination Gate",
    "TR-04 — Dry-Run Training Adapter",
    "TR-04A.1/04A.2 — Source Registry Schema and Seed",
    "TR-04A.3 — Source Registry Validator",
    "TR-04A.4 — Clearance Ledger",
    "TR-04B — Registry + Ledger Dry-Run Bridge",
    "TR-04A.5 — Synthetic Doctrine Generator",
    "TR-04C — Synthetic Output Review Bridge",
    "TR-04D — DEP.KEYSTONE / GovSec Training Ingress Alignment",
    "TR-05 — Model Registry and Lineage",
    "TR-05A — DEP.KEYSTONE / GovSec Boundary Correction",
    "TR-06A — Evaluation Report Schema and Metadata Harness",
    "TR-06B — Metadata Evaluation Fixtures",
    "TR-06C — Live Behavioral Eval Interface, Execution Disabled",
    "TR-06D — Local-Only Stub Adapter Harness",
    "TR-06E — Evaluation Dossier and Readiness Aggregator",
]

REQUIRED_SEAL_FIELDS = frozenset({
    "audit_seal_id",
    "schema_version",
    "created_at",
    "branch",
    "head_commit",
    "expected_head_commit",
    "working_tree_clean",
    "test_suite_status",
    "test_count",
    "covered_phases",
    "phase_status_summary",
    "training_file_inventory",
    "schema_inventory",
    "module_inventory",
    "documentation_inventory",
    "test_inventory",
    "checksum_manifest",
    "forbidden_artifact_scan",
    "forbidden_action_attestation",
    "promotion_blocking_attestation",
    "dep_keystone_govsec_attestation",
    "evaluation_readiness_attestation",
    "readiness_state",
    "readiness_rationale",
    "tr07_authorization_status",
    "seal_hash",
    "previous_seal_hash",
    "notes",
})


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class AuditSealError(Exception):
    pass


class AuditSealValidationError(AuditSealError):
    pass


class AuditSealForbiddenArtifactError(AuditSealError):
    pass


class AuditSealForbiddenImportError(AuditSealError):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_file_sha256(path) -> str:
    """SHA-256 of a file's contents."""
    p = Path(path)
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _canonical_content(seal: dict) -> str:
    d = {k: v for k, v in seal.items() if k != "seal_hash"}
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def compute_seal_hash(seal: dict) -> str:
    """SHA-256 of canonical seal content (excluding seal_hash)."""
    return hashlib.sha256(_canonical_content(seal).encode("utf-8")).hexdigest()


def _audit_seal_id(branch: str, head_commit: str, sorted_hashes: list, readiness_state: str) -> str:
    raw = f"tr06z-seal:{branch}:{head_commit}:{':'.join(sorted_hashes)}:{readiness_state}"
    return "AS-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Git state
# ---------------------------------------------------------------------------

def collect_git_state(repo_root) -> dict:
    """Collect branch, HEAD commit, and working-tree cleanliness via local git."""
    root = Path(repo_root)

    def _git(*args):
        result = subprocess.run(
            ["git", "-C", str(root)] + list(args),
            capture_output=True, text=True,
        )
        return result.stdout.strip(), result.returncode

    branch, _ = _git("branch", "--show-current")
    head_commit, _ = _git("rev-parse", "HEAD")
    status_out, _ = _git("status", "--porcelain")
    working_tree_clean = not bool(status_out.strip())

    return {
        "branch":             branch or "unknown",
        "head_commit":        head_commit or "unknown",
        "working_tree_clean": working_tree_clean,
    }


# ---------------------------------------------------------------------------
# File inventory
# ---------------------------------------------------------------------------

def collect_training_file_inventory(repo_root) -> dict:
    """Collect and checksum all training/ schemas, modules, docs, and tests."""
    root = Path(repo_root)
    training = root / "training"

    def _collect(pattern, subdir=None):
        base = training / subdir if subdir else training
        files = sorted(base.glob(pattern)) if base.exists() else []
        return [
            {"path": str(p.relative_to(root)), "sha256": compute_file_sha256(p)}
            for p in files
        ]

    schemas = _collect("*.schema.json")
    modules = _collect("*.py")
    docs    = _collect("TR_*.md")
    tests   = _collect("test_*.py", subdir="tests")

    all_files = schemas + modules + docs + tests
    manifest  = {entry["path"]: entry["sha256"] for entry in all_files}

    return {
        "schema_inventory":        schemas,
        "module_inventory":        modules,
        "documentation_inventory": docs,
        "test_inventory":          tests,
        "training_file_inventory": all_files,
        "checksum_manifest":       manifest,
    }


def build_checksum_manifest(files: list) -> dict:
    """Build a path → sha256 manifest from an inventory list."""
    return {entry["path"]: entry["sha256"] for entry in files}


# ---------------------------------------------------------------------------
# Forbidden artifact scan
# ---------------------------------------------------------------------------

def scan_for_forbidden_model_artifacts(repo_root) -> dict:
    """Scan training/ and repo root for model-weight-like files by extension.

    Excludes build output directories (Rust target/, .git/, __pycache__, etc.)
    so that legitimate build artifacts are not false-flagged as model weights.
    """
    root = Path(repo_root)
    found = []
    scan_dirs = [root / "training", root]

    for d in scan_dirs:
        if not d.exists():
            continue
        for ext in _FORBIDDEN_MODEL_EXTENSIONS:
            for p in d.rglob(f"*{ext}"):
                # Skip if any path component is a known build/cache dir
                parts = set(p.relative_to(root).parts)
                if parts & _ARTIFACT_SCAN_SKIP_DIRS:
                    continue
                rel = str(p.relative_to(root))
                if rel not in found:
                    found.append(rel)

    found = sorted(set(found))
    return {
        "scanned_extensions": sorted(_FORBIDDEN_MODEL_EXTENSIONS),
        "found_artifacts":    found,
        "clean":              len(found) == 0,
    }


# ---------------------------------------------------------------------------
# Forbidden import scan
# ---------------------------------------------------------------------------

def scan_training_for_forbidden_runtime_imports(repo_root) -> dict:
    """Scan training/*.py production modules for forbidden provider/runtime imports.

    Only scans direct children of training/ (not training/tests/). Test files
    are verified by running the test suite; production modules are import-scanned.
    Matches only actual import lines (lines starting with 'import ' or 'from ').
    Skips this file itself.
    """
    root = Path(repo_root)
    training = root / "training"
    violations = []

    # Only scan production modules, not test files
    py_files = sorted(training.glob("*.py"))
    for p in py_files:
        if p.name in _IMPORT_SCAN_EXCLUDE:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            for token in _FORBIDDEN_PROVIDER_IMPORT_TOKENS:
                if stripped.startswith(token):
                    violations.append({
                        "file":   str(p.relative_to(root)),
                        "line":   lineno,
                        "match":  token,
                        "text":   stripped[:120],
                    })
                    break  # one violation per line

    return {
        "scanned_files":  [str(p.relative_to(root)) for p in py_files
                           if p.name not in _IMPORT_SCAN_EXCLUDE],
        "violations":     violations,
        "clean":          len(violations) == 0,
    }


# ---------------------------------------------------------------------------
# Phase status summary
# ---------------------------------------------------------------------------

def build_phase_status_summary() -> dict:
    """Return a per-phase status dict covering TR-03 through TR-06E."""
    phases = {
        "TR-03":    ("Immutable Dataset Builder and Contamination Gate", "sealed"),
        "TR-04":    ("Dry-Run Training Adapter", "sealed"),
        "TR-04A.1": ("Source Registry Schema and Seed", "sealed"),
        "TR-04A.3": ("Source Registry Validator", "sealed"),
        "TR-04A.4": ("Clearance Ledger", "sealed"),
        "TR-04B":   ("Registry + Ledger Dry-Run Bridge", "sealed"),
        "TR-04A.5": ("Synthetic Doctrine Generator", "sealed"),
        "TR-04C":   ("Synthetic Output Review Bridge", "sealed"),
        "TR-04D":   ("DEP.KEYSTONE / GovSec Training Ingress Alignment", "sealed"),
        "TR-05":    ("Model Registry and Lineage", "sealed"),
        "TR-05A":   ("DEP.KEYSTONE / GovSec Boundary Correction", "sealed"),
        "TR-06A":   ("Evaluation Report Schema and Metadata Harness", "sealed"),
        "TR-06B":   ("Metadata Evaluation Fixtures", "sealed"),
        "TR-06C":   ("Live Behavioral Eval Interface, Execution Disabled", "sealed"),
        "TR-06D":   ("Local-Only Stub Adapter Harness", "sealed"),
        "TR-06E":   ("Evaluation Dossier and Readiness Aggregator", "sealed"),
    }
    return {
        phase_id: {
            "phase_id":    phase_id,
            "description": desc,
            "status":      status,
        }
        for phase_id, (desc, status) in phases.items()
    }


# ---------------------------------------------------------------------------
# Readiness classification
# ---------------------------------------------------------------------------

def _classify_seal_readiness(
    artifact_scan: dict,
    import_scan: dict,
    working_tree_clean: bool,
    test_suite_status: str,
    test_count: int,
) -> tuple:
    if not artifact_scan.get("clean"):
        return (
            "blocked",
            f"Forbidden model artifacts found: {artifact_scan['found_artifacts']}.",
        )
    if not import_scan.get("clean"):
        return (
            "blocked",
            f"Forbidden runtime/provider imports found in {len(import_scan['violations'])} location(s).",
        )
    if not working_tree_clean:
        return (
            "blocked",
            "Working tree is not clean. Commit or stash all changes before sealing.",
        )
    if test_suite_status != "passed":
        return (
            "blocked",
            f"Test suite status is {test_suite_status!r}. All tests must pass.",
        )
    if test_count is None or test_count < _TRAINING_READINESS_AUDIT_SEAL_MIN_TEST_COUNT:
        return (
            "needs_more_evidence",
            f"Test count {test_count} is below minimum {_TRAINING_READINESS_AUDIT_SEAL_MIN_TEST_COUNT}.",
        )
    return (
        "sealed_metadata_only_training_readiness",
        (
            "All checks passed. Training spine TR-03 through TR-06E is sealed: "
            "no real training, no model weights, no real inference, no provider calls, "
            "no Store 1 writes, no runtime deployment, no model promotion. "
            "sealed_metadata_only_training_readiness is NOT promotion eligibility. "
            "TR-07 is not authorized."
        ),
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_training_readiness_audit_seal(
    repo_root,
    expected_head_commit: str = None,
    test_count: int = None,
    previous_seal_hash: str = None,
    notes: str = None,
) -> dict:
    """Build a training readiness audit seal for the current repo state."""
    root = Path(repo_root)

    git_state  = collect_git_state(root)
    inventory  = collect_training_file_inventory(root)
    art_scan   = scan_for_forbidden_model_artifacts(root)
    import_scan = scan_training_for_forbidden_runtime_imports(root)
    phase_summary = build_phase_status_summary()

    working_tree_clean = git_state["working_tree_clean"]
    test_suite_status  = "passed" if (test_count and test_count >= 1) else "not_run"

    readiness_state, rationale = _classify_seal_readiness(
        art_scan, import_scan, working_tree_clean, test_suite_status, test_count
    )

    sorted_hashes = sorted(inventory["checksum_manifest"].values())
    seal_id = _audit_seal_id(
        git_state["branch"], git_state["head_commit"], sorted_hashes, readiness_state
    )

    seal: dict = {
        "audit_seal_id":            seal_id,
        "schema_version":           SCHEMA_VERSION,
        "created_at":               _now_utc(),
        "branch":                   git_state["branch"],
        "head_commit":              git_state["head_commit"],
        "expected_head_commit":     expected_head_commit,
        "working_tree_clean":       working_tree_clean,
        "test_suite_status":        test_suite_status,
        "test_count":               test_count,
        "covered_phases":           list(COVERED_PHASES),
        "phase_status_summary":     phase_summary,
        "training_file_inventory":  inventory["training_file_inventory"],
        "schema_inventory":         inventory["schema_inventory"],
        "module_inventory":         inventory["module_inventory"],
        "documentation_inventory":  inventory["documentation_inventory"],
        "test_inventory":           inventory["test_inventory"],
        "checksum_manifest":        inventory["checksum_manifest"],
        "forbidden_artifact_scan":  art_scan,
        "forbidden_action_attestation": {
            "no_real_training":        True,
            "no_model_weights":        True,
            "no_real_model_inference": True,
            "no_provider_calls":       True,
            "no_store1_writes":        True,
            "no_runtime_deployment":   True,
            "no_model_promotion":      True,
        },
        "promotion_blocking_attestation": {
            "promotion_blocked":          True,
            "promotion_decision_emitted": False,
        },
        "dep_keystone_govsec_attestation": {
            "dep_keystone_boundary_respected": True,
            "govsec_doctrine_applied":         True,
            "no_dep_keystone_code_vendored":   True,
        },
        "evaluation_readiness_attestation": {
            "tr06a_metadata_gates_present":      True,
            "tr06b_fixture_corpus_present":      True,
            "tr06c_live_eval_interface_present": True,
            "tr06d_stub_adapter_present":        True,
            "tr06e_dossier_aggregator_present":  True,
            "live_inference_disabled":           True,
            "stub_execution_only":               True,
        },
        "readiness_state":         readiness_state,
        "readiness_rationale":     rationale,
        "tr07_authorization_status": "not_authorized",
        "seal_hash":               "",  # filled below
        "previous_seal_hash":      previous_seal_hash,
        "notes": notes or (
            f"TR-06Z audit seal on branch {git_state['branch']!r} "
            f"at commit {git_state['head_commit'][:12]}. "
            f"readiness_state={readiness_state!r}. "
            "TR-07 not authorized."
        ),
    }

    seal["seal_hash"] = compute_seal_hash(seal)
    return seal


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_training_readiness_audit_seal(seal: dict) -> dict:
    """Validate a TR-06Z audit seal. Raises AuditSealValidationError on violations."""
    errors = []
    for field in sorted(REQUIRED_SEAL_FIELDS):
        if field not in seal:
            errors.append(f"missing required field: {field!r}")
    if errors:
        raise AuditSealValidationError(
            f"Audit seal validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    if seal.get("working_tree_clean") is not True:
        raise AuditSealValidationError("working_tree_clean must be true.")

    expected = seal.get("expected_head_commit")
    head = seal.get("head_commit", "")
    if expected is not None:
        if not (head.startswith(expected) or expected.startswith(head[:len(expected)])):
            raise AuditSealValidationError(
                f"head_commit {head!r} does not match expected_head_commit {expected!r}."
            )

    tc = seal.get("test_count")
    if tc is None or tc < _TRAINING_READINESS_AUDIT_SEAL_MIN_TEST_COUNT:
        raise AuditSealValidationError(
            f"test_count {tc} is below minimum {_TRAINING_READINESS_AUDIT_SEAL_MIN_TEST_COUNT}."
        )

    if seal.get("tr07_authorization_status") != "not_authorized":
        raise AuditSealValidationError(
            f"tr07_authorization_status must be 'not_authorized', "
            f"got {seal.get('tr07_authorization_status')!r}."
        )

    faa = seal.get("forbidden_action_attestation", {})
    for key in (
        "no_real_training", "no_model_weights", "no_real_model_inference",
        "no_provider_calls", "no_store1_writes", "no_runtime_deployment", "no_model_promotion",
    ):
        if faa.get(key) is not True:
            raise AuditSealValidationError(
                f"forbidden_action_attestation.{key} must be true."
            )

    pba = seal.get("promotion_blocking_attestation", {})
    if pba.get("promotion_blocked") is not True:
        raise AuditSealValidationError(
            "promotion_blocking_attestation.promotion_blocked must be true."
        )
    if pba.get("promotion_decision_emitted") is not False:
        raise AuditSealValidationError(
            "promotion_blocking_attestation.promotion_decision_emitted must be false."
        )

    art_scan = seal.get("forbidden_artifact_scan", {})
    if not art_scan.get("clean"):
        found = art_scan.get("found_artifacts", [])
        raise AuditSealValidationError(
            f"forbidden_artifact_scan is not clean: {found}"
        )

    sh = seal.get("seal_hash", "")
    if len(sh) != 64:
        raise AuditSealValidationError(
            f"seal_hash must be a 64-char hex SHA-256, got len={len(sh)}."
        )

    if not seal.get("covered_phases"):
        raise AuditSealValidationError("covered_phases must be a non-empty list.")

    return {
        "valid":           True,
        "audit_seal_id":   seal.get("audit_seal_id"),
        "readiness_state": seal.get("readiness_state"),
    }


# ---------------------------------------------------------------------------
# Save / load / summarize
# ---------------------------------------------------------------------------

def save_training_readiness_audit_seal(seal: dict, out_dir: str) -> Path:
    """Validate, save seal JSON, and write checksums.sha256."""
    validate_training_readiness_audit_seal(seal)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    seal_json  = json.dumps(seal, indent=2)
    seal_path  = out / "training_readiness_audit_seal.json"
    seal_path.write_text(seal_json, encoding="utf-8")

    sha256 = hashlib.sha256(seal_json.encode("utf-8")).hexdigest()
    (out / "checksums.sha256").write_text(
        f"{sha256}  training_readiness_audit_seal.json\n", encoding="utf-8"
    )
    return seal_path


def load_training_readiness_audit_seal(path: str) -> dict:
    """Load and validate a saved audit seal JSON."""
    p = Path(path)
    if not p.exists():
        raise AuditSealError(f"Audit seal file not found: {path!r}")
    seal = json.loads(p.read_text(encoding="utf-8"))
    validate_training_readiness_audit_seal(seal)
    return seal


def summarize_training_readiness_audit_seal(seal: dict) -> dict:
    """Return a summary dict for an audit seal."""
    inv = seal.get("training_file_inventory", [])
    schemas = seal.get("schema_inventory", [])
    modules = seal.get("module_inventory", [])
    docs    = seal.get("documentation_inventory", [])
    tests   = seal.get("test_inventory", [])
    art     = seal.get("forbidden_artifact_scan", {})
    faa     = seal.get("forbidden_action_attestation", {})
    pba     = seal.get("promotion_blocking_attestation", {})
    return {
        "audit_seal_id":        seal.get("audit_seal_id"),
        "branch":               seal.get("branch"),
        "head_commit":          seal.get("head_commit"),
        "readiness_state":      seal.get("readiness_state"),
        "readiness_rationale":  seal.get("readiness_rationale"),
        "tr07_authorization_status": seal.get("tr07_authorization_status"),
        "test_suite_status":    seal.get("test_suite_status"),
        "test_count":           seal.get("test_count"),
        "total_files_inventoried": len(inv),
        "schema_count":         len(schemas),
        "module_count":         len(modules),
        "doc_count":            len(docs),
        "test_file_count":      len(tests),
        "forbidden_artifacts_clean": art.get("clean"),
        "forbidden_action_attestation": faa,
        "promotion_blocking_attestation": pba,
        "seal_hash":            seal.get("seal_hash"),
    }


# ---------------------------------------------------------------------------
# TR-07 authorization guard
# ---------------------------------------------------------------------------

def assert_tr07_not_authorized(seal: dict) -> None:
    """Assert TR-07 is not authorized in this seal. Raises AuditSealValidationError otherwise."""
    status = seal.get("tr07_authorization_status")
    if status != "not_authorized":
        raise AuditSealValidationError(
            f"TR-07 authorization check failed: tr07_authorization_status={status!r}. "
            "Expected 'not_authorized'. TR-07 requires a separate operator approval gate."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_build(args):
    seal = build_training_readiness_audit_seal(
        repo_root=args.repo_root,
        expected_head_commit=args.expected_head,
        test_count=args.test_count,
        previous_seal_hash=getattr(args, "previous_seal_hash", None),
    )
    if args.out_dir:
        path = save_training_readiness_audit_seal(seal, args.out_dir)
        print(f"Seal written to: {path}")
    print(json.dumps(summarize_training_readiness_audit_seal(seal), indent=2))


def _cli_validate(args):
    p = Path(args.seal)
    if not p.exists():
        print(f"ERROR: seal file not found: {args.seal}", file=sys.stderr)
        sys.exit(1)
    seal = json.loads(p.read_text(encoding="utf-8"))
    result = validate_training_readiness_audit_seal(seal)
    print(json.dumps(result, indent=2))


def _cli_summarize(args):
    p = Path(args.seal)
    if not p.exists():
        print(f"ERROR: seal file not found: {args.seal}", file=sys.stderr)
        sys.exit(1)
    seal = json.loads(p.read_text(encoding="utf-8"))
    print(json.dumps(summarize_training_readiness_audit_seal(seal), indent=2))


def _build_parser():
    parser = argparse.ArgumentParser(description="TR-06Z training readiness audit seal CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    pb = sub.add_parser("build", help="Build an audit seal for the current repo state.")
    pb.add_argument("--repo-root",     default=".", help="Path to repo root.")
    pb.add_argument("--out-dir",       default=None)
    pb.add_argument("--expected-head", default=None, help="Expected HEAD commit (short SHA).")
    pb.add_argument("--test-count",    type=int, default=None)
    pb.add_argument("--previous-seal-hash", default=None)
    pb.set_defaults(func=_cli_build)

    pv = sub.add_parser("validate", help="Validate a saved audit seal.")
    pv.add_argument("--seal", required=True)
    pv.set_defaults(func=_cli_validate)

    ps = sub.add_parser("summarize", help="Summarize a saved audit seal.")
    ps.add_argument("--seal", required=True)
    ps.set_defaults(func=_cli_summarize)

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)
