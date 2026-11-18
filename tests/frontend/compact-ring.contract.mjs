// TEST PATTERN: contract — browser IIFE exposes pure compact decisions for parity tests
// USE WHEN: compact history counting / retention / failure guard changes
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../../shared/compact-ring.js", import.meta.url), "utf8");

function loadCompactCore() {
  const store = new Map();
  globalThis.window = globalThis;
  globalThis.window.gateway = {};
  globalThis.localStorage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => store.set(key, String(value)),
  };
  globalThis.document = {
    readyState: "loading",
    addEventListener() {},
    querySelector() { return null; },
  };
  globalThis.setInterval = () => 0;
  globalThis.addEventListener = () => {};
  (0, eval)(SRC);
  return globalThis.window.gateway.compactRing;
}

test("PC compact counts content, tool payloads and reasoning", () => {
  const core = loadCompactCore();
  const history = [{
    content: "abc",
    reasoning_content: "why",
    _actions: [{ args: { n: 1 }, result: { ok: true } }],
  }];
  assert.equal(
    core.historyChars(history),
    3 + 3 + JSON.stringify({ n: 1 }).length + JSON.stringify({ ok: true }).length,
  );
});

test("PC compact counts canonical model transcript once instead of duplicate _actions", () => {
  const core = loadCompactCore();
  const toolCalls = [{ id: "c1", function: { name: "x", arguments: "{\"n\":1}" } }];
  const history = [{
    content: "done",
    reasoning_content: "duplicate-reasoning",
    _actions: [{ args: { duplicate: true }, result: { duplicate: true } }],
    model_messages: [
      { role: "assistant", content: "", reasoning_content: "why", tool_calls: toolCalls },
      { role: "tool", content: "{\"ok\":true}", tool_call_id: "c1" },
      { role: "assistant", content: "done" },
    ],
  }];
  assert.equal(
    core.historyChars(history),
    "done".length + "why".length + JSON.stringify(toolCalls).length + "{\"ok\":true}".length,
  );
});

test("PC compact creates a checkpoint and leaves History untouched", () => {
  const core = loadCompactCore();
  const snapshot = [{ role: "assistant", content: "old summary" }];
  for (let i = 1; i <= 6; i++) {
    snapshot.push({ role: "user", content: `u${i}` });
    snapshot.push({ role: "assistant", content: `a${i}` });
  }
  const checkpoint = core.createCompactCheckpoint(snapshot, "summary", "2026-08-19T00:00:00.000Z");
  assert.deepEqual(checkpoint, { summary: "summary", through: 3, at: "2026-08-19T00:00:00.000Z" });
  assert.equal(snapshot.length, 13, "Compact 不得改写原数组");
});

test("PC compact returns null on empty summary so callers cannot truncate history", () => {
  const core = loadCompactCore();
  assert.equal(
    core.createCompactCheckpoint([{ role: "user", content: "keep me" }], ""),
    null,
  );
});
