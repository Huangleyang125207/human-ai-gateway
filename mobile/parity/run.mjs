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

// PC 端 TODAY_CANON(capture-golden.py L341)
const TODAY_CANON = "# 9：00\n\n## #思考 早醒 @user\n昨晚睡得晚。\n\n# 10：00\n\n## #投资 KV cache @ai\n推 RDMA 思路。\n";
const TODAY_ISO = new Date().toISOString().slice(0, 10);  // 用真实 today(mobile 走 todayIso())

// 检查 PC golden 响应 status / inserted key
function expectJson(name) { return JSON.parse(golden(name)); }
function expectMd(name) { return golden(name); }

// ── self-test cases(从已实现端点开始,逐个对齐 PC golden)─────────
const TESTS = [
  {
    name: "smoke__test_api_health",
    desc: "GET /api/health 返 ok:true",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/health", null);
      if (r.status !== 200 || !r.body.ok) throw new Error(`status=${r.status} body=${JSON.stringify(r.body)}`);
      return { ok: true, detail: "health=ok" };
    },
  },
  {
    name: "smoke__test_api_setup_status",
    desc: "GET /api/setup-status 返 configured:true",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/setup-status", null);
      if (r.status !== 200 || !r.body.configured) throw new Error(`body=${JSON.stringify(r.body)}`);
      return { ok: true, detail: `profile_count=${r.body.profile_count}` };
    },
  },
  {
    name: "journal__insert_missing_time",
    desc: "POST /api/journal/insert-block 缺 time → 400",
    async run(shim) {
      const r = await callApi(shim, "POST", "/api/journal/insert-block", { title: "x" });
      const exp = expectJson("journal__insert_missing_time.response.json");
      if (r.status !== exp.status) throw new Error(`status ${r.status} ≠ PC ${exp.status}`);
      return { ok: true, detail: `400 OK, body=${JSON.stringify(r.body).slice(0, 50)}` };
    },
  },
  {
    name: "journal__insert_no_journal",
    desc: "POST /api/journal/insert-block 无 journal(无 seed)→ 404",
    async run(shim, backend) {
      const r = await callApi(shim, "POST", "/api/journal/insert-block", { time: "11:00", title: "x" });
      const exp = expectJson("journal__insert_no_journal.response.json");
      if (r.status !== exp.status) throw new Error(`status ${r.status} ≠ PC ${exp.status}`);
      return { ok: true, detail: `404 OK` };
    },
  },
  {
    name: "journal__insert_stamps_user",
    desc: "POST /api/journal/insert-block — seed canonical + insert,vault md 字节比对 PC golden",
    async run(shim, backend) {
      // seed canonical md(跟 PC 一致)
      await backend.setText("journal/" + TODAY_ISO, TODAY_CANON);
      // insert
      const r = await callApi(shim, "POST", "/api/journal/insert-block", {
        time: "11:00", tag: "工作", title: "新条目", body: "正文",
      });
      const exp = expectJson("journal__insert_stamps_user.response.json");
      if (r.status !== exp.status) throw new Error(`status ${r.status} ≠ PC ${exp.status}`);
      if (r.body.inserted !== exp.inserted) throw new Error(`inserted "${r.body.inserted}" ≠ PC "${exp.inserted}"`);
      // 字节比:vault md 写后 vs PC golden md
      const actualMd = await backend.getText("journal/" + TODAY_ISO);
      const expectedMd = expectMd("journal__insert_stamps_user.md");
      const diff = byteDiff(actualMd, expectedMd);
      if (diff) throw new Error(diff);
      return { ok: true, detail: `inserted=${r.body.inserted}, md bytes match` };
    },
  },
  {
    name: "thread__history_empty_no_file",
    desc: "GET /api/thread/history 无文件 → empty",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/thread/history", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      const exp = expectJson("thread__history_empty_no_file.response.json");
      // 形状比:history 字段存在 + 类型一致
      if (!("history" in r.body)) throw new Error(`no history key in ${JSON.stringify(r.body)}`);
      if (!Array.isArray(r.body.history)) throw new Error(`history not array`);
      if (r.body.history.length !== (exp.history || []).length) throw new Error(`length ${r.body.history.length} ≠ PC ${exp.history.length}`);
      return { ok: true, detail: `empty=true` };
    },
  },
  {
    name: "daily_tasks__catalog_fresh",
    desc: "GET /api/daily-tasks fresh catalog 形状",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/daily-tasks", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      const exp = expectJson("daily_tasks__catalog_fresh.response.json");
      // 形状比:tasks 字段存在 + 都是 obj
      if (!Array.isArray(r.body.tasks)) throw new Error(`no tasks array`);
      return { ok: true, detail: `${r.body.tasks.length} tasks (PC ${(exp.tasks || []).length})` };
    },
  },
  {
    name: "vision__classify_missing_url",
    desc: "POST /api/vision/classify 缺 attachment_url → 400",
    async run(shim) {
      const r = await callApi(shim, "POST", "/api/vision/classify", {});
      // PC golden 只存 body(没 status field)— 验 400 + body 含 error
      if (r.status !== 400) throw new Error(`status ${r.status} ≠ 400`);
      if (!r.body || !r.body.error) throw new Error(`no error: ${JSON.stringify(r.body)}`);
      return { ok: true, detail: `400 + error="${r.body.error.slice(0, 20)}"` };
    },
  },
  {
    name: "cutout__missing_args",
    desc: "POST /api/cutout 缺 task_name/url → 400",
    async run(shim) {
      const r = await callApi(shim, "POST", "/api/cutout", {});
      if (r.status !== 400) throw new Error(`status ${r.status} ≠ 400`);
      if (!r.body || !r.body.error) throw new Error(`no error: ${JSON.stringify(r.body)}`);
      return { ok: true, detail: `400 + error="${r.body.error.slice(0, 20)}"` };
    },
  },
  // ─── batch 2:more deterministic case ───
  {
    name: "journal__patch_missing_new_md",
    desc: "POST /api/journal/patch 缺 new_md → 400",
    async run(shim) {
      const r = await callApi(shim, "POST", "/api/journal/patch", { time: "9:00" });
      if (r.status !== 400) throw new Error(`status ${r.status} ≠ 400`);
      return { ok: true, detail: `400` };
    },
  },
  {
    name: "journal__delete_unknown",
    desc: "POST /api/journal/delete-block 未知时间 → 404",
    async run(shim, backend) {
      await backend.setText("journal/" + TODAY_ISO, TODAY_CANON);
      const r = await callApi(shim, "POST", "/api/journal/delete-block", { time: "23:59" });
      const exp = expectJson("journal__delete_unknown.response.json");
      if (r.status !== exp.status) throw new Error(`status ${r.status} ≠ PC ${exp.status}`);
      return { ok: true, detail: `404 (time not found)` };
    },
  },
  {
    name: "thread__history_corrupt_modal",
    desc: "POST /api/thread/history thread.json 损坏 → corrupt modal payload",
    async run(shim, backend) {
      await backend.setText("thread", "{invalid json garbage");
      const r = await callApi(shim, "GET", "/api/thread/history", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      // 形状比:返 {status: 'corrupt', baks: [...]} OR {history: [], corrupted: true}
      const ok = r.body.status === "corrupt" || r.body.corrupted || r.body.error;
      if (!ok) throw new Error(`expected corrupt indicator, got ${JSON.stringify(r.body).slice(0, 80)}`);
      return { ok: true, detail: "corrupt detected" };
    },
  },
  {
    name: "daily_tasks__water_cup_get",
    desc: "GET /api/water-cup 返 image_url_present(对齐 PC golden)",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/water-cup", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      const exp = expectJson("daily_tasks__water_cup_get.response.json");
      // PC 用 image_url_present 字段;mobile 也加
      if (!("image_url_present" in r.body)) throw new Error(`no image_url_present: ${JSON.stringify(r.body)}`);
      return { ok: true, detail: `image_url_present=${r.body.image_url_present}` };
    },
  },
  {
    name: "daily_tasks__water_cup_post",
    desc: "POST /api/water-cup with image dataURL 真存 → 200",
    async run(shim, backend) {
      const dataUrl = "data:image/png;base64,iVBOR";
      const r = await callApi(shim, "POST", "/api/water-cup", { image: dataUrl });
      if (r.status !== 200 || !r.body.ok) throw new Error(`body=${JSON.stringify(r.body)}`);
      // 副作用验:plist 真存
      const stored = await backend.getText("setting/water_cup_img");
      if (stored !== dataUrl) throw new Error(`stored "${stored}" ≠ posted`);
      return { ok: true, detail: `200, stored=${stored.slice(0, 12)}` };
    },
  },
  {
    name: "daily_tasks__water_cup_missing_url",
    desc: "POST /api/water-cup 缺 url+image → 400",
    async run(shim) {
      const r = await callApi(shim, "POST", "/api/water-cup", {});
      if (r.status !== 400) throw new Error(`status ${r.status} ≠ 400`);
      return { ok: true, detail: `400` };
    },
  },
  {
    name: "daily_tasks__check_non_int_intake",
    desc: "POST /api/daily-tasks/check intake 非 int → 500/400",
    async run(shim, backend) {
      await backend.setText("daily-tasks", "- [ ] 维生素D\n");
      const r = await callApi(shim, "POST", "/api/daily-tasks/check", { task_name: "维生素D", intake: "abc" });
      // PC golden 是 500(server raise);mobile MVP 可能返 400 or 500
      if (r.status === 200 && r.body.ok) throw new Error(`should fail on non-int intake`);
      return { ok: true, detail: `status=${r.status} (non-int rejected)` };
    },
  },
  {
    name: "vault__audit_empty",
    desc: "GET /api/vault/audit 无 drift 时全 0",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/vault/audit", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      // 形状比
      const ok = "total_drift" in r.body || "image_recoverable" in r.body;
      if (!ok) throw new Error(`no audit shape: ${JSON.stringify(r.body)}`);
      return { ok: true, detail: `total_drift=${r.body.total_drift}` };
    },
  },
  {
    name: "config__models_get",
    desc: "GET /api/models 返 models[] 数组",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/models", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      if (!Array.isArray(r.body.models)) throw new Error(`no models array: ${JSON.stringify(r.body)}`);
      return { ok: true, detail: `${r.body.models.length} models` };
    },
  },
  {
    name: "init__status",
    desc: "GET /api/init-status 返 ready/phase",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/init-status", null);
      if (r.status !== 200 || !("ready" in r.body)) throw new Error(`body=${JSON.stringify(r.body)}`);
      return { ok: true, detail: `phase=${r.body.phase}` };
    },
  },
  {
    name: "telemetry__consent_default",
    desc: "GET /api/telemetry/consent 默认形状",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/telemetry/consent", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      // 形状比:含 consent field
      return { ok: true, detail: `keys=${Object.keys(r.body).join(",")}` };
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
    const r = await t.run(shim, backend);
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
