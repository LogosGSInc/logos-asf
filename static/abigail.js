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

  // ── admin token (set in Settings; IN-MEMORY ONLY) ────────────────────
  // Per this environment's constraints the admin token is NEVER persisted to
  // localStorage. It lives only in this closure for the current page session and
  // is wiped on reload. adminHeaders() is the single source that attaches it to
  // every admin-gated call the UI makes; the backend remains the real gate.
  var adminTokenValue = "";
  function adminToken() { return adminTokenValue; }
  function setAdminToken(t) { adminTokenValue = String(t == null ? "" : t).trim(); }
  function adminHeaders() { var t = adminToken(); return t ? { Authorization: "Bearer " + t } : {}; }
  function operatorName() { try { return localStorage.getItem("abigail.operator") || "Operator"; } catch (e) { return "Operator"; } }

  // ── fetch helper (never throws to caller) ────────────────────────────
  async function fetchJSON(path, opts) {
    try {
      var r = await fetch(API + path, opts || {});
      var body = await r.json().catch(function () { return {}; });
      return { ok: r.ok, status: r.status, body: body };
    } catch (e) {
      return { ok: false, status: 0, body: { error: "unreachable" } };
    }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // ── shared state (only real, sourced data lives here) ────────────────
  var state = { status: null, sentinel: null, audit: [], auditLive: false, lastRefresh: null };

  // ── refresh: pulls ONLY real endpoints ──────────────────────────────
  async function refresh() {
    var s = await fetchJSON("/api/status");
    state.status = s.ok ? s.body : null;
    var sh = await fetchJSON("/api/sentinel-health");
    state.sentinel = sh.ok ? sh.body : null;
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

  function renderWorkspace() {
    var el = document.getElementById("tab-workspace");
    if (!el) return;
    el.innerHTML =
      '<div class="chat">' +
        '<div class="chat-head"><div><h3>Workspace · Chat</h3>' +
          '<div class="tiny">Governed Abigail channel — audit-logged</div></div>' +
          provBadge("live") + "</div>" +
        '<div class="chat-stream" id="chatStream">' +
          chat.map(function (m) {
            return '<div class="msg ' + m.role + '">' +
              (m.role === "user" ? '<div class="role">You</div>' : '<div class="role">' + (m.role === "sys" ? "System" : "Abigail") + "</div>") +
              '<div class="bubble">' + esc(m.text) + "</div></div>";
          }).join("") +
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
    chatBusy = true; renderWorkspace();
    var r = await fetchJSON("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg })
    });
    chatBusy = false;
    var text = (r.body && (r.body.text || r.body.error)) || "[no response]";
    chat.push({ role: r.body && r.body.ok ? "abigail" : "sys", text: text });
    renderWorkspace();
  }

  // ── empty state for phases not yet built (honest, no fabricated data) ─
  function emptyTab(id, title, note) {
    var el = document.getElementById("tab-" + id);
    if (!el) return;
    el.innerHTML = '<div class="card"><div class="empty"><h3>' + esc(title) + "</h3>" +
      '<div class="tiny">' + esc(note) + "</div>" + provBadge("offline") + "</div></div>";
  }

  // ══════════════════════════════════════════════════════════════════════
  // GOVERNANCE — Trust, safety, audit (P2, Slice 1).
  //   Sentinel health is LIVE (/api/sentinel-health, ungated).
  //   Audit history is LIVE but admin-gated (/api/audit/tail via adminHeaders()).
  //   No token → honest "auth required" panel, never a blank section.
  //   Raw event_type enums are translated to plain-language sentences for a
  //   non-technical viewer; the raw name + full record stay available on hover.
  // ══════════════════════════════════════════════════════════════════════

  // Plain-language translations of backend audit event_type enums. Anything not
  // listed here falls back to humanizeEvent() so a new event never surfaces as a
  // bare enum string to the operator.
  var AUDIT_LABELS = {
    AGENT_DEF_RESOLVED: "An agent definition was loaded",
    AGENT_SPAWN_ATTEMPT: "An agent was asked to start",
    AGENT_SPAWN_BLOCKED: "An agent was prevented from starting",
    AGENT_SPAWN_COMPLETE: "An agent started successfully",
    AGENT_SPAWN_ERROR: "An agent failed to start",
    AGENT_SPAWN_NO_DOCKER: "An agent could not start — its sandbox was unavailable",
    AGENT_SPAWN_TIMEOUT: "An agent took too long to start and was stopped",
    APPROVAL_REQUIRED_ENFORCED: "An action was held for human approval",
    BACKEND_ERROR: "The AI backend reported an error",
    BACKEND_SWITCH: "The AI backend was switched",
    BIND_NONLOCAL_REFUSED: "A non-local network binding was refused",
    CONTROL_PLANE_AUTH_REJECTED: "An unauthorized control-plane access was rejected",
    COST_GATE_BLOCK: "An action was blocked for exceeding cost limits",
    DEPT_KILL: "A department was shut down",
    DEPT_RESTART: "A department was restarted",
    DISPATCH_APPROVAL_REQUIRED: "An action was held for human approval",
    DISPATCH_AUTH_FAILED: "An action was refused for failing authorization",
    DISPATCH_AUTH_REJECTED: "An unauthorized action attempt was rejected",
    DISPATCH_BLOCKED: "An action was blocked by governance",
    DISPATCH_COMPLETE: "An action completed",
    DISPATCH_COST_BLOCK: "An action was blocked for exceeding cost limits",
    DISPATCH_ERROR: "An action failed with an error",
    DISPATCH_SENTINEL_BLOCK: "An action was blocked by the security layer",
    GOVERNANCE_UNAVAILABLE_FAIL_CLOSED: "Governance was unavailable, so the action was safely refused",
    HAAP_CONSTITUTIONAL_BLOCK: "A request was blocked for violating core policy",
    HAAP_DRS_DECISION: "A request was risk-scored and ruled on",
    HAAP_SENTINEL_BLOCK: "A request was blocked by the security layer",
    KILL_SWITCH_ACTIVATED: "The emergency kill switch was activated",
    KILL_SWITCH_CLEARED: "The emergency kill switch was cleared",
    MODEL_ROUTE_CARD: "A request was routed to a model",
    MODEL_ROUTER_ERROR: "The model router reported an error",
    MOE_ROUTE_DECISION: "A request was routed among expert models",
    MOE_ROUTER_CONFIG_WARNING: "The expert router flagged a configuration warning",
    MOE_ROUTER_ERROR: "The expert router reported an error",
    OVERWATCH_DRIFT: "Sentinel OverWatch detected behavioral drift",
    PROVIDER_ADAPTER_ERROR: "An AI provider connection reported an error",
    PROVIDER_DRY_RUN_CARD: "A provider action was simulated (dry run)",
    PUBLIC_DISCLOSURE_CLAMP: "A public response was trimmed to prevent oversharing",
    PUBLIC_INTENT_ANSWER: "A public-facing answer was produced",
    REQUEST_BLOCKED: "A request was blocked",
    ROUTER_APPROVAL_ANOMALY: "The router flagged an approval anomaly",
    ROUTER_DISPATCH_ERROR: "The router failed to dispatch an action",
    ROUTER_DRY_RUN: "A routed action was simulated (dry run)",
    ROUTER_LIVE_DISPATCH: "The router dispatched a live action",
    ROUTER_MODE_CONFIG_WARNING: "The router flagged a configuration warning",
    SCOPE_ESCALATION_REJECTED: "An attempt to gain extra permissions was rejected",
    SENTINEL_BLOCK: "A request was blocked by the security layer",
    SENTINEL_INSPECT_ERROR: "The security layer could not inspect a request",
    SENTINEL_RESTRICT: "A request was restricted by the security layer",
    SESSION_END: "A session ended",
    SESSION_INTERRUPTED: "A session was interrupted",
    SKILL_ACTIVATED: "A skill was activated",
    SKILL_SELECT_ERROR: "A skill could not be selected",
    SPAWN_AUTH_REJECTED: "An unauthorized attempt to start an agent was rejected",
    SPAWN_BLOCKED_DEPT_KILLED: "An agent was blocked because its department is shut down",
    SYSTEM_START: "The system started",
    TACIT_PREPASS_CARD: "A request passed a pre-check",
    TOPOLOGY_AUTH_FAILED: "An unauthorized topology request was refused",
    TURN_COMPLETE: "A conversation turn completed"
  };

  // Fallback humanizer: "SOME_NEW_EVENT" → "System event: some new event".
  function humanizeEvent(t) {
    return "System event: " + String(t == null ? "event" : t).toLowerCase().replace(/_/g, " ");
  }
  function auditSentence(t) { return AUDIT_LABELS[t] || humanizeEvent(t); }

  // Severity for the colored chip. crit = blocked/rejected/kill-switch;
  // warn = errors/warnings/restrictions/drift/approvals; info = everything else.
  function auditSeverity(t) {
    var u = String(t || "").toUpperCase();
    if (u === "KILL_SWITCH_ACTIVATED" || /BLOCK|REJECT|REFUS|ESCALATION|FAIL_CLOSED|AUTH_FAILED/.test(u))
      return { cls: "crit", word: "Blocked" };
    if (/ERROR|WARN|RESTRICT|DRIFT|TIMEOUT|INTERRUPT|CLAMP|APPROVAL|ANOMALY|NO_DOCKER/.test(u))
      return { cls: "warn", word: "Notice" };
    return { cls: "ok", word: "Info" };
  }

  // Short, safe timestamp. Falls back to the raw string if unparseable.
  function fmtAuditTs(ts) {
    try {
      var d = new Date(ts);
      if (isNaN(d.getTime())) return String(ts == null ? "" : ts);
      return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch (e) { return String(ts == null ? "" : ts); }
  }

  // Three-state Sentinel indicator derived from the LIVE /api/sentinel-health call.
  // ok:true → Online; a degraded signal inside status → Degraded; otherwise Offline.
  function sentinelStatus() {
    var s = state.sentinel;
    if (!s || !s.ok) return { label: "Offline", cls: "crit" };
    var st = s.status || {};
    var deg = st.degraded === true ||
      /degrad|warn|restrict|partial|unhealth/i.test(String(st.status || st.state || st.health || ""));
    return deg ? { label: "Degraded", cls: "warn" } : { label: "Online", cls: "ok" };
  }

  function renderGovernance() {
    var el = document.getElementById("tab-governance");
    if (!el) return;
    var sent = sentinelStatus();
    var vc = violationCount();
    var ks = killSwitchActive();

    // Audit history panel body — honest in every state, never blank.
    var auditBody;
    if (!adminToken()) {
      auditBody =
        '<div class="empty"><h3>Admin authentication required</h3>' +
          '<div class="tiny">Audit history is privileged. Add an operator admin token in ' +
          'Settings to view the live, plain-language governance log.</div>' +
          provBadge("offline") +
          '<div style="margin-top:14px"><button class="btn primary" data-go="settings">Open Settings →</button></div>' +
        "</div>";
    } else if (!state.auditLive) {
      auditBody =
        '<div class="empty"><h3>Audit history unavailable</h3>' +
          '<div class="tiny">A token is set, but the governance log could not be read. ' +
          'The token may be invalid or expired, or the backend may be unreachable. ' +
          'Check the token in Settings, then Refresh.</div>' + provBadge("offline") + "</div>";
    } else if (!state.audit.length) {
      auditBody =
        '<div class="empty"><h3>No governance events yet</h3>' +
          '<div class="tiny">The audit log is connected and empty — nothing has been recorded so far.</div>' +
          provBadge("live") + "</div>";
    } else {
      auditBody = state.audit.slice().reverse().map(function (e) {
        var sev = auditSeverity(e.event_type);
        var raw = e.event_type == null ? "" : String(e.event_type);
        var detail = "";
        try { detail = e.data ? JSON.stringify(e.data) : ""; } catch (x) { detail = ""; }
        var tip = raw + (detail ? " · " + detail : "");
        return '<div class="brief-line" title="' + esc(tip) + '">' +
          '<span class="lbl">' +
            '<span class="chip ' + sev.cls + '"><span class="dot"></span>' + sev.word + "</span> " +
            esc(auditSentence(e.event_type)) +
          "</span>" +
          '<span class="val">' +
            '<span class="tiny" style="font-family:var(--font-m);font-weight:600">' + esc(raw) + "</span>" +
            '<span class="tiny">' + esc(fmtAuditTs(e.ts)) + "</span>" +
          "</span>" +
        "</div>";
      }).join("");
    }

    el.innerHTML =
      // Sentinel health — prominent, LIVE, three-state indicator.
      '<div class="card">' +
        '<div class="row"><h3>Sentinel OverWatch</h3>' + provBadge("live") + "</div>" +
        '<div class="section">' +
          '<div class="brief-line"><span class="lbl">Security layer status</span>' +
            '<span class="val"><span class="chip ' + sent.cls + '"><span class="dot"></span>' +
              sent.label + "</span></span></div>" +
          '<div class="brief-line"><span class="lbl">Kill switch</span>' +
            '<span class="val">' + (ks
              ? '<span class="chip crit"><span class="dot"></span>Active</span>'
              : '<span class="chip ok"><span class="dot"></span>Armed</span>') + "</span></div>" +
          '<div class="brief-line"><span class="lbl">Governance violations (recent)</span>' +
            '<span class="val">' + (vc == null ? "—" : vc) + " " +
            provBadge(state.auditLive ? "live" : "offline") + "</span></div>" +
        "</div>" +
      "</div>" +

      // Audit history — plain-language, admin-gated, honest empty states.
      '<div class="card" style="margin-top:16px">' +
        '<div class="row"><h3>Audit History</h3>' +
          provBadge(state.auditLive ? "live" : "offline") + "</div>" +
        '<div class="section">' +
          '<div class="tiny" style="margin-bottom:8px">Recent governance events in plain language. ' +
            "Hover any row to see the raw event name and record.</div>" +
          auditBody +
        "</div>" +
      "</div>";

    el.querySelectorAll("[data-go]").forEach(function (b) {
      b.onclick = function () { activateTab(b.getAttribute("data-go")); };
    });
  }

  // ── tab router ───────────────────────────────────────────────────────
  var activeTab = "home";
  function renderActive() {
    if (activeTab === "home") renderHome();
    else if (activeTab === "workspace") renderWorkspace();
    else if (activeTab === "operations") emptyTab("operations", "Operations", "Departments & jobs — arriving in Phase 2.");
    else if (activeTab === "governance") renderGovernance();
    else if (activeTab === "observability") emptyTab("observability", "Observability", "Runtime, provider status & raw metrics — arriving in Phase 2.");
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
          '<div class="tiny" style="margin-top:12px">Operator admin token (sent only on privileged calls; held in memory for this session only — never saved, cleared on page reload)</div>' +
          '<input id="setTok" type="password" class="btn" style="width:100%;margin-top:6px" placeholder="paste admin token to enable admin-gated panels"/>' +
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
      // Operator name is a cosmetic local preference; the admin token is NOT persisted.
      try { localStorage.setItem("abigail.operator", document.getElementById("setName").value.trim() || "Operator"); } catch (e) {}
      var t = document.getElementById("setTok").value.trim();
      if (t) setAdminToken(t);   // set only on non-empty so an empty Save never silently wipes
      syncTokState();
      refresh();                 // re-pull gated panels with the new header
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
