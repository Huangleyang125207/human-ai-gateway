// thread.characterization.mjs — RECORD-LOCK 第一张 characterization 网
// 目标：shared/thread.js（998 行，全站耦合中心，零测试——清册 03 章卡片）。
// 参照 tests/parity/harness.mjs 的手法：polyfill browser globals + eval IIFE + 抓公开面。
//
// thread.js 是全闭包 IIFE，唯一导出面是 window.gateway.thread
// （addRef/open/close/toggle/isOpen/pushAI/history/clear/replaceHistory）。
// _actions→协议回放、Compact checkpoint 派生这两块逻辑完全埋在
// send() 内部（需要真 fetch + SSE stream 才能触发），公开面抓不到 ——
// 按任务要求的 fallback：这两处改成【文本级不变量锁】（源码子串断言），
// 其余能通过 window.gateway.thread 公开面 + localStorage 观测的，走可执行锁。
//
// RECORD-LOCK：锁的是现行为，不是"应该怎样"。下次改 thread.js 这些
// 断言炸了 = 行为漂了，回来看是不是故意的。

import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const SRC_PATH = new URL("../../shared/thread.js", import.meta.url);
const SRC = readFileSync(SRC_PATH, "utf-8");

// ── 极简 DOM stub（参照 harness.mjs 的 polyfill 手法，本文件自建，
//    因为 thread.js 直接引用裸 document/localStorage/fetch/setInterval，
//    不是 window.X 前缀，所以让 window === globalThis）──────────────
function makeEl(id) {
  const listeners = new Map();
  const el = {
    id,
    _children: [],
    style: {},
    dataset: {},
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    value: "",
    scrollTop: 0,
    scrollHeight: 0,
    disabled: false,
    addEventListener(type, fn) {
      const arr = listeners.get(type) || [];
      arr.push(fn);
      listeners.set(type, arr);
    },
    removeEventListener() {},
    dispatchEvent(event) {
      for (const fn of listeners.get(event.type) || []) fn(event);
      return true;
    },
    _emit(type, event = {}) {
      for (const fn of listeners.get(type) || []) fn({ type, ...event });
    },
    appendChild(child) { el._children.push(child); return child; },
    insertBefore(child) { el._children.push(child); return child; },
    setAttribute() {},
    removeChild() {},
    remove() {},
    focus() {},
    click() {},
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
    closest() { return null; },
    getContext() { return { fillStyle: "", fillRect() {}, fillText() {}, font: "", textBaseline: "" }; },
    toDataURL() { return ""; },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._innerHTML || ""; },
    set(v) { el._innerHTML = v; if (v === "") el._children = []; },
  });
  el.textContent = "";
  return el;
}

function makeLocalStorage(seed = {}) {
  const store = new Map(Object.entries(seed));
  return {
    getItem(k) { return store.has(k) ? store.get(k) : null; },
    setItem(k, v) { store.set(k, String(v)); },
    removeItem(k) { store.delete(k); },
    _dump() { return Object.fromEntries(store); },
  };
}

// 全局重挂一份新鲜环境，eval thread.js（间接 eval → 全局作用域执行，
// 但 thread.js 自身是 (function(){...})() IIFE，内部 const 不泄漏）。
// 每次调用都是一次"冷启动"，state.history 从传入的 localStorage 种子重建。
function freshLoad({ localStorageSeed = {}, fetchImpl } = {}) {
  const intervals = [];
  const ids = [
    "thread", "threadTab", "threadStream", "threadPending", "threadInput",
    "threadStatus", "threadClose", "threadToggleTop", "whisper", "threadHintLeft",
    "threadModel", "threadAttachBtn", "threadFileInput", "threadResizer",
  ];
  const registry = new Map(ids.map(id => [id, makeEl(id)]));

  const doc = {
    getElementById(id) { return registry.get(id) || null; },
    createElement() { return makeEl(); },
    body: makeEl("body"),
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
  };
  const ls = makeLocalStorage(localStorageSeed);
  const fetchStub = fetchImpl || (() => Promise.reject(new Error("no network in characterization test")));

  globalThis.document = doc;
  globalThis.localStorage = ls;
  globalThis.fetch = fetchStub;
  globalThis.location = { origin: "http://test" };
  // setInterval/clearInterval 必须 no-op：thread.js 顶层起了两个真计时器
  // （60s 跨午夜检测 + 3s server poll），不 stub 会让 node:test 进程挂起不退出。
  globalThis.setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
  globalThis.clearInterval = () => {};
  globalThis.setTimeout = (fn) => { void fn; return 0; }; // 不真跑延迟回调，测试不需要
  globalThis.clearTimeout = () => {};
  globalThis.requestAnimationFrame = (fn) => { void fn; return 0; };
  globalThis.window = globalThis; // thread.js 写 window.gateway.xxx，裸引用走 globalThis 其余部分
  globalThis.window.gateway = {}; // 每次冷启动重置命名空间，防止上一轮残留
  globalThis.addEventListener = () => {};
  globalThis.removeEventListener = () => {};

  // eslint-disable-next-line no-eval
  (0, eval)(SRC);

  return {
    api: globalThis.window.gateway.thread,
    localStorage: ls,
    els: registry,
    intervals,
  };
}

const THREAD_KEY = "gateway.thread.history.v1";
const MTIME_KEY = "gateway.thread.synced_mtime.v1";
const DIRTY_KEY = "gateway.thread.unsaved.v1";

// ============================================================
// A. 可执行锁 — 走 window.gateway.thread 公开面 + localStorage 观测
// ============================================================

test("addRef: 同 (kind,label) 第二次调用去重 — pendingBox 不新增 chip", () => {
  const { api, els } = freshLoad();
  api.addRef({ kind: "note", label: "L1", payload: {} });
  const afterFirst = els.get("threadPending")._children.length;
  api.addRef({ kind: "note", label: "L1", payload: {} }); // 重复
  const afterDup = els.get("threadPending")._children.length;
  assert.equal(afterFirst, 1, "第一次 addRef 应渲染 1 个 chip");
  assert.equal(afterDup, 1, "重复 (kind,label) 去重，chip 数不变");
});

test("addRef: 不同 label 各自新增 chip", () => {
  const { api, els } = freshLoad();
  api.addRef({ kind: "note", label: "L1", payload: {} });
  api.addRef({ kind: "note", label: "L2", payload: {} });
  assert.equal(els.get("threadPending")._children.length, 2);
});

test("loadHistory: localStorage 里是坏 JSON → 冷启动 history() 恢复为空数组，不抛异常", () => {
  const { api } = freshLoad({ localStorageSeed: { [THREAD_KEY]: "{not valid json" } });
  assert.deepEqual(api.history(), []);
});

test("loadHistory: localStorage 值不是数组（对象）→ 恢复为空数组", () => {
  const { api } = freshLoad({ localStorageSeed: { [THREAD_KEY]: JSON.stringify({ foo: "bar" }) } });
  assert.deepEqual(api.history(), []);
});

test("loadHistory: 超过 200 条的完整历史，冷启动不截断", () => {
  const seedArr = Array.from({ length: 250 }, (_, i) => ({ role: "user", content: String(i) }));
  const { api } = freshLoad({ localStorageSeed: { [THREAD_KEY]: JSON.stringify(seedArr) } });
  const h = api.history();
  assert.equal(h.length, 250, "History 是用户真源，不能由缓存窗口截断");
  assert.equal(h[0].content, "0");
  assert.equal(h[249].content, "249", "最后一条应是原数组最后一条");
});

test("loadHistory: 恰好 200 条不截断（边界不多不少）", () => {
  const seedArr = Array.from({ length: 200 }, (_, i) => ({ role: "user", content: String(i) }));
  const { api } = freshLoad({ localStorageSeed: { [THREAD_KEY]: JSON.stringify(seedArr) } });
  assert.equal(api.history().length, 200);
});

test("compact checkpoint 只派生模型上下文，不改写完整 History", () => {
  const seedArr = Array.from({ length: 12 }, (_, i) => ({
    role: i % 2 === 0 ? "user" : "assistant",
    content: String(i),
  }));
  const { api } = freshLoad({ localStorageSeed: { [THREAD_KEY]: JSON.stringify(seedArr) } });
  api.setCompactCheckpoint({ summary: "前情摘要", through: 6, at: "2026-08-19T00:00:00.000Z" });
  assert.equal(api.history().length, 12);
  assert.deepEqual(api.modelContext().map((m) => m.content), [
    "[系统整理摘要]\n前情摘要", "6", "7", "8", "9", "10", "11",
  ]);
});

test("send 请求的 history 排除本轮 user，避免 message 动态信封重复发送", async () => {
  const requests = [];
  const fetchImpl = (url, opts = {}) => {
    if (url === "/api/thread/history") return Promise.resolve({ json: async () => ({ history: [], mtime: 0 }) });
    if (url === "/api/config-status") return Promise.resolve({ json: async () => ({ ok: true, model: "test" }) });
    if (url === "/api/models") return Promise.resolve({ json: async () => ({ models: [] }) });
    if (url === "/api/thread/save") return Promise.resolve({ status: 200, ok: true, json: async () => ({ ok: true, mtime: 1 }) });
    if (url === "/api/chat") {
      requests.push(JSON.parse(opts.body));
      return Promise.resolve({ ok: false, status: 503 });
    }
    return Promise.reject(new Error("unexpected fetch " + url));
  };
  const { els } = freshLoad({ fetchImpl });
  await new Promise((resolve) => setImmediate(resolve));
  const input = els.get("threadInput");
  input.value = "只出现一次";
  input._emit("keydown", { key: "Enter", shiftKey: false, keyCode: 13, preventDefault() {} });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].message, "只出现一次");
  assert.equal(requests[0].history.some((m) => m.content === "只出现一次"), false);
});

test("saveHistory: 同一 tab 的连续保存串行推进 CAS 基线", async () => {
  const posts = [];
  let releaseFirst;
  const firstResponse = new Promise((resolve) => { releaseFirst = resolve; });
  const fetchImpl = (url, opts = {}) => {
    if (url === "/api/thread/history") return Promise.reject(new Error("offline boot"));
    if (url === "/api/config-status") return Promise.reject(new Error("offline config"));
    if (url === "/api/thread/save") {
      posts.push(JSON.parse(opts.body));
      if (posts.length === 1) return firstResponse;
      return Promise.resolve({ status: 200, ok: true, json: async () => ({ ok: true, mtime: 2 }) });
    }
    return Promise.reject(new Error("unexpected fetch " + url));
  };
  const { api } = freshLoad({ fetchImpl });
  api.pushAI("one");
  api.pushAI("two");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(posts.length, 1, "第二次保存必须等第一次完成");
  releaseFirst({ status: 200, ok: true, json: async () => ({ ok: true, mtime: 1 }) });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(posts.length, 2);
  assert.equal(posts[1].base_mtime, 1);
  assert.deepEqual(posts[1].history.map((m) => m.content), ["one", "two"]);
});

test("setCompactCheckpoint: server 失败时回滚，不伪报保存成功", async () => {
  const history = [
    { role: "user", content: "u1" },
    { role: "assistant", content: "a1" },
  ];
  const fetchImpl = (url) => {
    if (url === "/api/thread/history" || url === "/api/config-status" || url === "/api/models") {
      return Promise.reject(new Error("offline boot"));
    }
    if (url === "/api/thread/save") return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
    return Promise.reject(new Error("unexpected fetch " + url));
  };
  const { api } = freshLoad({ localStorageSeed: { [THREAD_KEY]: JSON.stringify(history) }, fetchImpl });
  const saved = await api.setCompactCheckpoint({ summary: "摘要", through: 1, at: "2026-08-19T00:00:00Z" });
  assert.equal(saved, false);
  assert.equal(api.compactCheckpoint(), null);
  assert.deepEqual(api.modelContext(), history);
});

test("CAS 409: 合并 server 与本地未同步消息，不用空重载覆盖本地", async () => {
  const base = { role: "user", content: "base", ts: "2026-08-19T00:00:00Z" };
  const remote = { role: "assistant", content: "remote", ts: "2026-08-19T00:00:01Z" };
  let historyReads = 0;
  const fetchImpl = (url) => {
    if (url === "/api/thread/history") {
      historyReads += 1;
      if (historyReads === 1) return Promise.reject(new Error("boot offline"));
      return Promise.resolve({ json: async () => ({ history: [base, remote], compact: null, mtime: 20 }) });
    }
    if (url === "/api/config-status" || url === "/api/models") return Promise.reject(new Error("offline ancillary"));
    if (url === "/api/thread/save") return Promise.resolve({ ok: false, status: 409, json: async () => ({}) });
    return Promise.reject(new Error("unexpected fetch " + url));
  };
  const { api, localStorage } = freshLoad({
    localStorageSeed: { [THREAD_KEY]: JSON.stringify([base]), [MTIME_KEY]: "10" },
    fetchImpl,
  });
  api.pushAI("local");
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const contents = api.history().map((m) => m.content);
  assert.deepEqual(contents, ["base", "remote", "local"]);
  assert.deepEqual(JSON.parse(localStorage.getItem(THREAD_KEY)).map((m) => m.content), contents);
});

test("网络恢复且 mtime 未变: 轮询自动重试 dirty History", async () => {
  const base = { role: "user", content: "base", ts: "2026-08-19T00:00:00Z" };
  const posts = [];
  const fetchImpl = (url, opts = {}) => {
    if (url === "/api/thread/history") {
      return Promise.resolve({ json: async () => ({ history: [base], compact: null, mtime: 10 }) });
    }
    if (url === "/api/config-status" || url === "/api/models") return Promise.reject(new Error("offline ancillary"));
    if (url === "/api/thread/save") {
      posts.push(JSON.parse(opts.body));
      if (posts.length === 1) return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true, mtime: 11 }) });
    }
    return Promise.reject(new Error("unexpected fetch " + url));
  };
  const { api, localStorage, intervals } = freshLoad({
    localStorageSeed: { [THREAD_KEY]: JSON.stringify([base]), [MTIME_KEY]: "10" },
    fetchImpl,
  });
  await new Promise((resolve) => setImmediate(resolve));
  api.pushAI("offline-local");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(posts.length, 1);
  assert.equal(localStorage.getItem(DIRTY_KEY), "1");
  const poll = intervals.find((item) => item.ms === 3000);
  assert.ok(poll, "应注册 server sync 轮询");
  await poll.fn();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(posts.length, 2);
  assert.deepEqual(posts[1].history.map((m) => m.content), ["base", "offline-local"]);
  assert.equal(localStorage.getItem(DIRTY_KEY), null);
});

test("history(): 返回的是拷贝，外部 push 不污染内部 state", () => {
  const { api } = freshLoad();
  const h1 = api.history();
  h1.push({ role: "user", content: "leaked" });
  const h2 = api.history();
  assert.equal(h2.length, 0, "外部对 history() 返回值的修改不应影响内部 state.history");
});

test("pushAI: 追加 assistant 消息并写入 localStorage（带 ts 字段）", () => {
  const { api, localStorage } = freshLoad();
  api.pushAI("hello from AI");
  const h = api.history();
  assert.equal(h.length, 1);
  assert.equal(h[0].role, "assistant");
  assert.equal(h[0].content, "hello from AI");
  assert.ok(typeof h[0].ts === "string" && h[0].ts.length > 0, "pushAI 消息应带 ts");
  const persisted = JSON.parse(localStorage.getItem(THREAD_KEY));
  assert.equal(persisted.length, 1);
  assert.equal(persisted[0].content, "hello from AI");
});

test("clear(): 清空 history() 并把空数组写回 localStorage", () => {
  const { api, localStorage } = freshLoad();
  api.pushAI("will be cleared");
  api.clear();
  assert.deepEqual(api.history(), []);
  assert.equal(localStorage.getItem(THREAD_KEY), "[]");
});

// ============================================================
// B. 文本级不变量锁 — send() 内部逻辑（_actions 展开 / checkpoint 派生）
//    完全埋在闭包深处，需要真 fetch+SSE 流才能触发，公开面抓不到。
//    按任务要求的 fallback：锁源码子串，改动这些行会让测试失败提醒复核。
// ============================================================

test("[文本锁] History 不得重新引入固定条数截断", () => {
  assert.doesNotMatch(SRC, /MAX_HISTORY|PERSIST_LIMIT/);
  assert.doesNotMatch(SRC, /state\.history\.slice\(\s*-\d+/);
});

test("[文本锁] send() 从 Compact checkpoint 派生模型上下文", () => {
  assert.match(
    SRC,
    /const recentMsgs = modelContextFromHistory\(state\.history\.slice\(0, -1\), state\.compactCheckpoint\);/,
    "模型上下文必须由 checkpoint 派生，不能切 History 头部"
  );
});

test("[thinking 迁移] 升级前 _actions 降级为系统摘要，不伪造缺 reasoning_content 的工具协议", () => {
  assert.doesNotMatch(SRC, /tool_calls: acts\.map\(a => \(\{/, "旧动作不能重建成缺 reasoning_content 的 thinking 工具轮");
  assert.doesNotMatch(SRC, /role: "tool",\s*\n\s*tool_call_id: a\.id,/, "旧 tool result 不能脱离原始 reasoning_content 回放");
  assert.match(SRC, /升级前历史摘要/, "旧动作需要保留为不可执行的系统摘要");
});

test("[契约] 已退役的模型自授权工具不得重新进入历史", () => {
  assert.match(SRC, /RETIRED_HISTORY_TOOLS\s*=\s*new Set\(\["load_tool_group"\]\)/);
  assert.match(SRC, /!RETIRED_HISTORY_TOOLS\.has\(a\.name\)/);
});

test("[缓存合同] 新轮以 model_messages 为真源，仅旧服务响应回退保存 _actions", () => {
  assert.match(
    SRC,
    /if \(turnActions\.length && !modelMessages\.length\) meta\._actions = turnActions\.slice\(\);/,
    "有 canonical transcript 时不得再重复持久化完整 args/result；旧服务响应仍须保留 _actions 回退"
  );
});

test("[缓存合同] canonical user/assistant 模型消息优先原样重放并持久化", () => {
  assert.match(SRC, /if \(m\.model_content\) \{\s*history\.push\(\{ role: "user", content: m\.model_content, _canonical: true \}\);/s);
  assert.match(SRC, /const replayMessages = Array\.isArray\(m\.model_messages\)/);
  assert.match(SRC, /history\.push\(\.\.\.replayMessages\.map\(x => \(\{ \.\.\.x, _canonical: true \}\)\)\);/);
  assert.match(SRC, /data\.type === "request_meta"/);
  assert.match(SRC, /userMsg\.model_content = data\.model_content/);
  assert.match(SRC, /meta\.model_messages = modelMessages/);
});

test("[思考展示] canonical 多轮思考默认以安全折叠区呈现", () => {
  assert.match(SRC, /protocolReasoning\.join\("\\n\\n"\)/, "多轮 reasoning_content 应按协议顺序汇总");
  assert.match(SRC, /document\.createElement\("details"\)/, "PC 应使用默认收起的原生 details");
  assert.match(SRC, /body\.textContent = text/, "思考正文必须走 textContent,不能作为 HTML 注入");
  assert.match(SRC, /appendReasoningDisclosure\(streamMsgEl, reasoning\)/, "新流式回复收尾时也应挂载思考折叠区");
  assert.match(SRC, /else if \(reasoning\) \{[\s\S]*content: "", \.\.\.meta/, "纯思考空答也应落入本地历史");
});
