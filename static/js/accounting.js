const CATEGORIES = [
  { key: "input_tokens", label: "New input", color: "76, 114, 176" },
  { key: "cache_write_tokens", label: "Cache write", color: "221, 132, 82" },
  { key: "cache_read_tokens", label: "Cache read", color: "85, 168, 104" },
  { key: "output_tokens", label: "Output", color: "196, 78, 82" },
];

let chart = null;

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
    tbody.appendChild(tr);
  }
}

async function loadAndRender() {
  const groupBy = document.getElementById("group-by").value;
  const response = await fetch(`/api/records/summary?group_by=${groupBy}`);
  const rawRows = await response.json();
  const rows = combineBySourcelessPeriod(rawRows);

  renderChart(rows);
  renderTotals(rows);
  renderTable(rows);
}

document.getElementById("group-by").addEventListener("change", loadAndRender);
loadAndRender();
