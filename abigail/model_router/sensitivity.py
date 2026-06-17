import re
from typing import Tuple

_REGULATED = [
    r"\b(hipaa|phi|pii|ssn|social\s+security|irs|tax\s+return|medical\s+record|diagnosis|prescription)\b",
    r"\b(gdpr|ccpa|regulated|compliance|legal\s+hold)\b",
]

_SACRED_DOCTRINAL = [
    r"\b(scripture|bible|quran|torah|art\s+of\s+war|covenant|creed)\b",
    r"\b(constitutional\s+bound|founder.s?\s+intent|doctrine\s+card)\b",
]

_CONFIDENTIAL = [
    r"\b(internal|proprietary|trade\s+secret|nda|confidential|board|investor)\b",
    r"\b(salary|compensation|equity|cap\s+table|runway|burn\s+rate)\b",
]

_USER_PRIVATE = [
    r"my\s+(private|personal)\s+(recovery\s+)?journal",
    r"\b(private\s+(memory|notes?|diary)|personal\s+diary)\b",
    r"(summarize|review|read|access)\s+my\s+(private|personal|confidential)\b",
]

_COMPILED: list[tuple[str, list[re.Pattern]]] = [
    ("regulated",        [re.compile(p, re.IGNORECASE) for p in _REGULATED]),
    ("sacred_doctrinal", [re.compile(p, re.IGNORECASE) for p in _SACRED_DOCTRINAL]),
    ("confidential",     [re.compile(p, re.IGNORECASE) for p in _CONFIDENTIAL]),
    ("user_private",     [re.compile(p, re.IGNORECASE) for p in _USER_PRIVATE]),
]


def classify_sensitivity(text: str) -> Tuple[str, str]:
    """Return (sensitivity_level, matched_signal). Never logs raw text."""
    for level, patterns in _COMPILED:
        for rx in patterns:
            m = rx.search(text)
            if m:
                return level, m.group(0)[:40]
    return "public", ""
