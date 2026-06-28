# 移动端迁移 · 权威入口

> 这是 gateway 桌面 → 移动端迁移的**唯一权威导航**。先读这份，再按下面的路线深入。
> 凡本文与其他 `mobile/*.md` 冲突，以本文 + `PARITY_LEDGER.md` 为准。
> 核实日期：2026-06-28（行数/版本/文件数均本机真扫，非凭注释）。

---

## 1. 一句话 + 现状

**迁移是什么**：桌面 `server.py`（5243 行 kernel + 9 个 `*_routes.py`）是产品的 canonical 真相；移动端不搬代码，搬**契约** —— 用 `mobile/mobile-api.js`（3184 行的本地"假后端"，IIFE 劫持 `fetch`/`EventSource`）字节级复刻桌面行为，`server.py` 一行不改。信条：**代码搬不动，契约搬得动**。

**到哪了（核实过的真数字）**：

| 维度 | 数字 | 注意 |
|---|---|---|
| 桌面版本 | `APP_VERSION = "0.1.39"`（server.py L514） | PULSE/CLAUDE.md 记的 9499/6271 行已过期，现 **5243 行** |
| golden 快照 | **109 文件**（`mobile/parity/golden/`，capture-golden.py 产） | 跨文档计数不一：TEST_FIRST §3.2 说 57 case、LEDGER 顶部说 84 case —— 文件数 109 是确数，case 数以 ledger 为准 |
| 契约层 | **78/78 PASS**（`node mobile/parity/run.mjs`） | 无 LLM、无 simulator，~78 个 case；run.mjs 跑法段残留"42 case"是旧数 |
| 交互层 | **64/64 真 tap**（`mobile/parity/interaction/`） | ⚠ 见下方诚实警示 |
| 招牌 E2E | 真照片→真 vision→端侧抠图→打卡 | 链路暴露**首尾 UI 洞**（入口/出口两头空），不进 CI |
| 平台 | **iOS 真集成；Android 源码预置但未 `cap add`** | cutout + native-ocr 的 iOS Swift 已进 Podfile.lock |

**⚠ 关于"64/64 真 tap"的诚实定义**（最重要，对外说明必须如实写）：
- 当前交互层执行器是 `idb_runner.sh`，走 fb-idb（SimulatorBridge IPC）注入物理 touch —— 这是**真 OS-level tap**。
- 但它**不是干净的 64/64 四断言全绿**：`all` 入口实际只 loop `01-20`；过半 case 仅 screenshot 单断言恒判 PASS（含已知 `pointer` 不接的 CSS bug 仍判 PASS）。协议 `run-cases.md` 要求的"snapshot_ui + plist + md + golden 四断言齐"严格度 **>** 执行器实际强度。
- 更早的 `run-in-app.js`（webview 内 SyntheticTap）报的 64/64 是 **fake-green**，`run-cases.md` 2026-06-28 修订已点名判死 —— 它漏掉两个真 bug（self-test 擦用户 deepseek_key `f44ca3c`、Capacitor Preferences group 配错 `d98bd74`）。
- 结论：契约层 78/78 是干净可信的回归基准；交互层"真逐条四断言全绿"仍是**持续活**，不是已收官。对外别照搬"64/64 真 tap PASS"。

---

## 2. 怎么上手（渐进式披露路线）

新人**只读这 5 份 + 本文**，其余 md 大多过期（见 §4）：

1. **本文（MIGRATION.md）** —— 现状 + 文档地图 + 避坑。
2. **`TEST_FIRST_MIGRATION.md`** —— 方法论总纲：两层模型（交互层撑在契约层 golden 上）+ Test-First 五步流程。**信条仍准**。
3. **`PARITY_LEDGER.md`** —— 单一进度真相，逐行带桌面 sha。"做到哪了"看这份。
4. **`INTERACTION_TEST_CASES.md`** —— 64 条交互 case 的人读规格（含真实 `[UI待建]`/`[golden 缺]` 标记）。"要验什么"看这份。
5. **`MIGRATION_FILES.md`** —— 文件归层导航（但其"真 tap ✅"措辞偏乐观，回到 §1 的诚实定义校正）。

深入子领域时：契约 harness 看 `mobile/parity/README.md`；iOS 真机发版看 `PHASE_2_RUNBOOK.md`；端侧 OCR 实装看 `OCR_NATIVE_PLAN.md`；设计 north-star 看 `MOBILE_DESIGN_BRIEF.md`。

---

## 3. 架构 4 层 + 2 源

### 范式层（方法论 spec）
| 文件 | 一句话 |
|---|---|
| `TEST_FIRST_MIGRATION.md` | 两层模型 + golden 实例机制 + Test-First 五步；代码搬不动契约搬得动。 |
| `INTERACTION_TEST_CASES.md` | 64 条原子交互 case 的人读规格（用户故事/seed/真 tap/三可观测/golden 底座/负例）。 |

### 契约层（golden 字节 oracle —— `mobile/parity/`）
| 文件 | 一句话 |
|---|---|
| `parity/capture-golden.py` | golden **唯一权威生产源**：fastapi TestClient 跑桌面真端点 dump canonical 输出；隔离 tempfile home + freeze now 2026-06-26。 |
| `parity/golden/`（109 文件） | 桌面 canonical 快照库，命名 `<feature>__<case>.<kind>`（8 簇：daily_tasks/journal/thread/attachments/cutout/vault/vision/get_attachment）。 |
| `parity/run.mjs` | 契约层主 runner，~78 case 跑 shim dispatch 对 golden 做字节/形状比；**78/78 PASS**。 |
| `parity/harness.mjs` | 运行时底座：内存版 Backend + `byteDiff` + `loadShim`（eval mobile-api.js）+ `callApi`。 |
| `parity/check-fe-be.sh` | C 类 grep oracle：FE↔BE↔PC 三维落差（死按钮/未迁缺口/命名漂移）。 |

### 交互层（真 OS tap —— `mobile/parity/interaction/`）
| 文件 | 一句话 |
|---|---|
| `interaction/cases.mjs` | 64 条 case 机器可读规格真源；`STATS={total:64,cannotBreak:20,uiBuilt:35,uiPending:29}` 自洽。 |
| `interaction/run-cases.md` | **现行 SOP**：2026-06-28 修订宣判 SyntheticTap fake-green，mandate fb-idb 真 tap 四断言链。 |
| `interaction/idb_runner.sh` | **现行落地执行器**（fb-idb 真 tap）；但 `all` 只跑 01-20、过半 case 弱断言（见 §1 警示）。 |

### PC 源（契约真相 —— `gateway/*.py`）
| 文件 | 一句话 |
|---|---|
| `server.py` | 权威 kernel（5243 行）：原子写/authorship 边界/LLM core/TOOL_IMPL 工具引擎/io-map/vault_git + 34 个 `@app` 端点 + include 9 router。补卡窗口/clamp 真逻辑在此。 |
| `daily_tasks_routes.py` | 8 端点；**移动 parity 价值最高**：揭穿 shim 的 is_writable/daily_dose/delete 级联三契约。 |
| `journal_routes.py` | 10 端点；危险 authorship helper（_patch_block/_check_author）故意留 server，路由是 thin handler。 |
| `chat_routes.py` | 2 端点；**PC chat 确有完整 tool loop（MAX_ROUNDS=10）** + DSML 泄漏闸（U+FF5C）+ claim 审计。 |
| `thread_routes.py` | 3 端点；Cannot-break = 损坏返 corrupt+baks（5.17）+ save CAS 409（5.26）。 |
| `image_routes.py` | 7 端点；attachments/vision/cutout 的 thin handler（抠图逻辑在 cutout_local.py）。 |
| `board_routes.py` | 4 端点；**desktop-only 不迁**（留言板/21:30 仪式，past_boards 跨夜注入）。 |
| `setup_routes.py` | 10 端点；config 向导（含 gemini/baidu 可选 provider 探针）。 |
| `pulse_routes.py` | 7 端点；**desktop-only**（PULSE dashboard）。 |
| `migration_routes.py` + `migration_plan.py` | 迁移横幅状态机 + LLM 迁移引擎；**纯 PC 概念，移动端无对应**。 |

### mobile 端（shim + 前端 —— `mobile/mobile-api.js` + `mobile/m/`）
| 文件 | 一句话 |
|---|---|
| `mobile-api.js` | **权威移动后端**（3184 行）：~50 个 `/api/*` handler；check intake/clamp、isWritableDate 补卡窗口、chat 多轮 tool loop、thread CAS 全已实装。 |
| `m/gw-real-bridge.js` | **真集成层**：把 cd 5 件套 mock 接到 shim；prefetch 真数据 + syncJournalDiff 写链路。 |
| `m/index.html` | 真入口页：激活 shim + 加载顺序契约（bridge 在 cd 之后、prefetch 在 mount 之前）。 |
| `m/gw-app.js` | 应用壳：bus/tab/日期带/设置页（设置真 wired）/chatbar。 |
| `m/gw-journal.js` | 时间线 + 5 套写操作习语（journal CRUD 真；daily-task 管理态/贴图假）。 |
| `m/gw-widgets.js` | 关怀区 4 widget（八杯水/打卡/PULSE/心情）。 |
| `m/gw-chat.js` | 对话流渲染（renderThread/buildChip live；mock sendChat 已被 bridge 覆盖）。 |
| `m/tokens.css` + `m/components.css` | design tokens（双模式零裸色值）+ 组件样式。 |
| `plugins/cutout/ios/…CutoutPlugin.swift` | iOS 17+ Vision 端侧抠主体（已进 Podfile.lock）。 |
| `plugins/native-ocr/ios/…NativeOcrPlugin.swift` | iOS Vision 端侧 OCR（已接线 mobile-api.js L1514）。 |
| `plugins/native-ocr/android/…NativeOcrPlugin.kt` | Android ML Kit OCR（**wip**：源码全但无 `cap add android`，孤立）。 |
| `app/` | Capacitor 应用壳（iOS-only；capacitor.config 含 contentInset=never / NoCloud 防 iCloud 撑满）。 |

---

## 4. 文档健康度表

所有 `mobile/*.md`（现 14 份，本轮 git rm 了 4 个 stale 快照）。**stale/redundant 的别当现状读**。

| 文件 | 状态 | 取代者 | 归档? | 备注 |
|---|---|---|---|---|
| `TEST_FIRST_MIGRATION.md` | **live** | — | 留 | 方法论总纲；§7.2"已接通"括注与历史层并存，读时认现状=已接通 |
| `INTERACTION_TEST_CASES.md` | **live** | — | 留 | 64 条 case 本体；`[UI待建]`/`[golden 缺]` 是真实未完成项 |
| `INTERACTION_E2E_PHOTO.md` | **live** | — | 留 | 诚实的双端落差表 + E2E 施工清单（照片 fixture 待建） |
| `PARITY_LEDGER.md` | **live** | — | 留 | **单一进度真相**；但顶部"64/64 真 tap"措辞偏乐观，校正见 §1 |
| `MIGRATION_FILES.md` | **live** | — | 留 | 文件归层导航；"真 tap ✅"略高于实情 |
| `MIGRATION_PARITY_GUIDE.md` | **stale** | `PARITY_LEDGER.md` | 顶部加批注，不必删 | §4"已知洞"(is_writable/daily_dose clamp/CAS)已全修；mobile-api.js 行号(L97/293/184/227，标691行)全过期(现3184行)。方法论框架(有用5类/没用4类)仍有用 |
| `PARITY_LOOP.md` | **stale** | `PARITY_LEDGER.md` | 留作提示词模板 | 双 loop 提示词仍 live；但"现成的洞"举的 D2/D8/D3/T5 已修完，是历史 |
| ~~`MIGRATION_AUDIT_REPORT` · `PM_REPORT` · `ROADMAP` · `RUNBOOK`~~ | **已删** | `PARITY_LEDGER.md` | ✅ 本轮 git rm | 4 个 6.17-6.26 stale 快照；salvage 的 3 条 Android 缺口 + 1 条触控收口已迁入 §5.C/§5.D |
| `SESSION_HANDOFF.md` | **live（已刷新）** | — | 留 | 2026-06-28 重写为「session 测试钥匙 + 模拟器接续手册」；真 key 经用户确认**刻意保留**（仅 simulator 自验、不入 source git） |
| `PHASE_2_RUNBOOK.md` | **live** | — | 留 | iOS 真机操作手册（Pod/签名/权限/ATS/HEIC/backup 排除），工程知识稳定 |
| `TEST_WORKFLOW.md` | **live** | — | 留 | plist-as-evidence 测试方法论可复用；内嵌 22-tool 验收状态表已过期（只看名单别看 ⬜/✅ 列） |
| `OCR_NATIVE_PLAN.md` | **live** | — | 留 | Android Phase B/C 仍是实装依据；但"N2 当前 OUT"叙述过期、plugin 命名漂成 `native-ocr` |
| `MOBILE_DESIGN_BRIEF.md` | **live** | — | 留 | 设计契约/色板/IA north-star；§四路线图批次标记已被实现追上（别当 todo 读） |
| `INTERACTION_E2E_DIARY.md` | 未扫 | — | — | 8 组报告未覆盖；推测与 E2E_PHOTO 同层（日记招牌场景），用前自核 |
| **本文 `MIGRATION.md`** | **live** | — | 留 | 权威入口 |

**`mobile/parity/interaction/` 下的探索脚本**（非 md，附此避坑）：`realOsTap.sh`（cliclick Mac mouse 链）已被 `idb_runner.sh` 取代，**本轮已 git rm**。`run-in-app.js`（webview SyntheticTap，fake-green 本体）**不删** —— `build-web.sh` 仍把它打包进 web bundle 作 in-app self-test 冗余；但它**不再是 parity oracle 凭证**，真 tap 一律走 `idb_runner.sh`。

---

## 5. 已知洞 / 矛盾（集中清单）

### A. 过期/矛盾的文档断言（读时要无视）
1. **"chat 无 tool loop" 已彻底过期** —— 那指更早的 shim。**桌面** `chat_routes.py` 有完整 MAX_ROUNDS=10 tool loop（`test_chat_routes.py` 锁定）；**移动** `mobile-api.js` L1180 `chatViaDeepseek` 也有完整多轮 tool loop（maxRounds=5）。两端都有。CLAUDE.md/PULSE Findings 里那条 Finding 已死。
2. **mobile parity"四洞"已全修** —— PULSE/CLAUDE.md Findings 写的 `is_writable=date>=todayIso(L454)`、`daily_dose 恒1(L184/227)`、`chat 无 tool loop`、`thread/save 无 CAS` **四条全部已修补**：shim L504 `isWritableDate` 复刻补卡窗口、L1657 check 有完整 intake/clamp、L1180 有 tool loop、L1763 thread save 有 CAS 409。那段 Finding 描述的是历史版本。
3. **`server.py` 顶部 docstring 整段过期**：写"v0.4 / Proxies chat to DeepSeek / 3 widget tools / .gateway-config.json"，现状是 0.1.39 / 双钥匙（阿里云=眼睛+DeepSeek=声音）/ 整套 TOOL_IMPL / setup 向导。
4. **`pulse_routes.py` header"P2-P5 后续阶段"路线图已完成**（pulse_io/eval/evolve 已抽出），header 是历史快照。
5. **行数全过期**：CLAUDE.md/PULSE 记的 server.py 9499/6271 → 现 **5243**；GUIDE/LOOP 记的 mobile-api.js 691 → 现 **3184**。

### B. 测试套真 RED（不是 fake-green，是真矛盾）
- **`tests/test_authorship.py` T3 真失败**（`test_patch_block_ai_allows_ai_block`）：它期望 AI 改 @ai 块 H2 标题成功，但 6.4 落地的 H2-rename guard 默认拒 H2 异。权威应留 **`tests/test_patch_h2_rename.py`**（较新、代表当前真行为）；test_authorship T3 该改成传 `allow_h2_rename=True` 或删。其余 32 条 authorship 真边界仍 GREEN。
- 连带：`test_journal_routes.py` 头注"test_authorship(13)... STAY GREEN"的全绿声明已不实（现 1 红）。

### C. 移动 UI 洞（后端已实现、前端入口/渲染端缺失 —— "后端先行、前端滞后"）
1. **file picker / 相机入口全是 demo 桩**：
   - chatbar 附件（`gw-app.js` L160）点击只 push 写死的灰色占位 SVG dataURL，不调真相册/相机/upload-image。
   - 打卡换图 + entry 贴图（`gw-journal.js` openEntrySheet L123）也是死 stub，只 whisper，无 file picker/cutout。
2. **daily-task 管理态四按钮全死**（`gw-journal.js` openTaskSheet L224-241）：换图标/改剂量/看完成率/删除 统一 `whisper('（demo）这一项接 daily-task API')`，不调 shim 已实现的 `/api/cutout`、`/api/daily-tasks/meta`、`/delete`。
3. **打卡 chip 配图永不显示**（双缺）：`gw-real-bridge.js` L97 有 image_url 时把 glyph 置空 → 但 `gw-widgets.js` L87 只渲 `t.glyph` 从不渲 `image_url` 成 `<img>`，且 `components.css` 无 `.gw-task-img` 样式 → 配图打卡 chip 空白。
4. **招牌 E2E 首尾两头空**（`INTERACTION_E2E_PHOTO.md`）：入口=换图标按钮 demo 桩（`gw-app.js:160`）、出口=chip 不渲 image_url（`gw-widgets.js:87`）；且 AI 链缺 `set_daily_task_image` tool + 缺 vision-pre-router 注入 → 整条根本走不通。真照片 fixture 也未就位。**← Phase 1 攻坚目标**
5. **窄屏触控/字号未收口**（删 RUNBOOK 时抢救）：当前间距是桌面调的，触控目标尺寸 + 字号待移动端 P3 收口。

### D. 平台 / 接线缺口
- **Android 整条链未集成**：`mobile/app/` 下只有 `ios/`，无 `android/` 目录，从未 `cap add android`。native-ocr 的 Kotlin + build.gradle 齐全但孤立（**wip**）。OCR_NATIVE_PLAN 的无-GMS 回落 PaddleOCR 也是 TODO 未做。具体未做项（删 ROADMAP/PM_REPORT 时抢救进此处）：
  - **`cap add android` + Android build runbook**：iOS 有 `PHASE_2_RUNBOOK.md`，Android 无对等手册（Android Studio 开 → run + signing key 配，~0.5 天）。
  - **cutout 抠主体 Android 实装**：`plugins/cutout/` 只有 iOS `CutoutPlugin.swift`，Android 完全没做；需 ML Kit Subject/Selfie Segmentation 对标 iOS Vision Subject Lift（~1-2 天）。OCR_NATIVE_PLAN 只覆盖 OCR 文字识别、不覆盖 cutout 抠图。
  - **AndroidManifest 权限文案**：camera/storage/internet 权限声明 + 中英双语，Play Store 审核硬性 gating（~0.5 天）。
- **cutout 触发点本组证据缺失**：iOS CutoutPlugin Swift + Pod 集成是真的，但 grep `mobile-api.js`/前端找不到对 `window.Capacitor.Plugins.Cutout.cutout()` 的调用；`/api/cutout`（mobile-api.js:1491）只调 `NativeOcr.recognize`。抠图实际触发应在上游拖图/Camera 流，需到上传 UI 流核实接线点。
- **iOS/Android bbox 语义不一致**：iOS OCR bbox 是 Vision 归一化坐标（0-1，左下原点），Android ML Kit 是像素坐标（左上原点）。JS 消费方若按统一契约处理会出错。

### E. 契约层"真绿但弱 oracle"（绿 ≠ Cannot-break 真验到）
`run.mjs` 多条 case 有容忍分支：`thread__save_stale_409`（没 CAS 直接放过）、`patch_h2_rename_gate`（200/409 都行）、`catalog_writable_yesterday`（is_writable 缺了也过）。所有 golden 烤死在基准日 **2026-06-26**，但 run.mjs 多数 case 用 wall-clock `todayIso()` —— 非 6.26 当天日期相关 `.md` golden 退化为形状比才能过字节比。

---

## 6. 跑法速查

```bash
# 契约层（最快、最干净的回归基准，~10s，无 LLM/simulator）
node mobile/parity/run.mjs

# 重新生成 golden（改桌面后刷新；需 .venv-test py3.11，系统 py3.9 跑不了 PEP604）
.venv-test/bin/python mobile/parity/capture-golden.py

# C 类覆盖闸（grep FE↔BE↔PC 三维落差）
bash mobile/parity/check-fe-be.sh

# 交互层真 OS tap（fb-idb；注意 all 当前只跑 01-20，且依赖固定 SIMID/日期 stem）
bash mobile/parity/interaction/idb_runner.sh setup    # seed
bash mobile/parity/interaction/idb_runner.sh case 03  # 单条
bash mobile/parity/interaction/idb_runner.sh all      # ⚠ 实际只 01-20

# 桌面 characterization / parity oracle（同时是 mobile 必须追平的真行为）
.venv-test/bin/python -m pytest tests/test_daily_tasks_routes.py tests/test_journal_routes.py -q
```
