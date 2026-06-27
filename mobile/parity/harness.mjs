// harness.mjs — parity oracle 的 node 骨架。
// 给 mobile-api.js 一个内存版 Backend(Store 底座)+ 字节-diff,让 parity 断言在 node 里跑。
// ⚠ 骨架:`loadShim()` / `callApi()` 需 mobile session 接上 mobile-api.js 真正的 dispatch 入口(见 TODO)。
//
// 用法(接好后): node mobile/parity/run.mjs   或挂进 mobile 的 vitest。

import { readFileSync } from "node:fs";

// ── 内存 Backend:复刻 Capacitor Preferences / FS 的 get/set/remove/keys ──────
export function makeBackend(seed = {}) {
  const store = new Map(Object.entries(seed));
  return {
    async getText(k) { return store.has(k) ? store.get(k) : null; },
    async setText(k, v) { store.set(k, v); },
    async remove(k) { store.delete(k); },
    async keys() { return [...store.keys()]; },
    _dump() { return Object.fromEntries(store); },   // 测试里拿全量状态查副作用
  };
}

// ── 字节-diff:写操作的金标准(空串 = 字节一致)──────────────────────────
export function byteDiff(actual, expected) {
  if (actual === expected) return "";
  // 找第一处不同,给可读定位
  const n = Math.min(actual.length, expected.length);
  let i = 0;
  while (i < n && actual[i] === expected[i]) i++;
  return `byte-diff @${i}: got …${JSON.stringify(actual.slice(Math.max(0,i-20), i+20))}…`
       + ` want …${JSON.stringify(expected.slice(Math.max(0,i-20), i+20))}…`
       + ` (len got=${actual.length} want=${expected.length})`;
}

export function golden(name) {
  return readFileSync(new URL(`./golden/${name}`, import.meta.url), "utf-8");
}

// ── 接钩子(mobile session 已接):mobile-api.js IIFE 末尾挂 globalThis.__GW_TEST_API__
//   含 dispatch(method, path, body) → {status, body}
//        setBackend(tb) → 注入 harness makeBackend() 替 Capacitor Preferences
//        dumpBackend() → 全量 state inspect
//   loadShim() polyfill browser globals,eval mobile-api.js IIFE,挂 __GW_TEST_API__
export async function loadShim({ backend } = {}) {
  // Polyfill browser globals 让 mobile-api.js IIFE 能在 node 跑
  if (typeof globalThis.window === "undefined") {
    const fetchStub = function () { return Promise.reject(new Error("no real fetch")); };
    globalThis.window = { Capacitor: null, addEventListener: function () {}, removeEventListener: function () {}, fetch: fetchStub };
    globalThis.fetch = fetchStub;
    globalThis.realFetch = fetchStub;
    globalThis.document = {
      createElement: function () { return { style: {}, appendChild: function () {}, getContext: function () { return { fillStyle: "", fillRect: function () {}, fillText: function () {}, font: "", textBaseline: "" }; }, toDataURL: function () { return ""; } }; },
      body: { appendChild: function () {} },
      getElementById: function () { return null; },
    };
    globalThis.location = { origin: "http://test" };
    globalThis.localStorage = { getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} };
    globalThis.fetch = function () { return Promise.reject(new Error("no real fetch in node test")); };
    globalThis.realFetch = globalThis.fetch;
  }
  // 注入 backend(替 LocalBackend / CapacitorBackend)
  if (backend && globalThis.__GW_TEST_API__) {
    globalThis.__GW_TEST_API__.setBackend(backend);
  }
  // 首次:eval mobile-api.js 把 __GW_TEST_API__ 挂上
  if (!globalThis.__GW_TEST_API__) {
    const { readFileSync } = await import("node:fs");
    const text = readFileSync(new URL("../mobile-api.js", import.meta.url), "utf-8");
    // eslint-disable-next-line no-eval
    (0, eval)(text);
    if (backend) globalThis.__GW_TEST_API__.setBackend(backend);
  }
  return globalThis.__GW_TEST_API__;
}

export async function callApi(shim, method, path, body) {
  return await shim.dispatch(method, path, body);
}

// ── 例:daily-task check 的 parity 断言(B 类读 + A 类写一起)───────────────
// 桌面 oracle = tests/test_daily_tasks_routes.py::test_check_intake_increment_clamp_and_md_box
export async function example_check_clamp() {
  const backend = makeBackend({
    // seed:今天日记 md(顶部打卡段)+ meta(维生素D daily_dose=2)
    // 具体 key 用 mobile-api.js 的 Store 命名(readDailyTasksMd / setting/taskmeta/…)
  });
  const shim = await loadShim({ backend });
  // 1) check 满量 → today_intake==daily_dose,md [x]
  const r = await callApi(shim, "POST", "/api/daily-tasks/check",
                          { task_name: "维生素D", intake: 5 });
  console.assert(r.status === 200, "status");
  console.assert(r.json.today_intake === 2, "★clamp 到 daily_dose=2(桌面契约;mobile L184/227 硬编 1 = 这里红)");
  // 2) md 字节:跟 golden 比
  const md = await backend.getText("dailytasks/2026-06-25");   // 用真 Store key
  const d = byteDiff(md, golden("daily_tasks__check_clamp.md"));
  console.assert(d === "", d);
}

// run.mjs 里 import 这些 example_* 跑;红 = 该 row 未对齐。
