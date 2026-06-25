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

// ── TODO(mobile session 接):把 mobile-api.js 的 dispatch 暴露出来 ─────────
// mobile-api.js 现在是浏览器 IIFE / fetch 拦截。要在 node 里调一个 /api 端点,需要:
//   1) 注入 makeBackend() 当它的 Store 底座(替 Capacitor Preferences)
//   2) 拿到它处理 /api 的入口函数(handleApi(method, path, body) 之类)
// 两种接法,挑一种:
//   A. 给 mobile-api.js 加一个 `export`(或 `globalThis.__mobileApiDispatch`)只在测试环境暴露 dispatch
//   B. 用 jsdom 起一个最小 DOM + fetch 拦截,真发 fetch("/api/...") 让 shim 接
// 接好后实现下面两个:
export async function loadShim(/* { backend } */) {
  throw new Error("TODO: 注入 backend + 加载 mobile-api.js dispatch(见上方两种接法)");
}
export async function callApi(/* shim, method, path, body */) {
  throw new Error("TODO: 经 shim dispatch 调一个 /api 端点,返 {status, json|text}");
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
