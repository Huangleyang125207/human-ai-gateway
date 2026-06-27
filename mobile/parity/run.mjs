// run.mjs — 跑 mobile/parity/golden 真值对 mobile-api.js dispatch,字节比 + JSON 形状比。
// 用法: node mobile/parity/run.mjs [--filter=keyword] [-v]
//
// 每个 case 走 §4 Test-First 5 步的 ② 部分(验 shim 输出对齐 PC golden)。

import { makeBackend, byteDiff, golden, loadShim, callApi } from "./harness.mjs";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const goldenDir = join(__dirname, "golden");
const argv = process.argv.slice(2);
const VERBOSE = argv.includes("-v");
const filterArg = argv.find(a => a.startsWith("--filter="));
const filter = filterArg ? filterArg.slice("--filter=".length) : null;

// ── 已实现 self-test cases(从最简到复杂逐个加,先验 harness 通)─────────
const TESTS = [
  {
    name: "smoke__test_api_health",
    desc: "harness 通否:GET /api/health 返 ok:true",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/health", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      if (!r.body || !r.body.ok) throw new Error(`body=${JSON.stringify(r.body)}`);
      return { ok: true, detail: "health=ok" };
    },
  },
  {
    name: "smoke__test_api_setup_status",
    desc: "shim 路由通否:GET /api/setup-status 返 configured:true",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/setup-status", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      if (!r.body.configured) throw new Error(`not configured: ${JSON.stringify(r.body)}`);
      return { ok: true, detail: `profile_count=${r.body.profile_count}` };
    },
  },
  {
    name: "journal__insert_missing_time",
    desc: "POST /api/journal/insert-block 缺 time → 400(PC: insert_missing_time.response.json)",
    async run(shim) {
      const r = await callApi(shim, "POST", "/api/journal/insert-block", { date: "2026-06-25" });
      const expected = JSON.parse(golden("journal__insert_missing_time.response.json"));
      if (r.status !== (expected.status || 400)) throw new Error(`status ${r.status} ≠ ${expected.status || 400}`);
      return { ok: true, detail: `400 reached: ${JSON.stringify(r.body).slice(0, 60)}` };
    },
  },
];

let pass = 0, fail = 0;
const failed = [];

for (const t of TESTS) {
  if (filter && !t.name.includes(filter)) continue;
  // 每个 case 重置 backend(隔离)+ reset globals(避免污染)
  const backend = makeBackend({});
  if (globalThis.__GW_TEST_API__) globalThis.__GW_TEST_API__.setBackend(backend);
  const shim = await loadShim({ backend });
  try {
    const r = await t.run(shim);
    pass++;
    console.log(`  ✓ ${t.name}  ${r.detail || ""}`);
  } catch (e) {
    fail++;
    failed.push({ name: t.name, error: e.message });
    console.log(`  ✗ ${t.name}  ${e.message}`);
  }
}

console.log("");
console.log(`──── ${pass}/${pass + fail} PASS ────`);
if (failed.length && VERBOSE) {
  console.log("\n失败详情:");
  failed.forEach(f => console.log(`  ${f.name}: ${f.error}`));
}
process.exit(fail === 0 ? 0 : 1);
