/* ======================================================================
   Abigail — Governed Operating Environment · app logic (P0 + P1)
   LOGOS Governance Systems Inc.

   Vanilla JS, no framework, no build step. Served via Flask static route.

   GOVERNANCE UI RULES (enforced here + by tests):
   - A widget renders LIVE only when a named real endpoint backs it.
     Everything else is SIMULATED / OFFLINE / LOCAL — never a bare "live" number.
   - Advanced Mode only REVEALS controls; it grants nothing. Every privileged
     call still sends the admin token; the backend is the real gate (401/403).
   - Destructive actions require a confirmation + reason before firing.
   - No raw /api/* endpoint paths are surfaced in standard-view copy.
   ====================================================================== */
(function () {
  "use strict";

  // Same-origin API base (no hardcoded host, no exposed path in the UI copy).
  var API = "";

  // ── provenance badge ────────────────────────────────────────────────
  function provBadge(kind) {
    var k = String(kind || "offline").toLowerCase();
    return '<span class="prov ' + k + '" title="Data provenance">' + k.toUpperCase() + "</span>";
  }

  // ── admin token (set in Settings; SESSION-SCOPED ONLY) ───────────────
  // The admin token is never persisted to localStorage or sent anywhere except
  // privileged backend calls. sessionStorage preserves it across reloads and
  // same-tab navigation, then clears it when the browser tab/session ends.
  // adminHeaders() is the single source that attaches it to gated calls.
  function adminToken() {
    try {
      return sessionStorage.getItem("ABIGAIL_ADMIN_TOKEN") || "";
    } catch (e) {
      return "";
    }
  }

  function setAdminToken(t) {
    var token = String(t == null ? "" : t).trim();
    try {
      if (token) {
        sessionStorage.setItem("ABIGAIL_ADMIN_TOKEN", token);
      } else {
        sessionStorage.removeItem("ABIGAIL_ADMIN_TOKEN");
      }
    } catch (e) {}
  }
  function adminHeaders() { var t = adminToken(); return t ? { Authorization: "Bearer " + t } : {}; }
  function operatorName() { try { return localStorage.getItem("abigail.operator") || "Operator"; } catch (e) { return "Operator"; } }

  // ── fetch helper (never throws to caller) ────────────────────────────
  async function fetchJSON(path, opts) {
    try {
      var r = await fetch(API + path, opts || {});
      var body = await r.json().catch(function () { return {}; });
      return {
        ok: r.ok,
        status: r.status,
        body: body,
        errorType: null
      };
    } catch (e) {
      var aborted = e && e.name === "AbortError";
      return {
        ok: false,
        status: 0,
        body: {
          error: aborted
            ? "The browser dispatch deadline expired."
            : "Required service is unreachable."
        },
        errorType: aborted ? "AbortError" : "NetworkError"
      };
    }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // ── shared state (only real, sourced data lives here) ────────────────
  var state = {
    status: null,
    sentinel: null,
    audit: [],
    auditLive: false,
    agents: [],
    agentsLive: false,
    agentLoaderOk: false,
    agentGovernedBy: null,
    agentDispatch: {
      status: "ready",
      evidence: null,
      error: null,
      agentId: null
    },
    lastRefresh: null
  };

  // ── refresh: pulls ONLY real endpoints ──────────────────────────────
  async function refresh() {
    var s = await fetchJSON("/api/status");
    state.status = s.ok ? s.body : null;
    var sh = await fetchJSON("/api/sentinel-health");
    state.sentinel = sh.ok ? sh.body : null;

    // Agent inventory is a real read-only endpoint. It describes loaded agent
    // definitions only; it does not imply dispatch authorization.
    var ar = await fetchJSON("/api/agents");
    var agentRows = ar.ok && Array.isArray(ar.body.agents)
      ? ar.body.agents
      : null;

    if (agentRows) {
      state.agents = agentRows;
      state.agentsLive = true;
      state.agentLoaderOk = ar.body.loader_ok === true;
      state.agentGovernedBy = ar.body.governed_by || null;
    } else {
      state.agents = [];
      state.agentsLive = false;
      state.agentLoaderOk = false;
      state.agentGovernedBy = null;
    }

    // audit tail is admin-gated; best-effort, honestly OFFLINE without a token
    var a = await fetchJSON("/api/audit/tail?n=25", { headers: adminHeaders() });
    // Backend returns {events:[...]}; accept legacy {entries:[...]} defensively. Without a
    // valid token this is 401/empty and the panel honestly stays OFFLINE.
    var auditRows = a.ok ? (a.body.events || a.body.entries) : null;
    if (Array.isArray(auditRows)) { state.audit = auditRows; state.auditLive = true; }
    else { state.audit = []; state.auditLive = false; }
    state.lastRefresh = new Date();
    var rs = document.getElementById("refreshStatus");
    if (rs) rs.textContent = "Refreshed " + state.lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    renderOnRefresh();
  }

  // Polled refresh must NEVER clobber in-progress input. The chat stream and the
  // Settings inputs are re-rendered only on explicit tab switch / send, not on the
  // 15s poll. This preserves the textarea value + focus while the user types.
  function renderOnRefresh() {
    if (activeTab === "workspace") return;            // chat has no polled data
    var ae = document.activeElement;
    if (ae && (ae.tagName === "TEXTAREA" || ae.tagName === "INPUT")) return; // user is typing
    renderActive();
  }

  // ── governance health (LIVE) ─────────────────────────────────────────
  function systemHealthy() { return !!(state.status && state.status.backend) && !!(state.sentinel && state.sentinel.ok); }
  function killSwitchActive() { return !!(state.status && state.status.kill_switch); }
  function violationCount() {
    // Derived from the admin audit tail (LIVE); OFFLINE without it.
    if (!state.auditLive) return null;
    var n = 0;
    state.audit.forEach(function (e) {
      var t = JSON.stringify(e).toUpperCase();
      if (t.indexOf("BLOCK") >= 0 || t.indexOf("APPROVAL_REQUIRED") >= 0) n++;
    });
    return n;
  }

  // ── greeting ─────────────────────────────────────────────────────────
  function greetWord() {
    var h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  }

  // ══════════════════════════════════════════════════════════════════════
  // HOME — operational briefing (P1). Every data line is provenance-badged.
  // ══════════════════════════════════════════════════════════════════════
  function renderHome() {
    var el = document.getElementById("tab-home");
    if (!el) return;
    var healthy = systemHealthy();
    var vc = violationCount();
    var ks = killSwitchActive();

    el.innerHTML =
      '<div class="greeting">' + greetWord() + ', <span class="accent">' + esc(operatorName()) + "</span></div>" +
      '<div class="sub" style="margin:4px 0 18px">Here is what Abigail can tell you right now. Signals are labeled by source.</div>' +

      '<div class="grid brief">' +
        // Abigail status (LIVE)
        '<div class="card">' +
          '<div class="row"><h3>Abigail Status</h3>' + provBadge("live") + "</div>" +
          '<div class="section">' +
            '<div class="brief-line"><span class="lbl">Control plane + Sentinel</span>' +
              '<span class="val">' + (healthy
                ? '<span class="chip ok"><span class="dot"></span>Healthy</span>'
                : '<span class="chip warn"><span class="dot"></span>Degraded</span>') + "</span></div>" +
            '<div class="brief-line"><span class="lbl">Kill switch</span>' +
              '<span class="val">' + (ks
                ? '<span class="chip crit"><span class="dot"></span>Active</span>'
                : '<span class="chip ok"><span class="dot"></span>Armed</span>') + "</span></div>" +
            '<div class="brief-line"><span class="lbl">Backend</span>' +
              '<span class="val">' + esc((state.status && state.status.backend) || "—") + "</span></div>" +
          "</div>" +
        "</div>" +

        // Needs attention (mixed provenance — each line labeled)
        '<div class="card">' +
          '<div class="row"><h3>Needs Attention</h3></div>' +
          '<div class="section">' +
            '<div class="brief-line"><span class="lbl">Governance violations (recent)</span>' +
              '<span class="val">' + (vc == null ? "—" : vc) + " " +
              provBadge(state.auditLive ? "live" : "offline") + "</span></div>" +
            '<div class="brief-line"><span class="lbl">Approvals pending</span>' +
              '<span class="val">— ' + provBadge("simulated") + "</span></div>" +
            '<div class="brief-line"><span class="lbl">Policy updates</span>' +
              '<span class="val">— ' + provBadge("simulated") + "</span></div>" +
            (state.auditLive ? "" :
              '<div class="tiny" style="margin-top:8px">Sign in with an operator token in Settings to see the live governance tail.</div>') +
          "</div>" +
        "</div>" +
      "</div>" +

      // While you were away (honest: Sentinel LIVE, activity counts SIMULATED)
      '<div class="card" style="margin-top:16px">' +
        '<div class="row"><h3>While you were away</h3></div>' +
        '<div class="section">' +
          '<div class="brief-line"><span class="lbl">Sentinel OverWatch</span>' +
            '<span class="val">' + ((state.sentinel && state.sentinel.ok)
              ? '<span class="chip ok"><span class="dot"></span>Healthy</span>'
              : '<span class="chip warn"><span class="dot"></span>Unknown</span>') + " " + provBadge("live") + "</span></div>" +
          '<div class="brief-line"><span class="lbl">Conversations completed</span><span class="val">— ' + provBadge("simulated") + "</span></div>" +
          '<div class="brief-line"><span class="lbl">Deployments approved</span><span class="val">— ' + provBadge("simulated") + "</span></div>" +
          '<div class="tiny" style="margin-top:8px">Activity counters become LIVE once an activity/jobs endpoint exists; shown as SIMULATED until then.</div>' +
        "</div>" +
      "</div>" +

      // Suggested actions (navigation affordances — not telemetry)
      '<div class="card" style="margin-top:16px">' +
        '<div class="row"><h3>Suggested Actions</h3><span class="tiny">suggestions</span></div>' +
        '<div class="section suggest">' +
          '<button data-go="workspace">Ask Abigail to review recent governance events<span class="arrow">→</span></button>' +
          '<button data-go="observability">Open the engineering truth view (Observability)<span class="arrow">→</span></button>' +
          '<button data-go="governance">Check governance controls and posture<span class="arrow">→</span></button>' +
        "</div>" +
        '<div style="margin-top:14px"><button class="btn primary" data-go="workspace">Ask Abigail…</button></div>' +
      "</div>";

    el.querySelectorAll("[data-go]").forEach(function (b) {
      b.onclick = function () { activateTab(b.getAttribute("data-go")); };
    });
  }

  // ══════════════════════════════════════════════════════════════════════
  // WORKSPACE — chat as Mission Control (P1). Chat is LIVE (/api/chat).
  // ══════════════════════════════════════════════════════════════════════
  var chat = [{ role: "sys", text: "Mission Control ready. Ask Abigail to review activity, or type a question. Every turn runs the governed pipeline (Sentinel · HAAP · approval · cost)." }];
  var chatBusy = false;


  // ── Governance evidence state contract ───────────────────────────────
  // Only one exact conjunction may produce VERIFIED. Missing, ambiguous,
  // legacy, or partial evidence always falls away from green.
  function nonEmpty(value) {
    return typeof value === "string" && value.trim().length > 0;
  }

  function deriveGovState(resp) {
    if (!resp) {
      return {
        state: "UNAVAILABLE",
        icon: "—",
        label: "Governance unavailable",
        detail: "No governance evidence was returned."
      };
    }

    if (resp.pending === true) {
      return {
        state: "VERIFYING",
        icon: "○",
        label: "Verifying",
        detail: "Authorization and response review are in progress."
      };
    }

    var mode = String(resp.mode || "").toUpperCase();
    var gov = resp.governance || {};

    if (
      mode === "APPROVAL_REQUIRED" ||
      mode === "STEP_UP_REQUIRED" ||
      mode === "HAAP_GATED"
    ) {
      return {
        state: "APPROVAL_REQUIRED",
        icon: "!",
        label: "Authorization required",
        detail: "This transaction stopped. A newly authorized request is required."
      };
    }

    if (
      mode === "SENTINEL_UNREACHABLE" ||
      mode === "SENTINEL_AUTHORITY_ERROR"
    ) {
      return {
        state: "UNAVAILABLE",
        icon: "—",
        label: "Governance unavailable",
        detail: "The required governance service or evidence was unavailable."
      };
    }

    if (
      resp.ok === false ||
      mode === "BLOCKED" ||
      mode === "SENTINEL_BLOCK" ||
      mode === "PROVIDER_EXECUTION_BLOCKED"
    ) {
      return {
        state: "BLOCKED",
        icon: "×",
        label: "Execution blocked",
        detail: "No unapproved response was released."
      };
    }

    var localGoverned =
      resp.ok === true &&
      mode === "PUBLIC_ASSIST" &&
      gov.execution_path === "deterministic_public_assist" &&
      gov.provider_execution_required === false &&
      gov.execution_status === "completed" &&
      gov.capability_outcome === "NOT_REQUIRED" &&
      gov.outbound_verdict === "NOT_REQUIRED";

    if (localGoverned) {
      return {
        state: "LOCAL_GOVERNED",
        icon: "✓",
        label: "Governed local response",
        detail: "No external model execution was required"
      };
    }

    var complete =
      resp.ok === true &&
      gov.execution_status === "completed" &&
      gov.capability_outcome === "CAPABILITY_CONSUMED" &&
      gov.outbound_verdict === "APPROVED" &&
      nonEmpty(gov.gov_tx_id) &&
      nonEmpty(gov.verdict_id) &&
      nonEmpty(gov.decision_id) &&
      nonEmpty(gov.capability_id) &&
      nonEmpty(gov.backend) &&
      nonEmpty(gov.model);

    if (complete) {
      return {
        state: "VERIFIED",
        icon: "✓",
        label: "Governance verified",
        detail: "Authorized provider · Single-use authority · Response approved"
      };
    }

    return {
      state: "UNAVAILABLE",
      icon: "—",
      label: "Governance unavailable",
      detail: "Complete execution evidence was not returned."
    };
  }

  function govStateClass(stateName) {
    var map = {
      VERIFYING: "verifying",
      VERIFIED: "verified",
      LOCAL_GOVERNED: "local-governed",
      APPROVAL_REQUIRED: "approval",
      BLOCKED: "blocked",
      UNAVAILABLE: "unavailable"
    };
    return map[stateName] || "unavailable";
  }

  function readableValue(value, fallback) {
    return nonEmpty(value) ? value : (fallback || "Not reported");
  }

  function titleCaseMachineValue(value) {
    if (!nonEmpty(value)) return "Not reported";
    return String(value)
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function renderGovernanceEvidence(resp) {
    var derived = deriveGovState(resp);
    var stateClass = govStateClass(derived.state);
    var gov = resp && resp.governance ? resp.governance : {};
    var orchestration = resp && resp.orchestration ? resp.orchestration : {};

    if (derived.state === "VERIFYING") {
      return (
        '<div class="gov-proof ' + stateClass + '" role="status" aria-live="polite">' +
          '<div class="gov-proof-summary">' +
            '<span class="gov-proof-icon" aria-hidden="true">' + esc(derived.icon) + "</span>" +
            '<div class="gov-proof-copy">' +
              '<strong>' + esc(derived.label) + "</strong>" +
              '<span>' + esc(derived.detail) + "</span>" +
            "</div>" +
          "</div>" +
        "</div>"
      );
    }

    var isLocalGoverned = derived.state === "LOCAL_GOVERNED";

    var hasExecutionProof =
      isLocalGoverned ||
      nonEmpty(gov.backend) ||
      nonEmpty(gov.model) ||
      nonEmpty(gov.gov_tx_id) ||
      nonEmpty(gov.capability_id);

    var executionDetails = "";

    if (isLocalGoverned) {
      executionDetails =
        '<details class="gov-proof-details">' +
          '<summary>View proof</summary>' +
          '<div class="gov-proof-body">' +
            '<div class="gov-proof-grid">' +
              '<div><span>Response path</span><strong>Deterministic local response</strong></div>' +
              '<div><span>External model</span><strong>Not required</strong></div>' +
              '<div><span>Provider authority</span><strong>Not required</strong></div>' +
              '<div><span>Execution</span><strong>Completed locally</strong></div>' +
            "</div>" +
            '<details class="gov-proof-technical">' +
              '<summary>Technical evidence</summary>' +
              '<div class="gov-proof-id-list">' +
                '<div><span>Execution path</span><code>' +
                  esc(readableValue(gov.execution_path)) +
                "</code></div>" +
                '<div><span>Provider execution required</span><code>false</code></div>' +
                '<div><span>Capability outcome</span><code>' +
                  esc(readableValue(gov.capability_outcome)) +
                "</code></div>" +
                '<div><span>Outbound review</span><code>' +
                  esc(readableValue(gov.outbound_verdict)) +
                "</code></div>" +
              "</div>" +
            "</details>" +
            (nonEmpty(orchestration.gov_tx_id)
              ? (
                '<details class="gov-proof-planning">' +
                  '<summary>Planning metadata</summary>' +
                  '<div class="gov-proof-id-list">' +
                    '<div><span>Planning mode</span><strong>' +
                      esc(readableValue(orchestration.orchestration_mode, "Shadow")) +
                    "</strong></div>" +
                    '<div><span>Shadow planning transaction</span><code>' +
                      esc(orchestration.gov_tx_id) +
                    "</code></div>" +
                  "</div>" +
                "</details>"
              )
              : "") +
          "</div>" +
        "</details>";
    } else if (hasExecutionProof) {
      executionDetails =
        '<details class="gov-proof-details">' +
          '<summary>View proof</summary>' +
          '<div class="gov-proof-body">' +
            '<div class="gov-proof-grid">' +
              '<div><span>Provider</span><strong>' +
                esc(readableValue(gov.backend)) + " · " +
                esc(readableValue(gov.model)) +
              "</strong></div>" +
              '<div><span>Authorization</span><strong>' +
                (nonEmpty(gov.decision_id) ? "Approved for this request" : "Not confirmed") +
              "</strong></div>" +
              '<div><span>Single-use authority</span><strong>' +
                (gov.capability_outcome === "CAPABILITY_CONSUMED"
                  ? "Consumed before execution"
                  : titleCaseMachineValue(gov.capability_outcome)) +
              "</strong></div>" +
              '<div><span>Outbound review</span><strong>' +
                titleCaseMachineValue(gov.outbound_verdict) +
              "</strong></div>" +
              '<div><span>Execution</span><strong>' +
                titleCaseMachineValue(gov.execution_status) +
              "</strong></div>" +
            "</div>" +

            '<details class="gov-proof-technical">' +
              '<summary>Technical evidence</summary>' +
              '<div class="gov-proof-id-list">' +
                '<div><span>Governance transaction</span><code>' +
                  esc(readableValue(gov.gov_tx_id)) +
                "</code></div>" +
                '<div><span>Sentinel verdict</span><code>' +
                  esc(readableValue(gov.verdict_id)) +
                "</code></div>" +
                '<div><span>Authorization decision</span><code>' +
                  esc(readableValue(gov.decision_id)) +
                "</code></div>" +
                '<div><span>Single-use capability</span><code>' +
                  esc(readableValue(gov.capability_id)) +
                "</code></div>" +
              "</div>" +
            "</details>" +

            (nonEmpty(orchestration.gov_tx_id)
              ? (
                '<details class="gov-proof-planning">' +
                  '<summary>Planning metadata</summary>' +
                  '<div class="gov-proof-id-list">' +
                    '<div><span>Planning mode</span><strong>' +
                      esc(readableValue(orchestration.orchestration_mode, "Shadow")) +
                    "</strong></div>" +
                    '<div><span>Shadow planning transaction</span><code>' +
                      esc(orchestration.gov_tx_id) +
                    "</code></div>" +
                  "</div>" +
                "</details>"
              )
              : "") +
          "</div>" +
        "</details>";
    }

    return (
      '<div class="gov-proof ' + stateClass + '">' +
        '<div class="gov-proof-summary">' +
          '<span class="gov-proof-icon" aria-hidden="true">' + esc(derived.icon) + "</span>" +
          '<div class="gov-proof-copy">' +
            '<strong>' + esc(derived.label) + "</strong>" +
            '<span>' + esc(derived.detail) + "</span>" +
          "</div>" +
        "</div>" +
        executionDetails +
      "</div>"
    );
  }

  function renderChatMessage(message) {
    var role = message.role || "sys";
    var roleLabel = role === "user"
      ? "You"
      : (role === "sys" ? "System" : "Abigail");

    var response = message.response || null;
    var evidence = role === "abigail" || (role === "sys" && response)
      ? renderGovernanceEvidence(response)
      : "";

    var bubble = message.text
      ? '<div class="bubble">' + esc(message.text) + "</div>"
      : "";

    return (
      '<div class="msg ' + esc(role) + '">' +
        '<div class="role">' + esc(roleLabel) + "</div>" +
        bubble +
        evidence +
      "</div>"
    );
  }

  function renderWorkspace() {
    var el = document.getElementById("tab-workspace");
    if (!el) return;
    el.innerHTML =
      '<div class="chat">' +
        '<div class="chat-head"><div><h3>Workspace · Chat</h3>' +
          '<div class="tiny">Governed Abigail channel — audit-logged</div></div>' +
          provBadge("live") + "</div>" +
        '<div class="chat-stream" id="chatStream">' +
          chat.map(renderChatMessage).join("") +
          (chatBusy ? '<div class="thinking">Abigail is thinking…</div>' : "") +
        "</div>" +
        '<div class="composer">' +
          '<div class="composer-row">' +
            '<textarea id="chatInput" rows="1" placeholder="Ask Abigail… (e.g. \'Review recent governance events\')" ' + (chatBusy ? "disabled" : "") + "></textarea>" +
            '<button class="btn primary" id="sendBtn" ' + (chatBusy ? "disabled" : "") + ">Send</button>" +
          "</div>" +
          // Quick actions are affordances, not yet backed by endpoints → PREVIEW.
          '<div class="quick-actions">' +
            '<button class="btn" disabled title="Preview — no backing endpoint yet">Generate Report ' + provBadge("simulated") + "</button>" +
            '<button class="btn" disabled title="Preview — no backing endpoint yet">Review ' + provBadge("simulated") + "</button>" +
            '<button class="btn" disabled title="Preview — no backing endpoint yet">Approve ' + provBadge("simulated") + "</button>" +
          "</div>" +
        "</div>" +
      "</div>";
    var stream = document.getElementById("chatStream");
    if (stream) stream.scrollTop = stream.scrollHeight;
    var send = document.getElementById("sendBtn");
    var input = document.getElementById("chatInput");
    if (send) send.onclick = sendChat;
    if (input) input.onkeydown = function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } };
    if (input && !chatBusy) input.focus();
  }

  async function sendChat() {
    var input = document.getElementById("chatInput");
    if (!input) return;

    var msg = input.value.trim();
    if (!msg || chatBusy) return;

    chat.push({ role: "user", text: msg });

    var pendingMessage = {
      role: "abigail",
      text: "",
      response: { pending: true }
    };

    chat.push(pendingMessage);
    chatBusy = true;
    renderWorkspace();

    var r = await fetchJSON("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg })
    });

    chatBusy = false;

    var response = r.body && typeof r.body === "object"
      ? r.body
      : {
          ok: false,
          mode: "SENTINEL_UNREACHABLE",
          error: "No valid response was returned."
        };

    if (!r.ok && response.ok !== false) {
      response.ok = false;
    }

    var text =
      response.text ||
      response.error ||
      "[No response was released.]";

    var finalMessage = {
      role: response.ok ? "abigail" : "sys",
      text: text,
      response: response
    };

    var pendingIndex = chat.indexOf(pendingMessage);
    if (pendingIndex >= 0) {
      chat.splice(pendingIndex, 1, finalMessage);
    } else {
      chat.push(finalMessage);
    }

    renderWorkspace();
  }


  // ══════════════════════════════════════════════════════════════════════
  // OPERATIONS — live read-only agent inventory.
  // Loaded means present in the registry; it does NOT imply execution authority.
  // ══════════════════════════════════════════════════════════════════════
  function dispatchEvidenceVerified(governance) {
    return Boolean(
      governance &&
      governance.execution_status === "completed" &&
      governance.capability_outcome === "CAPABILITY_CONSUMED" &&
      governance.outbound_verdict === "APPROVED" &&
      governance.gov_tx_id &&
      governance.verdict_id &&
      governance.decision_id &&
      governance.capability_id &&
      governance.backend &&
      governance.model
    );
  }

  function dispatchPresentation() {
    var d = state.agentDispatch || {};
    var status = d.status || "ready";

    if (status === "verifying") {
      return {
        label: "VERIFYING",
        badge: "local",
        detail: "A capability-bound governed agent dispatch is in progress."
      };
    }

    if (status === "verified") {
      var g = d.evidence || {};
      return {
        label: "VERIFIED",
        badge: "live",
        detail:
          "Capability consumed · Outbound approved · " +
          String(g.backend || "provider") + " · " +
          String(g.model || "model")
      };
    }

    if (status === "blocked") {
      return {
        label: "BLOCKED",
        badge: "offline",
        detail:
          d.error ||
          "The governed execution boundary rejected the dispatch."
      };
    }

    if (status === "approval_required") {
      return {
        label: "APPROVAL REQUIRED",
        badge: "offline",
        detail:
          d.error ||
          "Human authorization is required before provider execution."
      };
    }

    if (status === "unavailable") {
      return {
        label: "UNAVAILABLE",
        badge: "offline",
        detail:
          d.error ||
          "A required governance or provider service is unavailable."
      };
    }

    if (status === "timed_out") {
      return {
        label: "TIMED OUT",
        badge: "offline",
        detail:
          d.error ||
          "The governed dispatch exceeded its bounded deadline."
      };
    }

    if (status === "not_verified") {
      return {
        label: "NOT VERIFIED",
        badge: "offline",
        detail:
          d.error ||
          "The dispatch response lacked complete governance evidence."
      };
    }

    return {
      label: "READY",
      badge: "local",
      detail:
        "No governed agent dispatch has been verified in this browser session."
    };
  }

  async function verifyAgentDispatch(agentId) {
    if (!agentId) return;
    if (state.agentDispatch.status === "verifying") return;

    if (!adminToken()) {
      state.agentDispatch = {
        status: "blocked",
        evidence: null,
        error: "Operator authorization is required to verify agent dispatch.",
        agentId: agentId
      };
      renderOperations();
      return;
    }

    state.agentDispatch = {
      status: "verifying",
      evidence: null,
      error: null,
      agentId: agentId
    };
    renderOperations();

    var headers = adminHeaders();
    headers["Content-Type"] = "application/json";

    var controller = new AbortController();
    var browserDeadlineMs = 70000;
    var deadline = window.setTimeout(function () {
      controller.abort();
    }, browserDeadlineMs);

    var response;

    try {
      response = await fetchJSON("/api/agents/dispatch", {
        method: "POST",
        headers: headers,
        signal: controller.signal,
        body: JSON.stringify({
          agent_id: agentId,
          task:
            "Confirm this governed dispatch completed successfully. " +
            "Return one concise sentence and perform no external actions."
        })
      });
    } finally {
      window.clearTimeout(deadline);
    }

    var body = response.body || {};
    var governance = body.governance || null;
    var terminalState = String(
      body.terminal_state ||
      body.mode ||
      ""
    ).trim().toUpperCase();

    if (
      response.ok &&
      body.ok === true &&
      dispatchEvidenceVerified(governance)
    ) {
      state.agentDispatch = {
        status: "verified",
        evidence: governance,
        error: null,
        agentId: agentId
      };
    } else if (
      response.errorType === "AbortError" ||
      terminalState === "TIMED_OUT" ||
      response.status === 504
    ) {
      state.agentDispatch = {
        status: "timed_out",
        evidence: governance,
        error:
          body.error ||
          "The governed dispatch exceeded its bounded deadline.",
        agentId: agentId
      };
    } else if (
      terminalState === "APPROVAL_REQUIRED" ||
      body.approval?.human_approval_required === true ||
      response.status === 409
    ) {
      state.agentDispatch = {
        status: "approval_required",
        evidence: governance,
        error:
          body.error ||
          body.text ||
          "Human approval is required before execution.",
        agentId: agentId
      };
    } else if (
      terminalState === "UNAVAILABLE" ||
      response.errorType === "NetworkError" ||
      response.status === 502 ||
      response.status === 503
    ) {
      state.agentDispatch = {
        status: "unavailable",
        evidence: governance,
        error:
          body.error ||
          "A required governance or provider service is unavailable.",
        agentId: agentId
      };
    } else if (
      terminalState === "BLOCKED" ||
      body.blocked === true ||
      response.status === 401 ||
      response.status === 403
    ) {
      state.agentDispatch = {
        status: "blocked",
        evidence: governance,
        error: body.error || "Governed dispatch was blocked.",
        agentId: agentId
      };
    } else {
      state.agentDispatch = {
        status: "not_verified",
        evidence: governance,
        error:
          body.error ||
          "Dispatch completed without the full verification evidence conjunction.",
        agentId: agentId
      };
    }

    renderOperations();
  }

  function renderOperations() {
    var el = document.getElementById("tab-operations");
    if (!el) return;

    var openDepartments = {};
    Array.prototype.forEach.call(
      el.querySelectorAll("details.ops-dept[open][data-department]"),
      function (details) {
        openDepartments[
          details.getAttribute("data-department")
        ] = true;
      }
    );

    var dispatchView = dispatchPresentation();
    var dispatchBusy =
      state.agentDispatch &&
      state.agentDispatch.status === "verifying";

    if (!state.agentsLive) {
      el.innerHTML =
        '<div class="card"><div class="empty">' +
          '<h3>Operations</h3>' +
          '<div class="tiny">Agent registry is currently unavailable.</div>' +
          provBadge("offline") +
        "</div></div>";
      return;
    }

    var grouped = {};
    state.agents.forEach(function (agent) {
      var dept = String(agent.department || "UNASSIGNED");
      if (!grouped[dept]) grouped[dept] = [];
      grouped[dept].push(agent);
    });

    var departments = Object.keys(grouped).sort();
    var cards = departments.map(function (dept) {
      var agents = grouped[dept].slice().sort(function (a, b) {
        return String(a.name || a.id).localeCompare(String(b.name || b.id));
      });

      var rows = agents.map(function (agent) {
        var specialty = agent.specialty
          ? String(agent.specialty).replace(/_/g, " ")
          : "general assignment";

        return (
          '<div class="ops-agent">' +
            '<div>' +
              '<div class="ops-agent-name">' +
                esc(agent.name || agent.id) +
              "</div>" +
              '<span class="ops-agent-id">' +
                esc(agent.id || "") +
              "</span>" +
              '<span class="ops-agent-specialty">' +
                esc(specialty) +
              "</span>" +
            "</div>" +
            '<div class="ops-agent-actions">' +
              provBadge("loaded") +
              '<button type="button" class="ops-verify-btn" ' +
                'data-dispatch-agent="' + esc(agent.id || "") + '" ' +
                (dispatchBusy ? "disabled " : "") +
                'aria-label="Verify governed dispatch for ' +
                  esc(agent.name || agent.id || "agent") + '">' +
                (dispatchBusy &&
                 state.agentDispatch.agentId === agent.id
                  ? "Verifying…"
                  : "Verify dispatch") +
              "</button>" +
            "</div>" +
          "</div>"
        );
      }).join("");

      var departmentOpen = openDepartments[dept] === true;

      return (
        '<details class="ops-dept" data-department="' +
          esc(dept) + '" ' +
          (departmentOpen ? "open" : "") +
        ">" +
          '<summary>' +
            '<span>' + esc(dept) + "</span>" +
            '<span class="tiny">' + agents.length + " loaded agents</span>" +
          "</summary>" +
          '<div class="ops-dept-body">' + rows + "</div>" +
        "</details>"
      );
    }).join("");

    el.innerHTML =
      '<div class="greeting">Operations</div>' +
      '<div class="sub" style="margin:4px 0 18px">' +
        'Live read-only inventory of agents loaded into Abigail.' +
      "</div>" +

      '<div class="card">' +
        '<div class="row">' +
          '<h3>Agent Registry</h3>' +
          provBadge("live") +
        "</div>" +
        '<div class="section">' +
          '<div class="brief-line">' +
            '<span class="lbl">Loaded agents</span>' +
            '<span class="val"><strong>' + state.agents.length + "</strong></span>" +
          "</div>" +
          '<div class="brief-line">' +
            '<span class="lbl">Departments</span>' +
            '<span class="val"><strong>' + departments.length + "</strong></span>" +
          "</div>" +
          '<div class="brief-line">' +
            '<span class="lbl">Registry loader</span>' +
            '<span class="val">' +
              (state.agentLoaderOk ? "Operational " + provBadge("live") : "Unavailable " + provBadge("offline")) +
            "</span>" +
          "</div>" +
          '<div class="brief-line">' +
            '<span class="lbl">Governed by</span>' +
            '<span class="val">' + esc(state.agentGovernedBy || "not reported") + "</span>" +
          "</div>" +
        "</div>" +
        '<div class="ops-dispatch-note">' +
          '<div class="row">' +
            '<strong>Dispatch status: ' +
              esc(dispatchView.label) +
              ".</strong>" +
            provBadge(dispatchView.badge) +
          "</div>" +
          '<div class="ops-dispatch-detail">' +
            esc(dispatchView.detail) +
          "</div>" +
          '<div class="ops-dispatch-explainer">' +
            'LOADED proves registry presence only. VERIFIED requires completed ' +
            'execution, single-use capability consumption, outbound approval, ' +
            'and complete transaction-bound authority evidence.' +
          "</div>" +
        "</div>" +
      "</div>" +

      '<div class="ops-grid">' +
        cards +
      "</div>";

    Array.prototype.forEach.call(
      el.querySelectorAll("[data-dispatch-agent]"),
      function (button) {
        button.addEventListener("click", function () {
          verifyAgentDispatch(
            button.getAttribute("data-dispatch-agent")
          );
        });
      }
    );

    Array.prototype.forEach.call(
      el.querySelectorAll("details.ops-dept[data-department]"),
      function (details) {
        details.addEventListener("toggle", function () {
          var department =
            details.getAttribute("data-department");

          if (details.open) {
            openDepartments[department] = true;
          } else {
            delete openDepartments[department];
          }
        });
      }
    );
  }

  // ══════════════════════════════════════════════════════════════════════
  // GOVERNANCE — live read-only control posture and audit evidence.
  // No control is presented as actionable unless a backing endpoint exists.
  // ══════════════════════════════════════════════════════════════════════
  function renderGovernance() {
    var el = document.getElementById("tab-governance");
    if (!el) return;

    var statusLive = !!state.status;
    var sentinelLive = !!state.sentinel;
    var sentinelOk = !!(state.sentinel && state.sentinel.ok);
    var ks = killSwitchActive();
    var recentViolations = violationCount();

    var auditRows = state.auditLive
      ? state.audit.slice().reverse().slice(0, 12).map(function (event) {
          var eventType =
            event.event_type ||
            event.type ||
            event.event ||
            "EVENT";

          var timestamp =
            event.ts ||
            event.timestamp ||
            event.time ||
            "Time not reported";

          var detail = event.data || event.details || event.payload || {};
          var detailText;

          try {
            detailText = typeof detail === "string"
              ? detail
              : JSON.stringify(detail);
          } catch (e) {
            detailText = "Evidence available";
          }

          return (
            '<div class="ops-agent">' +
              '<div>' +
                '<div class="ops-agent-name">' + esc(eventType) + "</div>" +
                '<span class="ops-agent-id">' + esc(timestamp) + "</span>" +
                '<span class="ops-agent-specialty">' + esc(detailText) + "</span>" +
              "</div>" +
              '<div>' + provBadge("live") + "</div>" +
            "</div>"
          );
        }).join("")
      : "";

    el.innerHTML =
      '<div class="greeting">Governance</div>' +
      '<div class="sub" style="margin:4px 0 18px">' +
        'Live, read-only posture from Abigail and Sentinel. Privileged actions remain backend-enforced.' +
      "</div>" +

      '<div class="grid brief">' +
        '<div class="card">' +
          '<div class="row"><h3>Runtime Authority</h3>' +
            provBadge(statusLive ? "live" : "offline") +
          "</div>" +
          '<div class="section">' +
            '<div class="brief-line"><span class="lbl">Control plane</span>' +
              '<span class="val">' +
                (statusLive
                  ? '<span class="chip ok"><span class="dot"></span>Online</span>'
                  : '<span class="chip warn"><span class="dot"></span>Unavailable</span>') +
              "</span></div>" +
            '<div class="brief-line"><span class="lbl">Kill switch</span>' +
              '<span class="val">' +
                (ks
                  ? '<span class="chip crit"><span class="dot"></span>Active</span>'
                  : '<span class="chip ok"><span class="dot"></span>Armed</span>') +
              "</span></div>" +
            '<div class="brief-line"><span class="lbl">Backend</span>' +
              '<span class="val">' +
                esc((state.status && state.status.backend) || "Not reported") +
              "</span></div>" +
            '<div class="brief-line"><span class="lbl">Runtime version</span>' +
              '<span class="val">' +
                esc((state.status && state.status.version) || "Not reported") +
              "</span></div>" +
          "</div>" +
        "</div>" +

        '<div class="card">' +
          '<div class="row"><h3>Sentinel OverWatch</h3>' +
            provBadge(sentinelLive ? "live" : "offline") +
          "</div>" +
          '<div class="section">' +
            '<div class="brief-line"><span class="lbl">Authority service</span>' +
              '<span class="val">' +
                (sentinelOk
                  ? '<span class="chip ok"><span class="dot"></span>Healthy</span>'
                  : '<span class="chip warn"><span class="dot"></span>Unavailable</span>') +
              "</span></div>" +
            '<div class="brief-line"><span class="lbl">Recent governed stops</span>' +
              '<span class="val">' +
                (recentViolations == null ? "—" : esc(recentViolations)) + " " +
                provBadge(state.auditLive ? "live" : "offline") +
              "</span></div>" +
            '<div class="brief-line"><span class="lbl">Audit evidence</span>' +
              '<span class="val">' +
                (state.auditLive
                  ? '<span class="chip ok"><span class="dot"></span>Available</span>'
                  : '<span class="chip warn"><span class="dot"></span>Token required</span>') +
              "</span></div>" +
            '<div class="brief-line"><span class="lbl">Control mode</span>' +
              '<span class="val">Read only</span></div>' +
          "</div>" +
        "</div>" +
      "</div>" +

      '<div class="card" style="margin-top:16px">' +
        '<div class="row"><h3>Recent Governance Evidence</h3>' +
          provBadge(state.auditLive ? "live" : "offline") +
        "</div>" +
        '<div class="section">' +
          (state.auditLive
            ? (auditRows || '<div class="tiny">No recent audit events were returned.</div>')
            : '<div class="empty">' +
                '<h3>Operator token required</h3>' +
                '<div class="tiny">Enter the admin token in Settings to retrieve the protected governance tail.</div>' +
                provBadge("offline") +
              "</div>") +
        "</div>" +
      "</div>" +

      '<div class="card" style="margin-top:16px">' +
        '<div class="row"><h3>Enforcement Boundary</h3></div>' +
        '<div class="section">' +
          '<div class="brief-line"><span class="lbl">Authorization decisions</span>' +
            '<span class="val">Enforced by backend</span></div>' +
          '<div class="brief-line"><span class="lbl">Advanced Mode</span>' +
            '<span class="val">Reveal only</span></div>' +
          '<div class="brief-line"><span class="lbl">Operator actions</span>' +
            '<span class="val">Use Operator Console</span></div>' +
          '<div style="margin-top:14px">' +
            '<a class="btn primary" href="dashboard.html">Open Operator Console →</a>' +
          "</div>" +
        "</div>" +
      "</div>";
  }

  // ── empty state for phases not yet built (honest, no fabricated data) ─
  function emptyTab(id, title, note) {
    var el = document.getElementById("tab-" + id);
    if (!el) return;
    el.innerHTML = '<div class="card"><div class="empty"><h3>' + esc(title) + "</h3>" +
      '<div class="tiny">' + esc(note) + "</div>" + provBadge("offline") + "</div></div>";
  }

  // ── tab router ───────────────────────────────────────────────────────
  var activeTab = "home";
  function renderActive() {
    if (activeTab === "home") renderHome();
    else if (activeTab === "workspace") renderWorkspace();
    else if (activeTab === "operations") renderOperations();
    else if (activeTab === "governance") renderGovernance();
    else if (activeTab === "observability") window.location.href = "dashboard.html";
    else if (activeTab === "settings") renderSettings();
  }
  function activateTab(id) {
    activeTab = id;
    document.querySelectorAll(".nav button").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-tab") === id); });
    document.querySelectorAll(".tab").forEach(function (t) { t.classList.toggle("active", t.id === "tab-" + id); });
    renderActive();
  }

  // Honest, never-blank indicator of whether a token is held this session.
  function tokenStateHtml() {
    return adminToken()
      ? '<span class="prov live">TOKEN SET</span> active for this session — admin-gated panels will attempt live data'
      : '<span class="prov offline">NO TOKEN</span> admin-gated panels stay OFFLINE until a token is supplied';
  }

  // ── Settings (P1 minimal: operator name + token, mode toggles) ───────
  function renderSettings() {
    var el = document.getElementById("tab-settings");
    if (!el) return;
    el.innerHTML =
      '<div class="card"><div class="row"><h3>Operator</h3>' + provBadge("local") + "</div>" +
        '<div class="section">' +
          '<div class="tiny">Display name (stored in this browser only)</div>' +
          '<input id="setName" class="btn" style="width:100%;margin-top:6px" value="' + esc(operatorName()) + '"/>' +
          '<div class="tiny" style="margin-top:12px">Operator admin token (sent only on privileged calls; stored only in this browser tab session; survives reloads and clears when the session ends)</div>' +
          '<input id="setTok" type="password" autocomplete="new-password" spellcheck="false" class="btn" style="width:100%;margin-top:6px" placeholder="paste admin token to enable admin-gated panels"/>' +
          '<div class="tiny" id="tokState" style="margin-top:6px">' + tokenStateHtml() + '</div>' +
          '<div style="margin-top:12px"><button class="btn primary" id="saveSettings">Save</button> ' +
          '<button class="btn" id="clearTok">Clear token</button></div>' +
        "</div></div>" +
      '<div class="card" style="margin-top:16px"><div class="row"><h3>Modes</h3></div>' +
        '<div class="section tiny">Advanced Mode reveals privileged controls in later phases. It grants nothing on its own — every privileged action still requires the admin token and is enforced by the backend.</div>' +
      "</div>";
    function syncTokState() {
      var st = document.getElementById("tokState");
      if (st) st.innerHTML = tokenStateHtml();
    }
    document.getElementById("saveSettings").onclick = function () {
      var nameInput = document.getElementById("setName");
      var tokenInput = document.getElementById("setTok");

      try {
        localStorage.setItem(
          "abigail.operator",
          nameInput.value.trim() || "Operator"
        );
      } catch (e) {}

      var t = String(tokenInput.value || "").trim();

      if (!t) {
        var st = document.getElementById("tokState");
        if (st) {
          st.innerHTML =
            '<span class="prov offline">TOKEN NOT SAVED</span> ' +
            'The token field was empty. Paste or manually type the token, then Save.';
        }
        tokenInput.focus();
        return;
      }

      setAdminToken(t);

      if (!adminToken()) {
        var failedState = document.getElementById("tokState");
        if (failedState) {
          failedState.innerHTML =
            '<span class="prov offline">STORAGE FAILED</span> ' +
            'The browser rejected sessionStorage access.';
        }
        return;
      }

      tokenInput.value = "";
      syncTokState();
      refresh();
    };
    document.getElementById("clearTok").onclick = function () {
      setAdminToken("");
      document.getElementById("setTok").value = "";
      syncTokState();
      refresh();                 // panels honestly drop back to OFFLINE
    };
  }

  // ── Advanced mode toggle (reveal-only) ───────────────────────────────
  function initAdvanced() {
    var on = false;
    try { on = localStorage.getItem("abigail.adv") === "1"; } catch (e) {}
    document.body.classList.toggle("adv", on);
    var t = document.getElementById("advToggle");
    if (t) t.onclick = function () {
      var now = !document.body.classList.contains("adv");
      document.body.classList.toggle("adv", now);
      try { localStorage.setItem("abigail.adv", now ? "1" : "0"); } catch (e) {}
    };
  }

  // ── confirm + reason modal (for destructive actions in later phases) ─
  // Exposed for future phases; no destructive action wires it yet.
  window.confirmReason = function (title, desc) {
    return new Promise(function (resolve) {
      var back = document.getElementById("modalBack");
      document.getElementById("modalTitle").textContent = title;
      document.getElementById("modalDesc").textContent = desc || "";
      var ta = document.getElementById("modalReason"); ta.value = "";
      back.classList.add("open");
      document.getElementById("modalCancel").onclick = function () { back.classList.remove("open"); resolve(null); };
      document.getElementById("modalConfirm").onclick = function () {
        var reason = ta.value.trim();
        if (!reason) { ta.focus(); return; }   // reason is REQUIRED
        back.classList.remove("open"); resolve(reason);
      };
    });
  };

  // ── boot ─────────────────────────────────────────────────────────────
  function init() {
    document.querySelectorAll(".nav button").forEach(function (b) {
      b.onclick = function () { activateTab(b.getAttribute("data-tab")); };
    });
    initAdvanced();
    var rb = document.getElementById("refreshBtn");
    if (rb) rb.onclick = refresh;
    activateTab("home");
    refresh();
    setInterval(refresh, 15000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // export a tiny surface for tests / future phases
  window.Abigail = { provBadge: provBadge, fetchJSON: fetchJSON };
})();
