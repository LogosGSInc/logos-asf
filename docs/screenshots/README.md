# Abigail Screenshots — MM-03 Control-Plane Proof

Captured against the live Abigail CP-00 runtime after MM-03 approval-gate promotion.

Truthful scope:
- Governed runtime: live on localhost:7070
- Backend: Groq
- Cost gate: live
- MM-02 shadow orchestration: live
- MM-03 approval gate: live
- Command bus: live
- Kill-switch state and turn count: live

Not shown as live autonomous execution:
- Sentinel Rust spine was not running in this session
- Department metrics are cockpit/demo visibility
- Agent registry is authored/dormant, not autonomous worker execution
- 77-agent swarm is product architecture, not yet live execution

Use these (`01`–`03`) as control-plane proof, not as full-stack Sentinel-green marketing screenshots.

---

## Full-stack set (`fullstack_*`) — Sentinel green

Captured 2026-07-05 against the full Docker stack (`asf-sentinel` + `asf-abby`) after
fixing the abby image to include the governance stack (see commit for details).

Truthful scope:
- Sentinel OverWatch Rust spine: LIVE and healthy (`/api/sentinel-health` proxied → ok)
- MM-01/02/03 orchestration + approval gate: LIVE in the container (validated)
- MM-02 shadow orchestration + SEC-02 cost gate: LIVE in the container
- Abigail CP-00 control plane: LIVE (localhost-only host publish, binds 0.0.0.0 in-container)

Still NOT live autonomous execution:
- Department metrics, agent count (48), token usage, job register are cockpit/demo values
- Agent registry remains authored/dormant — no autonomous worker execution
- Operator chat commands (e.g. `status`) are governed-refused in-container (command bus
  only honors operator commands from a true-loopback origin; Docker NAT is not loopback —
  production authenticates with an admin token instead). This is correct governance, not a defect.

Files:
- `fullstack_01_overview_sentinel_green.png` — dashboard overview, Sentinel "Healthy" (green)
- `fullstack_02_operator_cockpit.png` — operator cockpit against the full stack

Note: the dashboard's dedicated Governance sub-tab is click-driven and not captured by the
headless screenshot tool; the overview's "Live Service Health" panel shows Sentinel green +
kill-switch state.
