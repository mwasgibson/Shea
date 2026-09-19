/* SHEA Control Console — InteractionService only; no secrets in UI */

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const state = {
  stages: {
    intent: false,
    plan: false,
    policy: false,
    authorize: false,
    execute: false,
    verify: false,
  },
  events: [],
};

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
    const loaders = {
      tasks: loadTasks,
      pending: loadPending,
      memory: loadMemories,
      vault: loadVault,
      profiles: loadProfiles,
      tools: loadTools,
      audit: loadAudit,
      system: refreshSystem,
    };
    loaders[v]?.();
  });
});

/* pipeline */
function renderPipeline() {
  $$("#pipeline .stage").forEach((el) => {
    el.classList.toggle("on", !!state.stages[el.dataset.stage]);
    el.classList.toggle("ok", !!state.stages[el.dataset.stage]);
  });
}
function resetPipeline() {
  Object.keys(state.stages).forEach((k) => (state.stages[k] = false));
  renderPipeline();
}
function inferStages(type, message) {
  const t = `${type} ${message}`.toLowerCase();
  if (/intent|understand/.test(t)) state.stages.intent = true;
  if (/plan/.test(t)) state.stages.plan = true;
  if (/policy|decision|risk/.test(t)) state.stages.policy = true;
  if (/authoriz|confirm/.test(t)) state.stages.authorize = true;
  if (/execut|tool|adapter/.test(t)) state.stages.execute = true;
  if (/verif|complete/.test(t)) state.stages.verify = true;
  renderPipeline();
}

/* chat */
function appendMsg(role, text, extraHtml = "") {
  const log = $("#chat-log");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  let bodyContent = escapeHtml(text);
  if (role === "agent" && typeof marked !== "undefined") {
    bodyContent = marked.parse(text);
  }
  div.innerHTML = `<div class="role">${role}</div><div class="body markdown-body">${bodyContent}</div>${extraHtml}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function sendChat() {
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  appendMsg("user", message);
  resetPipeline();
  state.stages.intent = true;
  renderPipeline();

  try {
    const res = await fetch("/api/interaction/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: $("#chat-session")?.value || "web-console",
        profile_id: $("#chat-profile")?.value || "default",
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    if (data.needs_confirmation) {
      state.stages.policy = true;
      state.stages.authorize = true;
      renderPipeline();
      const taskId = data.task_id || data.confirmation?.task_id || "";
      const extra = `
        <div class="confirm-card" style="margin-top:10px">
          <h3>Confirmation required</h3>
          <div class="body">Task ${escapeHtml(shortId(taskId))} needs explicit acknowledgement before execution.</div>
          <div class="confirm-actions">
            <button class="btn primary" data-confirm="${escapeHtml(taskId)}">Confirm</button>
            <button class="btn danger" data-deny="${escapeHtml(taskId)}">Deny</button>
          </div>
        </div>`;
      appendMsg("system", data.text || "Confirmation required", extra);
      extra && bindConfirmButtons();
      loadPending();
    } else {
      appendMsg("system", data.text || "Accepted");
      if (data.task_id)
        appendMsg("system", `task ${data.task_id} · ${data.state || ""}`);
    }
  } catch (err) {
    appendMsg("system", `Error: ${err.message}`);
  }
}

function bindConfirmButtons() {
  $$("[data-confirm]").forEach((btn) => {
    btn.onclick = async () => {
      const task_id = btn.dataset.confirm;
      const res = await fetch("/api/interaction/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id, actor: "web-user", acknowledge: true }),
      });
      const data = await res.json().catch(() => ({}));
      appendMsg(
        "system",
        data.text || (res.ok ? "Confirmed" : "Confirm failed"),
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
      appendMsg("system", data.text || (res.ok ? "Denied" : "Deny failed"));
      loadPending();
    };
  });
}

$("#chat-send")?.addEventListener("click", sendChat);
$("#chat-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

/* SSE */
function connectSSE() {
  const es = new EventSource("/api/interaction/stream");
  es.onopen = () => {
    $("#sse-dot")?.classList.add("ok");
    if ($("#sse-label")) $("#sse-label").textContent = "stream live";
  };
  es.onerror = () => {
    $("#sse-dot")?.classList.remove("ok");
    if ($("#sse-label")) $("#sse-label").textContent = "stream reconnecting";
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
      JSON.stringify(payload).slice(0, 200);
    pushEvent(type, message);
    inferStages(type, message);
  };

  ["execution.started", "execution.completed", "execution.failed"].forEach(
    (name) => {
      es.addEventListener(name, (ev) => {
        let payload = {};
        try {
          payload = JSON.parse(ev.data);
        } catch {
          return;
        }
        pushEvent(name, JSON.stringify(payload).slice(0, 200));
        inferStages(name, "");

        if (name === "execution.completed" && payload.tool === "system.reply") {
          appendMsg("agent", payload.data);
        }
      });
    },
  );
}
function pushEvent(type, message) {
  state.events.unshift({ ts: new Date().toISOString(), type, message });
  if (state.events.length > 200) state.events.pop();
  renderEvents();
}
function renderEvents() {
  const feed = $("#events-feed");
  if (!feed) return;
  if (!state.events.length) {
    feed.innerHTML = `<div class="empty">Waiting for SSE…</div>`;
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

/* tasks */
async function loadTasks() {
  const body = $("#tasks-body");
  if (!body) return;
  body.innerHTML = `<tr><td colspan="5">Loading…</td></tr>`;
  try {
    const res = await fetch("/api/tasks/?limit=100");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="5">No tasks</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map(
        (t) => `<tr>
          <td class="mono" title="${escapeHtml(t.id)}">${escapeHtml(shortId(t.id))}</td>
          <td><span class="pill">${escapeHtml(t.state)}</span></td>
          <td>${escapeHtml(t.session_id || "—")}</td>
          <td class="mono">${escapeHtml(shortId(t.plan_id))}</td>
          <td>${escapeHtml(fmtTime(t.updated_at))}</td>
        </tr>`,
      )
      .join("");
  } catch (err) {
    body.innerHTML = `<tr><td colspan="5">${escapeHtml(err.message)}</td></tr>`;
  }
}
$("#tasks-refresh")?.addEventListener("click", loadTasks);

/* pending */
async function loadPending() {
  const list = $("#pending-list");
  const session = $("#chat-session")?.value || "web-console";
  try {
    const res = await fetch(
      `/api/interaction/pending?session_id=${encodeURIComponent(session)}`,
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    const badge = $("#pending-badge");
    if (badge) {
      badge.textContent = String(rows.length);
      badge.classList.toggle("hidden", rows.length === 0);
    }
    if (!list) return;
    if (!rows.length) {
      list.innerHTML = `<div class="empty">No pending confirmations for this session.</div>`;
      return;
    }
    list.innerHTML = rows
      .map(
        (p) => `<div class="item-card">
          <div class="item-title">Task ${escapeHtml(shortId(p.task_id))} · risk ${escapeHtml(p.risk || "—")}</div>
          <div class="item-body">${escapeHtml(p.explanation || "")}</div>
          <div class="item-meta">
            <span class="mono">${escapeHtml(p.task_id)}</span>
            <span>${(p.capabilities || []).map(escapeHtml).join(", ")}</span>
            <button class="btn primary" data-confirm="${escapeHtml(p.task_id)}">Confirm</button>
            <button class="btn danger" data-deny="${escapeHtml(p.task_id)}">Deny</button>
          </div>
        </div>`,
      )
      .join("");
    bindConfirmButtons();
  } catch (err) {
    if (list)
      list.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  }
}
$("#pending-refresh")?.addEventListener("click", loadPending);

/* memory */
async function loadMemories() {
  const list = $("#memory-list");
  const profile = $("#memory-profile")?.value || "default";
  if (!list) return;
  try {
    const res = await fetch(
      `/api/memory/?profile_id=${encodeURIComponent(profile)}`,
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    if (!rows.length) {
      list.innerHTML = `<div class="empty">No active memories.</div>`;
      return;
    }
    list.innerHTML = rows
      .map(
        (m) => `<div class="item-card">
          <div class="item-title">${escapeHtml(m.type)} · ${escapeHtml(m.source)}</div>
          <div class="item-body">${escapeHtml(m.content)}</div>
          <div class="item-meta">
            <span>${escapeHtml(fmtTime(m.created_at))}</span>
            <button class="btn danger" data-del-mem="${escapeHtml(m.id)}">Delete</button>
          </div>
        </div>`,
      )
      .join("");
    $$("[data-del-mem]").forEach((b) => {
      b.onclick = async () => {
        await fetch(`/api/memory/${b.dataset.delMem}`, { method: "DELETE" });
        loadMemories();
      };
    });
  } catch (err) {
    list.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  }
}
$("#memory-refresh")?.addEventListener("click", loadMemories);

/* vault */
async function loadVault() {
  const list = $("#vault-list");
  if (!list) return;
  try {
    const res = await fetch("/api/credentials/");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    if (!rows.length) {
      list.innerHTML = `<div class="empty">No credential references.</div>`;
      return;
    }
    list.innerHTML = rows
      .map(
        (c) => `<div class="item-card">
          <div class="item-title">${escapeHtml(c.name)}</div>
          <div class="item-body">${escapeHtml(c.description || "—")}</div>
          <div class="item-meta">
            <span>profile ${escapeHtml(c.profile_id)}</span>
            <span>${(c.allowed_tools || []).map(escapeHtml).join(", ")}</span>
            <button class="btn danger" data-rev="${escapeHtml(c.id)}">Revoke</button>
          </div>
        </div>`,
      )
      .join("");
    $$("[data-rev]").forEach((b) => {
      b.onclick = async () => {
        await fetch(`/api/credentials/${b.dataset.rev}`, { method: "DELETE" });
        loadVault();
      };
    });
  } catch (err) {
    list.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  }
}
$("#vault-refresh")?.addEventListener("click", loadVault);
$("#vault-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const allowed = String(fd.get("allowed_tools") || "*")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const res = await fetch("/api/credentials/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: fd.get("name"),
      secret: fd.get("secret"),
      profile_id: fd.get("profile_id") || "default",
      description: fd.get("description") || "",
      allowed_tools: allowed,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || `HTTP ${res.status}`);
    return;
  }
  e.target.reset();
  loadVault();
});

/* profiles */
async function loadProfiles() {
  const list = $("#profiles-list");
  if (!list) return;
  try {
    const res = await fetch("/api/profiles/");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    if (!rows.length) {
      list.innerHTML = `<div class="empty">No profiles.</div>`;
      return;
    }
    list.innerHTML = rows
      .map(
        (p) => `<div class="item-card">
          <div class="item-title">${escapeHtml(p.name)} <span class="mono">${escapeHtml(p.id)}</span></div>
          <div class="item-body"><pre>${escapeHtml(JSON.stringify(p.context_rules || {}, null, 2))}</pre></div>
        </div>`,
      )
      .join("");
  } catch (err) {
    list.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
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
    alert("Invalid JSON");
    return;
  }
  const res = await fetch(`/api/profiles/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id,
      name: fd.get("name"),
      preferences: {},
      context_rules: rules,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || `HTTP ${res.status}`);
    return;
  }
  loadProfiles();
});

/* tools — graceful if route missing */
async function loadTools() {
  const body = $("#tools-body");
  const empty = $("#tools-empty");
  try {
    const res = await fetch("/api/tools/");
    if (res.status === 404) {
      empty?.classList.remove("hidden");
      if (body) body.innerHTML = "";
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    empty?.classList.add("hidden");
    const rows = await res.json();
    if (!body) return;
    body.innerHTML =
      (rows || [])
        .map(
          (t) => `<tr>
          <td class="mono">${escapeHtml(t.name)}</td>
          <td>${(t.capabilities || []).map((c) => `<span class="pill">${escapeHtml(c)}</span>`).join(" ")}</td>
          <td>${escapeHtml(t.description || "")}</td>
        </tr>`,
        )
        .join("") || `<tr><td colspan="3">No tools registered</td></tr>`;
  } catch (err) {
    empty?.classList.remove("hidden");
    if (body) body.innerHTML = "";
  }
}
$("#tools-refresh")?.addEventListener("click", loadTools);

/* audit */
async function loadAudit() {
  const body = $("#audit-body");
  if (!body) return;
  try {
    const res = await fetch("/api/observability/audit?limit=100");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
          <td>${escapeHtml(e.actor || "—")}</td>
        </tr>`,
        )
        .join("") || `<tr><td colspan="5">No events</td></tr>`;
  } catch (err) {
    body.innerHTML = `<tr><td colspan="5">${escapeHtml(err.message)}</td></tr>`;
  }
}
$("#audit-refresh")?.addEventListener("click", loadAudit);

/* system metrics */
async function refreshSystem() {
  try {
    const res = await fetch("/api/observability/metrics");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const m = await res.json();
    $("#m-cpu").textContent = `${m.cpu_percent ?? 0}%`;
    $("#m-load").textContent = `load ${m.load_1m ?? 0}`;
    $("#m-ram").textContent = `${m.ram_percent ?? 0}%`;
    $("#m-ram-detail").textContent =
      `${m.ram_used_mb ?? 0} / ${m.ram_total_mb ?? 0} MB`;
    $("#m-disk").textContent = `${m.disk_percent ?? 0}%`;
    $("#m-disk-detail").textContent =
      `${m.disk_used_gb ?? 0} / ${m.disk_total_gb ?? 0} GB`;
    $("#m-prov").textContent = `${m.provider_health ?? "—"}`;
    $("#m-rpm").textContent = `${m.requests_per_minute ?? 0}`;
    $("#m-budget").textContent =
      `${Math.round((m.rate_limit_remaining ?? 1) * 100)}%`;
    $("#m-rl-hits").textContent = `${m.rate_limit_hits ?? 0} limit hits`;
    $("#m-active").textContent = `${m.active_tasks ?? 0}`;
    $("#m-sec").textContent = `${m.security_blocks ?? 0}`;
    $("#m-intents").textContent = `${m.total_intents ?? 0}`;
    $("#m-tools").textContent = `${m.total_tools_executed ?? 0}`;
    $("#m-rate").textContent =
      `${((m.tool_success_rate ?? 0) * 100).toFixed(1)}%`;
    $("#m-avg").textContent = `${(m.avg_tool_duration_ms ?? 0).toFixed(0)} ms`;
  } catch {
    $("#m-cpu").textContent = "—";
  }
}
$("#sys-refresh")?.addEventListener("click", refreshSystem);

connectSSE();
refreshSystem();
setInterval(refreshSystem, 8000);
loadPending();
