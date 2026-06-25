# 移动端 parity 台账(loop 的持久记忆)

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
| J1 | test_today_returns_blocks | mobile-api.js readJournalMd/解析 | ❌ | — | 读:今天 blocks 形状 |
| J2 | test_days_lists_files | journal/days 等价 | ❌ | — | |
| J3 | test_tag_stats_top_and_default_for_new_user | tag-stats | ❌ | — | 新用户兜底 5 default tag |
| J4 | test_new_day_creates_then_idempotent | new-day 骨架生成 | ❌ | — | 幂等;dayN 编号;半点格 |
| J5 | test_insert_block_http_stamps_user | insert-block | ❌ | — | ★HTTP=user-trust,新 H2 stamp @user |
| J6 | test_insert_block_missing_time_400 | insert-block 校验 | ❌ | — | |
| J7 | test_insert_block_no_journal_404 | insert-block | ❌ | — | |
| J8 | test_delete_block_clears_to_placeholder | delete-block | ❌ | — | 清块→`##`,别块不动 |
| J9 | test_delete_block_unknown_time_404 | delete-block | ❌ | — | |
| J10 | test_patch_http_user_can_patch_ai_block | patch | ❌ | — | ★HTTP user 可改 @ai 块 |
| J11 | test_patch_routes_by_date_not_today | patch date 路由 | ❌ | — | ★历史视图编辑别打到今天(5.x 修) |
| J12 | test_patch_missing_new_md_400 | patch 校验 | ❌ | — | |
| J13 | test_tag_register_appends_and_commits | tag-aggregate register | ❌ | — | mobile 若不做聚合可标 OUT |
| J14 | test_tag_register_rejects_dup_and_subtag | 同上 | ❌ | — | |
| J15 | test_tag_aggregate_get_sections | tag-aggregate 读 | ❌ | — | |
| **J-CB1** | **test_authorship**(13 条)| mobile-api.js patch L1674 + insert-block L1386 + append-comment L1644 + checkAuthor L510 | ✅ | b1c8a5b\* | ★Cannot-break 实装齐:T1 checkAuthor 默认 user fail-safe + T2 ai 拒 @user 块 (403) + T3 H2-rename guard (409;canonical 5.22 fixture vs 5.29 guard drift,mobile 跟桌面实装一致 reject) + T4 user 任意改 + T5 default ai 严 + T6 insert stamp @author marker (本 commit fix,HTTP 默认 user user-trust) + T7 append-comment 不动原 body。JS oracle 11/11 pass。\*pending commit |
| **J-CB2** | test_patch_h2_rename(4) | patch H2 guard | ❌ | — | patch 不能当 insert 吃 entry |
| **J-CB3** | test_insert_block_body(6) | insert 写 title+body 一体 | ❌ | — | |

---

## P0 · daily-tasks(打卡 + 八杯水;3 个已确认洞)

oracle 文件:`tests/test_daily_tasks_routes.py`

| id | 契约(oracle test) | mobile shim 处 | 状态 | sha | 备注 |
|----|---|---|---|---|---|
| D1 | test_catalog_shape_and_is_writable | mobile-api.js L439-449 catalog | ❌ | — | tasks 字段形状 |
| **D2** | **test_check_backfill_window_yesterday_before_noon_else_403** | mobile-api.js **L466 isWritableDate** | ✅ | fde19c1 | 闭集 `{today, yesterday-if-hour<12}` 已实装(L466-475);桌面 pytest 16/16 GREEN + JS oracle 5/5 + check-fe-be 干净 |
| **D3** | **test_check_intake_increment_clamp_and_md_box** | mobile-api.js **L1262 check + L634/646 setSupplement{Checked,Progress}** | ✅ | 53230fc | _bump_intake 数学已实装:三入口 intake/increment/checked/toggle + clamp [0,dose] + dose>=2 sub-box(setSupplementProgress)+ dose<2 单行(setSupplementChecked)+ intake=0 log pop。桌面 16/16 GREEN + JS oracle 6/6 + md 字节级 "- [x] parity-D3-鱼油" 验通 |
| D4 | test_meta_update_total_pills_daily_dose_and_clear | meta 更新 | ❌ | — | total_pills None/''/0→pop;daily_dose max1 |
| D5 | test_history_per_day_oldest_first | history | ❌ | — | oldest→newest;null=无文件 |
| D6 | test_water_cup_get_set_roundtrip_reserved_key | water-cup | ❌ | — | `__water_cup__` 保留 key |
| D7 | test_delete_cascade_md_image_meta | delete | ❌ | — | md 双写目标 + image + meta 全清(5.15 肌酸丢 guard) |
| **D8** | test_check_rejects_future_and_catalog_is_writable_window | 同 D2 | ✅ | fde19c1 | 同 D2;5 assert oracle 全 pass(future_check_400 / twoAgo_check_400 / tomorrow_writable_false / yesterday_writable_per_hour / today_writable_true) |
| D9 | test_backfill_progress_idempotent | (desktop-only repair) | ❌ | — | mobile 无对等可标 OUT |

---

## P1 · thread 聊天历史持久化

oracle:`tests/test_thread_routes.py` + `tests/test_thread_cas.py`

| id | 契约(oracle test) | mobile shim 处 | 状态 | sha | 备注 |
|----|---|---|---|---|---|
| T1 | test_history_empty_when_no_file | thread/history | ❌ | — | 无文件→`{history:[],mtime:0}` |
| T2 | test_history_happy_returns_list_and_mtime | thread/history | ❌ | — | |
| T3 | test_history_corrupt_returns_modal_payload_and_rings | thread/history | ❌ | — | ★Cannot-break:损坏→`status:'corrupt'`+baks,不空覆盖(5.17) |
| T4 | test_restore_from_bak_roundtrip | restore-from-bak | ❌ | — | mobile 若无 bak 机制标 OUT |
| **T5** | **test_thread_cas**(9 条:base_mtime/409/不动文件)| thread/save(grep 无 base_mtime/409)| 🔴 | — | ★已确认洞:mobile save 裸覆盖,无 CAS;多设备同步必踩 5.26 |
| T6 | test_save_rejects_non_list_history_400 | thread/save 校验 | ❌ | — | |

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
| X1 | test_chat_routes.py(15)+test_claim_audit | /api/chat | ❌ | — | partial-parity:SSE 主流有 oracle;tool-loop 形态独立 |
| X2 | test_chat_routes + test_attachment_dedup | /api/chat/upload-image | ❌ | — | 拖图上传:sha 去重 + 校验 |
| X3 | test_web_search_resilience.py(3) | /api/web/search | ❌ | — | AI web 搜(360/搜狗解析韧性) |
| X4 | test_authorship.py::test_append_comment_* | /api/journal/append-comment | ❌ | — | ★批注 append-only,原 body 一字不动(authorship) |
| X5 | (template/task 近似) | /api/daily-tasks/add | ❌ | — | 新增打卡项(补剂段插行) |

---

## ⚠️ NEEDS-ORACLE-FIRST(parity loop 开跑前的前置工作)

> **台账最大的洞**:这些 mobile 已 shim,但桌面**没** characterization → loop 无对照可对。
> 每条**先写桌面 oracle(characterization / capture golden),它才从"无法对齐"变成可进 loop 的 row。**
> 排序 = 双侧零覆盖 × mobile 高频 × 数据丢失风险。

| id | mobile 端点 | ↔桌面行为 | 怎么补 oracle(前置活) |
|----|---|---|---|
| **N1** | /api/journal/search | tool_search_journal | ★最优先:双侧零 oracle + AI 高频。直测 tool_search_journal:hits 形状(time/snippet 200字/total/top30/days clamp) |
| **N2** | /api/daily-tasks/set-image | /api/cutout 换图标 | 测 _save_task_image_map roundtrip:写进 map[name]+catalog 读到(5.15 肌酸丢同类) |
| **N3** | /api/daily-tasks/water | 喝水 md 父子勾选 | 复用 dt fixture:water{filled:N}→子项<=N 勾、父项 N>=8 才勾、clamp[0,8]、404 |
| **N4** | /api/vision/classify | _qwen_classify_image | mock vision API:url 校验 + cache-hit 不重调 + 默认描述 cache 回 meta |
| **N5** | /api/uploads/list | /api/attachments(list) | 建 attachment+index,断言排序+limit+OCR 摘要;标 mobile 排序键(uploaded_at)分叉 |
| **N6** | /api/uploads/search | /api/attachments/search | 索引带 OCR,搜 q 命中/空q空;标 mobile 搜 vision 字段 vs 桌面搜 OCR 文本 |
| **N7** | /api/uploads/delete | /api/attachments/delete | ★删除有数据丢失风险。复用 isolated_attachments:delete→文件+索引都没+../拒 |
| **N8** | /api/attachments/get | /attachments/{date}/{name} | GET 200字节/坏date 400/404/traversal 拒;标 mobile 返 dataURL vs 桌面文件流 |
| **N9** | /api/web/fetch | tool_fetch_url | mock HTTP→strip 纯文本+3000字截断+https 校验+cleartext hint |
| **N10** | /api/widgets/list | /api/widgets/catalog | mobile widget 模型与桌面 manifest 迥异,parity 价值低 → 仅桌面 catalog 防回归,标 mobile-only-divergent |

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

_(loop 收敛时在此写 `PARITY CONVERGED @ <sha> @ <date>` + 剩余 OUT/已知不可迁项)_
