const MAX_CHUNK_LEN = 400;
const STATES = ["unmarked", "used", "discarded"];

let currentRecordId = null;
let currentResponseText = "";
// chunk = { start, end, state }
let chunks = [];

// picker filters: id/date/session are mutually narrowing over allRecords.
// { id, date, session_id }, each "" meaning "Any".
let allRecords = [];
let filters = { id: "", date: "", session_id: "" };

function splitOnBlankLines(text) {
  const ranges = [];
  const blankLineRe = /\n[ \t]*\n+/g;
  let start = 0;
  let match;
  while ((match = blankLineRe.exec(text)) !== null) {
    if (match.index > start) ranges.push([start, match.index]);
    start = blankLineRe.lastIndex;
  }
  if (start < text.length) ranges.push([start, text.length]);
  return ranges;
}

function splitOnSingleNewlines(text, blockStart, blockEnd, maxLen) {
  const ranges = [];
  let chunkStart = blockStart;
  let i = blockStart;
  while (i < blockEnd) {
    const nlIndex = text.indexOf("\n", i);
    const lineEnd = nlIndex === -1 || nlIndex >= blockEnd ? blockEnd : nlIndex + 1;
    if (lineEnd - chunkStart > maxLen && i > chunkStart) {
      ranges.push([chunkStart, i]);
      chunkStart = i;
    }
    i = lineEnd;
  }
  if (chunkStart < blockEnd) ranges.push([chunkStart, blockEnd]);
  return ranges;
}

function splitIntoChunks(text, maxLen = MAX_CHUNK_LEN) {
  const ranges = [];
  for (const [start, end] of splitOnBlankLines(text)) {
    if (end - start <= maxLen) {
      ranges.push([start, end]);
    } else {
      ranges.push(...splitOnSingleNewlines(text, start, end, maxLen));
    }
  }
  return ranges;
}

function computeRatio() {
  let usedChars = 0;
  let discardedChars = 0;
  let reviewed = 0;
  for (const chunk of chunks) {
    const length = chunk.end - chunk.start;
    if (chunk.state === "used") {
      usedChars += length;
      reviewed += 1;
    } else if (chunk.state === "discarded") {
      discardedChars += length;
      reviewed += 1;
    }
  }
  const reviewedChars = usedChars + discardedChars;
  const ratio = reviewedChars === 0 ? null : usedChars / reviewedChars;
  return { ratio, reviewed, total: chunks.length };
}

function renderRatio() {
  const { ratio, reviewed, total } = computeRatio();
  const ratioText = ratio === null ? "no chunks reviewed yet" : `${(ratio * 100).toFixed(0)}% adopted`;
  document.getElementById("ratio-info").textContent = `${ratioText} (${reviewed} of ${total} reviewed)`;
}

function renderChunks() {
  const container = document.getElementById("chunks");
  container.innerHTML = "";
  chunks.forEach((chunk, index) => {
    const el = document.createElement("div");
    el.className = `chunk ${chunk.state}`;
    el.textContent = currentResponseText.slice(chunk.start, chunk.end);
    el.addEventListener("click", () => {
      const nextIndex = (STATES.indexOf(chunk.state) + 1) % STATES.length;
      chunks[index].state = STATES[nextIndex];
      renderChunks();
      renderRatio();
    });
    container.appendChild(el);
  });
  renderRatio();
}

async function loadTagsIntoChunks(recordId) {
  const response = await fetch(`/api/records/${recordId}/tags`);
  const tags = await response.json();
  const manualByRange = new Map(
    tags
      .filter((t) => t.source === "manual")
      .map((t) => [`${t.span_start}:${t.span_end}`, t.used]),
  );
  for (const chunk of chunks) {
    const key = `${chunk.start}:${chunk.end}`;
    if (manualByRange.has(key)) {
      chunk.state = manualByRange.get(key) ? "used" : "discarded";
    } else {
      chunk.state = "unmarked";
    }
  }
}

async function loadRecord(recordId) {
  currentRecordId = recordId;
  document.getElementById("save-status").textContent = "";

  const record = await (await fetch(`/api/records/${recordId}`)).json();
  currentResponseText = record.response_text || "";
  document.getElementById("prompt-text").textContent = record.prompt_text || "";
  const sessionLabel = record.session_name || record.session_id;
  document.getElementById("record-label").textContent =
    `Record #${record.id} — ${record.timestamp} — session ${sessionLabel}`;

  chunks = splitIntoChunks(currentResponseText).map(([start, end]) => ({
    start,
    end,
    state: "unmarked",
  }));

  await loadTagsIntoChunks(recordId);
  renderChunks();
}

function recordMatchesFilters(record, activeFilters, skipKey) {
  if (skipKey !== "id" && activeFilters.id && String(record.id) !== activeFilters.id) {
    return false;
  }
  if (skipKey !== "date" && activeFilters.date && record.date !== activeFilters.date) {
    return false;
  }
  if (
    skipKey !== "session_id" &&
    activeFilters.session_id &&
    record.session_id !== activeFilters.session_id
  ) {
    return false;
  }
  return true;
}

// Options for one filter are computed against the OTHER two filters only,
// so a dropdown never filters out its own currently selected value.
function buildFilterOptions(key) {
  const candidates = allRecords.filter((r) => recordMatchesFilters(r, filters, key));

  if (key === "id") {
    // id is an opaque UUID string, not orderable -- candidates is already
    // timestamp-DESC (from allRecords), so preserve that order rather than
    // sorting the ids themselves.
    const ids = [...new Set(candidates.map((r) => r.id))];
    return ids.map((id) => ({ value: id, label: `#${id.slice(0, 8)}…` }));
  }

  if (key === "date") {
    const dates = [...new Set(candidates.map((r) => r.date))].sort().reverse();
    return dates.map((date) => ({ value: date, label: date }));
  }

  // session_id: label with the session's AI-generated title when one
  // exists, ordered by most recent activity. Falls back to a truncated id
  // for sessions too short to have gotten a title.
  const latestBySession = new Map();
  const countBySession = new Map();
  const nameBySession = new Map();
  for (const r of candidates) {
    countBySession.set(r.session_id, (countBySession.get(r.session_id) || 0) + 1);
    const latest = latestBySession.get(r.session_id);
    if (!latest || r.timestamp > latest) {
      latestBySession.set(r.session_id, r.timestamp);
    }
    if (r.session_name && !nameBySession.has(r.session_id)) {
      nameBySession.set(r.session_id, r.session_name);
    }
  }
  const sessionIds = [...latestBySession.keys()].sort((a, b) =>
    latestBySession.get(b) > latestBySession.get(a) ? 1 : -1,
  );
  return sessionIds.map((sessionId) => {
    const name = nameBySession.get(sessionId) || `${sessionId.slice(0, 8)}…`;
    return { value: sessionId, label: `${name} (${countBySession.get(sessionId)})` };
  });
}

function renderFilterSelect(selectEl, key, options) {
  selectEl.innerHTML = "";
  const anyOption = document.createElement("option");
  anyOption.value = "";
  anyOption.textContent = "Any";
  selectEl.appendChild(anyOption);
  for (const { value, label } of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    selectEl.appendChild(option);
  }
  selectEl.value = filters[key];
}

// Changing one filter can make another's current value impossible (e.g. a
// previously picked date that doesn't exist in the newly picked session).
// Resolve all three to a mutually consistent state before any of them are
// rendered, so a stale value from one filter can't hide a still-valid
// option in another (each key's own options ignore its own filter, so this
// converges in at most 3 passes).
function stabilizeFilters() {
  for (let pass = 0; pass < 3; pass++) {
    let changed = false;
    for (const key of ["id", "date", "session_id"]) {
      if (!filters[key]) continue;
      const validValues = new Set(buildFilterOptions(key).map((o) => o.value));
      if (!validValues.has(filters[key])) {
        filters[key] = "";
        changed = true;
      }
    }
    if (!changed) break;
  }
}

function renderFilters() {
  stabilizeFilters();

  renderFilterSelect(document.getElementById("filter-id"), "id", buildFilterOptions("id"));
  renderFilterSelect(
    document.getElementById("filter-date"),
    "date",
    buildFilterOptions("date"),
  );
  renderFilterSelect(
    document.getElementById("filter-session"),
    "session_id",
    buildFilterOptions("session_id"),
  );

  const candidates = allRecords
    .filter((r) => recordMatchesFilters(r, filters, null))
    .sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));

  const statusEl = document.getElementById("filter-status");
  if (candidates.length === 0) {
    statusEl.textContent = "No matching records.";
    currentRecordId = null;
    chunks = [];
    document.getElementById("prompt-text").textContent = "";
    document.getElementById("record-label").textContent = "";
    renderChunks();
    return;
  }
  statusEl.textContent =
    candidates.length > 1 ? `${candidates.length} matching records — showing most recent.` : "";

  const target = candidates[0];
  if (target.id !== currentRecordId) {
    loadRecord(target.id);
  }
}

function onFilterChange(key, value) {
  filters[key] = value;
  renderFilters();
}

async function loadPicker() {
  allRecords = await (await fetch("/api/records/picker")).json();
  for (const record of allRecords) {
    record.date = record.timestamp.slice(0, 10);
  }

  document
    .getElementById("filter-id")
    .addEventListener("change", (e) => onFilterChange("id", e.target.value));
  document
    .getElementById("filter-date")
    .addEventListener("change", (e) => onFilterChange("date", e.target.value));
  document
    .getElementById("filter-session")
    .addEventListener("change", (e) => onFilterChange("session_id", e.target.value));

  renderFilters();
}

async function saveTags() {
  const reviewed = chunks.filter((c) => c.state !== "unmarked");
  const payload = reviewed.map((c) => ({
    span_start: c.start,
    span_end: c.end,
    used: c.state === "used",
  }));

  await fetch(`/api/records/${currentRecordId}/tags`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  document.getElementById("save-status").textContent = "Saved.";
}

document.getElementById("save-btn").addEventListener("click", saveTags);
loadPicker();
