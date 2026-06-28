# 迁移文件总清单 · gateway 桌面 → iOS 移动端

> 一处看全"迁移用到/产出的所有文件"。按**心智模型分层**列,每条带一句话作用 + 状态。
> 心智模型(自上而下,读文件先认这 4 层 + 2 源):
>
> ```
> ① 范式/spec 文档   —— 怎么迁(方法论 + case 清单 + 进度台账)
> ② 契约层 golden    —— 数据底座(callApi→字节,node 跑,CI 兜底)
> ③ 交互层 runner    —— 真 OS-level tap(fb-idb,simulator 真点)
> ④ 源:PC 契约(真相)  ←迁移自→  mobile 端(shim + UI + 原生)
> ```
>
> 新人路线:`TEST_FIRST_MIGRATION.md`(范式)→ `PARITY_LEDGER.md`(进度)→ `INTERACTION_TEST_CASES.md`(原子 case)→ `parity/interaction/run-cases.md`(怎么真跑)。

---

## ① 范式 / spec 文档(`mobile/*.md`)

**核心(必读)**
| 文件 | 作用 |
|---|---|
| `TEST_FIRST_MIGRATION.md` | ★范式总纲:两层模型(交互层=本体 / golden=底座)+ 五步工作流 + 三层测试平衡。先读这个 |
| `MIGRATION_PARITY_GUIDE.md` | parity 方法论:桌面 characterization 测试当移动 oracle;有用5类/没用4类 |
| `INTERACTION_TEST_CASES.md` | 64 条**原子**交互 case(真 click→效果),按簇 + ★Cannot-break + 执行 checklist |
| `INTERACTION_E2E_PHOTO.md` | **E2E 招牌场景**:拖药瓶/水杯真照片 → AI 识别 → 抠图 → 打卡图标(跨簇链 + 真 LLM)|
| `PARITY_LEDGER.md` | ★**进度台账**:端点×oracle×状态×sha;契约层 78/78 真绿、交互层真 tap **持续活**(非 64/64 收官,见其顶部诚实校正) |

**进度 / 计划 / 报告**
| 文件 | 作用 |
|---|---|
| `MIGRATION.md` | ★**唯一权威入口**:现状 + 文档地图 + 已知洞;凡冲突以它 + `PARITY_LEDGER` 为准 |
| `PARITY_LOOP.md` | parity loop 提示词模板(收敛 + 维护双 loop) |
| `PHASE_2_RUNBOOK.md` | iOS 真机操作手册(Pod/签名/权限/ATS/HEIC) |
| `SESSION_HANDOFF.md` · `TEST_WORKFLOW.md` | session 测试钥匙 + 模拟器接续 / plist 测试工作流 |
| `OCR_NATIVE_PLAN.md` | 原生 OCR(iOS Vision / Android MLKit)方案 |
| `INTERACTION_E2E_DIARY.md` | E2E 日记招牌场景(5 条 E2E 用户旅程) |
| `MOBILE_DESIGN_BRIEF.md` | 移动视觉 brief |
| `MIGRATION_FILES.md` | (本文件)文件总清单 |

> 本轮 git rm(salvage 已迁入 `MIGRATION.md` §5):~~`MIGRATION_AUDIT_REPORT` · `PM_REPORT` · `ROADMAP` · `RUNBOOK`~~

---

## ② 契约层 golden + harness(`mobile/parity/`)

| 文件 | 作用 | 状态 |
|---|---|---|
| `run.mjs` | node 契约层 runner(callApi + golden 字节比),CI 兜底 | ✅ 78/78 |
| `harness.mjs` | `loadShim`/`callApi`:把 mobile-api.js 在 node 里 hijack | ✅ 已接通 |
| `capture-golden.py` | 跑桌面 canonical 端点 → dump golden 字节(隔离 fixture,不碰真 vault)| ✅ 产 109 golden 文件 |
| `golden/` | **109 份"标准答案"字节**(response/md/副作用),交互最终须复刻它 | ✅ |
| `check-fe-be.sh` | grep fe↔be 死引用 / 未 shim / 覆盖落差 | ✅ |
| `README.md` | oracle 三类说明(字节比 / 形状比 / grep)| ✅ |

---

## ③ 交互层 runner — 真 OS-level tap(`mobile/parity/interaction/`)

| 文件 | 作用 | 状态 |
|---|---|---|
| `cases.mjs` | 64 条交互 case 机读索引(name/seed/tap/expect/golden/cannotBreak)| ✅ |
| `run-cases.md` | ★fb-idb 真 tap 协议:seed→tap→snapshot_ui→plist→screenshot→比 golden(含 webview fake-green 教训)| ✅ |
| `idb_runner.sh` | fb-idb OS-level touch 注入驱动(现行真 tap 执行器)| ⚠ 真 tap,但 `all` 仅 01-20、过半弱断言(见 MIGRATION §1) |
| `run-in-app.js` | webview SyntheticTap self-test(`build-web.sh` 打包进 bundle)| ⚠ **非 parity oracle**(fake-green 本体);真 tap 走 idb_runner |
| `screenshots/` | 真机截图证据 | ✅ |

---

## ④a PC 契约源(预期效果的真相 = kernel + route 模块)

| 文件 | 作用 |
|---|---|
| `server.py`(5243 行)| kernel:共享写盘/配置/LLM/authorship/tool 引擎/io-map(危险 helper 都留这)|
| `image_routes.py` | /api/attachments* + /api/cutout + /api/vision/classify |
| `daily_tasks_routes.py` | /api/daily-tasks/* + /api/water-cup |
| `journal_routes.py` | /api/journal/* + /api/tag-aggregate/* |
| `thread_routes.py` | /api/thread/*(history/save/restore,CAS + corrupt modal)|
| `chat_routes.py` | /api/chat(SSE + tool loop + vision-pre-router 注入)|
| `board_routes.py` | /api/eval/*(留言板;past_boards 跨夜注入)|
| `migration_routes.py` | MD/schema 迁移编排(横幅状态机 + 启动 hook)|
| `pulse_routes.py` · `setup_routes.py` | PULSE / 钥匙配置 |
| `migration_plan.py` | schema 迁移 engine(被 migration_routes 调)|

## ④b PC oracle 测试(`tests/` — parity 对照源)

**parity 核心 oracle**(每个对应一组 golden + 移动 case):
`test_journal_routes` · `test_authorship` · `test_patch_h2_rename` · `test_insert_block_body` · `test_daily_tasks_routes` · `test_day_one_and_water_cup` · `test_thread_routes` · `test_thread_cas` · `test_image_routes` · `test_attachment_dedup` · `test_chat_routes` · `test_claim_audit` · `test_board_routes` · `test_tool_specs` · `test_migration_glue` · `test_cutout_local_prewarm` · `test_ocr_local` · `test_task_icon_normalize` · `test_port_url_discipline`

**非 parity(desktop-infra,不进移动对照)**:`pulse_*` · `consent` · `heartbeat` · `history_exporter` · `background_init` · `outcome_tracker` · `vault_git` · `updater_report` · `silent_failure_probe` · `web_search_resilience` · `migration`

## ④c mobile 端代码(`mobile/`)

| 文件 | 作用 | 状态 |
|---|---|---|
| `mobile-api.js`(3184 行)| ★**shim**:fetch 层 hijack,所有端点的 JS 重实现 + `__GW_TEST_API__` | ✅ 主力 |
| `m/index.html` + `m/gw-app.js` | 移动前端入口 + 装配 | ✅ |
| `m/gw-journal.js` · `gw-chat.js` · `gw-widgets.js` | 单日页/对话流/打卡水杯 widget | ⚠️ 首尾 UI 有洞(见 E2E)|
| `m/gw-real-bridge.js` · `gw-mock.js` | 真后端桥 / mock | ✅ |
| `m/tokens.css` · `components.css` · `copy-allow.css` · `manifest.json` | 设计 token / 组件 / PWA | ✅ |
| `plugins/cutout/...CutoutPlugin.swift` | iOS Vision 端侧抠图 native plugin | ✅ |
| `plugins/native-ocr/...NativeOcrPlugin.swift` + `.../NativeOcrPlugin.kt` | iOS Vision OCR / Android MLKit | ✅ |
| `app/`(Capacitor shell)| ios/android 工程壳(`app/ios/DerivedData`、`node_modules` 是构建产物,非源)| — |

---

## ⑤ fixtures + 外围

| 项 | 作用 | 状态 |
|---|---|---|
| `mobile/parity/fixtures/photos/` | E2E 真照片(yuyou / ashwa / cup / nonpill)| ★**待建**(INTERACTION_E2E_PHOTO §2 标的)|
| `~/.claude/scripts/precompact-session-index.py` + `settings.json` PreCompact hook | compact 前自动产"改动报告"(全局 config,非 gateway 仓)| ✅ |
| 迁移 session 提示词 | 冷启动接手提示词(已在对话给过;可存 `mobile/MIGRATION_SESSION_PROMPT.md`)| 未落盘 |

---

> 维护:新增迁移文件 → 归到对应层 → 加一行。判断归层:讲"怎么迁"=①;golden/harness=②;真 tap=③;
> PC 端点/测试=④a/b;mobile 实现=④c。**层错位是迁移混乱的根源**(契约/交互别混,见 TEST_FIRST §0)。
