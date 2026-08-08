const MAX_CHUNK_LEN = 400;
const STATES = ["unmarked", "used", "discarded"];

let currentRecordId = null;
let currentResponseText = "";
// chunk = { start, end, state }
let chunks = [];

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

  chunks = splitIntoChunks(currentResponseText).map(([start, end]) => ({
    start,
    end,
    state: "unmarked",
  }));

  await loadTagsIntoChunks(recordId);
  renderChunks();
}

async function loadPicker() {
  const records = await (
    await fetch("/api/records?has_response_text=true&limit=100")
  ).json();

  const picker = document.getElementById("record-picker");
  picker.innerHTML = "";
  for (const record of records) {
    const option = document.createElement("option");
    option.value = record.id;
    const preview = (record.prompt_text || "").slice(0, 60).replace(/\s+/g, " ");
    option.textContent = `#${record.id} — ${record.timestamp} — ${preview}`;
    picker.appendChild(option);
  }
  picker.addEventListener("change", () => loadRecord(Number(picker.value)));

  if (records.length > 0) {
    await loadRecord(records[0].id);
  }
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
