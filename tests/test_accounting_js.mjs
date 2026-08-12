// Headless verification of accounting.js's collapseFragments, the display-only
// workaround for stage 1's prompt-fragmentation (see CLAUDE.md's stage 4 notes).
// No package.json/test runner is set up in this repo for JS yet, so this uses
// Node's built-in test runner directly: `node tests/test_accounting_js.mjs`.
// Run manually (not wired into `pytest`), same status as tagging.js's
// chunk-splitter verification.

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { collapseFragments } = require("../static/js/accounting.js");

const baseFragment = {
  session_id: "sess1",
  prompt_text: "why am I getting a calibre not found",
  is_subagent: false,
  agent_type: null,
  agent_description: null,
  model: "claude-sonnet-5",
  timestamp: "2026-01-01T10:00:00Z",
  input_tokens: 10,
  cache_write_tokens: 0,
  cache_read_tokens: 100,
  output_tokens: 20,
  cost_usd: 0.01,
  response_text: "checking...",
};

test("collapses consecutive same-session same-prompt records into one group", () => {
  const records = [
    { ...baseFragment, response_text: "checking install" },
    { ...baseFragment, response_text: "found the binary" },
    { ...baseFragment, response_text: "trying a different path" },
    { ...baseFragment, response_text: "done, it works now" },
  ];

  const groups = collapseFragments(records);

  assert.equal(groups.length, 1);
  assert.equal(groups[0].fragments.length, 4);
  assert.equal(groups[0].totals.input_tokens, 40);
  assert.equal(groups[0].totals.output_tokens, 80);
  assert.equal(groups[0].totals.cache_read_tokens, 400);
  assert.ok(Math.abs(groups[0].totals.cost_usd - 0.04) < 1e-9);
});

test("does not collapse different prompts or different sessions", () => {
  const records = [
    { ...baseFragment, prompt_text: "prompt A" },
    { ...baseFragment, prompt_text: "prompt B" },
    { ...baseFragment, session_id: "sess2", prompt_text: "prompt B" },
  ];

  const groups = collapseFragments(records);

  assert.equal(groups.length, 3);
  assert.deepEqual(groups.map((g) => g.fragments.length), [1, 1, 1]);
});

test("re-collapses a repeated prompt_text if a different prompt interrupts it", () => {
  const records = [
    { ...baseFragment, prompt_text: "prompt A" },
    { ...baseFragment, prompt_text: "prompt B" },
    { ...baseFragment, prompt_text: "prompt A" },
  ];

  const groups = collapseFragments(records);

  assert.equal(groups.length, 3);
});

test("treats a null cost fragment as not contributing, keeping combined cost null only if all are null", () => {
  const records = [
    { ...baseFragment, cost_usd: null },
    { ...baseFragment, cost_usd: null },
  ];

  const groups = collapseFragments(records);

  assert.equal(groups[0].totals.cost_usd, null);
});
