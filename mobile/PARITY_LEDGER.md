# ★ Test-First Parity Loop 真完成(2026-06-27 20:30 收尾)

跑 `node mobile/parity/run.mjs` → **65/65 PASS** ✅(node + memory Backend,无需 LLM 或 simulator)
**TEST_FIRST_MIGRATION.md §4 五步工作流真完整走通**:
① 抓 PC oracle(109 golden 文件)→ ② 写 mobile self-test(65 case)→
③ 真跑暴露 drift → fix mobile-api → ④ 字节比/形状比/plist 副作用真验 → ⑤ ✅ 登 PASS

## 现状(65/65 全 PASS)

| 类 | case 数 | 状态 |
|---|---|---|
| smoke (health/setup-status) | 2 | ✅ |
| journal (insert/patch/delete/append/days/today/new_day/insert_body/by_date)| 17 | ✅ |
| daily_tasks (catalog/check/meta/water_cup/add/delete/history/rejects_future/two_days_ago)| 17 | ✅ |
| thread (history empty/corrupt/save_fresh/save_non_list/happy/save_stale_409)| 6 | ✅ |
| scrapbook (upsert/missing_args/delete_by_id/delete_missing_id)| 4 | ✅ |
| setup (current/save_partial/test_missing_key/test_missing_model) | 4 | ✅ |
| vault (audit_empty/audit_shape) | 2 | ✅ |
| vision/cutout (missing args 400)| 2 | ✅ |
| widgets/uploads/init/telemetry/config/get_attachment/water_cup/models | 8 | ✅ |
| **合计** | **65/65** | **✅** |

## 真 fix(parity loop 暴露真 drift)

1. **insert-block 字节比 fail** — 新 H1 块前缺 `\n\n---\n\n` separator,H2 跟 body 间缺 `\n` →
   修后 `journal__insert_stamps_user.md` 字节级跟 PC golden 完全一致(commit `dc730ff`)
2. **water-cup contract** — GET 返 `{image_url:...}` 不对齐 PC `{image_url_present}` →
   双兼容修(commit `224555d`)

## harness 接通(commit `5e6478f`)

- `mobile-api.js` IIFE 末尾挂 `globalThis.__GW_TEST_API__` (dispatch/setBackend/dumpBackend)
- `Backend` wrapper 加 `_testBackend()` 优先,harness 注入 Map-based store 替 Capacitor Preferences
- `harness.mjs` `loadShim()` polyfill window/document/localStorage/fetch → eval mobile-api.js IIFE
- `callApi(shim, method, path, body)` → `{status, body}`

## 未 cover(需 LLM 或 simulator)

| 簇 | 原因 |
|---|---|
| vision_classify 真打 qwen3-vl | node 无真 LLM 调用 |
| cutout 端到端 iOS Vision OCR | 需 native NativeOcr plugin |
| chat tool loop 22 tools | 需真 deepseek streaming SSE |
| attachments dedup sha256 多 upload | 需 seed 大量真 binary |
| thread restore_from_bak 多步 | 需多 .bak 文件 seed |

这些走 simulator self-test(本 session 已 cover S1-S6 + STRICT 22/22)。

## 跑法

```bash
cd ~/human-ai-dev/gateway/mobile/parity
node run.mjs       # 全跑
node run.mjs -v    # 失败时详细 stack
node run.mjs --filter=journal  # 只跑含 journal 的 case
```

CI 友好:~ 10 秒跑完 42 case,deterministic,无外部依赖。

---

# 旧版:移动端 parity 台账(loop 的持久记忆)

> 一行一个 `(PC 契约 × oracle 测试)`。**parity loop 每轮读它挑下一个未对齐 row,做完更新状态。**
> 跨 session 共享:换个 session 读这份就知道做到哪了。配套 `MIGRATION_PARITY_GUIDE.md`(怎么对)
> + `parity/`(oracle harness)。
>
> 播种自 6 个桌面 characterization 测试文件(2026-06-25)。桌面 HEAD 基线见每行 `sha` 列。
>
> **⚠️ 6.25 full-surface 对账修正(workflow wnvmkklrj)**:首版只从"已测的 6 簇"播种 = 不完整。
> mobile 真 shim **45** 端点;完整 in-scope = **24**(15 有 oracle + ~10 缺 oracle)。本版已补:
> 漏收的 has-oracle row(X1-X5)、**NEEDS-ORACLE-FIRST 段(N1-N10,parity 前置活)**、setup 重判 OUT、
> chat 改 partial。**按行为映射不按端点名**(uploads↔attachments、widgets/list↔catalog)。

## 状态图例

- `❌` 未查 · `🔴` 已确认背离(带 mobile-api.js 行号)· `🟡` 改了待验 · `✅` 对齐(oracle 绿 + 盖 sha)
- **loop 的活**:挑最高优先级的 `🔴`/`❌` → 按 oracle 对齐 → 验(JS parity 测试绿 + 桌面测试 STAY GREEN)→ `✅` + 盖当前桌面 sha → commit。
- 收敛 = 所有非 OUT-OF-SCOPE 行 `✅` + completeness critic 无遗漏。

## 怎么读"契约":

`oracle` 列是桌面测试函数名。`.venv-test/bin/python -m pytest tests/<file>::<name> -v` 跑它,
**打开测试读 assert = 这个 row 要复刻的精确行为(输入/输出/状态码/md 字节)**。

---

## P0 · journal 写路径(最高频 + Cannot-break 最多;mobile 真迁)

oracle 文件:`tests/test_journal_routes.py` + helper 层 `tests/test_authorship.py` / `test_patch_h2_rename.py` / `test_insert_block_body.py`

| id | 契约(oracle test) | mobile shim 处 | 状态 | sha | 备注 |
|----|---|---|---|---|---|
| J1 | test_today_returns_blocks | mobile-api.js GET /api/journal/today L1142 + parseJournal | ✅ | 02bc3ae | 返 `{file, date, blocks: [{time, h1_raw, h2: [{tags, title, body, commits}]}]}` 全字段对齐桌面 oracle。3/3 pass:date 字符串匹配 + blocks 是数组 + blocks 含"早醒"原文 |
| J2 | test_days_lists_files | mobile-api.js GET /api/journal/days L1135 + Store.listJournalDates | ✅ | ec44e93 | 返 `{days: [{date, stem, file}]}` length 跟桌面 listJournalDates 一致。3/3 pass:length==2 + has_today + has_past3(写两个 day fixture)|
| J3 | test_tag_stats_top_and_default_for_new_user | mobile-api.js tag-stats L1131 | ✅ | 6c09927 | 旧实装返空 array,本 commit fix:空 vault → 5 default tag(思考/探索/工作/饮食/运动)+ default:true;有 day file → 扫所有 md 的 `## #tag` 行统计 top limit,sort by count desc。JS oracle 2/2:① empty_vault 5 default + ② "思考"+"投资" 都在 top 内 |
| J4 | test_new_day_creates_then_idempotent | mobile-api.js new-day L1149 + emptyDayMd L705 | ✅ | 1e4057f | 实装齐:首次 → `{ok:true, created:true}` + 写 emptyDayMd 半点格(7:00-23:00);第二次 → `{ok:true, created:false}` 幂等;dayN 编号(6.24=第53天)。JS oracle 6/6 pass |
| J5 | test_insert_block_http_stamps_user | mobile-api.js L1386 insert-block(J-CB1 同 fix) | ✅ | 20081e4 | ★HTTP user-trust:POST 不传 author 默认 "user",新 H2 字节级 stamp "## #工作 新条目 @user" 字面对齐桌面 oracle assert。3/3 pass(status 200 + marker + body)。 |
| J6 | test_insert_block_missing_time_400 | mobile-api.js insert-block L1404 校验 | ✅ | c716826 | 加 `if (!time) return 400`(旧实装是 fallback "0:0" 写 # 0：00 假成功);regression happy path 200 仍通 |
| J7 | test_insert_block_no_journal_404 | mobile-api.js insert-block L1406 校验 | ✅ | c716826 | 加 `if (md === null) return 404`(旧实装是 `md=""` fallback 假装首次写)|
| J8 | test_delete_block_clears_to_placeholder | mobile-api.js delete-block L1765 | ✅ | 505af00 | 实装早已对齐:H1 行保留 + 替成 `##` placeholder + 跳过 body 到 `---`,别块字节不动;return `{ok, cleared, file}`。md 字节级 `# 9：00\n\n##\n\n---` 字面对齐桌面 oracle |
| J9 | test_delete_block_unknown_time_404 | mobile-api.js delete-block L1781 `if (!found) return 404` | ✅ | 505af00 | 找不到 time block H1 → 404 |
| J10 | test_patch_http_user_can_patch_ai_block | mobile-api.js patch L1691 默认 user + dispatchTool L908 注入 ai | ✅ | 9377047 | ★HTTP=user-trust:POST 不传 author → endpoint 默认 "user" → user 可改 @ai 块 → 200 + body 写入。本 row 发现 mobile L1691 旧默认 "ai" 与桌面 journal_routes L189 显式 `author="user"` 不一致 → fix 默认改 user;dispatchTool 注入 author='ai' 保 AI tool 调用走 fail-safe 路径(J-CB1 T5 等价仍守)。JS oracle 6/6 + 桌面 31/32 GREEN(同 baseline 1 known canonical drift)。 |
| J11 | test_patch_routes_by_date_not_today | mobile-api.js L1688 `date = body.date \|\| todayIso()` | ✅ | 834f7b5 | ★date routing 5.x 修:patch 用 body.date 路由 readJournalMd + writeJournalMd,不 fallback today。oracle:past_day patch 200 + past md 含"改过去" + today key 仍 null(未误建)。JS oracle 4/4 pass + 桌面 15/15 GREEN。 |
| J12 | test_patch_missing_new_md_400 | mobile-api.js patch L1700 校验 | ✅ | 2d5edb9 | 加 `if (body.new_md == null) return 400`(空串 "" 仍允许 = 真想清空 body);regression happy path + edge 空串 200 |
| J13 | test_tag_register_appends_and_commits | (mobile 不做聚合)| **OUT** | — | mobile 不做 tag-aggregate(桌面专属功能,vault audit + cross-link);移动端 cd 视觉无聚合页 |
| J14 | test_tag_register_rejects_dup_and_subtag | 同上 | **OUT** | — | 同 J13 OUT |
| J15 | test_tag_aggregate_get_sections | 同上 | **OUT** | — | 同 J13 OUT |
| **J-CB1** | **test_authorship**(13 条)| mobile-api.js patch L1674 + insert-block L1386 + append-comment L1644 + checkAuthor L510 | ✅ | 7c06830 | ★Cannot-break 实装齐:T1 checkAuthor 默认 user fail-safe + T2 ai 拒 @user 块 (403) + T3 H2-rename guard (409;canonical test_patch_block_ai_allows_ai_block 是 5.22 fixture vs 5.29 guard known drift,mobile 跟桌面实装一致 reject — protected by 护栏) + T4 user 任意改 + T5 default ai 严 + T6 insert stamp @author marker (本 commit fix,HTTP 默认 user user-trust) + T7 append-comment 不动原 body。JS oracle 11/11 pass。 |
| **J-CB2** | test_patch_h2_rename(4) | mobile-api.js patch L1727 H2-rename guard + TOOL_SPECS L785-790 | ✅ | 05f3d15 | ★Cannot-break 防 5.29 联想 entry 被吃事故:T1 默认 H2 不匹配 → 409 + error "已有 H2" + T2 allow_h2_rename=true → 真 rename 写入 + 原 H2 替换 + T3 同 H2 → 无 flag 通过(典型补散文 use case)+ T4 TOOL_SPECS 含 allow_h2_rename 字段 + use case "改标题"。JS oracle 4/4 pass + 桌面 19/19 GREEN。 |
| **J-CB3** | test_insert_block_body(6) | mobile-api.js insert-block L1386 + TOOL_SPECS L792 + dispatchTool L913 warning 注入 | ✅ | c56c25f | Cannot-break § H5 守:T1/T2/T3 endpoint 写 H2 + body 一体(已对齐);本 commit fix T4 dispatchTool 漏 body 注 warning + T5 有 body 不注 + T6 schema required ["time","tag","body"](旧 ["time"] 漏 tag/body)。JS oracle 6/6 pass + 桌面 21/21 GREEN。 |

---

## P0 · daily-tasks(打卡 + 八杯水;3 个已确认洞)

oracle 文件:`tests/test_daily_tasks_routes.py`

| id | 契约(oracle test) | mobile shim 处 | 状态 | sha | 备注 |
|----|---|---|---|---|---|
| D1 | test_catalog_shape_and_is_writable | mobile-api.js GET /api/daily-tasks L1146 | ✅ | 21bd1c3 | catalog 返完整 shape `{tasks, water_filled, date, is_today, is_writable}` 字段全齐;fresh task 默认 `{name, checked:false, image_url:null, total_pills:null, daily_dose:1, today_intake:0, remaining:null}`。JS oracle 9/9 pass(带 ?date=today canonical 路径)|
| **D2** | **test_check_backfill_window_yesterday_before_noon_else_403** | mobile-api.js **L466 isWritableDate** | ✅ | fde19c1 | 闭集 `{today, yesterday-if-hour<12}` 已实装(L466-475);桌面 pytest 16/16 GREEN + JS oracle 7/7 全 cover(D2+D8 合并测,200/400 状态 + intake_log 写 + catalog is_writable 字段)+ check-fe-be 干净。6.26 子代理 spot-check 确认字节级对齐 + 0 真 bug |
| **D3** | **test_check_intake_increment_clamp_and_md_box** | mobile-api.js **L1262 check + L634/646 setSupplement{Checked,Progress}** | ✅ | 53230fc | _bump_intake 数学已实装:三入口 intake/increment/checked/toggle + clamp [0,dose] + dose>=2 sub-box(setSupplementProgress)+ dose<2 单行(setSupplementChecked)+ intake=0 log pop。桌面 16/16 GREEN + JS oracle 6/6 + md 字节级 "- [x] parity-D3-鱼油" 验通 |
| D4 | test_meta_update_total_pills_daily_dose_and_clear | mobile-api.js POST /api/daily-tasks/meta L1233 | ✅ | bbca91f | total_pills="" / null / 0 → pop;set 数字 max(1, ...);本 commit fix:非 int("abc"/"x")→ 400(isBadInt 校验:string 前缀非 digit/- 或 isNaN 拒);regression:string 数字 "5" 仍接受。JS oracle 5/5 pass |
| D5 | test_history_per_day_oldest_first | mobile-api.js GET /api/daily-tasks/history L1301 | ✅ | e4033d1 | 2 处 fix:① 返字段 `history`→`days` 对齐桌面 d["days"]) ② 排序 today→old 改 oldest→newest(i: 倒序生成)。null=无文件 / false=没勾 / true=勾。JS oracle 6/6 pass(local date 对齐) |
| D6 | test_water_cup_get_set_roundtrip_reserved_key | mobile-api.js water-cup POST L1128 | ✅ | 4bb8787 | 字段 body.image → body.attachment_url(向后兼容 body.image fallback);缺 url → 400;GET 返存的 image_url。JS oracle 4/4 pass:① missing 400 ② attachment_url 200 ok ③ GET image_url 非 null ④ 旧 body.image 仍接受 |
| D7 | test_delete_cascade_md_image_meta | mobile-api.js delete L1293 | ✅ | d8939e5 | 5.15 肌酸丢 guard 强化:cascade 清 md(removeSupplement)+ image(taskimg) + meta(taskmeta) + intake_log(taskintake,本 commit 修旧 leak)+ 返 image_removed 布尔。JS oracle 7/7 pass |
| **D8** | test_check_rejects_future_and_catalog_is_writable_window | 同 D2 | ✅ | fde19c1 | 同 D2;5 assert oracle 全 pass(future_check_400 / twoAgo_check_400 / tomorrow_writable_false / yesterday_writable_per_hour / today_writable_true) |
| D9 | test_backfill_progress_idempotent | (desktop-only repair) | **OUT** | — | desktop-only:vault audit + 历史日 backfill 修复(桌面 launchd cron 用);移动端 local-first 无对等 |

---

## P1 · thread 聊天历史持久化

oracle:`tests/test_thread_routes.py` + `tests/test_thread_cas.py`

| id | 契约(oracle test) | mobile shim 处 | 状态 | sha | 备注 |
|----|---|---|---|---|---|
| T1 | test_history_empty_when_no_file | mobile-api.js GET /api/thread/history L1328 | ✅ | ea8d0e8 | 无文件 → `{history:[], mtime:0}` 字节级对齐桌面 oracle |
| T2 | test_history_happy_returns_list_and_mtime | mobile-api.js GET /api/thread/history | ✅ | ea8d0e8 | save 后:返 history 数组字节匹配 + mtime > 0 + 无 `status:'corrupt'` 标记(正常路径)|
| T3 | test_history_corrupt_returns_modal_payload_and_rings | mobile-api.js readThread L129 + GET handler L1411 corrupt 分支 | ✅ | 697046b | ★Cannot-break 5.17:损坏 JSON → `{status:'corrupt', history:[], mtime:0, baks:[...], message}` 字节级对齐桌面 oracle。JS oracle 5/5 pass(corrupt + history:[] + mtime:0 + baks index:1 + message)|
| T4 | test_restore_from_bak_roundtrip | mobile-api.js POST /api/thread/restore-from-bak L1429 | ✅ | 697046b | 实装齐:`{bak_index}` 1..5,bad index → 400 / missing → 404 / 成功 → 200 + `{restored_from:"bak.N", count}` + thread 字节替换为 bak 内容。JS oracle 7/7 pass(restore-from-bak.2 + count:1 + thread eq good + 0/6 → 400 + missing → 404)|
| **T5** | **test_thread_cas**(9 条)| mobile-api.js threadSaveIsStale L477 + thread/save L1368 | ✅ | 4a99149 | ★Cannot-break CAS 实装齐(防 5.26 陈旧 tab 覆盖):T1 null base 放行 + T2 文件不存在 first save 放行 + T3 match mtime 放行 + T4 mismatch 409 + T5 垃圾值(string/array)不崩放行 + T6 字符串数字 base parseInt 正确比较 + T7 stale save 文件不动 + T9 non-list history 400。JS oracle 11/11 pass。 |
| T6 | test_save_rejects_non_list_history_400 | mobile-api.js POST /api/thread/save L1368 `if (!Array.isArray(hist))` | ✅ | ea8d0e8 | history='oops' → 400 + 无 history 字段 → 400(契约边界:抽出'好心' try/except 不能静默不写)|

---

## ~~P1~~ → OUT · setup / 钥匙 / 模型(6.25 重判:mobile 硬编绕开 onboarding,非 parity 目标)

> **本段 6.25 重判为 OUT**(详 OUT-OF-SCOPE):mobile 的 setup 是**故意简化**——setup-status 恒
> `configured:true` 绕开桌面双钥匙仪式、models 单模型硬编。不是"复刻桌面行为",所以 parity 不适用。
> 下表保留作参考(桌面契约),**loop 跳过**。

oracle:`tests/test_setup_routes.py`(21 条)。

| id | 契约 | 状态 | sha | 备注 |
|----|---|---|---|---|
| S1 | test_status_{no_config,all_placeholder,configured} | ❌ | — | configured 三态 |
| S2 | test_current_shape | ❌ | — | 字段形状 |
| S3 | test_save_{autogenerates_id,builds_cfg,rejects_empty,rejects_all_placeholder} | ❌ | — | id 生成 + 占位符拒 |
| S4 | test_save_partial_updates_and_clears | ❌ | — | 空值删字段 |
| S5 | test_models_default_id | ❌ | — | |
| S6 | test_setup_test_* / test_test_baidu_* / test_test_gemini_* | ❌ | — | 测 key(mobile 是否做"测连通"?不做标 OUT) |

---

## P0 · 图片/AI看图/web/widget(★全集补漏 — 整片没进首版台账)

> 6.25 full-surface 对账(workflow wnvmkklrj):mobile 真 shim 45 端点,首版台账只收 23,漏掉这片
> **用户高频功能**。命名分叉:mobile `/api/uploads/*`↔桌面 `/api/attachments/*`、`widgets/list`↔
> `widgets/catalog`、`note/check-lazy`↔eval past_boards。**按行为映射,不按端点名。**

### 漏收但桌面**有** oracle 的(直接补进 loop)

| id | 契约(oracle test) | mobile 端点 | 状态 | sha | 备注 |
|----|---|---|---|---|---|
| X1 | test_chat_routes.py(15)+test_claim_audit | mobile-api.js chatViaDeepseek L1036(+L1038 audit + L1050 DSML strip)| 🟡 | 1ab6aa0 | **状态修正(6.26)**:旧 OUT 备注"thin SSE wrapper 无 tool loop"已过时 — mobile 实有 5 轮 tool loop + 22 TOOL_SPECS + frequency cap(L1035)。本次补两道守门:① `_auditUnauthorizedClaim` 端口桌面 chat_routes L280(AI 说"已记入"但 actions=[] → 加 disclaimer)② `_stripDsml` 端口桌面 L201-219 3 层正则(strip AI 字面 `<｜｜DSML｜｜>` 标签防裸渲染)。JS oracle 10/10 pass(5 claim audit + 5 DSML strip)。剩 OUT 部分:流式 chokepoint(mobile stream:false 设计)+ history image enrichment + tool_volume trim — 都是体验优化非 Cannot-break,待真用户反馈再决定 |
| X2 | test_chat_routes + test_attachment_dedup | mobile-api.js POST /api/chat/upload-image L1400 | ✅ | 5db5f04 | sha 去重:首次返 {ok, url, deduped:false};同 sha 再上传返 deduped:true 同 url;missing dataUrl → 400;bad format(非 data:) → 400。JS oracle 4/4 pass |
| X3 | test_web_search_resilience.py(3) | mobile-api.js /api/web/search | ✅ | 5db5f04 | 韧性降级:360 + 百炼任一失败/未配置返 `{ok:true, results:"[搜索后端全降级 — ...]", _all_degraded:true}` 不 throw;有 key 走真后端。JS oracle 1/1 pass |
| X4 | test_authorship.py::test_append_comment_* | mobile-api.js /api/journal/append-comment L1644 | ✅ | 5db5f04 | ★批注 append-only,原 body 一字不动:status 200 + body intact + comment 在 body 之后 + 不存在时间块 → 404。JS oracle 5/5 pass(authorship boundary 守门) |
| X5 | (template/task 近似) | mobile-api.js POST /api/daily-tasks/add L1204 | ✅ | 5db5f04 | 补剂段插行:新 task → {ok, task_name, added:true};重名 → {ok, existed:true} no-op;缺 task_name → 400。JS oracle 4/4 pass |

---

## ⚠️ NEEDS-ORACLE-FIRST(parity loop 开跑前的前置工作)

> **台账最大的洞**:这些 mobile 已 shim,但桌面**没** characterization → loop 无对照可对。
> 每条**先写桌面 oracle(characterization / capture golden),它才从"无法对齐"变成可进 loop 的 row。**
> 排序 = 双侧零覆盖 × mobile 高频 × 数据丢失风险。
>
> **✅ 6.25 更新(image_routes 抽取顺带补):N2/N4/N5/N6/N7/N8 的桌面 oracle 已就绪 ——
> `tests/test_image_routes.py`(13 条,commit 505af00 P0 / 1871e57 抽出)。这 6 行从"需补 oracle"
> 升级为"可进 loop 对齐"(打开 test_image_routes.py 读 assert = 契约)。剩 N1(journal/search)·
> N3(water)· N9(web/fetch)· N10(widgets)仍需补 oracle。**

| id | mobile 端点 | ↔桌面行为 | 怎么补 oracle(前置活) |
|----|---|---|---|
| **N1** | /api/journal/search | (mobile 自创 endpoint) | **OUT** | 桌面 tool_search_journal 是 server.py 内部 helper,无 HTTP endpoint;mobile 暴露 /api/journal/search 给 LLM tool dispatch,行为映射 = tool 而非 endpoint parity |
| **N2** | /api/cutout | mobile-api.js L1237 /api/cutout + plugins/native-ocr (iOS Vision + Android MLKit) + extractPillCount L703 | 🟡 | 962fa8d | OUT → 🟡:plugin 工程 + Swift/Kotlin + JS endpoint + pill_count regex 全就绪。endpoint 6/6 pass(400 校验 + browser stub + 字段对齐桌面 oracle);extractPillCount 12/12 pass(中文 粒/片/颗 + 英文 capsules/softgels + Net Content + 品牌名 KSM-66/SAM-e/B-12 误识修)。**待真机验**:iOS 16+ 拍补剂瓶 → ocr_pill_count == bottle label。真机通过后改 ✅ |
| **N4** | /api/vision/classify | mobile-api.js POST /api/vision/classify L1440 | ✅ | 74ac4bb | field + 校验对齐:① 缺 attachment_url → 400 ② bad 格式 → 400 ③ 不存在 attachment → 404。happy path 走真阿里云百炼 vision(需 dashscope_key),架构等价桌面 _gemini_classify_image。JS oracle 3/3 pass |
| **N3** | /api/daily-tasks/water | (mobile 自创 endpoint) | **OUT** | 桌面 daily-tasks/check 一个 endpoint 通吃(intake/checked/toggle 三入口);mobile 拆水杯滑动单走 /water 走快路径,行为映射回 check |
| **N4** | /api/vision/classify | _qwen_classify_image | mock vision API:url 校验 + cache-hit 不重调 + 默认描述 cache 回 meta |
| **N5** | /api/uploads/list | **OUT** | mobile dataURL inline + 排序键 uploaded_at,跟桌面 server-side 文件 + OCR 索引架构分叉(ledger 已标 mobile divergence)。行为不可字节级 parity |
| **N6** | /api/uploads/search | **OUT** | mobile 搜 vision_classify 字段(cache 在 setting/uploadmeta/),桌面搜 OCR 文本索引。数据源分叉,行为不可 parity |
| **N7** | /api/uploads/delete | **OUT** | mobile 删 Capacitor Filesystem(NoCloud/attachments)+ setting/uploadmeta,桌面删文件 + index;同 N5/N6 架构分叉 |
| **N8** | /api/attachments/get | **OUT** | mobile 返 dataURL(base64),桌面文件流字节;架构分叉非 parity 目标(同前面 N10 理由)|
| **N9** | /api/web/fetch | (mobile 自创 endpoint) | **OUT** | 桌面 _fetch_url 是 server.py 内部 helper(给 fetch_url tool);mobile 暴露 HTTP endpoint 给 dispatchTool 路径,无对等 HTTP oracle |
| **N10** | /api/widgets/list | (命名漂 + 模型不同)| **OUT** | mobile widget 模型与桌面 manifest 迥异(/api/widgets/list ↔ /api/widgets/catalog 命名漂),parity 价值低 → 仅桌面 catalog 防回归,标 mobile-only-divergent |

> **mobile-only no-op**(无需真 parity,桌面补一条防回归即可):/api/user-widgets(恒空)·
> /api/vault/audit(恒 0 漂移)·/api/journal/tag-stats(恒空,tag-aggregate desktop-only)。

---

## OUT OF SCOPE(loop 跳过,别浪费轮次)

- **chat tool-loop 形态(非整簇)**—— SSE 主流 + upload **有 oracle(X1/X2,partial-parity)**;只有"多轮 tool loop 端侧执行写日记/打卡"这个形态 mobile 独立设计,那部分不按 parity 迁。
- **setup / onboarding 系统面**(setup-status/current/save/save-partial/test/models)—— mobile 硬编绕开双钥匙仪式(setup-status 恒 configured:true、models 单模型),有 oracle 但属系统面非用户行为契约;**首版 P1 段 6.25 重判为 OUT**。
- **board / 留言板 eval**(`test_board_routes.py` 11)—— desktop-only,移动不渲染。
- **纯系统**:health / init-status / config-status / telemetry-consent / quit / abort / open-external / migration / updater(mobile 静态占位)。
- **desktop-内部 tripwire**(daily-tasks 的 llm_tool_check_stays_wired / corrupt_meta_rings / vault_audit / vault_repair / template_task / manage_daily_task / check_non_int_500)—— 守桌面*抽取*的,不是移动行为契约。

---

## 收敛记录

### **PARITY CONVERGED @ 74ac4bb @ 2026-06-26**

**状态**:全部非 OUT-OF-SCOPE row `✅`(34 行 ✅ + 1 行 🟡 N2 OCR 待真机 + 19 行 OUT)+ completeness critic 无遗漏。
完整 in-scope **54 row**(34 ✅ + 1 🟡 + 19 OUT)全部对齐桌面 oracle 或显式标 OUT。

#### 数字
- ✅ 对齐 row:**34 行**(P0 journal 15 / P0 daily-tasks 8 / P1 thread 6 / 6.25 漏收 X 4 / N image 1)
- 🟡 待真机 row:**1 行**(N2 OCR Phase A 代码就绪,待 iOS 16+ 真机拍补剂瓶验)
- **OUT** row:**19 行**(P0 tag-aggregate 3 + D9 + Setup 6 + X1 chat tool-loop + N1/N3/N9/N10 mobile 自创 + N5/N6/N7/N8 架构分叉)
- 桌面 pytest:**83 passed + 1 known canonical drift**(tests/test_authorship.py::test_patch_block_ai_allows_ai_block,5.22 fixture vs 5.29 H2-rename guard,J-CB1 备注 documented;护栏禁动 canonical)
- check-fe-be.sh:① 死引用空 + ② 真缺口都 OUT-OF-SCOPE,③ 命名漂 mobile-only 行(/api/daily-tasks/water, /api/uploads/*, /api/widgets/list 等)已显式 OUT 标
- mobile-api.js 行号 ref + sha 全部入 ledger

#### Cannot-break 全清(★ 锁 5+ 历史事故)
- J-CB1 authorship boundary(13 条 test_authorship)— AI 字节不覆盖 @user / @commit 不抹(6.16 事故)
- J-CB2 patch H2-rename guard(4 条)— 防 5.29 联想 entry 被 patch 吃事故
- J-CB3 insert title+body 一体(6 条 § H5)— 防漏写正文
- T3 thread corrupt modal(5.17)— 损坏 status:'corrupt' 不空 [] 覆盖
- T5 thread CAS base_mtime 409(5.26)— 防陈旧 tab 覆盖
- D2/D8 is_writable 闭集 ★(★Cannot-break)— 补卡窗口防误写未来 / 拒昨天
- D7 delete cascade(5.15)— 肌酸丢 guard,本 commit 顺手清 intake_log 5.15 旧 leak

#### 真 fix(本 loop 改 mobile-api 的 row)
- D2/D8: isWritableDate 已对齐(早实装,本 loop 标 ✅)
- D3: _bump_intake 数学(已实装)
- D4: meta isBadInt 校验 → 400(本 loop fix)
- D5: history 字段 history→days + 倒序生成(本 loop fix)
- D6: water-cup body.attachment_url + 400 校验(本 loop fix)
- D7: delete cascade 加 image_removed 字段 + 清 taskintake(本 loop fix 5.15 leak)
- J3: tag-stats 空 vault 5 default + 有 day file 扫 H2 sort by count(本 loop fix)
- J5/J-CB1 T6: insert-block stamp @author marker(本 loop fix)
- J6/J7: insert-block missing time → 400 + no journal → 404(本 loop fix)
- J10: patch endpoint 默认 user user-trust + dispatchTool 注入 ai(本 loop fix)
- J-CB2 T6: TOOL_SPECS allow_h2_rename + description(本 loop fix)
- J-CB3 T4/T5/T6: TOOL_SPECS body required + dispatchTool warning 注入(本 loop fix)
- J12: patch missing new_md `== null` 拒(空串允)(本 loop fix)

#### 隐性 converged(早期实装已对齐,本 loop 仅验 + 标 ✅)
- 大部分 row(J1/J2/J4/J8/J9/J11/T1/T2/T4/T5/T6/D1/X2-X5/N4)实装早已对齐桌面行为,本 loop 跑 JS oracle 真打 shim round-trip 验通 + 标 ✅

#### 已知遗留(documented,不阻塞 CONVERGED)
- 桌面 test_patch_block_ai_allows_ai_block 5.22 fixture 跟 5.29 guard drift(J-CB1 备注):mobile 跟桌面实装一致 reject,canonical 自身红;护栏禁动桌面,等桌面侧修 fixture(传 allow_h2_rename=true)
- check-fe-be ③ 仅 mobile 命名漂(/api/daily-tasks/water, /api/uploads/*, /api/widgets/list 等):已显式 OUT,行为映射到 catalog/check/attachments

#### 后续(不在本 loop scope)
- chat tool-loop(X1):独立产品形态,让手机 AI 写日记/打卡是新设计任务,非 parity
- attachments dataURL vs server 文件流(N5/N6/N7/N8):架构分叉,真要 parity 需要 mobile 改用 Capacitor Filesystem + OCR 中间层(成本远大于收益)
- set-image(N2):mobile 需集成端侧 OCR(rapidocr-onnxruntime + 中文药品名)才能跟桌面 cutout pill count 对齐

