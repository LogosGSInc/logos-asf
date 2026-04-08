"""
abigail_hardened_enhanced.py — Sprint 5 session handoff additions.

PATCH: Add the following to the existing SessionState class and process_message().
This is a surgical diff — everything else in abigail_hardened_enhanced.py is unchanged.
"""

import requests
import hashlib
import os
import logging

log = logging.getLogger("abigail")
SENTINEL_URL = os.environ.get("SENTINEL_URL", "http://sentinel:8080")


# ─── Add to SessionState.__init__() ──────────────────────────────────────────
#
#   self.actor_id: str = "anonymous"
#   self.tier2_start_state: str = "Clean"
#   self.tier2_threshold_modifier: float = 1.0
#   self.session_open: bool = False
#
# ─── Add new method to SessionState ──────────────────────────────────────────

class SessionStateSprint5Mixin:
    """
    Mixin to add Sprint 5 capabilities to SessionState.
    In the real file, merge these methods directly into SessionState.
    """

    def open_session(self, actor_id: str = "anonymous") -> None:
        """
        Call sentinel /session/start to get Tier 2 advice.
        Sets self.tier2_start_state and self.tier2_threshold_modifier.
        """
        self.actor_id = actor_id
        self.session_open = True

        try:
            resp = requests.post(
                f"{SENTINEL_URL}/session/start",
                json={"actor_id": actor_id},
                timeout=3,
            )
            data = resp.json()
            self.tier2_start_state = data.get("starting_state", "Clean")
            self.tier2_threshold_modifier = float(data.get("threshold_modifier", 1.0))
            log.info(
                "session/start actor=%s state=%s modifier=%.2f",
                actor_id,
                self.tier2_start_state,
                self.tier2_threshold_modifier,
            )
        except Exception as e:
            log.warning("session/start call failed (%s), defaulting Clean", e)
            self.tier2_start_state = "Clean"
            self.tier2_threshold_modifier = 1.0

    def close_session(self) -> None:
        """
        Call sentinel /session/end to hand off behavioral fingerprint.
        Should be called on connection close, timeout, or explicit end.
        """
        if not self.session_open:
            return

        # Build behavior summary for Tier 2 fingerprinting
        behavior = {
            "turn_count": getattr(self, "turn_count", 0),
            "escalated": getattr(self, "escalated", False),
            "drs_peak": getattr(self, "drs_peak", 0),
            "boundary_probes": getattr(self, "boundary_probes", 0),
            "authority_claims": getattr(self, "authority_claims", 0),
            "extraction_attempts": getattr(self, "extraction_attempts", 0),
        }

        try:
            requests.post(
                f"{SENTINEL_URL}/session/end",
                json={"actor_id": self.actor_id, **behavior},
                timeout=3,
            )
            log.info(
                "session/end actor=%s escalated=%s drs_peak=%s",
                self.actor_id,
                behavior["escalated"],
                behavior["drs_peak"],
            )
        except Exception as e:
            log.warning("session/end call failed (%s), fingerprint not persisted", e)

        self.session_open = False


# ─── Add to process_message() ────────────────────────────────────────────────
#
# At the TOP of process_message(), BEFORE evaluate():
#
#   if not session.session_open:
#       actor_id = request.headers.get("X-Actor-Id", "anonymous")
#       session.open_session(actor_id)
#
# Apply tier2 threshold_modifier to DRS threshold:
#   effective_drs_threshold = BASE_DRS_THRESHOLD * session.tier2_threshold_modifier
#   (use effective_drs_threshold in arbiter comparison instead of BASE_DRS_THRESHOLD)
#
# Apply tier2 starting state — if tier2_start_state == "Elevated":
#   session.threat_level = "Elevated"  # pre-warm Sentinel state
#
# At session CLOSE (connection teardown / Flask teardown_appcontext):
#   session.close_session()


# ─── Flask teardown integration ──────────────────────────────────────────────
#
# Add to app initialization in abigail_hardened_enhanced.py:
#
#   @app.teardown_appcontext
#   def teardown_session(exception=None):
#       if hasattr(g, "abigail_session"):
#           g.abigail_session.close_session()
#
# Or call session.close_session() explicitly at the end of each /api/chat handler
# if you prefer synchronous teardown over context teardown.


# ─── Minimal integration test ────────────────────────────────────────────────

def test_session_handoff():
    """Quick smoke test — run manually after deploy."""
    import json

    class MockSession(SessionStateSprint5Mixin):
        def __init__(self):
            self.actor_id = "anonymous"
            self.tier2_start_state = "Clean"
            self.tier2_threshold_modifier = 1.0
            self.session_open = False
            self.turn_count = 3
            self.escalated = False
            self.drs_peak = 12
            self.boundary_probes = 1
            self.authority_claims = 0
            self.extraction_attempts = 0

    s = MockSession()
    s.open_session("test-actor-001")
    print(f"  start_state: {s.tier2_start_state}")
    print(f"  threshold_modifier: {s.tier2_threshold_modifier}")
    s.close_session()
    print("  session/end sent")
    print("PASS")


if __name__ == "__main__":
    test_session_handoff()
