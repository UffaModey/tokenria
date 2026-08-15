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
      <td style="text-align: left;" class="prompt-cell" data-prompt="${escapeHtml(row.prompt_text || "")}">${escapeHtml((row.prompt_text || "").slice(0, 100))}${(row.prompt_text || "").length > 100 ? "…" : ""}</td>
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
        <td style="text-align: left;" class="session-cell" data-session-id="${escapeHtml(row.session_id)}">${name}</td>
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

function agentBadgeText(instance) {
  return instance.is_subagent ? ` · subagent (${escapeHtml(instance.agent_type || "unknown")})` : "";
}

function agentBadge(record) {
  if (!record.is_subagent) return "";
  const description = escapeHtml(record.agent_description || "");
  return `<span class="agent-badge" title="${description}">${escapeHtml(record.agent_type || "subagent")}</span>`;
}

function renderPromptInstancesPanel(instances) {
  const rows = instances
    .map((inst) => {
      const sessionName = escapeHtml(
        inst.session_name || `${inst.session_id.slice(0, 8)}…`,
      );
      return `
        <div class="prompt-instance">
          <div class="meta">
            ${escapeHtml(inst.timestamp)} · ${sessionName} · ${escapeHtml(inst.model || "unknown model")} ·
            ${formatCost(inst.cost_usd)}${agentBadgeText(inst)}
          </div>
          <div class="meta">
            in ${inst.input_tokens.toLocaleString()} · cache write ${inst.cache_write_tokens.toLocaleString()} ·
            cache read ${inst.cache_read_tokens.toLocaleString()} · out ${inst.output_tokens.toLocaleString()}
          </div>
          <div class="field-label">Prompt</div>
          <div class="field-value">${escapeHtml(inst.prompt_text || "")}</div>
          <div class="field-label">Response</div>
          <div class="field-value">${escapeHtml(inst.response_text || "")}</div>
        </div>
      `;
    })
    .join("");

  document.getElementById("detail-panel-title").innerHTML =
    `<h2>Instances <span class="prompt-count">(${instances.length})</span></h2>`;
  document.getElementById("detail-panel-controls").innerHTML = "";
  document.getElementById("detail-panel-body").innerHTML =
    rows || "<p>No instances found.</p>";
}

async function openPromptInstances(promptText) {
  const response = await fetch(
    `/api/analysis/repeated-prompts/instances?prompt_text=${encodeURIComponent(promptText)}`,
  );
  const instances = await response.json();
  renderPromptInstancesPanel(instances);
  document.getElementById("detail-panel").style.display = "flex";
}

// Consecutive records sharing session_id + prompt_text are one human/subagent
// turn split across several closing text blocks by stage 1's adapter -- a
// display-only workaround, not an ingestion-level fix. Duplicated from
// accounting.js (see tests/test_accounting_js.mjs) since this project has no
// build step / shared-module mechanism between static JS files.
function collapseFragments(records) {
  const groups = [];
  for (const record of records) {
    const last = groups[groups.length - 1];
    if (
      last &&
      last.session_id === record.session_id &&
      last.prompt_text === record.prompt_text
    ) {
      last.fragments.push(record);
    } else {
      groups.push({
        session_id: record.session_id,
        prompt_text: record.prompt_text,
        is_subagent: record.is_subagent,
        agent_type: record.agent_type,
        agent_description: record.agent_description,
        model: record.model,
        timestamp: record.timestamp,
        fragments: [record],
      });
    }
  }
  return groups.map((group) => {
    const totals = {
      input_tokens: 0,
      cache_write_tokens: 0,
      cache_read_tokens: 0,
      output_tokens: 0,
      cost_usd: null,
    };
    for (const fragment of group.fragments) {
      totals.input_tokens += fragment.input_tokens;
      totals.cache_write_tokens += fragment.cache_write_tokens;
      totals.cache_read_tokens += fragment.cache_read_tokens;
      totals.output_tokens += fragment.output_tokens;
      if (fragment.cost_usd !== null) {
        totals.cost_usd = (totals.cost_usd ?? 0) + fragment.cost_usd;
      }
    }
    return { ...group, totals };
  });
}

let currentSessionGroups = [];

function sortGroups(groups, sortBy) {
  const sorted = [...groups];
  if (sortBy === "cost") {
    sorted.sort((a, b) => (b.totals.cost_usd ?? -Infinity) - (a.totals.cost_usd ?? -Infinity));
  } else if (sortBy === "model") {
    sorted.sort((a, b) => (a.model || "").localeCompare(b.model || ""));
  } else {
    sorted.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }
  return sorted;
}

function renderSessionGroupsBody(groups) {
  const groupsHtml = groups
    .map((group) => {
      const fragmentsHtml = group.fragments
        .map(
          (fragment) => `
            <div class="fragment">
              <div class="meta">
                ${escapeHtml(fragment.model || "unknown model")} ·
                ${formatCost(fragment.cost_usd)}
                · in ${fragment.input_tokens.toLocaleString()} · cache write
                ${fragment.cache_write_tokens.toLocaleString()} · cache read
                ${fragment.cache_read_tokens.toLocaleString()} · out
                ${fragment.output_tokens.toLocaleString()}
              </div>
              <div>${escapeHtml((fragment.response_text || "").slice(0, 300))}${
                (fragment.response_text || "").length > 300 ? "…" : ""
              }</div>
            </div>
          `,
        )
        .join("");

      return `
        <details class="prompt-group">
          <summary>
            ${escapeHtml((group.prompt_text || "").slice(0, 120))}${agentBadge(group)}
            <div class="meta">
              ${escapeHtml(group.timestamp)} · ${escapeHtml(group.model || "unknown model")} ·
              ${formatCost(group.totals.cost_usd)}
              (${group.fragments.length} fragment${group.fragments.length > 1 ? "s" : ""})
            </div>
          </summary>
          ${fragmentsHtml}
        </details>
      `;
    })
    .join("");

  const total = groups.reduce(
    (sum, g) => (g.totals.cost_usd === null ? sum : sum + g.totals.cost_usd),
    0,
  );

  document.getElementById("detail-panel-body").innerHTML = `
    ${groupsHtml || "<p>No prompts found for this session.</p>"}
    <div class="panel-total">Total across all prompts shown: ${formatCost(total)}</div>
  `;
}

function renderSessionPromptsPanel(sessionName, groups) {
  currentSessionGroups = groups;

  document.getElementById("detail-panel-title").innerHTML =
    `<h2>${escapeHtml(sessionName)} <span class="prompt-count">(${groups.length})</span></h2>`;

  document.getElementById("detail-panel-controls").innerHTML = `
    <label class="panel-controls">
      Sort by:
      <select id="session-sort-by">
        <option value="date" selected>Date</option>
        <option value="cost">Cost</option>
        <option value="model">Model</option>
      </select>
    </label>
  `;
  document.getElementById("session-sort-by").addEventListener("change", (event) => {
    renderSessionGroupsBody(sortGroups(currentSessionGroups, event.target.value));
  });

  renderSessionGroupsBody(groups);
}

async function openSessionInstances(sessionId) {
  const response = await fetch(
    `/api/records?session_id=${encodeURIComponent(sessionId)}&limit=500`,
  );
  const records = await response.json();
  const sessionName = records[0]?.session_name || `${sessionId.slice(0, 8)}…`;
  renderSessionPromptsPanel(sessionName, collapseFragments(records));
  document.getElementById("detail-panel").style.display = "flex";
}

function closeDetailPanel() {
  document.getElementById("detail-panel").style.display = "none";
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
  document.getElementById("detail-panel-close").addEventListener("click", closeDetailPanel);
  document.querySelector("#repeated-prompts-table tbody").addEventListener("click", (event) => {
    const cell = event.target.closest(".prompt-cell");
    if (cell) openPromptInstances(cell.dataset.prompt);
  });
  document.querySelector("#top-sessions-table tbody").addEventListener("click", (event) => {
    const cell = event.target.closest(".session-cell");
    if (cell) openSessionInstances(cell.dataset.sessionId);
  });
  loadAndRender();
}

if (typeof module !== "undefined") {
  module.exports = { collapseFragments };
}
