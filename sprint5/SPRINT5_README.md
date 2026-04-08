# Sprint 5 — Strategic Memory Persistence + Python-Rust Session Handoff
**LOGOS Agentic Software Firm | Governance Spine v3.5**
Patent Ref: US Provisional 63/953,447

---

## What This Sprint Does

Closes the single remaining architectural gap: StrategicMemory (Tier 2) was
in-process Rust RAM. A container restart wiped all cross-session actor profiles,
leaving Abigail unable to pre-warn Sentinel about returning adversaries.

Sprint 5 adds four targeted changes:

| File | Change |
|---|---|
| `sentinel_server.py` | Adds `/session/start` and `/session/end` Flask endpoints |
| `session_memory.rs` | Adds `StrategicMemory` disk persistence via `serde_json` to named volume |
| `abigail_hardened_enhanced.py` | Adds `open_session()` / `close_session()` handoff calls |
| `docker-compose.yml` | Mounts `sentinel-data` named volume into governance-spine |

---

## Data Flow After Sprint 5

```
Actor connects
    │
    ▼
Abigail calls POST /session/start?actor_id=X
    │
    ▼
sentinel_server.py → forwards to governance-spine:8080/session/start
    │
    ▼
Rust StrategicMemory.advise_session_start(actor_id)
    → reads /data/strategic_memory.json
    → returns: starting_state, threshold_modifier, prior_escalations
    │
    ▼
Abigail pre-warms SessionState with Tier 2 advice
(Elevated actor starts in Watching/Elevated, threshold tightened)
    │
    [ conversation turns ... ]
    │
    ▼
Actor disconnects / session timeout
    │
    ▼
Abigail calls POST /session/end (actor_id + behavioral summary)
    │
    ▼
sentinel_server.py → forwards to governance-spine:8080/session/end
    │
    ▼
Rust StrategicMemory.record_session_end(actor_id, escalated, hash)
    → updates ActorProfile
    → writes /data/strategic_memory.json  ← PERSISTS ACROSS RESTARTS
```

---

## Apply Instructions

### 1. sentinel_server.py
Replace existing `sentinel_server.py` in `logos-asf/governance-spine/`
with `sprint5/sentinel_server.py`.

### 2. session_memory.rs
Append the structs and impls from `sprint5/session_memory_sprint5_additions.rs`
to `logos-asf/governance-spine/src/session_memory.rs`.
Then add two HTTP route handlers to `main.rs` (see comments in the .rs file).

Also confirm `Cargo.toml` has:
```toml
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

### 3. abigail_hardened_enhanced.py
Apply the patch from `sprint5/abigail_session_handoff_patch.py`:
- Add four fields to `SessionState.__init__()`
- Add `open_session()` and `close_session()` methods
- Add 3-line session open call at top of `process_message()`
- Add `@app.teardown_appcontext` handler

### 4. docker-compose.yml
Apply the additions from `sprint5/docker_compose_sprint5.diff`:
- Add `sentinel-data` named volume
- Mount `/data` in governance-spine
- Add env vars for STRATEGIC_MEMORY_PATH, SENTINEL_URL, GOVERNANCE_SPINE_URL

### 5. Deploy
```bash
docker-compose down
docker-compose up --build -d
bash sprint5/sprint5_integration_test.sh
```

---

## What Persists vs What Doesn't

| Data | Persists? | Where |
|---|---|---|
| SessionMemory (Tier 1) cumulative_threat | ❌ Per-session RAM only (by design) | Rust heap |
| StrategicMemory ActorProfiles | ✅ Sprint 5 | `/data/strategic_memory.json` |
| DRS / CRSV per turn | ❌ Session-scoped (by design) | Python heap |
| Audit log | ✅ Already implemented | Log file path |

---

## Threat Model This Closes

**Restart-gap attack:** Adversary waits for container restart, then reconnects.
Previously Abigail had no memory of prior escalated sessions — every restart
was a clean slate. After Sprint 5, Sentinel pre-loads Tier 2 advice before
the first token is processed.

---

## IP Note
This session handoff architecture — specifically the Tier 1 / Tier 2 split
where per-session accumulation feeds a cross-session strategic profile that
survives restarts and advises new session starting state — is novel governance
behavior for AI agents and is covered under US Provisional 63/953,447.
Document every behavioral variant for continuation filing.
