"""
LOGOS ASF — TR-03 Dataset Scanner v1.0.0
Deterministic, local-only contamination and quality scanner for approved
training candidates. No external calls, no embeddings.
"""
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field

SCANNER_VERSION = "dataset_scanner:1.0.0"

# Severity levels
SEV_CRITICAL = "critical"
SEV_WARNING  = "warning"
SEV_INFO     = "info"

# Categories
CAT_EXACT_DUPLICATE        = "exact_duplicate"
CAT_NORMALIZED_DUPLICATE   = "normalized_duplicate"
CAT_SECRET_PATTERN         = "secret_pattern"
CAT_CREDENTIAL             = "credential"
CAT_PII                    = "pii"
CAT_INJECTION_RESIDUE      = "injection_residue"
CAT_HARMFUL_OUTPUT         = "harmful_desired_output"
CAT_PROTECTED_EVAL         = "protected_evaluation_overlap"
CAT_CONFLICTING_LABEL      = "conflicting_label"
CAT_UNSUPPORTED_PROVENANCE = "unsupported_provenance"
CAT_MISSING_DESIRED_OUTPUT = "missing_desired_output"
CAT_LEAKAGE                = "cross_split_leakage"
CAT_IMBALANCE              = "source_imbalance"

# CRITICAL categories — fail closed
CRITICAL_CATEGORIES = frozenset({
    CAT_EXACT_DUPLICATE,
    CAT_HARMFUL_OUTPUT,
    CAT_PROTECTED_EVAL,
    CAT_INJECTION_RESIDUE,
    CAT_SECRET_PATTERN,
    CAT_CREDENTIAL,
    CAT_UNSUPPORTED_PROVENANCE,
    CAT_MISSING_DESIRED_OUTPUT,
    CAT_LEAKAGE,
})

# ── compiled patterns ─────────────────────────────────────────────────────────

_SECRET_PATTERNS = [
    (re.compile(r'\bsk-[A-Za-z0-9]{20,}\b'), "openai_api_key"),
    (re.compile(r'\bghp_[A-Za-z0-9]{36,}\b'), "github_pat"),
    (re.compile(r'\bgsk_[A-Za-z0-9]{20,}\b'), "groq_api_key"),
    (re.compile(r'\bAKIA[A-Z0-9]{16}\b'), "aws_access_key"),
    (re.compile(r'\bAIza[A-Za-z0-9_-]{35}\b'), "google_api_key"),
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}\b'), "bearer_token"),
    (re.compile(r'(?i)(password|passwd|secret|api_key|api-key|apikey)\s*[:=]\s*["\']?[A-Za-z0-9._\-!@#$%]{8,}'),
     "credential_assignment"),
]

_PII_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), "email_address"),
    (re.compile(r'\b\d{3}[-.\s]\d{2}[-.\s]\d{4}\b'), "ssn_pattern"),
    (re.compile(r'(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b'), "phone_number"),
    (re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'), "credit_card_number"),
]

_INJECTION_PATTERNS = [
    re.compile(r'(?i)ignore\s+(previous|above|all|prior)\s+instructions'),
    re.compile(r'(?i)forget\s+(everything|all|what|your)'),
    re.compile(r'(?i)jailbreak'),
    re.compile(r'(?i)developer\s+mode'),
    re.compile(r'(?i)DAN\s+(mode|prompt|protocol)'),
    re.compile(r'(?i)override\s+(your|all|the)\s+(guidelines|restrictions|rules|constraints)'),
    re.compile(r'(?i)you\s+are\s+now\s+(unrestricted|free|liberated|uncensored)'),
    re.compile(r'(?i)do\s+anything\s+now'),
    re.compile(r'(?i)prompt\s+(injection|override|bypass)'),
    re.compile(r'<\|system\|>'),
    re.compile(r'\[SYS(?:TEM)?\]'),
    re.compile(r'(?i)system\s+prompt\s+bypass'),
    re.compile(r'(?i)ignore\s+(?:all\s+)?(?:previous\s+)?(?:safety|content)\s+(?:filters?|guidelines?)'),
]

_HARMFUL_OUTPUT_PATTERNS = [
    re.compile(r'(?i)\b(synthesize|create|build|make)\s+(a\s+)?(bomb|weapon|explosive|poison|malware)'),
    re.compile(r'(?i)how\s+to\s+(make|build|create|synthesize)\s+\w+\s+(weapon|explosive|drug|poison)'),
    re.compile(r'(?i)\b(kill|murder|harm|assault)\s+(someone|a\s+person|people|user)'),
    re.compile(r'(?i)credit\s+card\s+fraud\s+(steps?|instructions?|guide)'),
    re.compile(r'(?i)identity\s+theft\s+(instructions?|steps?|guide|how)'),
    re.compile(r'(?i)child\s+(sexual|exploitation|abuse)'),
    re.compile(r'(?i)(launch|execute|run)\s+(a\s+)?(ddos|cyberattack|ransomware)'),
]

_PROTECTED_EVAL_PATTERNS = [
    re.compile(r'\bTAX2:\s*MT-[A-Z]\d+'),
    re.compile(r'\bBD1A:[A-Z]\d+'),
    re.compile(r'\bMT-G[456]-\d+'),
    re.compile(r'\bFASDTEST\b'),
    re.compile(r'\btacit_swarm_prepass\b'),
    re.compile(r'(?i)HAAP-X.*escalation'),
    re.compile(r'(?i)sentinel.*DRS=\d+'),
    re.compile(r'(?i)OverWatch.*threshold'),
    re.compile(r'\bHELD_OUT_BENCHMARK\b'),
]


# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class Finding:
    record_id: str
    severity: str
    category: str
    field: str
    detail: str


@dataclass
class ScanReport:
    findings: list = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEV_CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEV_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEV_INFO)

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0

    @property
    def scan_status(self) -> str:
        if self.has_critical:
            return "FAILED"
        if self.warning_count > 0:
            return "PASSED_WITH_WARNINGS"
        return "PASSED"

    @property
    def categories_found(self) -> list:
        return sorted(set(f.category for f in self.findings))

    def findings_for(self, record_id: str) -> list:
        return [f for f in self.findings if f.record_id == record_id]

    def critical_ids(self) -> set:
        return {f.record_id for f in self.findings if f.severity == SEV_CRITICAL}

    def to_dict(self) -> dict:
        return {
            "scanner_version": SCANNER_VERSION,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "has_critical": self.has_critical,
            "scan_status": self.scan_status,
            "categories_found": self.categories_found,
            "findings": [
                {
                    "record_id": f.record_id,
                    "severity": f.severity,
                    "category": f.category,
                    "field": f.field,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
        }


# ── scanner ───────────────────────────────────────────────────────────────────

class DatasetScanner:
    """Deterministic local scanner. No external calls, no embeddings."""

    def __init__(self, protected_eval_patterns: list = None):
        self._extra_protected = [re.compile(p) for p in (protected_eval_patterns or [])]

    def _record_id(self, record: dict) -> str:
        return record.get("candidate_id", record.get("record_id", "UNKNOWN"))

    def _text_fields(self, record: dict) -> list:
        """Return list of (field_name, text) to scan."""
        out = []
        for field in ("input", "desired_output", "title", "summary",
                      "problem_observed", "proposed_improvement"):
            v = record.get(field)
            if isinstance(v, str) and v:
                out.append((field, v))
        return out

    def _sha256_record(self, record: dict) -> str:
        return hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _normalize(self, text: str) -> str:
        """Normalize for near-duplicate detection."""
        return re.sub(r'\s+', ' ', text.lower().strip())

    def scan(self, records: list) -> ScanReport:
        report = ScanReport()
        findings = report.findings

        # --- per-record hashes for duplicate detection
        hashes: dict = {}            # sha256 → first_record_id
        normalized: dict = {}        # normalized_key → first_record_id
        input_to_outputs: dict = {}  # input_hash → set of output_hashes (conflicting label)

        # --- provenance
        for record in records:
            rid = self._record_id(record)

            # desired_output must be present and non-empty
            desired_output = record.get("desired_output")
            if not desired_output or not str(desired_output).strip():
                findings.append(Finding(
                    record_id=rid, severity=SEV_CRITICAL,
                    category=CAT_MISSING_DESIRED_OUTPUT, field="desired_output",
                    detail="desired_output is missing or empty; operator must author this field",
                ))

            # Unsupported provenance
            source_prov = record.get("source_provenance")
            if source_prov and source_prov != "sentinel_overwatch":
                findings.append(Finding(
                    record_id=rid, severity=SEV_CRITICAL,
                    category=CAT_UNSUPPORTED_PROVENANCE, field="source_provenance",
                    detail=f"source_provenance={source_prov!r}; only sentinel_overwatch supported",
                ))

            # Exact duplicate
            sha = self._sha256_record(record)
            if sha in hashes:
                findings.append(Finding(
                    record_id=rid, severity=SEV_CRITICAL,
                    category=CAT_EXACT_DUPLICATE, field="(record)",
                    detail=f"exact duplicate of {hashes[sha]}",
                ))
            else:
                hashes[sha] = rid

            # Normalized duplicate (input + desired_output)
            inp = record.get("input", "")
            out = str(desired_output) if desired_output else ""
            norm_key = self._normalize(inp + "\n" + out)
            if norm_key in normalized and norm_key:
                findings.append(Finding(
                    record_id=rid, severity=SEV_WARNING,
                    category=CAT_NORMALIZED_DUPLICATE, field="(input+desired_output)",
                    detail=f"near-duplicate of {normalized[norm_key]}",
                ))
            elif norm_key:
                normalized[norm_key] = rid

            # Conflicting label: same input, different desired_output
            inp_hash = hashlib.sha256(self._normalize(inp).encode()).hexdigest()
            out_hash = hashlib.sha256(self._normalize(out).encode()).hexdigest()
            if inp_hash not in input_to_outputs:
                input_to_outputs[inp_hash] = set()
            if out_hash not in input_to_outputs[inp_hash]:
                if input_to_outputs[inp_hash]:
                    findings.append(Finding(
                        record_id=rid, severity=SEV_WARNING,
                        category=CAT_CONFLICTING_LABEL, field="desired_output",
                        detail="same input maps to multiple desired outputs",
                    ))
                input_to_outputs[inp_hash].add(out_hash)

            # --- text field scans
            for fname, text in self._text_fields(record):
                # Secret patterns
                for pattern, label in _SECRET_PATTERNS:
                    if pattern.search(text):
                        findings.append(Finding(
                            record_id=rid, severity=SEV_CRITICAL,
                            category=CAT_SECRET_PATTERN, field=fname,
                            detail=f"possible {label} detected; do not include credentials in training data",
                        ))
                        break

                # PII patterns
                for pattern, label in _PII_PATTERNS:
                    if pattern.search(text):
                        findings.append(Finding(
                            record_id=rid, severity=SEV_WARNING,
                            category=CAT_PII, field=fname,
                            detail=f"possible {label} detected; operator must verify and redact",
                        ))
                        break

                # Injection residue (check input only — not desired_output)
                if fname == "input":
                    for pattern in _INJECTION_PATTERNS:
                        if pattern.search(text):
                            findings.append(Finding(
                                record_id=rid, severity=SEV_CRITICAL,
                                category=CAT_INJECTION_RESIDUE, field=fname,
                                detail="prompt injection residue detected in training input",
                            ))
                            break

                # Harmful desired output (check desired_output only)
                if fname == "desired_output":
                    for pattern in _HARMFUL_OUTPUT_PATTERNS:
                        if pattern.search(text):
                            findings.append(Finding(
                                record_id=rid, severity=SEV_CRITICAL,
                                category=CAT_HARMFUL_OUTPUT, field=fname,
                                detail="harmful content detected in desired_output; cannot be training material",
                            ))
                            break

                # Protected evaluation overlap
                for pattern in _PROTECTED_EVAL_PATTERNS + self._extra_protected:
                    if pattern.search(text):
                        findings.append(Finding(
                            record_id=rid, severity=SEV_CRITICAL,
                            category=CAT_PROTECTED_EVAL, field=fname,
                            detail="protected evaluation asset reference detected; must not enter training corpus",
                        ))
                        break

        return report

    def scan_splits_for_leakage(self, train: list, val: list, test: list) -> list:
        """Detect source_signature_id leakage across splits."""
        leakage_findings = []
        train_sigs = {r.get("source_signature_id", "") for r in train}
        val_sigs = {r.get("source_signature_id", "") for r in val}
        test_sigs = {r.get("source_signature_id", "") for r in test}

        for rec in val:
            rid = self._record_id(rec)
            sig = rec.get("source_signature_id", "")
            if sig and sig in train_sigs:
                leakage_findings.append(Finding(
                    record_id=rid, severity=SEV_CRITICAL,
                    category=CAT_LEAKAGE, field="source_signature_id",
                    detail=f"signature {sig!r} appears in both train and validation",
                ))
        for rec in test:
            rid = self._record_id(rec)
            sig = rec.get("source_signature_id", "")
            if sig and sig in train_sigs:
                leakage_findings.append(Finding(
                    record_id=rid, severity=SEV_CRITICAL,
                    category=CAT_LEAKAGE, field="source_signature_id",
                    detail=f"signature {sig!r} appears in both train and test",
                ))
            if sig and sig in val_sigs and sig:
                leakage_findings.append(Finding(
                    record_id=rid, severity=SEV_CRITICAL,
                    category=CAT_LEAKAGE, field="source_signature_id",
                    detail=f"signature {sig!r} appears in both validation and test",
                ))
        return leakage_findings

    def check_imbalance(self, records: list) -> list:
        """Flag source imbalance if any single source_signature_id dominates."""
        from collections import Counter
        counts = Counter(r.get("source_signature_id", "UNKNOWN") for r in records)
        n = len(records)
        findings = []
        if n == 0:
            return findings
        for sig, count in counts.items():
            fraction = count / n
            if fraction > 0.5:
                findings.append(Finding(
                    record_id="(dataset)",
                    severity=SEV_WARNING,
                    category=CAT_IMBALANCE,
                    field="source_signature_id",
                    detail=f"signature {sig!r} accounts for {fraction:.0%} of records ({count}/{n})",
                ))
        return findings
