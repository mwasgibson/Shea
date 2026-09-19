const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const PREFS_KEY = "shea.gui.prefs";

const state = {
  events: [],
  agentAvatar: "",
  userAvatar: "",
  listening: false,
  recognition: null,
};

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
  } catch {
    return {};
  }
}

function applyPrefs(p) {
  const theme = p.theme || "crt-green";
  document.documentElement.setAttribute("data-theme", theme);
  $("#set-theme") && ($("#set-theme").value = theme);

  const name = p.name || "SHEA";
  if ($("#brand-name")) $("#brand-name").textContent = name;
  if ($("#set-name")) $("#set-name").value = name;

  const mark = p.mark || "S";
  if ($("#brand-mark")) $("#brand-mark").textContent = mark;
  if ($("#set-mark")) $("#set-mark").value = mark;

  state.agentAvatar = p.agentAvatar || "";
  state.userAvatar = p.userAvatar || "";
  if ($("#set-agent-avatar")) $("#set-agent-avatar").value = state.agentAvatar;
  if ($("#set-user-avatar")) $("#set-user-avatar").value = state.userAvatar;

  if ($("#chat-session") && p.session) $("#chat-session").value = p.session;
  if ($("#chat-profile") && p.profile) $("#chat-profile").value = p.profile;
  if ($("#model-select") && p.model) $("#model-select").value = p.model;

  document.body.classList.toggle("no-scanlines", p.scanlines === false);
  if ($("#set-scanlines")) $("#set-scanlines").checked = p.scanlines !== false;

  document.body.classList.toggle("nav-anim", p.navAnim !== false);
  if ($("#set-nav-anim")) $("#set-nav-anim").checked = p.navAnim !== false;
}

function savePrefs() {
  const p = {
    theme: $("#set-theme")?.value || "crt-green",
    name: $("#set-name")?.value || "SHEA",
    mark: $("#set-mark")?.value || "S",
    agentAvatar: $("#set-agent-avatar")?.value || "",
    userAvatar: $("#set-user-avatar")?.value || "",
    session: $("#chat-session")?.value || "web-console",
    profile: $("#chat-profile")?.value || "default",
    model: $("#model-select")?.value || "",
    scanlines: $("#set-scanlines")?.checked !== false,
    navAnim: $("#set-nav-anim")?.checked !== false,
  };
  localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  applyPrefs(p);
}

applyPrefs(loadPrefs());
$("#set-save")?.addEventListener("click", savePrefs);

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function shortId(id) {
  if (!id) return "—";
  return id.length > 14 ? id.slice(0, 10) + "…" : id;
}
function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return String(iso);
  }
}

/* nav */
$$(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".nav-item").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const v = btn.dataset.view;
    $$(".view").forEach((el) => el.classList.remove("active"));
    $(`#view-${v}`)?.classList.add("active");
    ({
      tasks: loadTasks,
      pending: loadPending,
      memory: loadMemories,
      vault: loadVault,
      profiles: loadProfiles,
      tools: loadTools,
      audit: loadAudit,
      system: refreshSystem,
    })[v]?.();
  });
});

/* avatars */
function avatarHtml(kind) {
  const url = kind === "user" ? state.userAvatar : state.agentAvatar;
  if (url)
    return `<div class="avatar"><img src="${escapeHtml(url)}" alt="" /></div>`;
  const glyph = kind === "user" ? "U" : $("#brand-mark")?.textContent || "S";
  return `<div class="avatar">${escapeHtml(glyph)}</div>`;
}

function appendRow(kind, htmlBody) {
  const log = $("#chat-log");
  const row = document.createElement("div");
  row.className = `row ${kind}`;
  row.innerHTML = `${avatarHtml(kind)}<div class="bubble">${htmlBody}</div>`;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return row;
}

function appendText(kind, text) {
  return appendRow(kind, escapeHtml(text));
}

function showTyping() {
  return appendRow(
    "agent",
    `<div class="typing" aria-label="Loading"><span></span><span></span><span></span></div>`,
  );
}

function replaceTyping(row, htmlBody) {
  const bubble = row.querySelector(".bubble");
  if (bubble) bubble.innerHTML = htmlBody;
}

/* chat */
async function sendChat() {
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  appendText("user", message);
  const typing = showTyping();

  const model = $("#model-select")?.value || "";
  try {
    const res = await fetch("/api/interaction/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: $("#chat-session")?.value || "web-console",
        profile_id: $("#chat-profile")?.value || "default",
        context_overrides: model ? { model_provider: model } : {},
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    if (data.needs_confirmation) {
      const taskId = data.task_id || data.confirmation?.task_id || "";
      replaceTyping(
        typing,
        `${escapeHtml(data.text || "Confirmation required")}<div class="confirm-card">
          <h3>Confirm execution</h3>
          <div>${escapeHtml(shortId(taskId))}</div>
          <div class="confirm-actions">
            <button class="btn primary" data-confirm="${escapeHtml(taskId)}">Confirm</button>
            <button class="btn danger" data-deny="${escapeHtml(taskId)}">Deny</button>
          </div>
        </div>`,
      );
      bindConfirmButtons();
      loadPending();
    } else {
      if (data.text && data.text !== "Accepted") {
        let parsed = typeof marked !== "undefined" ? `<div style="white-space: normal;">${marked.parse(data.text)}</div>` : escapeHtml(data.text);
        replaceTyping(typing, parsed);
      } else {
        // Wait for SSE system.reply.
      }
    }
  } catch (err) {
    replaceTyping(typing, escapeHtml(`Error: ${err.message}`));
  }
}

function bindConfirmButtons() {
  $$("[data-confirm]").forEach((btn) => {
    btn.onclick = async () => {
      const task_id = btn.dataset.confirm;
      const typing = showTyping();
      const res = await fetch("/api/interaction/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id, actor: "web-user", acknowledge: true }),
      });
      const data = await res.json().catch(() => ({}));
      replaceTyping(
        typing,
        escapeHtml(data.text || (res.ok ? "Confirmed." : "Failed.")),
      );
      loadPending();
    };
  });
  $$("[data-deny]").forEach((btn) => {
    btn.onclick = async () => {
      const task_id = btn.dataset.deny;
      const res = await fetch("/api/interaction/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id,
          actor: "web-user",
          acknowledge: false,
        }),
      });
      const data = await res.json().catch(() => ({}));
      appendText("agent", data.text || (res.ok ? "Denied." : "Failed."));
      loadPending();
    };
  });
}

$("#chat-send")?.addEventListener("click", sendChat);
$("#chat-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

/* mic — Web Speech API when available */
function setupMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = $("#mic-btn");
  if (!SR || !btn) {
    if (btn) {
      btn.title = "Voice not supported in this browser";
      btn.disabled = true;
      btn.style.opacity = "0.4";
    }
    return;
  }
  const rec = new SR();
  rec.continuous = false;
  rec.interimResults = false;
  rec.lang = navigator.language || "en-US";
  rec.onresult = (ev) => {
    const text = ev.results[0][0].transcript;
    const input = $("#chat-input");
    if (input) input.value = (input.value ? input.value + " " : "") + text;
  };
  rec.onend = () => {
    state.listening = false;
    btn.classList.remove("live");
  };
  rec.onerror = () => {
    state.listening = false;
    btn.classList.remove("live");
  };
  state.recognition = rec;
  btn.addEventListener("click", () => {
    if (state.listening) {
      rec.stop();
      return;
    }
    state.listening = true;
    btn.classList.add("live");
    rec.start();
  });
}
setupMic();

/* SSE silent for chat; still feed Events view */
function connectSSE() {
  const es = new EventSource("/api/interaction/stream");
  es.onopen = () => {
    $("#sse-dot")?.classList.add("ok");
    if ($("#sse-label")) $("#sse-label").textContent = "live";
  };
  es.onerror = () => {
    $("#sse-dot")?.classList.remove("ok");
    if ($("#sse-label")) $("#sse-label").textContent = "…";
  };
  es.onmessage = (ev) => {
    let payload = {};
    try {
      payload = JSON.parse(ev.data);
    } catch {
      payload = { message: ev.data };
    }
    const type = payload.type || payload.event || "event";
    const message =
      payload.message ||
      payload.detail ||
      JSON.stringify(payload).slice(0, 160);
    state.events.unshift({ ts: new Date().toISOString(), type, message });
    if (state.events.length > 200) state.events.pop();
    renderEvents();
  };

  ["execution.started", "execution.completed", "execution.failed"].forEach((name) => {
    es.addEventListener(name, (ev) => {
      let payload = {};
      try {
        payload = JSON.parse(ev.data);
      } catch {
        return;
      }
      
      if (name === "execution.completed" && payload.tool === "system.reply") {
        const typingRow = document.querySelector(".typing")?.closest(".row");
        if (typingRow) typingRow.remove();
        
        let out = payload.data || "";
        let parsed = typeof marked !== "undefined" ? `<div style="white-space: normal;">${marked.parse(out)}</div>` : escapeHtml(out);
        appendRow("agent", parsed);
      }
    });
  });
}
function renderEvents() {
  const feed = $("#events-feed");
  if (!feed) return;
  if (!state.events.length) {
    feed.innerHTML = `<div class="empty">Waiting…</div>`;
    return;
  }
  feed.innerHTML = state.events
    .map(
      (e) => `<div class="event-line">
        <span class="event-ts">${escapeHtml(fmtTime(e.ts))}</span>
        <span class="event-type">${escapeHtml(e.type)}</span>
        <span>${escapeHtml(e.message)}</span>
      </div>`,
    )
    .join("");
}

/* rest of panels — same API wiring as before */
async function loadTasks() {
  const body = $("#tasks-body");
  if (!body) return;
  try {
    const res = await fetch("/api/tasks/?limit=100");
    const rows = await res.json();
    body.innerHTML =
      (rows || [])
        .map(
          (t) => `<tr>
          <td class="mono">${escapeHtml(shortId(t.id))}</td>
          <td><span class="pill">${escapeHtml(t.state)}</span></td>
          <td>${escapeHtml(t.session_id || "—")}</td>
          <td>${escapeHtml(fmtTime(t.updated_at))}</td>
        </tr>`,
        )
        .join("") || `<tr><td colspan="4">None</td></tr>`;
  } catch (e) {
    body.innerHTML = `<tr><td colspan="4">${escapeHtml(e.message)}</td></tr>`;
  }
}
$("#tasks-refresh")?.addEventListener("click", loadTasks);

async function loadPending() {
  const list = $("#pending-list");
  const session = $("#chat-session")?.value || "web-console";
  try {
    const res = await fetch(
      `/api/interaction/pending?session_id=${encodeURIComponent(session)}`,
    );
    const rows = await res.json();
    const badge = $("#pending-badge");
    if (badge) {
      badge.textContent = String(rows.length);
      badge.classList.toggle("hidden", !rows.length);
    }
    if (!list) return;
    if (!rows.length) {
      list.innerHTML = `<div class="empty">No pending confirmations.</div>`;
      return;
    }
    list.innerHTML = rows
      .map(
        (p) => `<div class="item-card">
          <div class="item-title">${escapeHtml(p.risk || "risk")} · ${escapeHtml(shortId(p.task_id))}</div>
          <div class="item-body">${escapeHtml(p.explanation || "")}</div>
          <div class="item-meta">
            <button class="btn primary" data-confirm="${escapeHtml(p.task_id)}">Confirm</button>
            <button class="btn danger" data-deny="${escapeHtml(p.task_id)}">Deny</button>
          </div>
        </div>`,
      )
      .join("");
    bindConfirmButtons();
  } catch (e) {
    if (list)
      list.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
  }
}
$("#pending-refresh")?.addEventListener("click", loadPending);

async function loadMemories() {
  const list = $("#memory-list");
  const profile = $("#memory-profile")?.value || "default";
  if (!list) return;
  try {
    const res = await fetch(
      `/api/memory/?profile_id=${encodeURIComponent(profile)}`,
    );
    const rows = await res.json();
    list.innerHTML =
      (rows || [])
        .map(
          (m) => `<div class="item-card">
            <div class="item-title">${escapeHtml(m.type)}</div>
            <div class="item-body">${escapeHtml(m.content)}</div>
            <div class="item-meta"><button class="btn danger" data-del-mem="${escapeHtml(m.id)}">Delete</button></div>
          </div>`,
        )
        .join("") || `<div class="empty">Empty</div>`;
    $$("[data-del-mem]").forEach((b) => {
      b.onclick = async () => {
        await fetch(`/api/memory/${b.dataset.delMem}`, { method: "DELETE" });
        loadMemories();
      };
    });
  } catch (e) {
    list.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
  }
}
$("#memory-refresh")?.addEventListener("click", loadMemories);

async function loadVault() {
  const list = $("#vault-list");
  if (!list) return;
  try {
    const res = await fetch("/api/credentials/");
    const rows = await res.json();
    list.innerHTML =
      (rows || [])
        .map(
          (c) => `<div class="item-card">
            <div class="item-title">${escapeHtml(c.name)}</div>
            <div class="item-body">${escapeHtml(c.description || "—")}</div>
            <div class="item-meta"><button class="btn danger" data-rev="${escapeHtml(c.id)}">Revoke</button></div>
          </div>`,
        )
        .join("") || `<div class="empty">Empty</div>`;
    $$("[data-rev]").forEach((b) => {
      b.onclick = async () => {
        await fetch(`/api/credentials/${b.dataset.rev}`, { method: "DELETE" });
        loadVault();
      };
    });
  } catch (e) {
    list.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
  }
}
$("#vault-refresh")?.addEventListener("click", loadVault);
$("#vault-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await fetch("/api/credentials/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: fd.get("name"),
      secret: fd.get("secret"),
      profile_id: fd.get("profile_id") || "default",
      allowed_tools: String(fd.get("allowed_tools") || "*")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    }),
  });
  e.target.reset();
  loadVault();
});

async function loadProfiles() {
  const list = $("#profiles-list");
  if (!list) return;
  try {
    const res = await fetch("/api/profiles/");
    const rows = await res.json();
    list.innerHTML =
      (rows || [])
        .map(
          (p) => `<div class="item-card">
            <div class="item-title">${escapeHtml(p.name)} <span class="mono">${escapeHtml(p.id)}</span></div>
          </div>`,
        )
        .join("") || `<div class="empty">Empty</div>`;
  } catch (e) {
    list.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
  }
}
$("#profiles-refresh")?.addEventListener("click", loadProfiles);
$("#profile-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const id = String(fd.get("id"));
  let rules = {};
  try {
    rules = JSON.parse(String(fd.get("context_rules") || "{}"));
  } catch {
    return;
  }
  await fetch(`/api/profiles/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id,
      name: fd.get("name"),
      preferences: {},
      context_rules: rules,
    }),
  });
  loadProfiles();
});

async function loadTools() {
  const body = $("#tools-body");
  const empty = $("#tools-empty");
  try {
    const res = await fetch("/api/tools/");
    if (res.status === 404) {
      empty?.classList.remove("hidden");
      return;
    }
    const rows = await res.json();
    empty?.classList.add("hidden");
    if (body)
      body.innerHTML = (rows || [])
        .map(
          (t) => `<tr>
            <td class="mono">${escapeHtml(t.name)}</td>
            <td>${(t.capabilities || []).map((c) => `<span class="pill">${escapeHtml(c)}</span>`).join(" ")}</td>
            <td>${escapeHtml(t.description || "")}</td>
          </tr>`,
        )
        .join("");
  } catch {
    empty?.classList.remove("hidden");
  }
}
$("#tools-refresh")?.addEventListener("click", loadTools);

async function loadAudit() {
  const body = $("#audit-body");
  if (!body) return;
  try {
    const res = await fetch("/api/observability/audit?limit=100");
    const data = await res.json();
    const events = data.events || [];
    body.innerHTML =
      events
        .map(
          (e) => `<tr>
          <td class="mono">${escapeHtml(String(e.sequence_number ?? "—"))}</td>
          <td>${escapeHtml(fmtTime(e.timestamp || e.created_at))}</td>
          <td>${escapeHtml(e.event_type || e.type || "—")}</td>
          <td class="mono">${escapeHtml(shortId(e.task_id))}</td>
        </tr>`,
        )
        .join("") || `<tr><td colspan="4">None</td></tr>`;
  } catch (e) {
    body.innerHTML = `<tr><td colspan="4">${escapeHtml(e.message)}</td></tr>`;
  }
}
$("#audit-refresh")?.addEventListener("click", loadAudit);

let sysChart = null;
const chartData = { labels: [], cpu: [], ram: [], disk: [] };

function initChart() {
  const ctx = $("#sys-chart");
  if (!ctx || sysChart || typeof Chart === 'undefined') return;
  sysChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: chartData.labels,
      datasets: [
        { label: 'CPU %', data: chartData.cpu, borderColor: '#4ade80', tension: 0.3 },
        { label: 'RAM %', data: chartData.ram, borderColor: '#3b82f6', tension: 0.3 },
        { label: 'Disk %', data: chartData.disk, borderColor: '#a855f7', tension: 0.3 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: { beginAtZero: true, max: 100 }
      },
      plugins: {
        legend: { labels: { color: getComputedStyle(document.body).getPropertyValue('--text').trim() || '#ffffff' } }
      }
    }
  });
}

function updateChart(m) {
  initChart();
  if (!sysChart) return;
  const now = new Date().toLocaleTimeString();
  chartData.labels.push(now);
  chartData.cpu.push(m.cpu_percent ?? 0);
  chartData.ram.push(m.ram_percent ?? 0);
  chartData.disk.push(m.disk_percent ?? 0);
  
  if (chartData.labels.length > 20) {
    chartData.labels.shift();
    chartData.cpu.shift();
    chartData.ram.shift();
    chartData.disk.shift();
  }
  sysChart.update();
}

async function refreshSystem() {
  try {
    const res = await fetch("/api/observability/metrics");
    const m = await res.json();
    
    if ($("#m-cpu")) {
      $("#m-cpu").textContent = `${(m.cpu_percent ?? 0).toFixed(1)}%`;
      $("#m-load").textContent = `load: ${(m.load_1m ?? 0).toFixed(2)}`;
      
      $("#m-ram").textContent = `${(m.ram_percent ?? 0).toFixed(1)}%`;
      $("#m-ram-detail").textContent = `${Math.round(m.ram_used_mb ?? 0)} / ${Math.round(m.ram_total_mb ?? 0)} MB`;
      
      $("#m-disk").textContent = `${(m.disk_percent ?? 0).toFixed(1)}%`;
      $("#m-disk-detail").textContent = `${(m.disk_used_gb ?? 0).toFixed(1)} / ${(m.disk_total_gb ?? 0).toFixed(1)} GB`;
      
      $("#m-prov").textContent = `${m.provider_health ?? "—"}`;
      
      $("#m-rpm").textContent = `${(m.requests_per_minute ?? 0).toFixed(1)}`;
      $("#m-budget").textContent = `${((m.rate_limit_remaining ?? 0) * 100).toFixed(1)}%`;
      $("#m-rl-hits").textContent = `hits: ${m.rate_limit_hits ?? 0}`;
      
      $("#m-active").textContent = `${m.active_tasks ?? 0}`;
      $("#m-sec").textContent = `${m.security_blocks ?? 0}`;
    }
    
    updateChart(m);
  } catch (err) {
    console.error("refreshSystem error:", err);
  }
}
$("#sys-refresh")?.addEventListener("click", refreshSystem);

connectSSE();
refreshSystem();
setInterval(refreshSystem, 10000);
loadPending();
