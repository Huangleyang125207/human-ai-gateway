# 移动端 parity 台账(loop 的持久记忆)

> 一行一个 `(PC 契约 × oracle 测试)`。**parity loop 每轮读它挑下一个未对齐 row,做完更新状态。**
> 跨 session 共享:换个 session 读这份就知道做到哪了。配套 `MIGRATION_PARITY_GUIDE.md`(怎么对)
> + `parity/`(oracle harness)。
>
> 播种自 6 个桌面 characterization 测试文件(2026-06-25)。桌面 HEAD 基线见每行 `sha` 列。

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
| **J-CB1** | **test_authorship**(13 条)| 改 journal 块的整块 reconstruct | 🔴 | — | ★Cannot-break:AI 字节不能覆盖 @user 块;`#commit` 批注不能被抹(6.16 踩过,靠拼回原始批注救) |
| **J-CB2** | test_patch_h2_rename(4) | patch H2 guard | ❌ | — | patch 不能当 insert 吃 entry |
| **J-CB3** | test_insert_block_body(6) | insert 写 title+body 一体 | ❌ | — | |

---

## P0 · daily-tasks(打卡 + 八杯水;3 个已确认洞)

oracle 文件:`tests/test_daily_tasks_routes.py`

| id | 契约(oracle test) | mobile shim 处 | 状态 | sha | 备注 |
|----|---|---|---|---|---|
| D1 | test_catalog_shape_and_is_writable | mobile-api.js L439-449 catalog | ❌ | — | tasks 字段形状 |
| **D2** | **test_check_backfill_window_yesterday_before_noon_else_403** | mobile-api.js **L97/293** | 🔴 | — | ★Cannot-break + 已确认洞:mobile `is_writable=date>=today`(反了);应 `{今天,昨天 if hour<12}` 闭集,未来+前天 403 |
| **D3** | **test_check_intake_increment_clamp_and_md_box** | mobile-api.js **L184/227**(check 路径硬编 daily_dose:1) | 🔴 | — | 已确认洞:check 路径要读 meta.daily_dose + clamp + sub-box(catalog L449 已读 meta,check 没跟上) |
| D4 | test_meta_update_total_pills_daily_dose_and_clear | meta 更新 | ❌ | — | total_pills None/''/0→pop;daily_dose max1 |
| D5 | test_history_per_day_oldest_first | history | ❌ | — | oldest→newest;null=无文件 |
| D6 | test_water_cup_get_set_roundtrip_reserved_key | water-cup | ❌ | — | `__water_cup__` 保留 key |
| D7 | test_delete_cascade_md_image_meta | delete | ❌ | — | md 双写目标 + image + meta 全清(5.15 肌酸丢 guard) |
| **D8** | test_check_rejects_future_and_catalog_is_writable_window | 同 D2 | 🔴 | — | 跟 D2 同源(未来 reject + catalog is_writable) |
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

## P1 · setup / 钥匙 / 模型(低风险,纯契约对齐)

oracle:`tests/test_setup_routes.py`(21 条)。mobile 已 shim setup/status·current·save·save-partial·test·models。

| id | 契约 | 状态 | sha | 备注 |
|----|---|---|---|---|
| S1 | test_status_{no_config,all_placeholder,configured} | ❌ | — | configured 三态 |
| S2 | test_current_shape | ❌ | — | 字段形状 |
| S3 | test_save_{autogenerates_id,builds_cfg,rejects_empty,rejects_all_placeholder} | ❌ | — | id 生成 + 占位符拒 |
| S4 | test_save_partial_updates_and_clears | ❌ | — | 空值删字段 |
| S5 | test_models_default_id | ❌ | — | |
| S6 | test_setup_test_* / test_test_baidu_* / test_test_gemini_* | ❌ | — | 测 key(mobile 是否做"测连通"?不做标 OUT) |

---

## OUT OF SCOPE(loop 跳过,别浪费轮次)

- **chat tool loop**(`test_chat_routes.py` 15 条)—— mobile chat 是 thin SSE wrapper 无 tool loop,**独立产品形态**,不按 parity 迁(要让手机 AI 写日记/打卡是另一个设计任务)。
- **board / 留言板 eval**(`test_board_routes.py` 11 条)—— desktop-only,移动不渲染。
- **desktop-内部 tripwire**(daily-tasks 的 llm_tool_check_stays_wired / corrupt_meta_rings / vault_audit / vault_repair / template_task / manage_daily_task / check_non_int_500)—— 守桌面*抽取*的,不是移动行为契约。

---

## 收敛记录

_(loop 收敛时在此写 `PARITY CONVERGED @ <sha> @ <date>` + 剩余 OUT/已知不可迁项)_
