// Lightweight Chart.js helpers (offline, no build step).
// The script is intentionally tiny and page-driven by window.* data objects.

function srmRenderBarChart(canvasId, labels, values, title) {
  const el = document.getElementById(canvasId);
  if (!el || !window.Chart) return;
  const ctx = el.getContext("2d");
  new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: title,
          data: values,
          backgroundColor: "rgba(59, 130, 246, 0.35)",
          borderColor: "rgba(59, 130, 246, 0.9)",
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true },
        title: { display: true, text: title },
      },
      scales: {
        x: { ticks: { color: "#cbd5e1" }, grid: { color: "rgba(148,163,184,0.12)" } },
        y: { ticks: { color: "#cbd5e1" }, grid: { color: "rgba(148,163,184,0.12)" }, beginAtZero: true },
      },
    },
  });
}

function srmRenderLineChart(canvasId, labels, values, title) {
  const el = document.getElementById(canvasId);
  if (!el || !window.Chart) return;
  const ctx = el.getContext("2d");
  new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: title,
          data: values,
          borderColor: "rgba(34, 197, 94, 0.95)",
          backgroundColor: "rgba(34, 197, 94, 0.18)",
          pointRadius: 3,
          tension: 0.25,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true },
        title: { display: true, text: title },
      },
      scales: {
        x: { ticks: { color: "#cbd5e1" }, grid: { color: "rgba(148,163,184,0.12)" } },
        y: { ticks: { color: "#cbd5e1" }, grid: { color: "rgba(148,163,184,0.12)" }, beginAtZero: true },
      },
    },
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const d = window.SRM_DASHBOARD_DATA;
  if (!d) return;

  if (d.violationsByType) {
    srmRenderBarChart(
      "chart-violations-by-type",
      d.violationsByType.labels || [],
      d.violationsByType.values || [],
      "Нарушения по типам"
    );
  }
  if (d.violationsTimeline) {
    srmRenderLineChart(
      "chart-violations-timeline",
      d.violationsTimeline.labels || [],
      d.violationsTimeline.values || [],
      "Динамика нарушений (по запускам анализа)"
    );
  }
  if (d.topRiskSuppliers) {
    srmRenderBarChart(
      "chart-top-risk-suppliers",
      d.topRiskSuppliers.labels || [],
      d.topRiskSuppliers.values || [],
      "Топ рискованных поставщиков (risk score)"
    );
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const d = window.SRM_INTEL_DATA;
  if (!d) return;

  if (d.riskLevels) {
    srmRenderBarChart(
      "chart-risk-levels",
      d.riskLevels.labels || [],
      d.riskLevels.values || [],
      "Поставщики по уровням риска"
    );
  }
  if (d.riskDynamics) {
    srmRenderLineChart(
      "chart-risk-dynamics",
      d.riskDynamics.labels || [],
      d.riskDynamics.values || [],
      "Динамика среднего risk score"
    );
  }
  if (d.f1Comparison) {
    srmRenderBarChart(
      "chart-f1-baseline-proposed",
      d.f1Comparison.labels || [],
      d.f1Comparison.values || [],
      "Сравнение методов: F1-score"
    );
  }
});
