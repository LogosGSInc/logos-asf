"""
LOGOS ASF — Sentinel OverWatch HTTP Service
Thin Flask wrapper exposing the Rust governance spine over REST.
The Rust spine runs as a subprocess; this layer handles HTTP routing
and JSON serialization until the native HTTP binary is built.

Endpoints:
  POST /inspect        — run inbound payload through full pipeline
  POST /outbound       — run outbound payload through pipeline
  GET  /health         — liveness check
  GET  /session/{id}   — session state diagnostics
  POST /session/reset  — operator-authorized session reset
"""

import json
import os
import subprocess
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

INDUSTRY_PROFILE = os.environ.get("SENTOW_INDUSTRY_PROFILE", "consumer")
HAAP_DRS_CEILING = int(os.environ.get("SENTOW_HAAP_DRS_CEILING", "60"))

# In-memory session state (backed by Rust spine state in subprocess)
# Production: replace with persistent store backed by Rust audit log
sessions = {}


def run_spine_check(payload: str, direction: str, session_id: str) -> dict:
    """
    Invoke the governance spine binary for a single payload check.
    Returns a structured verdict dict.

    In next sprint this calls the native Rust HTTP server directly.
    For now: JSON stdin/stdout protocol with governance_spine_demo.
    """
    # For local testing: invoke the demo binary with a test payload
    # Full integration: Rust HTTP server replaces this subprocess call
    try:
        input_data = json.dumps({
            "payload": payload,
            "direction": direction,
            "session_id": session_id,
            "industry_profile": INDUSTRY_PROFILE,
            "haap_drs_ceiling": HAAP_DRS_CEILING,
        })

        result = subprocess.run(
            ["./governance_spine_demo"],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Parse structured output when Rust server mode is active
        # Current demo binary outputs human-readable — parse for service mode
        if result.returncode == 0:
            return {
                "verdict": "APPROVED",
                "session_id": session_id,
                "chain_length": 0,
                "audit_entries": 0,
            }
        else:
            return {
                "verdict": "ERROR",
                "session_id": session_id,
                "error": result.stderr[:500],
            }
    except subprocess.TimeoutExpired:
        return {"verdict": "ERROR", "error": "Spine timeout"}
    except Exception as e:
        return {"verdict": "ERROR", "error": str(e)}


@app.route("/session/start", methods=["POST"])
def session_start():
    """
    Called by Abigail when a new session opens.
    Returns Tier 2 StrategicMemory advice: starting state + threshold modifier.
    This pre-warms the session before the first token is processed.

    Request: { "actor_id": "string", "session_id": "string" }
    Response: {
        "session_id": "...",
        "actor_id": "...",
        "starting_state": "Clear|Watching|Elevated|Escalated|Locked",
        "threshold_modifier": 0.0-1.0,
        "advisory": "string|null"
    }
    """
    data      = request.get_json(force=True)
    actor_id  = data.get("actor_id", "unknown")
    session_id = data.get("session_id", actor_id)

    # Load actor profile from persistent store if available
    # Full Rust integration: this calls GovernancePipeline::init_session_memory()
    # For now: check our in-memory session store for prior escalations
    prior = sessions.get(actor_id, {})
    escalated_count = prior.get("escalated_sessions", 0)
    total_sessions  = prior.get("total_sessions", 0)

    # Replicate Tier 2 logic: mirror StrategicMemory::advise_session_start()
    starting_state    = "Clear"
    threshold_modifier = 1.0
    advisory          = None

    if escalated_count >= 2 and total_sessions >= 3:
        starting_state     = "Escalated"
        threshold_modifier = 0.30
        advisory = (f"SENTINEL ADVISORY: Actor {actor_id} — {total_sessions} sessions, "
                    f"{escalated_count} escalated. Campaign pattern suspected. "
                    f"Starting Escalated at {int(threshold_modifier*100)}% threshold.")
    elif escalated_count >= 1 and total_sessions >= 2:
        starting_state     = "Elevated"
        threshold_modifier = 0.55
        advisory = (f"SENTINEL ADVISORY: Actor {actor_id} — {escalated_count}/{total_sessions} "
                    f"sessions escalated. Starting Elevated.")
    elif total_sessions >= 2 and escalated_count == 0:
        starting_state     = "Clear"
        threshold_modifier = 1.0

    sessions[session_id] = {
        **sessions.get(session_id, {}),
        "actor_id":           actor_id,
        "state":              starting_state,
        "threshold_modifier": threshold_modifier,
        "total_sessions":     total_sessions + 1,
        "escalated_sessions": escalated_count,
    }

    if advisory:
        print(f"[SENTINEL] {advisory}")

    return jsonify({
        "session_id":          session_id,
        "actor_id":            actor_id,
        "starting_state":      starting_state,
        "threshold_modifier":  threshold_modifier,
        "advisory":            advisory,
    })


@app.route("/session/end", methods=["POST"])
def session_end():
    """
    Called by Abigail when a session closes (clean or lockout).
    Receives the session behavioral fingerprint and updates actor profile.
    Triggers StrategicMemory persistence to disk.

    Request: {
        "session_id": "string",
        "actor_id":   "string",
        "escalated":  bool,
        "turn_count": int,
        "final_drs":  float,
        "boundary_probes": int,
        "authority_claims": int,
        "extraction_attempts": int
    }
    """
    data       = request.get_json(force=True)
    session_id = data.get("session_id", "unknown")
    actor_id   = data.get("actor_id", session_id)
    escalated  = data.get("escalated", False)

    # Update actor profile in session store
    prior = sessions.get(actor_id, {
        "total_sessions":     0,
        "escalated_sessions": 0,
        "cumulative_risk":    0.0,
    })

    prior["total_sessions"]     = prior.get("total_sessions", 0) + 1
    prior["escalated_sessions"] = prior.get("escalated_sessions", 0) + (1 if escalated else 0)
    prior["cumulative_risk"]    = prior.get("cumulative_risk", 0.0) + data.get("final_drs", 0) * 0.3
    prior["last_seen"]          = time.time()
    prior["last_escalated"]     = escalated

    sessions[actor_id] = prior
    sessions.pop(session_id, None)  # Remove session-scoped entry

    print(f"[SENTINEL] Session end: {session_id} | actor={actor_id} | "
          f"escalated={escalated} | profile: {prior['total_sessions']} sessions, "
          f"{prior['escalated_sessions']} escalated")

    return jsonify({
        "status":             "recorded",
        "actor_id":           actor_id,
        "total_sessions":     prior["total_sessions"],
        "escalated_sessions": prior["escalated_sessions"],
        "cumulative_risk":    round(prior["cumulative_risk"], 2),
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "sentinel-overwatch",
        "industry_profile": INDUSTRY_PROFILE,
        "haap_drs_ceiling": HAAP_DRS_CEILING,
        "timestamp": time.time(),
    })


@app.route("/inspect", methods=["POST"])
def inspect():
    data = request.get_json(force=True)
    payload    = data.get("payload", "")
    session_id = data.get("session_id", "default")
    token      = data.get("haap_token")  # Optional Intent Token

    if not payload:
        return jsonify({"error": "payload required"}), 400

    result = run_spine_check(payload, "inbound", session_id)
    result["haap_token_presented"] = bool(token)
    return jsonify(result)


@app.route("/outbound", methods=["POST"])
def outbound():
    data = request.get_json(force=True)
    payload    = data.get("payload", "")
    session_id = data.get("session_id", "default")

    if not payload:
        return jsonify({"error": "payload required"}), 400

    result = run_spine_check(payload, "outbound", session_id)
    return jsonify(result)


@app.route("/session/<session_id>", methods=["GET"])
def session_state(session_id):
    state = sessions.get(session_id, {
        "session_id": session_id,
        "state": "S1_MONITOR",
        "drs": 0,
        "memory_state": "Clear",
    })
    return jsonify(state)


@app.route("/session/reset", methods=["POST"])
def session_reset():
    data = request.get_json(force=True)
    session_id    = data.get("session_id")
    operator_token = data.get("operator_token", "")

    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    if not operator_token:
        return jsonify({"error": "operator_token required"}), 403

    # Token validation delegated to Rust spine in full integration
    sessions.pop(session_id, None)
    return jsonify({"status": "reset", "session_id": session_id})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
