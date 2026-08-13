const COST_CATEGORY_KEYS = [
  { key: "input_cost", label: "New input", color: "76, 114, 176" },
  { key: "cache_write_cost", label: "Cache write", color: "221, 132, 82" },
  { key: "cache_read_cost", label: "Cache read", color: "85, 168, 104" },
  { key: "output_cost", label: "Output", color: "196, 78, 82" },
];

const MODEL_PALETTE = [
  "76, 114, 176",
  "221, 132, 82",
  "85, 168, 104",
  "196, 78, 82",
  "129, 114, 179",
  "147, 120, 96",
];

const PAGE_SIZE = 5;

let currentGroupBy = "day";
const charts = {};

function escapeHtml(value) {
  const escapes = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, (ch) => escapes[ch]);
}

function formatCost(value) {
  return value === null || value === undefined ? "—" : `$${value.toFixed(2)}`;
}

function renderChart(key, ctx, config) {
  if (charts[key]) charts[key].destroy();
  charts[key] = new Chart(ctx, config);
}

// Shared by any table cell listing which models made up a cost figure (top
// sessions, repeated prompts) -- each entry's cost_usd sums back to the
// row's own total, since both come from the same SUM(cost_usd), just grouped
// differently.
function formatModelBreakdown(models) {
  return (
    models
      .map((m) => `<div>${escapeHtml(m.model || "unknown model")}: ${formatCost(m.cost_usd)}</div>`)
      .join("") || "—"
  );
}

// Shared pager for every list-shaped section (repeated prompts, most
// expensive periods/sessions, recommendations) so they all page the same
// way at the same page size, whether their container is a <tbody> or <ul>.
function createPaginatedList(containerSelector, paginationId, renderItemFn, emptyMessage) {
  let data = [];
  let page = 0;

  function render() {
    const container = document.querySelector(containerSelector);
    const pagination = document.getElementById(paginationId);

    if (data.length === 0) {
      container.innerHTML = emptyMessage;
      pagination.innerHTML = "";
      return;
    }

    const totalPages = Math.ceil(data.length / PAGE_SIZE);
    page = Math.max(0, Math.min(page, totalPages - 1));
    const start = page * PAGE_SIZE;

    container.innerHTML = data
      .slice(start, start + PAGE_SIZE)
      .map(renderItemFn)
      .join("");

    pagination.innerHTML = `
      <button class="page-prev" ${page === 0 ? "disabled" : ""}>&laquo; Prev</button>
      <span>Page ${page + 1} of ${totalPages}</span>
      <button class="page-next" ${page >= totalPages - 1 ? "disabled" : ""}>Next &raquo;</button>
    `;

    pagination.querySelector(".page-prev").addEventListener("click", () => {
      page -= 1;
      render();
    });
    pagination.querySelector(".page-next").addEventListener("click", () => {
      page += 1;
      render();
    });
  }

  return {
    setData(newData) {
      data = newData;
      page = 0;
      render();
    },
  };
}

const repeatedPromptsList = createPaginatedList(
  "#repeated-prompts-table tbody",
  "repeated-prompts-pagination",
  (row) => `
    <tr>
      <td style="text-align: left;">${escapeHtml((row.prompt_text || "").slice(0, 100))}${(row.prompt_text || "").length > 100 ? "…" : ""}</td>
      <td>${row.session_count}</td>
      <td>${row.record_count}</td>
      <td style="text-align: left;" class="model-breakdown">${formatModelBreakdown(row.models)}</td>
      <td>${formatCost(row.total_cost)}</td>
    </tr>
  `,
  `<tr><td colspan="5" class="empty-note">No repeated prompts above the threshold.</td></tr>`,
);

const topSessionsList = createPaginatedList(
  "#top-sessions-table tbody",
  "top-sessions-pagination",
  (row) => {
    const name = escapeHtml(row.session_name || `${row.session_id.slice(0, 8)}…`);
    return `
      <tr>
        <td style="text-align: left;"><a class="drilldown-link" href="${sessionLink(row.period, row.session_id)}">${name}</a></td>
        <td style="text-align: left;" class="model-breakdown">${formatModelBreakdown(row.models)}</td>
        <td>${formatCost(row.cost_usd)}</td>
      </tr>
    `;
  },
  `<tr><td colspan="3" class="empty-note">No priced sessions yet.</td></tr>`,
);

const recommendationsList = createPaginatedList(
  "#recommendations-list",
  "recommendations-pagination",
  (rec) => `
    <li>
      <div class="rule-tag">${escapeHtml(rec.rule)}</div>
      <div>${escapeHtml(rec.message)}</div>
    </li>
  `,
  `<li class="empty-note">No recommendations fire against the current data.</li>`,
);

function renderModelMixChart(byPeriodModel) {
  const periods = [...new Set(byPeriodModel.map((row) => row.period))].sort();
  const models = [...new Set(byPeriodModel.map((row) => row.model))];
  const datasets = models.map((model, index) => {
    const byPeriod = Object.fromEntries(
      byPeriodModel.filter((row) => row.model === model).map((row) => [row.period, row.record_count]),
    );
    const color = MODEL_PALETTE[index % MODEL_PALETTE.length];
    return {
      label: model || "unknown model",
      data: periods.map((p) => byPeriod[p] ?? 0),
      borderColor: `rgba(${color}, 1)`,
      backgroundColor: `rgba(${color}, 0.2)`,
      fill: false,
    };
  });
  renderChart("modelMix", document.getElementById("model-mix-chart"), {
    type: "line",
    data: { labels: periods, datasets },
    options: {
      responsive: true,
      scales: { y: { beginAtZero: true, title: { display: true, text: "Records" } } },
      plugins: { title: { display: true, text: "Model-usage mix over time" } },
    },
  });
}

// Merges what used to be two separate charts (cost-by-category, cost-by-model)
// into one: the stacked bars still show cost by category per period, and
// hovering a bar segment's tooltip adds the per-model breakdown behind that
// category's dollar figure for that period, via `costByCategoryModel`
// (`GET /api/analysis/cost-drivers`'s `cost_by_category_model`).
function renderCostByCategoryChart(costByCategory, costByCategoryModel) {
  const periods = costByCategory.map((row) => row.period);
  const datasets = COST_CATEGORY_KEYS.map(({ key, label, color }) => ({
    label,
    categoryKey: key,
    data: costByCategory.map((row) => row[key]),
    backgroundColor: `rgba(${color}, 0.85)`,
    borderColor: `rgba(${color}, 1)`,
    borderWidth: 1,
  }));
  renderChart("costByCategory", document.getElementById("cost-by-category-chart"), {
    type: "bar",
    data: { labels: periods, datasets },
    options: {
      responsive: true,
      scales: {
        x: { stacked: true },
        y: { stacked: true, beginAtZero: true, title: { display: true, text: "USD" } },
      },
      plugins: {
        title: { display: true, text: "Cost by category over time" },
        tooltip: {
          callbacks: {
            label: (context) => `${context.dataset.label}: ${formatCost(context.parsed.y)}`,
            afterLabel: (context) => {
              const period = context.label;
              const categoryKey = context.dataset.categoryKey;
              const breakdown = costByCategoryModel[period]?.[categoryKey] || [];
              return breakdown.map(
                (entry) => `  ${entry.model || "unknown model"}: ${formatCost(entry.cost_usd)}`,
              );
            },
          },
        },
      },
    },
  });
}

function renderHumanSubagentTable(split) {
  const tbody = document.querySelector("#human-subagent-table tbody");
  tbody.innerHTML = `
    <tr><td style="text-align: left;">Human</td><td>${formatCost(split.human_cost_usd)}</td></tr>
    <tr><td style="text-align: left;">Subagent</td><td>${formatCost(split.subagent_cost_usd)}</td></tr>
  `;
}

function periodLink(period) {
  return `/?period=${encodeURIComponent(period)}&group_by=${encodeURIComponent(currentGroupBy)}`;
}

function sessionLink(period, sessionId) {
  return `${periodLink(period)}&session_id=${encodeURIComponent(sessionId)}`;
}

function renderUnknownCostNote(unknownCost) {
  const el = document.getElementById("unknown-cost-note");
  if (unknownCost.length === 0) {
    el.textContent = "";
    return;
  }
  const parts = unknownCost.map(
    (row) => `${row.model || "unknown model"} (${row.record_count} record(s), ${row.token_count.toLocaleString()} tokens)`,
  );
  el.innerHTML = `<span class="unknown-cost-note">Unknown cost -- unpriced in db/pricing.py: ${escapeHtml(parts.join(", "))}. Every total above excludes these.</span>`;
}

async function loadTrends() {
  try {
    const [trendsRes, promptsRes] = await Promise.all([
      fetch(`/api/analysis/trends?group_by=${currentGroupBy}`),
      fetch("/api/analysis/repeated-prompts?min_occurrences=2&min_length=20"),
    ]);
    const trends = await trendsRes.json();
    const prompts = await promptsRes.json();
    renderModelMixChart(trends.by_period_model);
    repeatedPromptsList.setData(prompts);
  } catch (err) {
    console.error("Failed to load trends section", err);
  }
}

async function loadCostDrivers() {
  try {
    const response = await fetch(`/api/analysis/cost-drivers?group_by=${currentGroupBy}`);
    const data = await response.json();
    renderCostByCategoryChart(data.cost_by_category, data.cost_by_category_model);
    renderHumanSubagentTable(data.human_vs_subagent);
    topSessionsList.setData(data.top_sessions);
    renderUnknownCostNote(data.unknown_cost);
  } catch (err) {
    console.error("Failed to load cost-drivers section", err);
  }
}

async function loadRecommendations() {
  try {
    const response = await fetch(`/api/analysis/recommendations?group_by=${currentGroupBy}`);
    const recommendations = await response.json();
    recommendationsList.setData(recommendations);
  } catch (err) {
    console.error("Failed to load recommendations section", err);
  }
}

function loadAndRender() {
  currentGroupBy = document.getElementById("group-by").value;
  loadTrends();
  loadCostDrivers();
  loadRecommendations();
}

if (typeof window !== "undefined") {
  document.getElementById("group-by").addEventListener("change", loadAndRender);
  loadAndRender();
}
