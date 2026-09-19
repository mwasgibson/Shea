document.addEventListener("DOMContentLoaded", () => {
  const valIntents = document.getElementById("val-intents");
  const valTools = document.getElementById("val-tools");
  const valSuccessRate = document.getElementById("val-success-rate");
  const valAvgTime = document.getElementById("val-avg-time");
  const auditTableBody = document.getElementById("audit-table-body");

  Chart.defaults.color = "#9aa3ad";
  Chart.defaults.borderColor = "rgba(236,234,228,0.12)";
  Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";

  const successChart = new Chart(
    document.getElementById("successRateChart").getContext("2d"),
    {
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
    },
  );

  const timeChart = new Chart(
    document.getElementById("executionTimeChart").getContext("2d"),
    {
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
    },
  );

  async function refreshDashboard() {
    try {
      const metricsRes = await fetch("/api/observability/metrics");
      const metrics = await metricsRes.json();

      valIntents.textContent = metrics.total_intents ?? 0;
      valTools.textContent = metrics.total_tools_executed ?? 0;
      const rate = metrics.tool_success_rate ?? 0;
      valSuccessRate.textContent = `${(rate * 100).toFixed(1)}%`;
      valAvgTime.textContent = `${(metrics.avg_tool_duration_ms ?? 0).toFixed(0)} ms`;

      const total = metrics.total_tools_executed ?? 0;
      const successes = Math.round(total * rate);
      successChart.data.datasets[0].data = [
        successes,
        Math.max(0, total - successes),
      ];
      successChart.update();

      const now = new Date().toLocaleTimeString();
      if (timeChart.data.labels.length > 12) {
        timeChart.data.labels.shift();
        timeChart.data.datasets[0].data.shift();
      }
      timeChart.data.labels.push(now);
      timeChart.data.datasets[0].data.push(metrics.avg_tool_duration_ms ?? 0);
      timeChart.update();

      const auditRes = await fetch("/api/observability/audit?limit=20");
      const auditData = await auditRes.json();
      auditTableBody.innerHTML = "";

      (auditData.events || []).forEach((ev) => {
        const tr = document.createElement("tr");
        const timeStr = ev.timestamp
          ? new Date(ev.timestamp).toLocaleString()
          : "—";
        const result = (ev.result || "—").toString().toUpperCase();
        let resultColor = "var(--fg-muted)";
        if (String(ev.result).toLowerCase() === "success")
          resultColor = "var(--success)";
        if (
          ["failed", "flagged", "denied"].includes(
            String(ev.result).toLowerCase(),
          )
        )
          resultColor = "var(--danger)";

        tr.innerHTML = `
          <td>${ev.sequence_number ?? "—"}</td>
          <td>${timeStr}</td>
          <td>${ev.component ?? "—"}</td>
          <td><code>${ev.action ?? "—"}</code></td>
          <td style="color:${resultColor};font-weight:600">${result}</td>
          <td style="font-family:var(--font-mono);font-size:11px">${ev.task_id || "—"}</td>
        `;
        auditTableBody.appendChild(tr);
      });
    } catch (err) {
      console.error("Dashboard refresh error:", err);
    }
  }

  refreshDashboard();
  setInterval(refreshDashboard, 2000);
});
