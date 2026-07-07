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

  // ── admin token (set in Settings; stored client-side only) ───────────
  function adminToken() { try { return localStorage.getItem("abigail.adminToken") || ""; } catch (e) { return ""; } }
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
    if (a.ok && Array.isArray(a.body.entries)) { state.audit = a.body.entries; state.auditLive = true; }
    else { state.audit = []; state.auditLive = false; }
    state.lastRefresh = new Date();
    var rs = document.getElementById("refreshStatus");
    if (rs) rs.textContent = "Refreshed " + state.lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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

  // ── tab router ───────────────────────────────────────────────────────
  var activeTab = "home";
  function renderActive() {
    if (activeTab === "home") renderHome();
    else if (activeTab === "workspace") renderWorkspace();
    else if (activeTab === "operations") emptyTab("operations", "Operations", "Departments & jobs — arriving in Phase 2.");
    else if (activeTab === "governance") emptyTab("governance", "Governance", "Emergency / Controls / Audit — arriving in Phase 3.");
    else if (activeTab === "observability") emptyTab("observability", "Observability", "Runtime, provider status & raw metrics — arriving in Phase 2.");
    else if (activeTab === "settings") renderSettings();
  }
  function activateTab(id) {
    activeTab = id;
    document.querySelectorAll(".nav button").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-tab") === id); });
    document.querySelectorAll(".tab").forEach(function (t) { t.classList.toggle("active", t.id === "tab-" + id); });
    renderActive();
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
          '<div class="tiny" style="margin-top:12px">Operator admin token (never sent except on privileged calls; stored in this browser only)</div>' +
          '<input id="setTok" type="password" class="btn" style="width:100%;margin-top:6px" placeholder="paste admin token to enable Advanced actions"/>' +
          '<div style="margin-top:12px"><button class="btn primary" id="saveSettings">Save</button></div>' +
        "</div></div>" +
      '<div class="card" style="margin-top:16px"><div class="row"><h3>Modes</h3></div>' +
        '<div class="section tiny">Advanced Mode reveals privileged controls in later phases. It grants nothing on its own — every privileged action still requires the admin token and is enforced by the backend.</div>' +
      "</div>";
    document.getElementById("saveSettings").onclick = function () {
      try {
        localStorage.setItem("abigail.operator", document.getElementById("setName").value.trim() || "Operator");
        var t = document.getElementById("setTok").value.trim();
        if (t) localStorage.setItem("abigail.adminToken", t);
      } catch (e) {}
      refresh();
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
