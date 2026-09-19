(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  const state = {
    tasks: new Map(), // id -> { id, lastAction, result, updatedAt, note }
    events: [],
    memories: [],
    credentials: [],
  };

  // ── Navigation ────────────────────────────────────
  $$("#nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("#nav button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view;
      $$(".view").forEach((v) => v.classList.remove("active"));
      $(`#view-${view}`).classList.add("active");
      if (view === "memory") loadMemories();
      if (view === "audit" || view === "tasks") loadAudit();
      if (view === "dashboard") refreshDashboard();
      if (view === "vault") loadVault();
    });
  });

  // ── Chat helpers ──────────────────────────────────
  const history = $("#chat-history");
  function appendMsg(role, text, html) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    if (html) el.innerHTML = html;
    else el.textContent = text;
    history.appendChild(el);
    history.scrollTop = history.scrollHeight;
    return el;
  }

  appendMsg(
    "system",
    "Requests enter InteractionService only. The GUI never calls ToolExecutor or reads vault secrets.",
  );

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  const stages = $$(".stage");
  function resetPipeline() {
    stages.forEach((s) => s.classList.remove("ok", "fail", "run"));
  }
  function markStage(name, cls) {
    const el = stages.find((s) => s.dataset.stage === name);
    if (!el) return;
    el.classList.remove("ok", "fail", "run");
    if (cls) el.classList.add(cls);
  }
  function inferStages(type) {
    const t = String(type || "").toLowerCase();
    if (t.includes("intent") || t.includes("request"))
      markStage("intent", "ok");
    if (t.includes("plan"))
      markStage("plan", t.includes("fail") ? "fail" : "ok");
    if (t.includes("policy") || t.includes("decision"))
      markStage("policy", t.includes("den") ? "fail" : "ok");
    if (t.includes("auth")) markStage("authorize", "ok");
    if (t.includes("execut") || t.includes("tool"))
      markStage("execute", t.includes("fail") ? "fail" : "run");
    if (t.includes("verif"))
      markStage("verify", t.includes("fail") ? "fail" : "ok");
    if (t.includes("security") || t.includes("halt")) {
      markStage("policy", "fail");
      markStage("execute", "fail");
    }
    if (t.includes("completed") || t.includes("success")) {
      markStage("execute", "ok");
      markStage("verify", "ok");
    }
  }

  $("#hints").addEventListener("click", (e) => {
    const h = e.target.closest(".hint");
    if (!h) return;
    $("#chat-input").value = h.dataset.text || "";
    $("#chat-input").focus();
  });

  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $("#chat-input").value.trim();
    if (!text) return;
    appendMsg("user", text);
    $("#chat-input").value = "";
    resetPipeline();
    markStage("intent", "run");
    $("#send-btn").disabled = true;
    try {
      const res = await fetch("/api/interaction/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, profile_id: "default" }),
      });
      const data = await res.json();
      appendMsg("system", data.text || "Processing via InteractionService…");
    } catch (err) {
      console.error(err);
      appendMsg("system", "Failed to reach API.");
      markStage("intent", "fail");
    } finally {
      $("#send-btn").disabled = false;
    }
  });

  // ── Tasks from events/audit ───────────────────────
  function upsertTask(id, patch) {
    if (!id) return;
    const prev = state.tasks.get(id) || {
      id,
      lastAction: "—",
      result: "—",
      updatedAt: Date.now(),
      note: "",
    };
    state.tasks.set(id, { ...prev, ...patch, updatedAt: Date.now() });
    renderTasks();
    $("#count-tasks").textContent = String(state.tasks.size);
  }

  function renderTasks() {
    const list = $("#task-list");
    const rows = [...state.tasks.values()].sort(
      (a, b) => b.updatedAt - a.updatedAt,
    );
    if (!rows.length) {
      list.innerHTML = `<div class="empty">No tasks yet. Send a chat request to start the pipeline.</div>`;
      return;
    }
    list.innerHTML = rows
      .map((t) => {
        const badge = /success|completed|ok/i.test(t.result)
          ? "ok"
          : /fail|denied|halt|flag/i.test(t.result)
            ? "fail"
            : /run|process|start/i.test(t.result)
              ? "run"
              : "";
        return `<div class="row">
          <div>
            <div class="title">${escapeHtml(t.lastAction)}</div>
            <div class="detail">${escapeHtml(t.note || "")}</div>
            <div class="mono">${escapeHtml(t.id)}</div>
          </div>
          <span class="badge ${badge}">${escapeHtml(t.result)}</span>
        </div>`;
      })
      .join("");
  }

  // ── Events ────────────────────────────────────────
  function pushEvent(kind, payload, taskId) {
    const item = {
      at: new Date(),
      kind,
      payload:
        typeof payload === "string"
          ? payload
          : JSON.stringify(payload ?? {}, null, 0),
      taskId: taskId || null,
    };
    state.events.unshift(item);
    state.events = state.events.slice(0, 200);
    $("#count-events").textContent = String(state.events.length);
    renderEvents();
    if (taskId) {
      upsertTask(taskId, {
        lastAction: kind,
        result: kind,
        note: item.payload.slice(0, 160),
      });
    }
  }

  function renderEvents() {
    const feed = $("#event-feed");
    if (!state.events.length) {
      feed.innerHTML = `<div class="empty">Waiting for SSE events…</div>`;
      return;
    }
    feed.innerHTML = state.events
      .map(
        (e) => `<div class="event-line">
          <time>${e.at.toLocaleTimeString()}</time>
          <div>
            <div class="kind">${escapeHtml(e.kind)}</div>
            <div class="payload">${escapeHtml(e.payload)}</div>
          </div>
        </div>`,
      )
      .join("");
  }

  $("#btn-clear-events").addEventListener("click", () => {
    state.events = [];
    $("#count-events").textContent = "0";
    renderEvents();
  });

  // ── SSE ───────────────────────────────────────────
  function connectSSE() {
    const es = new EventSource("/api/interaction/stream");
    const pill = $("#status-pill");

    es.onopen = () => {
      pill.textContent = "Online";
      pill.className = "pill online";
    };
    es.onerror = () => {
      pill.textContent = "Offline";
      pill.className = "pill offline";
      es.close();
      setTimeout(connectSSE, 3000);
    };

    const handle = (type, raw) => {
      let payload = raw;
      try {
        payload = typeof raw === "string" ? JSON.parse(raw) : raw;
      } catch {
        /* keep string */
      }
      const kind = type || payload?.event || "message";
      const taskId =
        payload?.task_id || payload?.taskId || payload?.data?.task_id || null;
      inferStages(kind);
      pushEvent(kind, payload?.data ?? payload, taskId);

      if (
        /tool/i.test(kind) ||
        payload?.tool ||
        payload?.event === "ToolExecutionRecord"
      ) {
        const body =
          typeof payload?.data === "string"
            ? payload.data
            : JSON.stringify(payload?.data ?? payload, null, 2);
        if (payload?.tool === "system.reply") {
          appendMsg("agent", escapeHtml(body));
        } else {
          appendMsg(
            "agent",
            "",
            `<div class="meta">${escapeHtml(kind)}</div><strong>Tool</strong><div class="tool-block">${escapeHtml(body)}</div>`,
          );
        }
        markStage("execute", "run");
        return;
      }
      if (payload?.text || payload?.message) {
        appendMsg("agent", payload.text || payload.message);
      } else if (/plan|task|verif|security|auth|policy/i.test(kind)) {
        appendMsg("system", kind);
      }
    };

    es.onmessage = (ev) => handle(ev.type || "message", ev.data);

    [
      "PlanStepCompleted",
      "PlanCompleted",
      "ToolExecutionRecord",
      "task.state_changed",
      "task.created",
      "task.error",
      "security.violation",
      "policy.denied",
      "authorization.granted",
      "memory.stored",
      "memory.deleted",
      "execution.started",
      "execution.completed",
      "execution.failed",
      "execution.suppressed",
    ].forEach((name) => {
      es.addEventListener(name, (ev) => handle(name, ev.data));
    });
  }

  // ── Memory ────────────────────────────────────────
  async function loadMemories() {
    const list = $("#memory-list");
    try {
      const res = await fetch("/api/memory/?profile_id=default");
      const memories = await res.json();
      state.memories = Array.isArray(memories) ? memories : [];
      $("#count-memory").textContent = String(state.memories.length);
      if (!state.memories.length) {
        list.innerHTML = `<div class="empty">No active memories.</div>`;
        return;
      }
      list.innerHTML = state.memories
        .map(
          (m) => `<div class="row">
            <div>
              <div class="title">${escapeHtml(m.content || "")}</div>
              <div class="detail">${escapeHtml(m.type || "memory")} · confidence ${(m.confidence ?? 0).toFixed?.(2) ?? m.confidence} · ${escapeHtml(m.source || "")}</div>
              <div class="mono">${escapeHtml(m.id)}</div>
            </div>
            <button type="button" class="btn sm danger" data-del="${escapeHtml(m.id)}">Delete</button>
          </div>`,
        )
        .join("");
    } catch (err) {
      console.error(err);
      list.innerHTML = `<div class="empty">Memory API unavailable.</div>`;
    }
  }

  $("#memory-list").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-del]");
    if (!btn) return;
    const id = btn.getAttribute("data-del");
    try {
      await fetch(`/api/memory/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      await loadMemories();
      pushEvent("memory.deleted", { id }, null);
    } catch (err) {
      console.error(err);
    }
  });
  $("#btn-refresh-memory").addEventListener("click", loadMemories);

  // ── Vault (optional route) ────────────────────────
  async function loadVault() {
    const list = $("#vault-list");
    try {
      const res = await fetch("/api/credentials/");
      if (!res.ok) throw new Error(String(res.status));
      const rows = await res.json();
      state.credentials = Array.isArray(rows) ? rows : [];
      if (!state.credentials.length) {
        list.innerHTML = `<div class="empty">No credential references registered.</div>`;
        return;
      }
      list.innerHTML = state.credentials
        .map((c) => {
          const ops = (c.operations || c.allowed_operations || []).join(", ");
          return `<div class="row">
            <div>
              <div class="title">${escapeHtml(c.label || c.id)}</div>
              <div class="detail">destination <code>${escapeHtml(c.destination || "—")}</code> · ops ${escapeHtml(ops || "—")} · lifetime ${escapeHtml(String(c.lifetime_seconds ?? c.lifetimeSeconds ?? "—"))}s</div>
              <div class="mono">${escapeHtml(c.id)}</div>
            </div>
            <span class="badge ${c.revoked ? "fail" : "ok"}">${c.revoked ? "revoked" : "active"}</span>
          </div>`;
        })
        .join("");
    } catch {
      list.innerHTML = `<div class="empty">
        Credential list API not mounted yet (<code>/api/credentials/</code>).<br/>
        Core vault exists in <code>shea.credentials</code> — expose references only when you add the route.
        GUI will never display secret material.
      </div>`;
    }
  }
  $("#btn-refresh-vault").addEventListener("click", loadVault);

  // ── Audit ─────────────────────────────────────────
  async function loadAudit() {
    try {
      const res = await fetch("/api/observability/audit?limit=50");
      const data = await res.json();
      const events = data.events || [];
      const body = $("#audit-body");
      body.innerHTML = events
        .map((ev) => {
          const result = (ev.result || "—").toString();
          let color = "var(--fg-muted)";
          if (/success/i.test(result)) color = "var(--success)";
          if (/fail|flag|denied|halt/i.test(result)) color = "var(--danger)";
          if (ev.task_id) {
            upsertTask(ev.task_id, {
              lastAction: ev.action || ev.component || "event",
              result,
              note: ev.component || "",
            });
          }
          return `<tr>
            <td>${ev.sequence_number ?? "—"}</td>
            <td>${ev.timestamp ? new Date(ev.timestamp).toLocaleString() : "—"}</td>
            <td>${escapeHtml(ev.component || "—")}</td>
            <td><code>${escapeHtml(ev.action || "—")}</code></td>
            <td style="color:${color};font-weight:600">${escapeHtml(result.toUpperCase())}</td>
            <td class="mono" style="font-size:11px">${escapeHtml(ev.task_id || "—")}</td>
          </tr>`;
        })
        .join("");
      renderTasks();
    } catch (err) {
      console.error(err);
    }
  }
  $("#btn-refresh-audit").addEventListener("click", loadAudit);
  $("#btn-refresh-tasks").addEventListener("click", loadAudit);

  // ── Dashboard ─────────────────────────────────────
  let successChart, latencyChart;
  function initCharts() {
    Chart.defaults.color = "#9aa3ad";
    Chart.defaults.borderColor = "rgba(236,234,228,0.12)";
    Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";
    successChart = new Chart($("#chart-success").getContext("2d"), {
      type: "doughnut",
      data: {
        labels: ["Success", "Failure"],
        datasets: [
          {
            data: [0, 0],
            backgroundColor: ["#6f9f7a", "#c07272"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          title: { display: true, text: "Tool outcomes", color: "#eceae4" },
        },
      },
    });
    latencyChart = new Chart($("#chart-latency").getContext("2d"), {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Avg ms",
            data: [],
            borderColor: "#c5cdd6",
            backgroundColor: "rgba(197,205,214,0.12)",
            tension: 0.35,
            fill: true,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: true, grid: { color: "rgba(236,234,228,0.08)" } },
          x: { grid: { display: false } },
        },
        plugins: {
          legend: { display: false },
          title: { display: true, text: "Execution latency", color: "#eceae4" },
        },
      },
    });
  }

  async function refreshDashboard() {
    try {
      const metricsRes = await fetch("/api/observability/metrics");
      const metrics = await metricsRes.json();
      $("#m-cpu").textContent = `${metrics.cpu_percent ?? 0}%`;
      $("#m-load").textContent = `load ${metrics.load_1m ?? 0}`;
      $("#m-ram").textContent = `${metrics.ram_percent ?? 0}%`;
      $("#m-ram-detail").textContent =
        `${metrics.ram_used_mb ?? 0} / ${metrics.ram_total_mb ?? 0} MB`;
      $("#m-disk").textContent = `${metrics.disk_percent ?? 0}%`;
      $("#m-disk-detail").textContent =
        `${metrics.disk_used_gb ?? 0} / ${metrics.disk_total_gb ?? 0} GB`;
      $("#m-prov").textContent = `${metrics.provider_health ?? 100}`;
      $("#m-rpm").textContent = `${metrics.requests_per_minute ?? 0}`;
      $("#m-budget").textContent =
        `${Math.round((metrics.rate_limit_remaining ?? 1) * 100)}%`;
      $("#m-rl-hits").textContent =
        `${metrics.rate_limit_hits ?? 0} limit hits`;
      $("#m-active").textContent = `${metrics.active_tasks ?? 0}`;
      $("#m-sec").textContent = `${metrics.security_blocks ?? 0}`;
      $("#m-intents").textContent = metrics.total_intents ?? 0;
      $("#m-tools").textContent = metrics.total_tools_executed ?? 0;
      $("#m-rate").textContent =
        `${((metrics.tool_success_rate ?? 0) * 100).toFixed(1)}%`;
      $("#m-avg").textContent =
        `${(metrics.avg_tool_duration_ms ?? 0).toFixed(0)}`;

      const total = metrics.total_tools_executed ?? 0;
      const ok = Math.round(total * rate);
      successChart.data.datasets[0].data = [ok, Math.max(0, total - ok)];
      successChart.update();

      const now = new Date().toLocaleTimeString();
      if (latencyChart.data.labels.length > 12) {
        latencyChart.data.labels.shift();
        latencyChart.data.datasets[0].data.shift();
      }
      latencyChart.data.labels.push(now);
      latencyChart.data.datasets[0].data.push(
        metrics.avg_tool_duration_ms ?? 0,
      );
      latencyChart.update();

      const auditRes = await fetch("/api/observability/audit?limit=12");
      const auditData = await auditRes.json();
      $("#dash-audit").innerHTML = (auditData.events || [])
        .map((ev) => {
          const result = (ev.result || "—").toString().toUpperCase();
          return `<tr>
            <td>${ev.sequence_number ?? "—"}</td>
            <td><code>${escapeHtml(ev.action || "—")}</code></td>
            <td>${escapeHtml(result)}</td>
            <td style="font-family:var(--font-mono);font-size:11px">${escapeHtml(ev.task_id || "—")}</td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      console.error(err);
    }
  }
  $("#btn-refresh-dash").addEventListener("click", refreshDashboard);

  // ── Boot ──────────────────────────────────────────
  initCharts();
  connectSSE();
  loadMemories();
  loadAudit();
  renderTasks();
  renderEvents();
  setInterval(() => {
    if ($("#view-dashboard").classList.contains("active")) refreshDashboard();
  }, 4000);
})();
