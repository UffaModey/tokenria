const CATEGORIES = [
  { key: "input_tokens", label: "New input", color: "76, 114, 176" },
  { key: "cache_write_tokens", label: "Cache write", color: "221, 132, 82" },
  { key: "cache_read_tokens", label: "Cache read", color: "85, 168, 104" },
  { key: "output_tokens", label: "Output", color: "196, 78, 82" },
];

let chart = null;
let currentGroupBy = "day";

function combineBySourcelessPeriod(rows) {
  // Collapse across `source` so the chart shows structural breakdown per
  // period, split only by exact vs. estimated (not by ingestion source).
  const combined = new Map();
  for (const row of rows) {
    const key = `${row.period}|${row.is_estimated}`;
    if (!combined.has(key)) {
      combined.set(key, {
        period: row.period,
        is_estimated: row.is_estimated,
        input_tokens: 0,
        cache_write_tokens: 0,
        cache_read_tokens: 0,
        output_tokens: 0,
        cost_usd: null,
      });
    }
    const acc = combined.get(key);
    for (const { key: k } of CATEGORIES) acc[k] += row[k];
    if (row.cost_usd !== null) {
      acc.cost_usd = (acc.cost_usd ?? 0) + row.cost_usd;
    }
  }
  return [...combined.values()].sort((a, b) => a.period.localeCompare(b.period));
}

function buildDatasets(rows) {
  const periods = [...new Set(rows.map((r) => r.period))].sort();
  const datasets = [];

  for (const estimated of [false, true]) {
    const subset = rows.filter((r) => r.is_estimated === estimated);
    if (subset.length === 0) continue;

    for (const { key, label, color } of CATEGORIES) {
      const byPeriod = Object.fromEntries(subset.map((r) => [r.period, r[key]]));
      datasets.push({
        label: estimated ? `${label} (estimated)` : label,
        data: periods.map((p) => byPeriod[p] ?? 0),
        backgroundColor: `rgba(${color}, ${estimated ? 0.35 : 0.85})`,
        borderColor: `rgba(${color}, 1)`,
        borderWidth: estimated ? 2 : 1,
        borderDash: estimated ? [6, 4] : [],
        stack: estimated ? "estimated" : "exact",
      });
    }
  }

  return { periods, datasets };
}

function renderChart(rows) {
  const { periods, datasets } = buildDatasets(rows);
  const ctx = document.getElementById("accounting-chart");

  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "bar",
    data: { labels: periods, datasets },
    options: {
      responsive: true,
      onClick: (_event, elements) => {
        if (elements.length === 0) return;
        openSessionsPanel(periods[elements[0].index]);
      },
      scales: {
        x: { stacked: true },
        y: { stacked: true, beginAtZero: true, title: { display: true, text: "Tokens" } },
      },
      plugins: {
        title: { display: true, text: "Token breakdown by period" },
      },
    },
  });
}

function renderTotals(rows) {
  let totalTokens = 0;
  let totalCost = 0;
  let cacheReadTokens = 0;

  for (const row of rows) {
    for (const { key } of CATEGORIES) totalTokens += row[key];
    cacheReadTokens += row.cache_read_tokens;
    if (row.cost_usd !== null) totalCost += row.cost_usd;
  }

  document.getElementById("total-tokens").textContent = totalTokens.toLocaleString();
  document.getElementById("total-cost").textContent = `$${totalCost.toFixed(2)}`;
  document.getElementById("cache-read-share").textContent =
    totalTokens === 0 ? "—" : `${((cacheReadTokens / totalTokens) * 100).toFixed(1)}%`;
}

function renderTable(rows) {
  const tbody = document.querySelector("#detail-table tbody");
  tbody.innerHTML = "";

  for (const row of rows) {
    const tr = document.createElement("tr");
    const periodLabel = row.is_estimated
      ? `${row.period}<span class="estimated-tag">estimated</span>`
      : row.period;
    tr.innerHTML = `
      <td>${periodLabel}</td>
      <td>${row.input_tokens.toLocaleString()}</td>
      <td>${row.cache_write_tokens.toLocaleString()}</td>
      <td>${row.cache_read_tokens.toLocaleString()}</td>
      <td>${row.output_tokens.toLocaleString()}</td>
      <td>${row.cost_usd === null ? "—" : `$${row.cost_usd.toFixed(2)}`}</td>
    `;
    tr.addEventListener("click", () => openSessionsPanel(row.period));
    tbody.appendChild(tr);
  }
}

async function loadAndRender() {
  currentGroupBy = document.getElementById("group-by").value;
  const response = await fetch(`/api/records/summary?group_by=${currentGroupBy}`);
  const rawRows = await response.json();
  const rows = combineBySourcelessPeriod(rawRows);

  renderChart(rows);
  renderTotals(rows);
  renderTable(rows);
}

function escapeHtml(value) {
  const escapes = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, (ch) => escapes[ch]);
}

// Consecutive records sharing session_id + prompt_text are one human turn split
// across several closing text blocks by stage 1's adapter (see CLAUDE.md's stage 4
// notes) -- this is a display-only workaround, not an ingestion-level fix.
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

function closePanel() {
  document.getElementById("drilldown-panel").style.display = "none";
}

function agentBadge(record) {
  if (!record.is_subagent) return "";
  const description = escapeHtml(record.agent_description || "");
  return `<span class="agent-badge" title="${description}">${escapeHtml(record.agent_type || "subagent")}</span>`;
}

async function openSessionsPanel(period) {
  const response = await fetch(
    `/api/records/summary/${encodeURIComponent(period)}/sessions?group_by=${currentGroupBy}`,
  );
  const sessions = await response.json();
  renderSessionsView(period, sessions);
  document.getElementById("drilldown-panel").style.display = "block";
}

function renderSessionsView(period, sessions) {
  const rows = sessions
    .map((session) => {
      const name = escapeHtml(session.session_name || `${session.session_id.slice(0, 8)}…`);
      return `
        <div class="session-row" data-session-id="${escapeHtml(session.session_id)}">
          <strong>${name}</strong>
          <div class="meta">
            ${session.record_count} record(s) — ${session.human_count} human /
            ${session.subagent_count} subagent · ${escapeHtml(session.models.join(", "))}
          </div>
          <div class="meta">
            input ${session.input_tokens.toLocaleString()} · cache write
            ${session.cache_write_tokens.toLocaleString()} · cache read
            ${session.cache_read_tokens.toLocaleString()} · output
            ${session.output_tokens.toLocaleString()} ·
            ${session.cost_usd === null ? "cost unknown" : `$${session.cost_usd.toFixed(2)}`}
          </div>
        </div>
      `;
    })
    .join("");

  document.getElementById("panel-content").innerHTML = `
    <h2>Sessions — ${escapeHtml(period)}</h2>
    ${rows || "<p>No sessions in this period.</p>"}
  `;

  for (const el of document.querySelectorAll(".session-row")) {
    el.addEventListener("click", () => openSessionPrompts(period, el.dataset.sessionId));
  }
}

async function openSessionPrompts(period, sessionId) {
  const response = await fetch(
    `/api/records?session_id=${encodeURIComponent(sessionId)}` +
      `&group_by=${currentGroupBy}&period=${encodeURIComponent(period)}&limit=500`,
  );
  const records = await response.json();
  renderPromptsView(period, collapseFragments(records));
}

function renderPromptsView(period, groups) {
  const groupsHtml = groups
    .map((group, index) => {
      const fragmentsHtml = group.fragments
        .map(
          (fragment) => `
            <div class="fragment">
              <div class="meta">
                ${fragment.model || "unknown model"} ·
                ${fragment.cost_usd === null ? "cost unknown" : `$${fragment.cost_usd.toFixed(2)}`}
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
              ${group.timestamp} ·
              ${group.totals.cost_usd === null ? "cost unknown" : `$${group.totals.cost_usd.toFixed(2)}`}
              (${group.fragments.length} fragment${group.fragments.length > 1 ? "s" : ""})
            </div>
          </summary>
          ${fragmentsHtml}
        </details>
      `;
    })
    .join("");

  document.getElementById("panel-content").innerHTML = `
    <button class="panel-back" id="panel-back">&larr; back to sessions</button>
    <h2>Prompts — ${escapeHtml(period)}</h2>
    ${groupsHtml || "<p>No prompts for this session in this period.</p>"}
  `;

  document
    .getElementById("panel-back")
    .addEventListener("click", () => openSessionsPanel(period));
}

// Guarded so this file can be `require()`d headlessly (see
// tests/test_accounting_js.mjs) to unit-test collapseFragments without a
// real browser/Chart.js/fetch environment.
if (typeof window !== "undefined") {
  document.getElementById("group-by").addEventListener("change", loadAndRender);
  document.getElementById("panel-close").addEventListener("click", closePanel);
  loadAndRender();
}

if (typeof module !== "undefined") {
  module.exports = { collapseFragments };
}
