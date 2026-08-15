// Headless verification of tagging.js's splitIntoChunks and computeRatio, the
// chunk-splitting and adoption-ratio logic described in CLAUDE.md's stage 4
// notes. No package.json/test runner is set up in this repo for JS yet, so
// this uses Node's built-in test runner directly:
// `node tests/test_tagging_js.mjs` (not wired into `pytest`, same status as
// test_accounting_js.mjs and test_analysis_js.mjs).

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { splitIntoChunks, computeRatio } = require("../static/js/tagging.js");

test("splits on blank lines when each block already fits within maxLen", () => {
  const text = "para one\n\npara two";

  const ranges = splitIntoChunks(text);

  assert.deepEqual(
    ranges.map(([start, end]) => text.slice(start, end)),
    ["para one", "para two"],
  );
});

test("falls back to single-newline splits once a blank-line block exceeds maxLen", () => {
  const text = "aaaa\nbbbb\ncccc\ndddd\n";

  const ranges = splitIntoChunks(text, 8);

  assert.deepEqual(
    ranges.map(([start, end]) => text.slice(start, end)),
    ["aaaa\n", "bbbb\n", "cccc\n", "dddd\n"],
  );
});

test("a single block under maxLen is not split further", () => {
  const text = "aaaa\nbbbb\ncccc\ndddd\n";

  const ranges = splitIntoChunks(text, 400);

  assert.equal(ranges.length, 1);
  assert.equal(text.slice(ranges[0][0], ranges[0][1]), text);
});

test("computeRatio is null with nothing reviewed", () => {
  const chunks = [
    { start: 0, end: 4, state: "unmarked" },
    { start: 4, end: 10, state: "unmarked" },
  ];

  const { ratio, reviewed, total } = computeRatio(chunks);

  assert.equal(ratio, null);
  assert.equal(reviewed, 0);
  assert.equal(total, 2);
});

test("computeRatio counts only reviewed chunks, in character space", () => {
  const chunks = [
    { start: 0, end: 10, state: "used" }, // 10 chars used
    { start: 10, end: 15, state: "discarded" }, // 5 chars discarded
    { start: 15, end: 30, state: "unmarked" }, // excluded entirely
  ];

  const { ratio, reviewed, total } = computeRatio(chunks);

  assert.ok(Math.abs(ratio - 10 / 15) < 1e-9);
  assert.equal(reviewed, 2);
  assert.equal(total, 3);
});
