# -*- coding: utf-8 -*-
"""
privileged_credentials.py — LOGOS Governance Systems Inc. — Centralized
privileged-credential validation policy (C4).

Covers the two credentials Abigail's own control surface trusts:
  ABIGAIL_ADMIN_TOKEN — full operator/admin authority
  ABIGAIL_DEMO_TOKEN  — read-only demo authority

Before this module, validation was fragmented: require_admin_token() only
checked for a nonempty configured value and compared with `!=` (not
constant-time); the web app's _request_authority()/_valid_step_up() each
had their own placeholder checks; command_bus.py compared with `==` and
never checked for placeholders at all; startup_checks() had yet another
ad hoc placeholder check with no length floor. A short, forgotten, or
templated value could authenticate in some of these paths and not others.

Every privileged-token acceptance point in this codebase (startup,
require_admin_token, demo-token step-up, command_bus authority
resolution, control-plane registry) now resolves and compares tokens
through this module instead of reading os.environ directly.

Out of scope: SENTINEL_SERVICE_TOKEN and SENTINEL_OPERATOR_RESET_TOKEN.
Those are Sentinel/Rust-governed credentials (see
governance-spine/src/operator_reset.rs for the operator-reset authority)
and are validated entirely on that side of the boundary; nothing here
changes their semantics, and an admin/demo token must never substitute
for either of them.
"""
import enum
import hmac
import os

# Same floor as Sentinel's operator-reset token (governance-spine C3) —
# one consistent minimum-strength bar for every privileged credential in
# the system.
MIN_PRIVILEGED_TOKEN_LENGTH = 43

_PLACEHOLDER_MARKERS = (
    "PLACEHOLDER",
    "CHANGE_ME",
    "CHANGEME",
    "GENERATE_A_STRONG_RANDOM_TOKEN_HERE",
    "EXAMPLE-TOKEN",
    "EXAMPLE_TOKEN",
    "TEST-TOKEN",
    "TEST_TOKEN",
)


class CredentialError(enum.Enum):
    MISSING = "missing"
    EMPTY = "empty"
    WHITESPACE = "whitespace"
    TOO_SHORT = "too_short"
    PLACEHOLDER = "placeholder"


def _looks_like_placeholder(upper: str) -> bool:
    if any(marker in upper for marker in _PLACEHOLDER_MARKERS):
        return True
    # YOUR_*_HERE — e.g. YOUR_GROQ_API_KEY_HERE, YOUR_ADMIN_TOKEN_HERE
    return "YOUR_" in upper and "_HERE" in upper


def validate_privileged_token(value):
    """Validate a candidate privileged-credential VALUE on its own merits
    (not yet compared against anything presented). Returns None when the
    value is acceptable, otherwise a CredentialError.

    Deliberately does NOT strip-and-accept: a value with leading/trailing
    whitespace is rejected outright rather than silently normalized, so a
    stray space introduced by a shell export or a copy/paste can never
    become "the credential" by accident. A value is only ever acceptable
    exactly as configured/presented.
    """
    if value is None:
        return CredentialError.MISSING
    if not isinstance(value, str):
        return CredentialError.MISSING
    if value == "":
        return CredentialError.EMPTY
    if value.strip() == "" or value != value.strip():
        return CredentialError.WHITESPACE
    if len(value) < MIN_PRIVILEGED_TOKEN_LENGTH:
        return CredentialError.TOO_SHORT
    if _looks_like_placeholder(value.upper()):
        return CredentialError.PLACEHOLDER
    return None


def resolve_configured_token(name, env=None):
    """Read and validate a privileged token from the environment (or an
    injected mapping — tests only). Returns the exact configured string
    only when it passes validate_privileged_token(); otherwise None.

    This is the single choke point for reading ABIGAIL_ADMIN_TOKEN /
    ABIGAIL_DEMO_TOKEN. A missing, empty, whitespace-only/-wrapped,
    too-short, or placeholder-looking configured value is indistinguishable
    from "not configured" to every caller — all fail closed the same way.
    """
    source = env if env is not None else os.environ
    raw = source.get(name)
    if validate_privileged_token(raw) is not None:
        return None
    return raw


def credential_matches(presented, configured_name, env=None):
    """Constant-time check: does `presented` match the validated,
    configured privileged token named `configured_name`?

    False whenever the configured value is missing/invalid/placeholder, OR
    `presented` itself fails the same structural validation (missing,
    empty, whitespace-wrapped, too short, placeholder-looking) — a
    malformed presented credential is rejected before comparison and can
    never authenticate, regardless of what it's compared against.
    Comparison uses hmac.compare_digest — never a plain `==`/`!=`. Never
    logs, prints, or returns either value.
    """
    configured = resolve_configured_token(configured_name, env=env)
    if configured is None:
        return False
    if validate_privileged_token(presented) is not None:
        return False
    return hmac.compare_digest(presented, configured)
