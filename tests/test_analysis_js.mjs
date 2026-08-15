// Headless verification of analysis.js's collapseFragments -- a duplicate of
// accounting.js's function of the same name (see tests/test_accounting_js.mjs),
// kept in sync manually since this project has no shared-module mechanism
// between static JS files. Run manually: `node tests/test_analysis_js.mjs`
// (not wired into pytest, same status as test_accounting_js.mjs).

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { collapseFragments } = require("../static/js/analysis.js");

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
  ];

  const groups = collapseFragments(records);

  assert.equal(groups.length, 1);
  assert.equal(groups[0].fragments.length, 2);
  assert.ok(Math.abs(groups[0].totals.cost_usd - 0.02) < 1e-9);
});

test("does not collapse different prompts or different sessions", () => {
  const records = [
    { ...baseFragment, prompt_text: "prompt A" },
    { ...baseFragment, prompt_text: "prompt B" },
    { ...baseFragment, session_id: "sess2", prompt_text: "prompt B" },
  ];

  const groups = collapseFragments(records);

  assert.equal(groups.length, 3);
});

test("merging keys only on session_id + prompt_text, not is_subagent", () => {
  const records = [
    { ...baseFragment, prompt_text: "prompt B" },
    { ...baseFragment, prompt_text: "prompt B", is_subagent: true, agent_type: "Explore" },
  ];

  const groups = collapseFragments(records);

  assert.equal(groups.length, 1);
  assert.equal(groups[0].fragments.length, 2);
});

test("a session's collapsed group costs sum back to its own total cost", () => {
  const records = [
    { ...baseFragment, prompt_text: "prompt A", cost_usd: 5.5 },
    { ...baseFragment, prompt_text: "prompt A", cost_usd: 2.25 },
    { ...baseFragment, prompt_text: "prompt B", cost_usd: 10.0, is_subagent: true, agent_type: "Explore" },
  ];
  const sessionTotal = records.reduce((sum, r) => sum + r.cost_usd, 0);

  const groups = collapseFragments(records);
  const groupedTotal = groups.reduce((sum, g) => sum + g.totals.cost_usd, 0);

  assert.ok(Math.abs(groupedTotal - sessionTotal) < 1e-9);
});

test("treats a null cost fragment as not contributing, keeping combined cost null only if all are null", () => {
  const records = [
    { ...baseFragment, cost_usd: null },
    { ...baseFragment, cost_usd: null },
  ];

  const groups = collapseFragments(records);

  assert.equal(groups[0].totals.cost_usd, null);
});
