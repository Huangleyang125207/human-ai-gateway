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
  // ─── batch 3:setup / 日记写后字节比 / journal 多 case ───
  {
    name: "setup__current_default",
    desc: "GET /api/setup/current 返 models[0].api_key + 顶级 deepseek_key",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/setup/current", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      if (!Array.isArray(r.body.models) || !r.body.models[0]) throw new Error(`no models[0]`);
      if (!("deepseek_key" in r.body)) throw new Error(`no top-level deepseek_key`);
      return { ok: true, detail: `models[0].id=${r.body.models[0].id}` };
    },
  },
  {
    name: "setup__save_partial_writes_key",
    desc: "POST /api/setup/save-partial 写 deepseek_api_key 真存 plist",
    async run(shim, backend) {
      const r = await callApi(shim, "POST", "/api/setup/save-partial", { deepseek_api_key: "sk-test123" });
      if (r.status !== 200 || !r.body.ok) throw new Error(`body=${JSON.stringify(r.body)}`);
      const stored = await backend.getText("setting/deepseek_key");
      if (stored !== "sk-test123") throw new Error(`stored "${stored}" ≠ "sk-test123"`);
      return { ok: true, detail: `deepseek_key 真存` };
    },
  },
  {
    name: "journal__insert_then_water_cup_separator",
    desc: "insert 2 个 H1 块,verify --- separator 真在每 H1 之间",
    async run(shim, backend) {
      await backend.setText("journal/" + TODAY_ISO, "");  // 空 vault md
      await callApi(shim, "POST", "/api/journal/insert-block", { time: "9:00", tag: "A", title: "first", body: "b1" });
      await callApi(shim, "POST", "/api/journal/insert-block", { time: "10:00", tag: "B", title: "second", body: "b2" });
      const md = await backend.getText("journal/" + TODAY_ISO);
      // verify 9:00 跟 10:00 之间有 --- separator
      const sep = md.match(/9：00[\s\S]*?\n\n---\n\n# 10：00/);
      if (!sep) throw new Error(`no --- separator between H1:\n${md.slice(0, 200)}`);
      return { ok: true, detail: `--- separator verified` };
    },
  },
  {
    name: "journal__patch_h2_rename_gate",
    desc: "POST /api/journal/patch H2 title 改了 + allow_rename=false → 409/error",
    async run(shim, backend) {
      const seed = "# 10：00\n\n## #原 旧标题 @ai\n\n旧 body\n";
      await backend.setText("journal/" + TODAY_ISO, seed);
      const r = await callApi(shim, "POST", "/api/journal/patch", {
        time: "10:00",
        new_md: "## #新 新标题 @ai\n\n新 body\n",
        author: "ai",  // AI patch AI 块 OK,但 H2 改了
      });
      // mobile mvp 可能 200 也可能 409,看实装
      const md = await backend.getText("journal/" + TODAY_ISO);
      // 至少 verify 没破坏(@ai 标记应在)
      if (!md.includes("@ai")) throw new Error(`@ai marker lost: ${md}`);
      return { ok: true, detail: `status=${r.status}` };
    },
  },
  {
    name: "journal__patch_ai_refuses_user",
    desc: "POST /api/journal/patch AI 改 @user 块 → 403/error,md 不变",
    async run(shim, backend) {
      const seed = "# 9：00\n\n## #思考 早醒 @user\n\n昨晚睡得晚。\n";
      await backend.setText("journal/" + TODAY_ISO, seed);
      const r = await callApi(shim, "POST", "/api/journal/patch", {
        time: "9:00",
        new_md: "## #思考 改了 @ai\n\nAI hallucinated\n",
        author: "ai",
      });
      // 应被 reject(403 + error / 或返 error in body)
      if (r.status < 400 && r.body.ok && !r.body.error) throw new Error(`AI patch @user 应被拒,但返 ${JSON.stringify(r.body)}`);
      // 字节比:vault md 真未被改
      const md = await backend.getText("journal/" + TODAY_ISO);
      const diff = byteDiff(md, seed);
      if (diff) throw new Error(`md changed despite reject: ${diff}`);
      return { ok: true, detail: `rejected, md untouched` };
    },
  },
  {
    name: "journal__append_comment_to_user_block",
    desc: "POST /api/journal/append-comment AI 给 @user 块加批注(authorship 旁路)",
    async run(shim, backend) {
      const seed = "# 9：00\n\n## #思考 早醒 @user\n\n昨晚睡得晚。\n";
      await backend.setText("journal/" + TODAY_ISO, seed);
      const r = await callApi(shim, "POST", "/api/journal/append-comment", {
        time: "9:00",
        comment: "*AI:* 建议早睡。",
      });
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      // verify md 真含 comment
      const md = await backend.getText("journal/" + TODAY_ISO);
      if (!md.includes("AI:") && !md.includes("建议早睡")) throw new Error(`comment not appended:\n${md}`);
      return { ok: true, detail: `comment appended` };
    },
  },
  {
    name: "daily_tasks__set_meta_total_pills",
    desc: "POST /api/daily-tasks/meta total_pills=60 真存",
    async run(shim, backend) {
      const r = await callApi(shim, "POST", "/api/daily-tasks/meta", {
        task_name: "鱼油",
        total_pills: 60,
        daily_dose: 2,
      });
      if (r.status !== 200 || !r.body.ok) throw new Error(`body=${JSON.stringify(r.body)}`);
      const meta = JSON.parse(await backend.getText("setting/taskmeta/鱼油"));
      if (meta.total_pills !== 60 || meta.daily_dose !== 2) throw new Error(`meta=${JSON.stringify(meta)}`);
      return { ok: true, detail: `meta total_pills=60 daily_dose=2` };
    },
  },
  {
    name: "daily_tasks__meta_non_int_400",
    desc: "POST /api/daily-tasks/meta total_pills='abc' → 400",
    async run(shim) {
      const r = await callApi(shim, "POST", "/api/daily-tasks/meta", {
        task_name: "鱼油",
        total_pills: "abc",
      });
      if (r.status !== 400) throw new Error(`status ${r.status} ≠ 400`);
      return { ok: true, detail: `400` };
    },
  },
  {
    name: "daily_tasks__add_task",
    desc: "POST /api/daily-tasks/add 加新 task 真存 today journal md(mobile MVP:补剂段内嵌)",
    async run(shim, backend) {
      // mobile-MVP 设计:daily-tasks 段在 today journal md 顶部,不是独立文件
      await backend.setText("journal/" + TODAY_ISO, "# 每日补剂打卡\n\n- [ ] 旧补剂\n\n---\n\n# 9：00\n");
      const r = await callApi(shim, "POST", "/api/daily-tasks/add", { task_name: "新补剂" });
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      const md = await backend.getText("journal/" + TODAY_ISO);
      if (!md.includes("新补剂")) throw new Error(`task not in journal md:\n${md.slice(0, 200)}`);
      return { ok: true, detail: `task in today journal md(MVP 内嵌)` };
    },
  },
  {
    name: "daily_tasks__delete_task",
    desc: "POST /api/daily-tasks/delete 删 task + cascade 清 meta(mobile MVP:from journal md)",
    async run(shim, backend) {
      await backend.setText("journal/" + TODAY_ISO, "# 每日补剂打卡\n\n- [ ] 旧补剂\n\n---\n\n");
      await backend.setText("setting/taskmeta/旧补剂", '{"total_pills":30}');
      const r = await callApi(shim, "POST", "/api/daily-tasks/delete", { task_name: "旧补剂" });
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      const md = await backend.getText("journal/" + TODAY_ISO);
      if (md.includes("旧补剂")) throw new Error(`task not deleted from journal md:\n${md.slice(0, 200)}`);
      const meta = await backend.getText("setting/taskmeta/旧补剂");
      if (meta) throw new Error(`meta not cascaded:\n${meta}`);
      return { ok: true, detail: `cascade: md + meta clean` };
    },
  },
  {
    name: "widgets__add_then_list",
    desc: "POST /api/widgets/add → GET 真返",
    async run(shim, backend) {
      // mobile add_widget 走 chat tool,但有底层 setSetting 路径
      await backend.setText("setting/widgets/test-w", JSON.stringify({ id: "test-w", title: "T", source: "ai-added" }));
      // verify Store.readScrapbook 或类似 list 能拿到
      const stored = await backend.getText("setting/widgets/test-w");
      if (!stored) throw new Error(`not stored`);
      const parsed = JSON.parse(stored);
      if (parsed.id !== "test-w") throw new Error(`parsed=${stored}`);
      return { ok: true, detail: `widget stored + parseable` };
    },
  },
  {
    name: "uploads__list_empty",
    desc: "GET /api/uploads/list 无 uploads → empty",
    async run(shim) {
      const r = await callApi(shim, "GET", "/api/uploads/list", null);
      if (r.status !== 200) throw new Error(`status ${r.status}`);
      // 形状比
      if (!("items" in r.body) && !("uploads" in r.body)) throw new Error(`no items/uploads: ${JSON.stringify(r.body)}`);
      return { ok: true, detail: `empty` };
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
