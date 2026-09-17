document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const valIntents = document.getElementById("val-intents");
  const valTools = document.getElementById("val-tools");
  const valSuccessRate = document.getElementById("val-success-rate");
  const valAvgTime = document.getElementById("val-avg-time");
  const auditTableBody = document.getElementById("audit-table-body");

  // Chart.js Instances
  const ctxSuccess = document
    .getElementById("successRateChart")
    .getContext("2d");
  const ctxTime = document
    .getElementById("executionTimeChart")
    .getContext("2d");

  const successChart = new Chart(ctxSuccess, {
    type: "doughnut",
    data: {
      labels: ["Success", "Failure"],
      datasets: [
        {
          data: [0, 0],
          backgroundColor: ["#28a745", "#dc3545"],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: "Tool Execution Outcomes" } },
    },
  });

  const timeChart = new Chart(ctxTime, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Avg Execution Time (ms)",
          data: [],
          borderColor: "#007aff",
          tension: 0.4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true } },
    },
  });

  // Fetch and Update Data
  async function refreshDashboard() {
    try {
      // Fetch Metrics
      const metricsRes = await fetch("/api/observability/metrics");
      const metrics = await metricsRes.json();

      valIntents.textContent = metrics.total_intents;
      valTools.textContent = metrics.total_tools_executed;
      valSuccessRate.textContent = `${(metrics.tool_success_rate * 100).toFixed(1)}%`;
      valAvgTime.textContent = `${metrics.avg_tool_duration_ms.toFixed(0)} ms`;

      // Update Doughnut Chart
      const successes = Math.round(
        metrics.total_tools_executed * metrics.tool_success_rate,
      );
      const failures = metrics.total_tools_executed - successes;
      successChart.data.datasets[0].data = [successes, failures];
      successChart.update();

      // Update Line Chart (simulate timeline by appending current avg)
      const now = new Date().toLocaleTimeString();
      if (timeChart.data.labels.length > 10) {
        timeChart.data.labels.shift();
        timeChart.data.datasets[0].data.shift();
      }
      timeChart.data.labels.push(now);
      timeChart.data.datasets[0].data.push(metrics.avg_tool_duration_ms);
      timeChart.update();

      // Fetch Audit Logs
      const auditRes = await fetch("/api/observability/audit?limit=20");
      const auditData = await auditRes.json();

      auditTableBody.innerHTML = "";
      auditData.events.forEach((ev) => {
        const tr = document.createElement("tr");
        const timeStr = new Date(ev.timestamp).toLocaleTimeString();

        // Color code the result column
        let resultColor = "var(--text-primary)";
        if (ev.result === "success") resultColor = "#28a745";
        if (ev.result === "failed" || ev.result === "flagged")
          resultColor = "#dc3545";

        tr.innerHTML = `
                    <td>${ev.sequence_number}</td>
                    <td>${timeStr}</td>
                    <td>${ev.component}</td>
                    <td><code>${ev.action}</code></td>
                    <td style="color: ${resultColor}; font-weight: bold;">${ev.result.toUpperCase()}</td>
                    <td style="font-size: 11px;">${ev.task_id || "-"}</td>
                `;
        auditTableBody.appendChild(tr);
      });
    } catch (err) {
      console.error("Dashboard refresh error:", err);
    }
  }

  // Refresh every 2 seconds
  refreshDashboard();
  setInterval(refreshDashboard, 2000);
});
