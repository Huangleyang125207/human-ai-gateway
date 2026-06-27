# 移动端交互测试用例 · 真 click → 预期效果

> 给 iOS simulator 真跑的**交互层 spec**(XcodeBuildMCP `tap`/`snapshot_ui`/`screenshot` 驱动)。
> 扫 PC 契约(handler + characterization 断言 = 预期效果真相)× 移动 UI(`mobile/m` = tap 目标)生成。
> 配套:`TEST_FIRST_MIGRATION.md`(范式)· `mobile/parity/golden/`(契约底座)· `PARITY_LEDGER.md`(endpoint key)。

## 两层模型(为什么是交互层,不是 API 层)

```
交互层(本文件 · case 本体)   真 tap → 屏幕效果 + plist 落账 + 截图   ← 这才是"feature 存在"
        ↑ 撑在 ↑
契约层(golden · 数据底座)    callApi → md/plist 字节        ← 证"引擎对",快、CI 能跑
```

- **交互层**先于一切:`callApi(golden.input)` 跳过 UI 事件 + 重渲染,只验后端引擎;**真 click** 才验"用户点了到底对不对"。
- 每个 case 的**预期效果**分三可观测:① `snapshot_ui` 能断言的屏幕元素态 ② plist/Preferences 落账 ③ 截图回归点。
- **契约底座**:这次交互最终落的字节,必须 == 对应 `mobile/parity/golden/` 文件(否则两端 md 分叉,git 合不了)。

## 怎么读一个 case

| 字段 | 含义 |
|---|---|
| 用户故事 | 用户在屏幕上想干嘛 |
| 前置 seed | 设备初态(plist/md 该摆成啥),照着摆 |
| 操作(真 click) | 点哪个 `mobile/m` 元素 + 什么手势;`[UI待建]`=该交互 UI 还没做 |
| ① 屏幕 | `snapshot_ui`/`describe_ui` 可机器断言的元素态 |
| ② 存储 | plist/Preferences 哪个 key 变成啥 |
| ③ 截图 | 肉眼/diff 该看到的视觉变化 |
| 契约底座 | 该交互最终字节 == 哪个 golden |
| 负例 | 错误输入在 UI 上该表现成啥(不能静默) |

**★Cannot-break** = 事故护栏 case(authorship / 补卡窗口 / CAS / cutout / delete 级联…),迁移时这些必先绿。

---

## 执行 checklist(迁移逐条勾)

| case | 簇 | ★ | UI | 契约底座 golden |
|---|---|---|---|---|
| `journal_today__read_timeline` | journal |  | 已建 | 无独立 golden |
| `journal_days__date_band` | journal |  | 已建 | 无字节 golden;契约对齐 test_days_lists_files |
| `journal_insert__nib_new_entry` | journal |  | 已建 | mobile/parity/golden/journal__insert_stamps_user |
| `journal_insert__no_journal_404` | journal |  | 待建 | mobile/parity/golden/journal__insert_no_journal. |
| `journal_edit__tap_entry_patch` | journal |  | 已建 | 对齐 test_patch_http_user_can_patch_ai_block |
| `journal_edit__user_patches_ai_block` | journal |  | 已建 | 对齐 test_patch_http_user_can_patch_ai_block |
| `journal_authorship__ai_refuses_user_block` | journal |  | 已建 | mobile/parity/golden/journal__patch_ai_refuses_u |
| `journal_authorship__ai_allows_ai_block` | journal |  | 已建 | mobile/parity/golden/journal__patch_ai_allows_ai |
| `journal_h2guard__ai_rename_blocked` | journal |  | 已建 | mobile/parity/golden/journal__patch_h2_rename_bl |
| `journal_h2guard__ai_rename_allowed` | journal |  | 已建 | mobile/parity/golden/journal__patch_h2_rename_al |
| `journal_delete__swipe_clear_block` | journal |  | 已建 | mobile/parity/golden/journal__delete_clears.md |
| `journal_delete__undo_restores` | journal |  | 已建 | 无独立 golden;往返应回到 journal__delete_clears 的反向 |
| `journal_delete__unknown_time_404` | journal |  | 待建 | 无独立 golden |
| `journal_append__add_content_to_block` | journal |  | 已建 | 对齐 test_append_comment_preserves_original_body |
| `journal_strike__toggle_struck` | journal |  | 已建 | 无 golden |
| `journal_readonly__past_day_no_write` | journal |  | 已建 | 无字节 golden |
| `journal_patch__routes_by_date_not_today` | journal |  | 已建 | mobile/parity/golden/journal__patch_by_date.md |
| `journal_patch__missing_new_md_400` | journal |  | 待建 | mobile/parity/golden/journal__patch_missing_newm |
| `journal_newday__create_then_idempotent` | journal |  | 已建 | mobile/parity/golden/journal__new_day_26.6.22.md |
| `journal_tagstats__suggest_chips` | journal |  | 已建 | mobile/parity/golden/journal__tag_stats_default. |
| `tag_register__add_project_tag` | journal |  | 待建 | mobile/parity/golden/journal__tag_register.aggre |
| `tag_aggregate__view_sections` | journal |  | 待建 | mobile/parity/golden/journal__tag_aggregate_get. |
| `daily_tasks__catalog_fresh` | daily-tasks |  | 已建 | mobile/parity/golden/daily_tasks__catalog_fresh. |
| `daily_tasks__check_default_dose1` | daily-tasks |  | 已建 | mobile/parity/golden/daily_tasks__check_default_ |
| `daily_tasks__check_clamp` | daily-tasks | ★ | 待建 | mobile/parity/golden/daily_tasks__check_clamp.re |
| `daily_tasks__check_decrement_unchecks` | daily-tasks |  | 待建 | mobile/parity/golden/daily_tasks__check_decremen |
| `daily_tasks__check_backfill_yesterday_ok` | daily-tasks | ★ | 待建 | mobile/parity/golden/daily_tasks__check_backfill |
| `daily_tasks__check_backfill_yesterday_closed` | daily-tasks | ★ | 已建 | mobile/parity/golden/daily_tasks__check_backfill |
| `daily_tasks__check_rejects_future` | daily-tasks | ★ | 已建 | mobile/parity/golden/daily_tasks__check_rejects_ |
| `daily_tasks__check_non_int_intake` | daily-tasks | ★ | 已建 | mobile/parity/golden/daily_tasks__check_non_int_ |
| `daily_tasks__water_drag_fill` | daily-tasks |  | 已建 | 无独立 water golden response |
| `daily_tasks__catalog_writable_yesterday` | daily-tasks | ★ | 已建 | mobile/parity/golden/daily_tasks__catalog_writab |
| `daily_tasks__catalog_writable_tomorrow` | daily-tasks | ★ | 已建 | mobile/parity/golden/daily_tasks__catalog_writab |
| `daily_tasks__meta_set` | daily-tasks |  | 待建 | mobile/parity/golden/daily_tasks__meta_set.respo |
| `daily_tasks__meta_non_int` | daily-tasks |  | 待建 | mobile/parity/golden/daily_tasks__meta_non_int_t |
| `daily_tasks__meta_clear_pills` | daily-tasks |  | 待建 | mobile/parity/golden/daily_tasks__meta_clear_pil |
| `daily_tasks__delete_cascade` | daily-tasks | ★ | 待建 | mobile/parity/golden/daily_tasks__delete_cascade |
| `daily_tasks__history_oldest_first` | daily-tasks |  | 待建 | mobile/parity/golden/daily_tasks__history_oldest |
| `daily_tasks__water_cup_post` | daily-tasks |  | 待建 | mobile/parity/golden/daily_tasks__water_cup_post |
| `daily_tasks__task_set_image` | daily-tasks |  | 待建 | 无独立 set-image golden |
| `daily_tasks__want_new_task` | daily-tasks |  | 已建 | mobile/parity/golden/daily_tasks__template_task_ |
| `daily_tasks__backfill_progress` | daily-tasks |  | 已建 | mobile/parity/golden/daily_tasks__backfill_progr |
| `thread__send_message_streams_and_persists` | thread |  | 已建 | mobile/parity/golden/thread__save_fresh_writes.h |
| `thread__history_load_happy_on_launch` | thread |  | 已建 | mobile/parity/golden/thread__history_happy_retur |
| `thread__history_corrupt_shows_restore_modal` | thread | ★ | 待建 | mobile/parity/golden/thread__history_corrupt_mod |
| `thread__restore_from_bak_roundtrip` | thread | ★ | 待建 | mobile/parity/golden/thread__restore_from_bak_ro |
| `thread__save_stale_rejected_409` | thread | ★ | 待建 | mobile/parity/golden/thread__save_stale_409.resp |
| `thread__point_entry_into_chat` | thread |  | 已建 | mobile/parity/golden/thread__save_fresh_writes.h |
| `thread__attach_image_then_send` | thread |  | 已建 | mobile/parity/golden/thread__save_fresh_writes.h |
| `thread__tool_chip_three_states` | thread |  | 已建 | mobile/parity/golden/thread__save_fresh_writes.h |
| `cutout__writes_image_map_meta_and_ocr_pill_count` | image 簇 | ★ | 待建 | mobile/parity/golden/cutout__writes_image_map_me |
| `cutout__respects_existing_total_pills_PARITY_HOLE` | image 簇 | ★ | 待建 | mobile/parity/golden/ [缺] 需新增 cutout__respects_e |
| `vision_classify__delegates_and_echoes_question` | image 簇 | ★ | 已建 | mobile/parity/golden/vision__classify_delegates_ |
| `attachments__delete_removes_file_and_index_DATALOSS` | image 簇 | ★ | 待建 | mobile/parity/golden/attachments__delete_removes |
| `get_attachment__serves_bytes_and_path_guard` | image 簇 | ★ | 待建 | mobile/parity/golden/get_attachment__serves_byte |
| `attachments__list_sorted_desc_with_limit` | image 簇 |  | 待建 | mobile/parity/golden/attachments__list_sorted_de |
| `attachments__list_date_filter` | image 簇 |  | 待建 | mobile/parity/golden/attachments__list_date_from |
| `attachments__search_filename_original_ocr` | image 簇 |  | 待建 | mobile/parity/golden/attachments__search_q_yuyou |
| `attachments__reindex_missing_skips_existing` | image 簇 |  | 待建 | mobile/parity/golden/attachments__reindex_index_ |
| `chat_upload_image__dedup_and_logical_url` | image 簇 | ★ | 待建 | mobile/parity/golden/ [缺] 需新增 chat_upload_image_ |
| `scrapbook_place_sticker__anchor_to_entry` | image 簇 | ★ | 待建 | mobile/parity/golden/ [缺,image 簇暂无 scrapbook gol |
| `scrapbook_delete_sticker` | image 簇 | ★ | 待建 | mobile/parity/golden/ [缺] 需新增 scrapbook__delete. |
| `uploads_search_via_chat_curator` | image 簇 |  | 已建 | mobile/parity/golden/ [缺] 需新增 uploads__search_cu |
| `config_key_unlocks_image_powers` | image 簇 | ★ | 已建 | mobile/parity/golden/ [缺,属 setup 簇但 gating image |

---

## journal (单日页日记读写 + tag-aggregate)

> **UI 概况**:移动单日页 UI 在 /Users/claudecodedezhuanshumac/human-ai-dev/gateway/mobile/m/ —— 入口 index.html(冷启动 await GW.bridgePrefetch() 拉真数据后 GW.mount)。可点元素分布:① gw-journal.js:时间线 .gw-timeline > .gw-entry-wrap > .gw-entry(短tap=openCard编辑 / 长按>480ms=.gw-sheet action sheet[改一块/加内容/划掉收纸/贴图/指给AI看] / 左滑>60px=撕痕删除露 .gw-entry-del→deleteEntry+ .gw-undo 5s撤回);编辑信笺 .gw-card(.gw-chips标签 / .gw-time-in时分 / .gw-time-quick[现在/整点/半] / .gw-title-in / .gw-body-in / .gw-save落笔)。② gw-app.js:右下悬浮 .gw-nib「提笔」→openCard新建;顶部 .gw-dateband > .gw-day(today带朱印seal / past / creatable带「+」/ locked)→pickDay(locked拦截whisper『最多到明天』、creatable建空骨架);st.readonly(过去日)时 buildEntry 不 wireEntryGestures。真持久化不在 UI 层 —— UI 改 GW.journal 内存后 emit bus『reloadDay』→ gw-real-bridge.js syncJournalDiff diff 出增/删/改 → POST /api/journal/insert-block|delete-block|patch(全 author:'user',composeEntryMd 拼回 commits)。AI 写型(patch/insert/append-comment)走对话 tab .gw-chatbar→/api/chat SSE→tool chip .gw-chip-tool 三态(doing/ok/fail),dispatchTool 注入 author:'ai'(authorship 403 + H2-guard 409 只在此路径触发)。对应 handler 全在 mobile-api.js(忠实复刻 server.py:authorship boundary/H2-mismatch guard/missing-new_md 400/no-file 404/date 路由)。缺口标记:[UI待建] = 聚合页注册/浏览 UI、空 time 校验反馈、no-journal 404 的乐观回滚、readonly 日 .gw-nib 仍可点(误写过去日)、creatable 只建内存未调 new-day、struck 态无持久化(纯 UI 刷新即丢)。

### `journal_today__read_timeline`

**用户故事**:用户打开 app 默认看到今天的日记时间线,各时间块按时间升序排列

- **前置 seed**:设备 gw/journal/<today-iso>.md 存在,内容含两块:`# 9：00\n\n## #思考 早醒 @user\n昨晚睡得晚。\n\n# 10：00\n\n## #投资 KV cache @ai\n推 RDMA 思路。`(对齐 test fixture JOURNAL_MD)。无 md 则 prefetch 兜底 mock,需先 seed
- **操作(真 click)**:冷启动 app(index.html 自动 await GW.bridgePrefetch() → GET /api/journal/today?date=<today> → flatten blocks 进 GW.journal[dayKey] → GW.mount)。默认 tab=journal,无需 tap;若不在日记页,tap 顶栏「日记」tab
- **预期效果**:
  - ① 屏幕:snapshot_ui 在 .gw-timeline 下能查到 2 个 .gw-entry-wrap;第一个 .gw-entry .gw-entry-time 显示 09/00、.gw-entry-tag 含「#思考」、.gw-entry-author 含「@我」、body 含「早醒/昨晚睡得晚」;第二个 time 10/00、tag「#投资」、author「@ai」、body 含「推 RDMA 思路」。entries 按 time.localeCompare 升序(9:00 在 10:00 之前)
  - ② 存储:纯读,plist/IndexedDB(gw/journal/<today>.md)不变
  - ③ 截图:两张纸感 entry 卡纵向排列,左侧时分大字 09/00 与 10/00,@user 块用宋体、@ai 块标记区分
- **契约底座**:无独立 golden(读路径);blocks 结构对齐 test_today_returns_blocks(date==today + blocks 含「早醒」)
- **负例/边界**:当天无 md 文件:GET /api/journal/today 返 {error:'no journal file'};UI 应渲染 .gw-empty「这一天还是空白」而不是崩白屏

### `journal_days__date_band`

**用户故事**:用户在日期带上看到最近可读的日期,能横向滑动选日

- **前置 seed**:gw/journal/ 下有今天 + 至少一个过去日期的 md(如 today 与 today-3)。对齐 test_days_lists_files(2 个文件 → days 长度 2)
- **操作(真 click)**:进日记 tab → 顶部 .gw-dateband 自动 buildDateband(GET /api/journal/days?n=10);横向 swipe .gw-dateband 滚动;tap 某个 .gw-day 按钮(过去日期那颗,带 .past)
- **预期效果**:
  - ① 屏幕:snapshot_ui:.gw-dateband 下每个存在的日期一个 .gw-day,今天那颗有 .today 类 + .gw-day-seal;tap 过去那颗后它得 .sel 类,时间线 reload 成该日 entries。.gw-day-dow 显示星期、.gw-day-num 显示日号
  - ② 存储:纯读;不写
  - ③ 截图:水平日期 pill 条,今天有朱印 seal,选中日 high­light
- **契约底座**:无字节 golden;契约对齐 test_days_lists_files(days 数量 == md 文件数)。GET /api/journal/days 返 {days:[...iso]}
- **负例/边界**:days 接口失败:bridge catch → 沿用 mock days,console.warn,不崩;UI 仍可见至少今天那颗

### `journal_insert__nib_new_entry`

**用户故事**:用户点悬浮提笔按钮,在今天写一条新时间块条目

- **前置 seed**:今天 md 存在(如只有 9:00/10:00 两块)。device 当前时间决定预填 hh:mm(card 默认现在时间 floor 到半点)
- **操作(真 click)**:tap 右下悬浮 .gw-nib(aria-label「提笔写一段」)→ 升起 .gw-card(kicker「提笔 · 写一块」)→ tap 时间 .gw-time-quick「现在」或手填 .gw-time-in hh/mm = 11:00 → tap #标签 chip 选「#工作」→ .gw-title-in 输入「新条目」→ .gw-body-in 输入「正文」→ tap .gw-save「落笔」
- **预期效果**:
  - ① 屏幕:保存后 .gw-card 消失,GW.whisper 显示「已落笔 · 写进 11:00」;时间线新增一个 .gw-entry-wrap,.gw-entry-time=11/00、tag「#工作」、title「新条目」、author「@我」
  - ② 存储:reloadDay → syncJournalDiff 检出新 id → POST /api/journal/insert-block {date:today,time:'11:00',tag:'#工作',title:'新条目',body:'正文'} → gw/journal/<today>.md 追加 `# 11：00\n\n## #工作 新条目 @user\n\n正文\n`(stamp @user 因 HTTP 路径默认 user)
  - ③ 截图:信笺编辑卡从底部升起→保存后收起,时间线尾部多一张 11:00 卡
- **契约底座**:mobile/parity/golden/journal__insert_stamps_user.md(末块 `## #工作 新条目 @user` 字节真相)+ journal__insert_stamps_user.response.json
- **负例/边界**:不填时间直接落笔:time 缺失 → shim POST insert-block 返 400「缺 time」(对齐 test_insert_block_missing_time_400);UI 不该静默成功,应有错误提示且不新增 entry(★[UI待建] 当前 card 时间默认填好难触发,需校验空 time 路径的 UI 反馈)

### `journal_insert__no_journal_404`

**用户故事**:用户在一个还没有 md 文件的日期试图新建条目(边界)

- **前置 seed**:目标日期 gw/journal/<iso>.md 不存在(例如尚未 new-day 的某天)
- **操作(真 click)**:切到该无文件日期 → tap .gw-nib → 填时间+正文 → tap .gw-save
- **预期效果**:
  - ① 屏幕:[UI待建] 当前 UI 乐观新增 entry 但后端 404,会产生 UI 与持久化不一致;应有的元素:保存失败后回滚该 entry + whisper「这天还没有日记,先创建」。snapshot_ui 应最终不含该 entry
  - ② 存储:POST /api/journal/insert-block 返 404 {ok:false,error:'no journal file for <iso>'};md 不被创建
  - ③ 截图:失败提示纸条,时间线无新增
- **契约底座**:mobile/parity/golden/journal__insert_no_journal.response.json(404 契约,对齐 test_insert_block_no_journal_404)
- **负例/边界**:本 case 本身即负例;关键断言 = UI 不能把乐观条目留在屏上骗用户

### `journal_edit__tap_entry_patch`

**用户故事**:用户点一条已有条目,改它的标题/正文/标签

- **前置 seed**:今天 md 含可写 entry,如 9:00 `## #思考 早醒 @user\n昨晚睡得晚。`。非 readonly(今天)
- **操作(真 click)**:tap 9:00 那张 .gw-entry(短 tap,非长按非滑)→ 升起 .gw-card(kicker「改这一块」,时间输入 readonly 锁定)→ 改 .gw-body-in 为「改了」→ tap .gw-save「改完」
- **预期效果**:
  - ① 屏幕:card 关闭,whisper「改好了 · 写进 9:00」;该 entry .gw-entry-body 更新为「改了」,time/tag 不变
  - ② 存储:reloadDay → syncJournalDiff 检出 body 变化 → POST /api/journal/patch {date:today,time:'9:00',new_md:composeEntryMd(含 @user + commits 拼回),author:'user'} → gw/journal/<today>.md 中 9:00 块 body 替换为「改了」,原 @user marker + commits 保留
  - ③ 截图:entry 卡正文文字变化
- **契约底座**:对齐 test_patch_http_user_can_patch_ai_block(HTTP=user 可改)+ composeEntryMd 拼 commits(6.16 教训);patched 响应对齐 journal__patch_by_date.response.json 结构
- **负例/边界**:composeEntryMd 漏拼 commits → @ai 批注被 patch 整段替换丢掉(6.16 真 bug);断言:patch 后 md 仍含原 `- #commit (...)` 行

### `journal_edit__user_patches_ai_block`

**用户故事**:用户点一条 AI 写的条目并接管修改(user 是最高权威)

- **前置 seed**:今天 md 含 10:00 `## #投资 KV cache @ai\n推 RDMA 思路。`
- **操作(真 click)**:tap 10:00 那张 @ai entry → .gw-card「改这一块」→ 改正文为「人接管了」→ tap .gw-save
- **预期效果**:
  - ① 屏幕:card 关闭 + whisper;10:00 entry body 变「人接管了」;不弹任何 authorship 拒绝提示(user 改 @ai 合法)
  - ② 存储:POST /api/journal/patch {time:'10:00',author:'user',...} 成功(200);gw/journal md 10:00 块 body 改写。★关键:HTTP/UI 路径 author 恒 'user' → 不触发 403
  - ③ 截图:@ai 卡正文被人手内容替换
- **契约底座**:对齐 test_patch_http_user_can_patch_ai_block(J10)+ test_patch_block_user_can_patch_ai_block(helper T4)
- **负例/边界**:若 UI 误把 author 传成 'ai' 改 @user 块 → 应 403;此 case 验正向(user 改 ai 必通)

### `journal_authorship__ai_refuses_user_block`

**用户故事**:AI 在对话里被要求改用户写的块,必须被拒(★Cannot-break authorship 边界)

- **前置 seed**:今天 md 含 9:00 `## #思考 早醒 @user`;DeepSeek key 已配,chat 可触发 patch_journal_block tool
- **操作(真 click)**:切到对话 tab → .gw-chatbar 输入框输入「把 9:00 那条改成 XXX」→ tap 发送 → AI 走 /api/chat SSE → emit tool_call patch_journal_block(dispatchTool 注入 author='ai')
- **预期效果**:
  - ① 屏幕:对话流出现 .gw-chip-tool patch_journal_block,状态最终 = fail(三态 doing→fail);AI 文字应转述「这是你写的块,我不能改,可加评论」。snapshot_ui:.gw-chip-tool[data-state=fail]
  - ② 存储:POST /api/journal/patch {author:'ai',time:'9:00'} 返 403;gw/journal md 的 9:00 块字节**完全不变**(早醒/昨晚睡得晚 原样)
  - ③ 截图:tool chip 显红/失败态,日记 9:00 卡无变化
- **契约底座**:mobile/parity/golden/journal__patch_ai_refuses_user.result.json(403 error 文案)+ journal__patch_ai_refuses_user.md(md 不变字节)
- **负例/边界**:本 case 即 ★Cannot-break 负例核心:断言 md 字节零变化 + 403 + tool chip fail;若 AI 成功覆盖 = 事故

### `journal_authorship__ai_allows_ai_block`

**用户故事**:AI 改自己之前写的 @ai 块,允许通过

- **前置 seed**:今天 md 含 10:00 `## #投资 KV cache @ai`;chat 可用
- **操作(真 click)**:对话 tab 输入「重写 10:00 那条 @ai 块」→ 发送 → AI emit patch_journal_block(author='ai',同 H2 或带 allow_h2_rename)
- **预期效果**:
  - ① 屏幕:.gw-chip-tool patch_journal_block 状态 = ok(三态 ok);10:00 entry body 更新
  - ② 存储:POST /api/journal/patch {author:'ai',time:'10:00'} 成功;md 10:00 块 body 替换,旧 body「推 RDMA 思路」消失
  - ③ 截图:tool chip 绿/成功,10:00 卡正文更新
- **契约底座**:mobile/parity/golden/journal__patch_ai_allows_ai.md + .result.json(对齐 helper test_patch_block_ai_allows_ai_block T3)
- **负例/边界**:若 AI 同时改了 H2 标题但没传 allow_h2_rename → 落到 H2-guard 409(见下一 case)

### `journal_h2guard__ai_rename_blocked`

**用户故事**:AI 误把 patch 当 insert,改了 @ai 块的 H2 标题但没声明 rename(★Cannot-break H2-guard,5.29 事故反向防御)

- **前置 seed**:今天 md 含 17:00 `## #探索 小红书 AI 产业链预警 @ai\n\n把昨天讨论的 capex...`(对齐 test_patch_h2_rename fixture)
- **操作(真 click)**:对话 tab 输入触发 AI patch 17:00 块、new_md 第一行 H2 改成不同标题(如「小红书牛奶 Omega-3 科普」)且 allow_h2_rename 缺省/false → 发送
- **预期效果**:
  - ① 屏幕:.gw-chip-tool patch_journal_block 状态 = fail;AI 文字应说明 H2 不一致被拒、提示用 insert 或传 allow_h2_rename。snapshot_ui:.gw-chip-tool[data-state=fail]
  - ② 存储:POST /api/journal/patch 返 409 {conflict:true,error:含「已有 H2」};gw/journal md 17:00 块**整段不变**(原标题 + 原 capex 正文都在)
  - ③ 截图:tool chip 失败,17:00 卡原样
- **契约底座**:mobile/parity/golden/journal__patch_h2_rename_blocked.md(原块字节不变)+ journal__patch_h2_rename_blocked.result.json(409 含「已有 H2」)
- **负例/边界**:本 case 即负例;断言 md 字节零变化 + 409 + chip fail。对照 allowed 版必须放行(下一 case)

### `journal_h2guard__ai_rename_allowed`

**用户故事**:用户明示让 AI 改标题,AI 传 allow_h2_rename=true,放行

- **前置 seed**:同上 17:00 `## #探索 小红书 AI 产业链预警 @ai`
- **操作(真 click)**:对话 tab 输入「把 17:00 的标题改成 小红书牛奶 Omega-3 科普」→ AI emit patch_journal_block(allow_h2_rename=true,author='ai')
- **预期效果**:
  - ① 屏幕:.gw-chip-tool 状态 = ok;17:00 entry .gw-entry-title 更新为新标题
  - ② 存储:POST /api/journal/patch {allow_h2_rename:true} 成功;gw/journal md 17:00 块 `## #探索 小红书牛奶 Omega-3 科普 @ai` 写入,原标题被替换
  - ③ 截图:17:00 卡标题文字变化
- **契约底座**:mobile/parity/golden/journal__patch_h2_rename_allowed.md + journal__patch_h2_rename_allowed.result.json(对齐 test_patch_allows_h2_rename_with_flag)
- **负例/边界**:缺 allow_h2_rename → 退回 409(blocked case);本 case 验 flag 真放行 + 真写字节

### `journal_delete__swipe_clear_block`

**用户故事**:用户左滑一条目把整个时间块删空(回占位)

- **前置 seed**:今天 md 含 9:00(早醒)+ 10:00(KV cache)两块;非 readonly
- **操作(真 click)**:在 9:00 那张 .gw-entry 上向左 swipe 超过 SWIPE_TRIG(60px,露出 .gw-entry-del「松手 · 收纸」)→ 松手触发 GW.deleteEntry
- **预期效果**:
  - ① 屏幕:9:00 entry 飞出(translateX -110%)消失;底部弹 .gw-undo「已删除『早醒…』」+ .gw-undo-btn「撤回」+ 5s 进度条 .gw-undo-bar;10:00 entry 不动
  - ② 存储:reloadDay → syncJournalDiff 检出 id 消失 → POST /api/journal/delete-block {date:today,time:'9:00'} → gw/journal md 中 9:00 块清成占位 `# 9：00\n\n##\n`,10:00 块原样保留
  - ③ 截图:9:00 卡撕痕滑出 + 撤回纸条浮起;10:00 卡留存
- **契约底座**:mobile/parity/golden/journal__delete_clears.md(9:00 清空、10:00 保留字节)+ journal__delete_clears.response.json(对齐 test_delete_block_clears_to_placeholder)
- **负例/边界**:swipe 距离不足 60px:row.style.transform 归零回弹,不删,不发 POST;断言 entry 仍在 + md 不变

### `journal_delete__undo_restores`

**用户故事**:用户删错了,5 秒内点撤回把条目找回

- **前置 seed**:刚完成上一个 swipe 删除,.gw-undo 撤回纸条还在(5s 窗内)
- **操作(真 click)**:在 .gw-undo 还可见时 tap .gw-undo-btn「撤回」
- **预期效果**:
  - ① 屏幕:被删 entry 重新出现在原 idx 位置(arr.splice 还原);.gw-undo 消失。snapshot_ui:9:00 entry 回到 .gw-timeline
  - ② 存储:★注意当前实现:撤回只在 GW.journal 内存还原 + emit reloadDay → syncJournalDiff 会把还原的 entry 当『新增』再 POST insert-block(因 snap 已无它)→ 净效果 md 恢复有内容。需验最终 gw/journal md 9:00 块内容回来(可能 author 变 @user/丢原 commits = [UI待建] 真删-撤回往返字节一致性的隐患点)
  - ③ 截图:撤回后 9:00 卡复现
- **契约底座**:无独立 golden;往返应回到 journal__delete_clears 的反向(内容恢复);此 case 暴露撤回-重insert 是否字节保真的 parity 风险
- **负例/边界**:超过 5s 才点:撤回纸条已 hideUndo 移除,无法点;此时删除已 commit,md 维持占位

### `journal_delete__unknown_time_404`

**用户故事**:删除一个不存在的时间块(边界/防御)

- **前置 seed**:今天 md 不含 23:30 块
- **操作(真 click)**:[UI待建] 正常 UI 只能滑删可见 entry,触发不到不存在的块;此路径由 bridge diff 异常或 AI tool 触发。模拟:对话让 AI 删 23:30 或直接 POST delete-block time=23:30
- **预期效果**:
  - ① 屏幕:无 entry 被移除;若 AI 路径,.gw-chip-tool 显 fail / whisper 提示未找到
  - ② 存储:POST /api/journal/delete-block {time:'23:30'} 返 404 {error:'not found'};md 字节不变
  - ③ 截图:时间线无变化
- **契约底座**:无独立 golden(delete unknown 在 PC 走 404,对齐 test_delete_block_unknown_time_404);mobile shim 返 404
- **负例/边界**:本 case 即负例:断言 404 + md 零变化,UI 不能假装删成功

### `journal_append__add_content_to_block`

**用户故事**:用户长按一条目选『加内容』,在原块尾追加一段

- **前置 seed**:今天 md 含 9:00 `## #思考 早醒 @user\n昨晚睡得晚。`;非 readonly
- **操作(真 click)**:长按 9:00 .gw-entry(>480ms 触发 .longpress + haptic)→ 升起 .gw-sheet → tap .gw-sheet-item[data-act=append]「加内容」→ .gw-card(kicker「加一段 · 接着写」,body 空白)→ 输入「补一句」→ tap .gw-save
- **预期效果**:
  - ① 屏幕:card 关闭;9:00 entry body 变为原文 + 换行 + 「补一句」(ent.body += '\n\n补一句');snapshot_ui:.gw-entry-body 同时含「昨晚睡得晚」「补一句」
  - ② 存储:reloadDay → body 变化走 patch(非 append-comment)→ POST /api/journal/patch {time:'9:00',author:'user',new_md 含追加段};md 9:00 块 body 增补,@user 保留。★注意 UI『加内容』走 patch 整块重写而非 PC 的 _append_comment_to_block,需验 commits/原文不丢
  - ③ 截图:9:00 卡正文变长
- **契约底座**:对齐 test_append_comment_preserves_original_body(原文一字不动语义);mobile/parity/golden/journal__append_comment.md 是 AI append-comment 路径字节;UI append 走 patch 路径需保同等『原文不丢』
- **负例/边界**:若 patch 重写时漏带原 body 行 → 原文被吃;断言追加后『昨晚睡得晚』仍在

### `journal_strike__toggle_struck`

**用户故事**:用户长按条目选『划掉收纸』,把它标记为划除(留痕不删)

- **前置 seed**:今天 md 含某 entry;非 readonly
- **操作(真 click)**:长按 .gw-entry → .gw-sheet → tap [data-act=strike]「划掉收纸」(再次操作显示『撤销划掉』)
- **预期效果**:
  - ① 屏幕:entry .gw-entry 加 .struck 类(划线视觉);whisper「已划掉收纸 · 痕迹留着」。再次 strike → 移除 .struck + whisper「划痕已抹去」
  - ② 存储:★当前实现:entry.struck 只在 GW.journal 内存切换 + emit reloadDay,**不映射到任何 md 字段/endpoint**;gw/journal md 不变。[UI待建/契约缺口]:划除态无持久化,刷新即丢;PC 无对应 struck 契约
  - ③ 截图:entry 文字带删除线,卡片略灰
- **契约底座**:无 golden(struck 是纯 UI 态,无 PC 契约);本 case 记录该 parity 缺口
- **负例/边界**:刷新 app 后 struck 态丢失(因未持久化)— 断言此为已知缺口,非『删除』,不能误当真删

### `journal_readonly__past_day_no_write`

**用户故事**:用户翻到过去某天查看,只读不能改(写操作习语应隐藏/禁用)

- **前置 seed**:gw/journal 有过去日期 md(如 today-3),其 day.state='past'
- **操作(真 click)**:date band tap 过去那颗 .gw-day → pickDay 设 st.dayKey + render → dayState='past' → st.readonly=true → renderTimeline(buildEntry 不调 wireEntryGestures)
- **预期效果**:
  - ① 屏幕:过去日 entries 渲染但 tap/长按/左滑全不响应(无 .gw-card 升起、无 .gw-sheet、无 swipe 删);snapshot_ui:.gw-entry 存在但无手势反馈。★[UI待建/缺口]:.gw-nib 悬浮提笔在 readonly 仍渲染且 click→openCard,会让用户在过去日新增 → 应隐藏或禁用 nib
  - ② 存储:只读浏览不产生任何 POST;若 nib 缺口被触发会误 insert 到过去日 md(date 路由会写对那天,但违反『过去只读』产品意图)
  - ③ 截图:过去日时间线静态展示,无编辑入口(理想态 nib 消失)
- **契约底座**:无字节 golden(readonly 是前端 gating);date 写入正确性由 patch-by-date 契约保证
- **负例/边界**:在 readonly 日尝试左滑:gestures 未 wire → 无反应,正确;但 nib 仍可点 = 缺口,需断言 readonly 时 .gw-nib 不存在或 disabled

### `journal_patch__routes_by_date_not_today`

**用户故事**:用户在历史日期视图编辑一条目,内容必须落到那天的 md,不能打到今天(★Cannot-break date 路由)

- **前置 seed**:只创建过去某天(today-5)的 md 含 10:00 块;今天 md **不存在**(对齐 test_patch_routes_by_date_not_today)。该日需可写场景(若纯 readonly 则用 AI tool 带 date 触发)
- **操作(真 click)**:date band 切到 today-5 → tap 10:00 entry 编辑 → 改正文「改过去」→ 保存(或对话 AI patch 带 date=today-5)。syncJournalDiff 用该 day 的 iso 发 POST
- **预期效果**:
  - ① 屏幕:today-5 的 10:00 entry body 更新为「改过去」;切回今天时今天仍为空/无该内容
  - ② 存储:POST /api/journal/patch {date:'<today-5 iso>',time:'10:00',new_md:含『改过去』} → gw/journal/<today-5>.md 写入『改过去』;gw/journal/<today>.md **不被创建/不被写**(date 决定目标文件)
  - ③ 截图:过去日卡更新,今天日记不受影响
- **契约底座**:mobile/parity/golden/journal__patch_by_date.md(过去日字节)+ journal__patch_today_not_created.json(今天文件未生成断言;对齐 test_patch_routes_by_date_not_today)
- **负例/边界**:若 UI/bridge 漏传 date 退回 today fallback → 内容打到今天 md 或在过去日找不到块 404;断言:目标必须是 date 对应文件,今天文件保持 null

### `journal_patch__missing_new_md_400`

**用户故事**:patch 请求缺 new_md(边界,防静默通过)

- **前置 seed**:今天 md 含 10:00 块
- **操作(真 click)**:[UI待建] 正常编辑卡保存必带 new_md;此为防御边界,由畸形 AI tool 调用或 bridge bug 触发。模拟:POST /api/journal/patch {time:'10:00'} 不带 new_md
- **预期效果**:
  - ① 屏幕:AI 路径:.gw-chip-tool fail;无 entry 内容变化
  - ② 存储:shim 返 400 {ok:false,error:'缺 new_md'}(对齐 J12 test_patch_missing_new_md_400,堵旧 fallback '' 静默通过);md 不变
  - ③ 截图:无变化
- **契约底座**:mobile/parity/golden/journal__patch_missing_newmd.response.json(400 契约)
- **负例/边界**:本 case 即负例;断言 new_md==null → 400 而非静默 200

### `journal_newday__create_then_idempotent`

**用户故事**:用户为某天(今天或+1)创建空骨架日记;重复创建幂等

- **前置 seed**:目标日期 md 不存在;date band 上该日 state='creatable'(明天 +1)或今天无文件
- **操作(真 click)**:date band tap 标 .creatable 的明天那颗 .gw-day(带 .gw-day-plus「+」)→ pickDay creatable 分支(当前仅内存 GW.journal[key]=[] + whisper「明天已创建」)。真 new-day 落 md 走 POST /api/journal/new-day {date}
- **预期效果**:
  - ① 屏幕:whisper「明天已创建 · 落了张空骨架」;该日变 .sel + .born 动画 1.3s;时间线显示 .gw-empty(空骨架)。★[UI待建/缺口]:pickDay creatable 只建内存,**未调 /api/journal/new-day** → md 文件没真生成;应补发 new-day POST
  - ② 存储:理想:POST /api/journal/new-day {date:'2026-06-22'} → 创建 gw/journal/26.6.22(...).md 含模板骨架,返 {ok:true,created:true};再点同日 → {ok:true,created:false}(幂等)
  - ③ 截图:日期带 +号变选中,空骨架页
- **契约底座**:mobile/parity/golden/journal__new_day_26.6.22.md(骨架字节)+ journal__new_day_create.response.json + journal__new_day_idempotent.response.json(对齐 test_new_day_creates_then_idempotent)
- **负例/边界**:date band tap +2 及以后(state='locked'):pickDay 拦截 → whisper「最多只能建到明天（+1）」,不创建、不发 POST(业务铁律 capped-at-tomorrow)

### `journal_tagstats__suggest_chips`

**用户故事**:用户打开编辑卡时,标签建议来自其历史最常用 tag(新用户给默认)

- **前置 seed**:情形A:空 vault(无任何 tag)→ 默认 5 tag;情形B:md 用过 #思考/#投资
- **操作(真 click)**:tap .gw-nib 或 tap entry → .gw-card 内 .gw-chips 渲染建议 chip(GW.SUGGEST_TAGS,源自 GET /api/journal/tag-stats)
- **预期效果**:
  - ① 屏幕:情形A:.gw-chips 含 5 个默认 chip(工作/饮食/运动/探索/投资 之类,带 default 来源);情形B:chips 含「#思考」「#投资」。snapshot_ui:.gw-chip 文本集合匹配
  - ② 存储:纯读 tag-stats;不写
  - ③ 截图:编辑卡顶部一排可选标签 chip
- **契约底座**:mobile/parity/golden/journal__tag_stats_default.response.json(新用户默认 + default:true;对齐 test_tag_stats_top_and_default_for_new_user)
- **负例/边界**:tag-stats 接口失败:回退 mock SUGGEST_TAGS;chips 仍可见,不空

### `tag_register__add_project_tag`

**用户故事**:用户/AI 注册一个新项目 tag 进标签聚合页

- **前置 seed**:标签聚合.md 存在(如 `# 标签聚合\n\n---\n`);#yanpai 未注册
- **操作(真 click)**:[UI待建] 移动端当前 m/ 无聚合页注册 UI;此交互经 AI tool 或聚合页按钮。模拟:POST /api/tag-aggregate/register {tag:'yanpai'}
- **预期效果**:
  - ① 屏幕:[UI待建] 应有:聚合页『+ 注册标签』入口 → 输入 tag → 提交后列表新增 `## #yanpai` section。当前仅 API 路径
  - ② 存储:标签聚合.md 末尾追加 `## #yanpai` + 空表头 section;vault_git.commit_after_write 触发一次(audit chain)
  - ③ 截图:聚合页多出 #yanpai 分组(UI 建成后)
- **契约底座**:mobile/parity/golden/journal__tag_register.aggregate.md(追加字节)+ journal__tag_register.response.json + journal__tag_register.vgit_count.json(vgit==1;对齐 test_tag_register_appends_and_commits)
- **负例/边界**:重复注册 #yanpai → {ok:false,error:'已经注册过了'};注册带 / 的子标签 #yanpai/传播 → {ok:false,error:'注册 parent tag'}(对齐 test_tag_register_rejects_dup_and_subtag,golden journal__tag_register_dup/subtag.response.json)

### `tag_aggregate__view_sections`

**用户故事**:用户查看按 tag 分组的横切聚合,点行跳到对应日期

- **前置 seed**:标签聚合.md 含 `## #yanpai` + 至少一行带 iso_date 的表格行
- **操作(真 click)**:[UI待建] 进聚合页(移动端待建)→ GET /api/tag-aggregate 渲染 sections;tap 某行 → window.gateway.journal.goto(iso_date) 跳该日日记
- **预期效果**:
  - ① 屏幕:[UI待建] 聚合页按 tag 分 section,每 section 列出 rows;tap row 路由到该 iso 的日记时间线。snapshot_ui:section 标题含『yanpai』、row 可点
  - ② 存储:纯读;不写
  - ③ 截图:聚合页分组列表
- **契约底座**:mobile/parity/golden/journal__tag_aggregate_get.response.json(sections 结构含 tag:'yanpai';对齐 test_tag_aggregate_get_sections)
- **负例/边界**:标签聚合.md 不存在:返 {sections:[],warning:'not found'};UI 应显示空态而非崩

---

## daily-tasks(今日打卡 · 八杯水 · 晨课管理 · 补卡)

> **UI 概况**:移动入口=mobile/m/index.html → GW.mount() 默认开在「日记」tab。daily-task 全部 UI 在 gw-app.js render() 注入的 `<section class="gw-care" id="care">` 里,由 gw-widgets.js 装配:① 八杯水 = `.gw-cups` 内 8 个 `.gw-cup`(SVG 杯,pointer 横滑设水位)② 今日打卡 = `.gw-tasks` 内每 task 一个 `<button class="gw-task">`(含 `.gw-task-name`/`.gw-task-dose`/`.gw-task-disc` ring+check)③ PULSE 行 ④ 心情行。
真后端走 gw-real-bridge.js:prefetch `GET /api/daily-tasks?date=iso` 填 GW.tasks/water;写操作走 bus —— tap 打卡 / 滑水 都 emit('pulse') → 防抖 250ms → syncPulseState():POST `/api/daily-tasks/water {date,filled}` + 逐 task POST `/api/daily-tasks/check {date,task_name,intake}`。
关键 [UI待建] 缺口:① **晨课管理全是假按钮** —— 长按 `.gw-task`(480ms)弹 openTaskSheet(gw-journal.js:224),里头「换图标/改每天几粒/看完成率/删除这项」点了只 whisper『(demo)这一项接 daily-task API』,没接 /meta /delete /water-cup;只有「想要新打卡项」真跳 chat。② **补卡日期没传进 check** —— syncPulseState 永远用 todayIso(),切到 date-band 历史日(`.gw-day`)打卡时 intake 仍写今天,backfill 写操作链未通。③ **/check 子格(daily_dose>=2 的 N 格进度)无独立 tap UI** —— 单 tap 是 0↔dose 整体 toggle,不能 +1 加到中间态(dose>=2 时 dose 显示 `today/dose` 但点一下直接满)。shim 端点齐全(mobile-api.js 1445-1760),UI 是瓶颈。

### `daily_tasks__catalog_fresh`

**用户故事**:打开 app 看到今天的打卡清单,每项显示名字 + 未完成状态

- **前置 seed**:设备 journal/<today> md 存在且顶部段有 `- [ ] 鱼油` `- [ ] 维生素D` 两行;Preferences 无 taskmeta/taskintake/* key(全新)。等价 PC: 今天 md + 空 meta-map/image-map。
- **操作(真 click)**:冷启动 app(GW.mount 自动 bridgePrefetch → GET /api/daily-tasks?date=today),不点任何东西,等 .gw-care 渲染完
- **预期效果**:
  - ① 屏幕:snapshot_ui 在 .gw-tasks 内见 2 个 .gw-task 按钮,.gw-task-name 文案分别为『鱼油』『维生素D』;两按钮均无 .done class(ring 为虚线 dasharray,无 .gw-task-check),.gw-task-dose 显示空白(  非 ✓);八杯水 .gw-cups-foot 的 <b> 为 0
  - ② 存储:无写入(纯读)。Preferences 仍无 taskmeta/* taskintake/* key;journal md 字节不变
  - ③ 截图:care 区两行:八杯水(8 个空杯灰描边)+ 今日打卡两枚未完成 chip(虚线 ring)
- **契约底座**:mobile/parity/golden/daily_tasks__catalog_fresh.response.json(tasks[].checked=false / daily_dose=1 / today_intake=0 / remaining=null / is_writable=true)
- **负例/边界**:date band 点未来日(.gw-day.locked)不应能进入可写态:catalog is_writable=false → 见 daily_tasks__catalog_writable_tomorrow 用例

### `daily_tasks__check_default_dose1`

**用户故事**:点一下某个打卡项,把它勾上(今天吃过了)

- **前置 seed**:今天 md 有 `- [ ] 鱼油`,鱼油 daily_dose=1(默认,无 taskmeta key)。
- **操作(真 click)**:tap 文案为『鱼油』的 .gw-task 按钮一次(短按 <480ms,不移动)→ 触发 toggle() 本地置 today_intake=1 → emit('pulse')→ 250ms 后 POST /api/daily-tasks/check {date:today, task_name:'鱼油', intake:1}
- **预期效果**:
  - ① 屏幕:该 .gw-task 立即加 .done class(snapshot_ui 可查),.gw-task-disc 内出现 .gw-task-check(朱砂勾 svg),ring 变实线(无 dasharray),.gw-task-dose 文案变 ✓;短暂 .confirm class(520ms 内)
  - ② 存储:journal/<today> md 中 `- [ ] 鱼油` → `- [x] 鱼油`(Capacitor Filesystem Directory.Data);Preferences setting/taskintake/鱼油 = {"<today>":1}。等价 PC: 今天 md box 翻 [x] + meta-map intake_log[today]=1
  - ③ 截图:鱼油 chip 实线圆环 + 朱砂对勾,dose 角标 ✓
- **契约底座**:mobile/parity/golden/daily_tasks__check_default_dose1.response.json + daily_tasks__check_default_dose1.md(- [x] 鱼油)
- **负例/边界**:再点一次同 chip → today_intake 回 0 → md 退回 `- [ ]`,taskintake/鱼油 key 被 removeSetting(log 空)

### `daily_tasks__check_clamp`  ★Cannot-break:★intake clamp+子格:超量必夹到 daily_dose,不能写入 >dose(test_check_intake_increment_clamp_and_md_box)

**用户故事**:对一个『每天 2 粒』的项,连点想加到超过 2 粒,应被夹到 2 粒封顶

- **前置 seed**:今天 md 有 `- [ ] 维生素D`;Preferences setting/taskmeta/维生素D = {"daily_dose":2}。等价 PC test_check_intake_increment_clamp daily_dose=2。
- **操作(真 click)**:[UI部分待建] 现 UI:单 tap .gw-task『维生素D』= 整体 toggle 到满(intake=2)。要测真 clamp(intake=5→2)需 [UI待建] 子格 N 连点或剂量步进控件;当前可经 longpress→openTaskSheet 但管理项是 demo 桩。机器层直接 POST /api/daily-tasks/check {task_name:'维生素D', intake:5}
- **预期效果**:
  - ① 屏幕:tap 后 .gw-task 加 .done(2>=2);.gw-task-dose 显示『2/2』(daily_dose>=2 显示 today/dose 而非 ✓);ring 实线 + .gw-task-check 出现
  - ② 存储:journal md `- [x] 维生素D` + dose>=2 时 setSupplementProgress 展开 N 个进度子 box(前 2 个 [x]);Preferences taskintake/维生素D = {"<today>":2}(clamp 后,非 5)。等价 PC _ensure_md_progress_children
  - ③ 截图:维生素D chip done 态,dose 角标『2/2』;md 顶部段展开两个勾选子格
- **契约底座**:mobile/parity/golden/daily_tasks__check_clamp.response.json(today_intake=2 非 5,checked=true)+ daily_tasks__check_clamp.md
- **负例/边界**:increment -1(decrement)→ 1 < 2 → .done 移除,md 退 `- [ ]`,dose 角标『1/2』:见 daily_tasks__check_decrement_unchecks 用例

### `daily_tasks__check_decrement_unchecks`

**用户故事**:对 2 粒项已满,减一粒,应从已完成退回进行中

- **前置 seed**:今天 md 有 维生素D dose=2 且 today_intake=2(已满,md `- [x]`)。
- **操作(真 click)**:[UI待建] 当前无『-1』手势(单 tap 是 toggle 到 0)。应有的元素:dose>=2 chip 上一个『−』子按钮或左滑减格手势。机器层 POST /api/daily-tasks/check {task_name:'维生素D', increment:-1}
- **预期效果**:
  - ① 屏幕:snapshot_ui:.gw-task『维生素D』移除 .done class,ring 回虚线,.gw-task-check 消失,.gw-task-dose 显示『1/2』
  - ② 存储:journal md 维生素D 行 `- [x]`→`- [ ]`(顶层),进度子格变 1 勾 1 空;Preferences taskintake/维生素D = {"<today>":1}
  - ③ 截图:维生素D chip 半完成态,角标『1/2』,一个子格勾一个空
- **契约底座**:mobile/parity/golden/daily_tasks__check_decrement_unchecks.response.json(today_intake=1,checked=false)+ daily_tasks__check_decrement_unchecks.md
- **负例/边界**:intake=0 → taskintake key 整个 removeSetting(当日不再有记录),md 退 `- [ ]`

### `daily_tasks__check_backfill_yesterday_ok`  ★Cannot-break:★补卡窗口闭集:只允许今天+昨天(hour<12),server/shim 端算时区,UI 不自己算(test_check_backfill_window_yesterday_before_noon_else_403)

**用户故事**:昨天忘了打卡,今天上午 12 点前切到昨天补上

- **前置 seed**:昨天 journal/<yesterday> md 存在且有 鱼油 行;设备时钟为今天 11:00(hour<12)。等价 PC test_check_backfill_window 11:00 分支。
- **操作(真 click)**:[UI部分待建] tap 顶栏 date-band 里昨天的 .gw-day pill 切到昨天(gw-app.js dayClick → st.dayKey=yesterday)→ bridge 重拉 catalog;再 tap 『鱼油』.gw-task。**已知 bug**:syncPulseState 硬用 todayIso(),date 不会传昨天 → 需 [UI待建] 让 sync 用 st.dayKey。机器层 POST /api/daily-tasks/check {date:yesterday, task_name:'鱼油', checked:true}
- **预期效果**:
  - ① 屏幕:切到昨天后 .gw-care 处于可写态(非 readonly,无 .gw-care-block.readonly);tap 鱼油 → 该 chip .done;八杯水 .readonly 不应出现(昨天 hour<12 可写)
  - ② 存储:journal/<yesterday> md 鱼油 → `- [x]`;Preferences taskintake/鱼油 = {"<yesterday>":1}。等价 PC meta-map intake_log[yesterday]=1
  - ③ 截图:date band 选中昨天 pill;昨天 care 区鱼油 chip done 态
- **契约底座**:mobile/parity/golden/daily_tasks__check_backfill_yesterday_ok.response.json + .meta.json(intake_log[yesterday]=1)
- **负例/边界**:过了次日 12:00(设时钟 13:00)再切昨天打卡 → 端点 400『不在补卡窗口』,UI 应进只读不接受 tap(见 check_backfill_yesterday_closed)

### `daily_tasks__check_backfill_yesterday_closed`  ★Cannot-break:★补卡窗口闭集对未来/过早日期闭合(test_check_rejects_future_and_catalog_is_writable_window)

**用户故事**:已过次日中午再想补昨天的卡,系统应拒绝

- **前置 seed**:昨天 md 存在;设备时钟今天 13:00(hour>=12)。等价 PC test_check_backfill_window 13:00 分支(403/400)。
- **操作(真 click)**:tap date-band 昨天 .gw-day → bridge GET catalog?date=yesterday 返 is_writable=false → 八杯水/打卡区应渲染 readonly(.gw-care-block.readonly,gw-widgets 据 st.readonly)。再 tap 鱼油 .gw-task — readonly 下 toggle() 早 return 不写。机器层 POST /api/daily-tasks/check {date:yesterday, checked:true}
- **预期效果**:
  - ① 屏幕:snapshot_ui:昨天 care 区 .gw-care-block 带 .readonly class,八杯水 label whisper 显示『历史日只读』;tap 鱼油 chip 状态不变(无 .done 切换)
  - ② 存储:无任何写入:journal/<yesterday> md 字节不变,Preferences 无新 taskintake key。端点返 400 时前端不落账
  - ③ 截图:昨天 care 区灰只读态,杯子不可点,whisper『历史日只读』
- **契约底座**:mobile/parity/golden/daily_tasks__check_backfill_yesterday_closed.response.json(status 400 detail『不在补卡窗口』)
- **负例/边界**:这是负例本身:窗口外日期端点必 400,UI 必只读;若 UI 仍接受 tap 并 POST = 违约(mobile L454 旧 date>=today 正好放过未来/拒昨天)

### `daily_tasks__check_rejects_future`  ★Cannot-break:★补卡窗口对未来闭合:写未来必 400,UI 锁定未来 pill(test_check_rejects_future_and_catalog_is_writable_window)

**用户故事**:试图给明天打卡(不该被允许)

- **前置 seed**:今天 md 存在;设备时钟今天 10:00。等价 PC test_check_rejects_future tomorrow 400。
- **操作(真 click)**:[UI部分待建] date-band 未来日 .gw-day 渲染为 .future.locked(gw-app dayClick:locked 不进入,只 creatable 可建当天链)。理论上点 locked pill 无反应。机器层 POST /api/daily-tasks/check {date:tomorrow, checked:true}
- **预期效果**:
  - ① 屏幕:snapshot_ui:date-band 中明天 pill 有 .future.locked class(灰/不可选),tap 它 st.dayKey 不变(无 catalog 重拉);care 区仍是今天
  - ② 存储:无写入:tomorrow 无 md 文件被创建,无 taskintake/* 写明天 key。端点 400
  - ③ 截图:date band 明天 pill 锁态(灰),care 区维持今天
- **契约底座**:mobile/parity/golden/daily_tasks__check_rejects_future.response.json(__now__ 2026-06-26T10:00,status 400)
- **负例/边界**:前天(two days ago)也 400(超出 yesterday)— 见 daily_tasks__check_rejects_two_days_ago golden

### `daily_tasks__check_non_int_intake`  ★Cannot-break:★非 int→500:/check 的 int(intake) 无 try/except 故意 500,锁住不被悄改成 400/静默(test_check_non_int_intake_is_500_not_400)

**用户故事**:(边界/防御)非法 intake 值进入 check

- **前置 seed**:今天 md 有鱼油。等价 PC test_check_non_int_intake_is_500_not_400。
- **操作(真 click)**:正常 UI 不可能产生非 int intake(toggle 只发整数)。这是契约锁:[UI不可达] 但端点必须保持 500 而非被『好心』包成 400/静默吞。机器层 POST /api/daily-tasks/check {task_name:'鱼油', intake:'abc'}
- **预期效果**:
  - ① 屏幕:N/A(UI 不暴露该路径);若未来加文本输入剂量框,非数字输入应在客户端拦截前不发请求,而不是依赖 500
  - ② 存储:无写入(请求 500 失败,md/Preferences 不变)
  - ③ 截图:N/A
- **契约底座**:mobile/parity/golden/daily_tasks__check_non_int_intake.response.json(status 500)+ check_non_int_increment.response.json
- **负例/边界**:本例即负例:intake='abc' / increment='x' 必 500;/meta 同样非 int 反而 400(不对称,不能抽出时统一掉)

### `daily_tasks__water_drag_fill`

**用户故事**:睡前把八杯水滑到喝够的杯数

- **前置 seed**:今天 md 存在(含八杯水段);GW.water 初始为 catalog water_filled。
- **操作(真 click)**:在 .gw-cups 上 pointerdown 第 1 杯位置 → 横向 drag/swipe 到第 5 杯松手(gesture/drag,XcodeBuildMCP swipe 横扫到第 5 个 .gw-cup 中心)→ apply() 设 st.water=5 → pointerup emit('pulse')→ POST /api/daily-tasks/water {date:today, filled:5}
- **预期效果**:
  - ① 屏幕:snapshot_ui:.gw-cups 前 5 个 .gw-cup 内 SVG 有 .water(填充),后 3 空;.gw-cups-foot <b> 文案=5,.hint 文案『还差 3 杯』
  - ② 存储:journal/<today> md 八杯水段子杯前 5 个勾上(setWaterFilled,Capacitor Filesystem)。等价 PC: 水杯进度内嵌当天 md 顶部(6.15 P0b)。注意 filled clamp [0,8]
  - ③ 截图:八杯水 5 杯有水 3 杯空,脚注『5 / 8 杯 · 还差 3 杯』
- **契约底座**:无独立 water golden response(/water 返 {ok,filled});底层契约 = setWaterFilled 写当天 md 八杯水段字节,对齐桌面 md 内嵌格式
- **负例/边界**:滑到第 8 杯 → filled=8,.hint『今天喝够了』;超滑也 clamp 8(Math.min(8))。历史只读日 st.readonly → apply() 早 return 不写

### `daily_tasks__catalog_writable_yesterday`  ★Cannot-break:★is_writable 由 server/shim 算,前端不自算时区(mobile is_writable 复刻 _writable_dates_set,L454 旧 date>=today 已是反向 bug)

**用户故事**:切到昨天看清单,确认上午还能补

- **前置 seed**:昨天 md 存在;设备时钟今天 hour<12。
- **操作(真 click)**:tap date-band 昨天 .gw-day pill → GET /api/daily-tasks?date=yesterday
- **预期效果**:
  - ① 屏幕:snapshot_ui:care 区 .gw-care-block 不带 .readonly(可写);八杯水 whisper 显示『睡前一抹点亮』而非『历史日只读』
  - ② 存储:无写入(读),catalog 返 is_writable=true
  - ③ 截图:昨天 care 区正常可点态
- **契约底座**:mobile/parity/golden/daily_tasks__catalog_writable_yesterday.response.json(is_writable=true,is_today=false)
- **负例/边界**:同日下午 hour>=12 切昨天 → is_writable=false → 只读(catalog_writable 反例)

### `daily_tasks__catalog_writable_tomorrow`  ★Cannot-break:★未来日 is_writable=false(test_check_rejects_future_and_catalog_is_writable_window)

**用户故事**:切到明天看,应是不可写

- **前置 seed**:设备时钟今天 10:00;明天无 md。
- **操作(真 click)**:date-band 明天 .gw-day(.future.locked)。机器层 GET /api/daily-tasks?date=tomorrow
- **预期效果**:
  - ① 屏幕:snapshot_ui:明天 pill 有 .future.locked class;若进入(机器层),care .gw-care-block 带 .readonly
  - ② 存储:无写入,catalog is_writable=false
  - ③ 截图:明天 pill 锁态
- **契约底座**:mobile/parity/golden/daily_tasks__catalog_writable_tomorrow.response.json(is_writable=false)
- **负例/边界**:is_writable=false 时 UI 仍允许打卡 = 违约

### `daily_tasks__meta_set`

**用户故事**:给某个补剂设置『每天 2 粒、一瓶 60 粒』,让它显示剩余天数

- **前置 seed**:今天 md 有鱼油;无 taskmeta/鱼油 key。
- **操作(真 click)**:[UI待建] 长按 .gw-task『鱼油』(long_press 480ms)→ openTaskSheet 弹出 → tap『改每天几粒 / 一瓶几粒』.gw-sheet-item。**现状是 demo 桩**(只 whisper『(demo)这一项接 daily-task API』,不接 /meta)。应有:点开后弹剂量/瓶量数字步进表单,保存 → POST /api/daily-tasks/meta {task_name:'鱼油', total_pills:60, daily_dose:2}
- **预期效果**:
  - ① 屏幕:[待建] 保存后 .gw-task『鱼油』.gw-task-dose 显示『0/2』(dose>=2);若 days_left<=3 出现 .gw-task-badge;openTaskSheet head 的 sub 显示『每天 2 粒』。当前 snapshot_ui 只能断言 whisper toast 出现『(demo)』
  - ② 存储:[待建] Preferences setting/taskmeta/鱼油 = {"total_pills":60,"daily_dose":2}。等价 PC meta-map[鱼油] 写 total_pills/daily_dose
  - ③ 截图:鱼油 chip dose 角标变『0/2』,管理 sheet 头部『每天 2 粒 · 还能吃 30 天』
- **契约底座**:mobile/parity/golden/daily_tasks__meta_set.response.json + daily_tasks__meta_after.meta.json
- **负例/边界**:daily_dose='x' / total_pills='abc' → 400『必须是整数』(表单应拦非数字);total_pills='' → pop(清空瓶量,days_left 消失)——见 meta_non_int / meta_clear_pills golden

### `daily_tasks__meta_non_int`

**用户故事**:(边界)在剂量表单里输入非数字

- **前置 seed**:今天有鱼油。
- **操作(真 click)**:[UI待建] openTaskSheet→改剂量表单输入 total_pills='abc' 保存。机器层 POST /api/daily-tasks/meta {task_name:'鱼油', total_pills:'abc'} 与 {daily_dose:'x'}
- **预期效果**:
  - ① 屏幕:[待建] 表单应显示错误提示(红字/抖动),不静默接受;不应把 chip 状态改掉。当前无表单 = UI 不可达
  - ② 存储:无写入(400),taskmeta/鱼油 不变
  - ③ 截图:[待建] 表单错误态
- **契约底座**:mobile/parity/golden/daily_tasks__meta_non_int_total_pills.response.json + daily_tasks__meta_non_int_daily_dose.response.json(均 400)
- **负例/边界**:本例即负例:非 int meta → 400(注意与 /check 非 int→500 不对称,UI 文案区分『拒绝』非『崩溃』)

### `daily_tasks__meta_clear_pills`

**用户故事**:把瓶量清空(不再追踪剩余天数)

- **前置 seed**:鱼油 taskmeta = {total_pills:60, daily_dose:2}。
- **操作(真 click)**:[UI待建] openTaskSheet→改剂量→total_pills 置空保存。机器层 POST /api/daily-tasks/meta {task_name:'鱼油', total_pills:''}
- **预期效果**:
  - ① 屏幕:[待建] .gw-task『鱼油』.gw-task-badge(Nd 剩余天数)消失;dose 角标仍『0/2』(daily_dose 不动)
  - ② 存储:Preferences taskmeta/鱼油 删除 total_pills 字段,保留 daily_dose=2
  - ③ 截图:鱼油 chip 无剩余天数角标
- **契约底座**:mobile/parity/golden/daily_tasks__meta_clear_pills.response.json(total_pills=null,daily_dose=2)
- **负例/边界**:清 pills 后不应把 daily_dose 也清掉(未传字段不动)

### `daily_tasks__delete_cascade`  ★Cannot-break:★delete 级联:必须同步清 md 双写目标 + image + meta + intake_log,不能漏任一(test_delete_cascade_md_image_meta,5.15 肌酸丢)

**用户故事**:长按某个补剂选『删除这项』,要彻底删干净(清单/图标/库存/打卡记录全没)

- **前置 seed**:daily-tasks.md 模板 + 今天 md 都有鱼油+维生素D;Preferences taskmeta/鱼油={daily_dose:1,intake_log...}、taskimg/鱼油=<rel>、taskintake/鱼油 有当日记录。等价 PC test_delete_cascade(5.15 肌酸丢 guard)。
- **操作(真 click)**:[UI待建] 长按 .gw-task『鱼油』(long_press 480ms)→ openTaskSheet → tap『删除这项』.gw-sheet-item.danger。**现 demo 桩**(whisper『(demo)』,不接 /delete)。应有:点删除 → 纸感二次确认(非垃圾桶 icon,撤回窗)→ 确认后 POST /api/daily-tasks/delete {task_name:'鱼油'}
- **预期效果**:
  - ① 屏幕:[待建] 删后 .gw-tasks 内『鱼油』.gw-task 消失,『维生素D』仍在(snapshot_ui chip 数 2→1);删除前应有撤回纸条(N 秒窗),撤回则恢复。当前只断言 whisper『(demo)』
  - ② 存储:[待建] 级联清:① journal/<today> md + daily-tasks.md 模板都删鱼油行(维生素D 留)② Preferences taskimg/鱼油 + taskmeta/鱼油 + taskintake/鱼油 全 removeSetting。等价 PC: md 双写目标 + image-map + image 文件 + meta-map 全清
  - ③ 截图:打卡区只剩维生素D 一枚 chip;模板与当天 md 均无鱼油
- **契约底座**:mobile/parity/golden/daily_tasks__delete_cascade.response.json + .day.md + .template.md + .images.json + .meta.json(鱼油 全部清,维生素D 全部留,image_removed=true)
- **负例/边界**:删除时缺 task_name → 400『缺 task_name』;删一项不能误删同段其他项(维生素D 必须 survive,5.15 肌酸误删教训)

### `daily_tasks__history_oldest_first`

**用户故事**:点开某补剂看最近几天的打卡连续情况(streak)

- **前置 seed**:今天 md 鱼油打勾;前天 md 鱼油没勾;昨天无文件。等价 PC test_history_per_day_oldest_first。
- **操作(真 click)**:[UI待建] 长按 .gw-task『鱼油』→ openTaskSheet → tap『看本周完成率』.gw-sheet-item。**现 demo 桩**。应有:弹历史 modal 显示 N 天格子。机器层 GET /api/daily-tasks/history?name=鱼油&days=3
- **预期效果**:
  - ① 屏幕:[待建] history modal 内 3 个日期格,顺序最早→最新:前天=未勾(空格)、昨天=null(无文件,灰/缺省)、今天=勾(实)。snapshot_ui 断言格子数=days 且最后一个为完成态
  - ② 存储:无写入(纯读)
  - ③ 截图:[待建] streak 行:空 · 缺 · 勾
- **契约底座**:mobile/parity/golden/daily_tasks__history_oldest_first.response.json(days 数组 oldest→newest:false / null / true)
- **负例/边界**:缺 name query → 400『需 name query』;days 超 60 夹到 60,<1 夹到 1

### `daily_tasks__water_cup_post`

**用户故事**:把八杯水的杯子图标换成自己拖进来的图(抠图后当贴纸)

- **前置 seed**:有一张已上传的 attachment(/attachments/<date>/<stem>);等价 PC test_water_cup_get_set_roundtrip(WATER_CUP_KEY 保留键)。
- **操作(真 click)**:[UI待建] 八杯水区当前无『换杯子图』入口(openTaskSheet 是补剂的,杯子无管理 sheet)。应有:八杯水 label 旁一个换图入口 → 选 attachment → POST /api/water-cup {attachment_url}。注意 /water-cup(图)≠ /daily-tasks/water(水位)
- **预期效果**:
  - ① 屏幕:[待建] 设置后八杯水 SVG 杯子替换为自定义图;GET /api/water-cup 返 image_url 非 null
  - ② 存储:[待建] 抠图落 data/daily-task-images/_water_cup.png;Preferences/image-map 写 WATER_CUP_KEY 保留键。等价 PC: image-map[WATER_CUP_KEY]=rel
  - ③ 截图:[待建] 八杯水用自定义杯图
- **契约底座**:mobile/parity/golden/daily_tasks__water_cup_post.response.json(image_url=/data/daily-task-images/_water_cup.png)+ daily_tasks__water_cup_get.response.json + daily_tasks__water_cup.images.json
- **负例/边界**:POST /api/water-cup 不带 attachment_url → 400『need attachment_url』(missing_url golden);抠图失败 → 400 透传 err

### `daily_tasks__task_set_image`

**用户故事**:给某个补剂换个图标(拖一张图当它的脸)

- **前置 seed**:今天有鱼油;有一张 attachment 可用。
- **操作(真 click)**:[UI待建] 长按 .gw-task『鱼油』→ openTaskSheet → tap『换图标』.gw-sheet-item。**现 demo 桩**。应有:选 attachment → 抠图 → POST /api/daily-tasks/set-image {task_name:'鱼油', attachment_url}
- **预期效果**:
  - ① 屏幕:[待建] 换图后 .gw-task『鱼油』的 .gw-task-glyph 由首字母变为图(catalog t.image_url 非 null → glyph 置空,渲染 image)。snapshot_ui 断言 chip 显示图而非『鱼』字
  - ② 存储:[待建] image-map/Preferences taskimg/鱼油 = <rel>;抠图落 data/daily-task-images/。等价 PC: image-map[鱼油]=rel,catalog 读回 image_url
  - ③ 截图:[待建] 鱼油 chip 圆盘内为自定义图标
- **契约底座**:无独立 set-image golden(可参 cutout__imgmap_after.json 的 image-map 写入契约);底层契约 = image-map 写 taskimg/<name> + catalog image_url 读回非 null
- **负例/边界**:缺 attachment_url → 400;换图后 catalog 必须能读到该 path(repair/catalog 共享 io-map,test_vault_repair_writes_iomap_then_catalog_sees_it)

### `daily_tasks__want_new_task`

**用户故事**:想新增一个打卡项,跟 AI 商量着加

- **前置 seed**:app 在日记 tab。
- **操作(真 click)**:长按任一 .gw-task → openTaskSheet → tap『想要新打卡项 · 跟 AI 商量 →』.gw-sheet-soft(data-act='want')→ m.close → emit('wantNewTask')→ 切到对话 tab 并把输入框预填『我想要新打卡项：』。这条是 openTaskSheet 里唯一真接通的动作
- **预期效果**:
  - ① 屏幕:snapshot_ui:tab 切到『对话』(.gw-nav-item[data-tab=chat] 带 .on),.gw-chat-input 文本预填『我想要新打卡项：』且 focus
  - ② 存储:无直接写入(走 AI chat tool loop:AI 调 manage_daily_task 才落 md+模板)。等价 PC: tool_manage_daily_task 经 _apply_task_op 写双目标 + io-map
  - ③ 截图:对话页输入框预填提示文案
- **契约底座**:mobile/parity/golden/daily_tasks__template_task_add.response.json(AI manage 新增 task 经 /template/task add 的契约)
- **负例/边界**:AI 改名(manage edit)必须迁移 meta+image key 不留孤儿(test_manage_daily_task_wired_and_migrates_keys);新增同名 task 不应重复行

### `daily_tasks__backfill_progress`

**用户故事**:(系统/隐式)历史多粒项的进度子格回填,保证翻旧日时子格完整

- **前置 seed**:维生素D dose=3,intake_log 某日=2,该日 md 文件存在。等价 PC test_backfill_progress_idempotent。
- **操作(真 click)**:[UI不可达] 无用户按钮触发(后台/迁移用)。机器层 POST /api/daily-tasks/backfill-progress(无 body)
- **预期效果**:
  - ① 屏幕:N/A(无 UI);效果是翻到该历史日时打卡区子格已展开正确勾数
  - ② 存储:该日 md 顶部段把维生素D 展成 3 个子 box(前 2 勾);幂等——再跑 touched_count=0,字节不再变
  - ③ 截图:N/A
- **契约底座**:mobile/parity/golden/daily_tasks__backfill_progress_first.response.json(touched_count>=1)+ daily_tasks__backfill_progress_second.response.json(touched_count=0)
- **负例/边界**:无对应 md 文件的日期 → 进 skipped_no_file 不报错;dose<2 的 task 跳过

---

## thread / 对话流（chat history persistence: send · history-load · corrupt→restore modal · CAS stale-overwrite）

> **UI 概况**:移动 UI 在 mobile/m/。tap 目标可定位元素：顶栏 tab 条 `.gw-nav-item[data-tab="chat"]`(文案"对话")/`[data-tab="journal"]`(文案"日记")，切 chat tab 即渲染对话流(gw-app.js L78-80 `.gw-thread` + chatbar)；chatbar = `.gw-chat-input`(textarea，placeholder "跟 Gateway 说点什么…")+ `.gw-chat-send`(纸笔 send icon，空文案时 disabled) + `.gw-chat-attach`(回形针)。消息气泡 gw-chat.js：用户 `.gw-msg.me`、AI `.gw-msg.ai`(流式时带 `.streaming`)、ref `.gw-ref`、note `.gw-note`、tool chip `.gw-chip-tool.{doing|ok|fail}`。发送链路：`.gw-chat-send` → GW.sendChat(gw-real-bridge.js L264 覆盖 mock，真打 /api/chat SSE，结束 postJson `/api/thread/save`)。历史加载：启动 GW.bridgePrefetch → GET /api/thread/history → 映射进 GW.thread(L138-156)。

★Cannot-break 两处在移动端 UI 缺位，必标[UI待建]：
1) 损坏→restore modal(5.17)：shim GET 损坏返 `status:'corrupt'+baks` 正确(mobile-api.js L1723-1737)，CSS 容器 `.gw-modal/.gw-modal-opt/.gw-modal-opt.fresh`(components.css L397-404)也在，但没有任何 JS 渲染/绑定它——gw-real-bridge.js L141-144 收到 corrupt 只 `hist=[]`+console.warn"cd 端 modal 兜底"，restore-from-bak 端点(shim L1740)无 UI 调用方。即损坏时用户看到空对话、无恢复入口=退化成 5.17 事故表象。
2) CAS 409 陈旧覆盖(5.26)：shim threadSaveIsStale + 409 完整(mobile-api.js L515,L1763-1772)，但 gw-real-bridge.js L321 save body 只有 `{history: st.thread}`，从不回传 base_mtime，409 路径客户端永不触发、收到 409 也无处理。多端/多标签场景移动端会静默盖掉新历史。
两条都是 parity 洞，case 里照 PC 契约写"应有的 UI + 动作"。

### `thread__send_message_streams_and_persists`

**用户故事**:我在对话框打一句话点发送，AI 流式回我，刷新后这轮对话还在。

- **前置 seed**:设备已配 DeepSeek key(gw/setting 有 key，否则 chat 不通)；thread.json 初态为空或仅历史 N 条；Backend setting/thread_mtime 记当前 mtime。模拟器停在「对话」tab。
- **操作(真 click)**:1) tap 顶栏 `.gw-nav-item[data-tab="chat"]`(文案『对话』) 2) tap `.gw-chat-input`(placeholder『跟 Gateway 说点什么…』) 3) type_text 『记一下我今天喝了咖啡』 4) tap `.gw-chat-send`(send icon，输入非空后由 disabled→可点)
- **预期效果**:
  - ① 屏幕:snapshot_ui 断言：发送后 `.gw-chat-input` value=''、send 回到 disabled；对话流先出 `.gw-msg.me`(文案=刚输入)、随后『磨墨中…』`.gw-grind` 短暂出现再消失、然后出 `.gw-msg.ai.streaming` 逐字增长、流结束后该气泡去掉 `.streaming` class。
  - ② 存储:对应 PC /api/thread/save：thread.json 被全量覆盖为含本轮 user+ai 两条的 array；setting/thread_mtime 推进到更大值(rotate 时 setting/thread_bak/1 = 旧 thread)。
  - ③ 截图:screenshot 看到一对气泡：右侧署名『我』的用户句 + 左侧署名『Gateway』的 AI 回复，AI 文本完整渲染(非半截)。
- **契约底座**:mobile/parity/golden/thread__save_fresh_writes.history.json + thread__save_fresh_writes.response.json(ok:true,count 增长)
- **负例/边界**:key 未配/网络断 → gw-real-bridge L395 push `.gw-msg.ai` 文案『(chat 出错:…)』，且不得 postJson 把 AI 错误占位当历史写丢；空文案点 send 应无效(send 保持 disabled，不发 POST)。

### `thread__history_load_happy_on_launch`

**用户故事**:我重开 app 切到对话，之前聊过的内容还在、顺序没乱。

- **前置 seed**:thread.json 存有 array(如 [{kind/role user '嗨'},{assistant '在'}])；setting/thread_mtime > 0。冷启动 app。
- **操作(真 click)**:1) 冷启动(GW.bridgePrefetch 自动 GET /api/thread/history) 2) tap `.gw-nav-item[data-tab="chat"]`
- **预期效果**:
  - ① 屏幕:snapshot_ui：对话流按存储顺序渲染等量气泡(2 条)，无『损坏』modal、无空态占位；最后一条 `.gw-msg` 在可视底部(scrollEnd)。
  - ② 存储:纯读，无写。GET 返 {history:[...], mtime>0}，响应不含 status 键。
  - ③ 截图:screenshot 两条历史气泡按原序(用户句在 AI 句之上)。
- **契约底座**:mobile/parity/golden/thread__history_happy_returns_list.response.json + thread__history_happy.asserts.json(mtime_gt_0,no_status_key)
- **负例/边界**:thread.json 不存在 → GET 返 {history:[],mtime:0}(golden thread__history_empty_no_file)，UI 显示空对话流(无气泡)而非报错。

### `thread__history_corrupt_shows_restore_modal`  ★Cannot-break:★5.17 损坏→modal：空 [] 不能当真覆盖；损坏读必返 status='corrupt'+baks 且响铃(_report_silent_failure thread_history_read_failed)

**用户故事**:我的对话历史文件坏了，打开对话时应弹一个『选 bak 恢复/从空开始』的窗，而不是默默清空我的聊天。

- **前置 seed**:thread.json 写入非法 JSON(如 '[{"role": BROKEN')；至少存在 setting/thread_bak/1(可恢复)。冷启动 app。
- **操作(真 click)**:[UI待建] 应有的元素：corrupt 时 gw-real-bridge L141 不该只 hist=[]+console.warn，而要渲染 `.gw-modal`(CSS 已备 components.css L397) → 标题『对话历史读取失败』+ `.gw-modal-body`『选 bak 恢复或从空开始，别直接覆盖』+ 每个 bak 一个 `.gw-modal-opt`(显 index/size/mtime) + 一个 `.gw-modal-opt.fresh`『从空开始』。动作：用户 tap 某 `.gw-modal-opt` 触发 restore。需先建该 modal 渲染+绑定。
- **预期效果**:
  - ① 屏幕:[UI待建] snapshot_ui：出现 `.gw-modal.on`，含 ≥1 个 `.gw-modal-opt`(对应 baks[].index) + 1 个 `.gw-modal-opt.fresh`；关键：此刻对话流不得被当作空历史覆盖(不得自动 postJson save 把 [] 写回)。
  - ② 存储:GET 阶段纯读，损坏不触发任何写(★绝不空 [] 当真覆盖)。底层 GET 返 status:'corrupt'+baks，shim 同时把损坏原文留存 setting/thread_corrupted/<ts>(对齐 PC .corrupted.<ts>)。
  - ③ 截图:[UI待建] screenshot 看到居中纸感弹窗，列出可恢复备份项 + 『从空开始』灰字项。
- **契约底座**:mobile/parity/golden/thread__history_corrupt_modal_payload.response.json(status:corrupt,baks:[{index:1}]) + thread__history_corrupt.asserts.json(rang_thread_history_read_failed:true)
- **负例/边界**:损坏但一个 bak 都没 → 返 baks:[](golden thread__history_corrupt_no_baks)，modal 仍弹但只剩 `.gw-modal-opt.fresh`『从空开始』，不得因扫不到 bak 崩溃/直接清空。

### `thread__restore_from_bak_roundtrip`  ★Cannot-break:★5.17 恢复路径必保留原损坏副本(corrupted_sibling_kept)，不能丢失用户原始字节

**用户故事**:历史坏了，我在恢复窗里选某个备份，对话就恢复成那个备份的内容。

- **前置 seed**:thread.json 当前损坏；setting/thread_bak/2 存有合法 array(如 [{assistant 'bak.2 的内容'}])。已弹出 corrupt modal(承上一 case)。
- **操作(真 click)**:[UI待建] tap modal 中对应 bak.2 的 `.gw-modal-opt`(显示『备份 2 · N KB · 时间』) → 触发 POST /api/thread/restore-from-bak {bak_index:2}
- **预期效果**:
  - ① 屏幕:[UI待建] snapshot_ui：`.gw-modal` 关闭(去 `.on`)，对话流重渲染为 bak.2 内容(1 条 `.gw-msg.ai` 文案『bak.2 的内容』)；whisper/toast『已从 备份2 恢复』。
  - ② 存储:对应 PC restore：thread.json 被写成 bak.2 内容；原损坏文件另存 setting/thread_corrupted/<ts>(不直接丢)；setting/thread_mtime 推进。
  - ③ 截图:[UI待建] screenshot：弹窗消失，对话流出现恢复的那条历史。
- **契约底座**:mobile/parity/golden/thread__restore_from_bak_roundtrip.response.json(ok,restored_from:bak.2,count:1) + .history.json + thread__restore_from_bak.asserts.json(corrupted_sibling_kept:true)
- **负例/边界**:选了不存在的备份(bak_index=3 但无 setting/thread_bak/3)→ shim 404 {error:'bak.3 不存在'}(golden thread__restore_missing_bak)，UI 应提示『该备份不存在』并保持 modal 开着让用户改选，不静默关窗。bak_index 越界(0 或 6)→ 400(golden thread__restore_bad_index_low/high)。

### `thread__save_stale_rejected_409`  ★Cannot-break:★5.26 CAS 409：陈旧标签页/设备不能盖新历史；base_mtime!=current → 409 + 文件原样不动

**用户故事**:我在另一处已更新过对话；这台旧标签页/旧设备再发消息时不能把新历史盖掉，应提示冲突让我先刷新。

- **前置 seed**:thread.json 已是较新版本(mtimeX，由别处写入)；本端持有的 base_mtime 停在旧值(< mtimeX)。本端在对话框发一句新消息触发 save。
- **操作(真 click)**:[UI待建] 正常发送链路(tap `.gw-chat-input` → type → tap `.gw-chat-send`)触发 save，但需先补：gw-real-bridge L321 save body 要带 `base_mtime`(当前只传 {history})，且收到 409 要弹冲突 UI(复用 `.gw-modal`：『历史已在别处更新 · 先刷新再保存/用我的覆盖』)。当前客户端不回传 base_mtime → 409 永不触发 = parity 洞。
- **预期效果**:
  - ① 屏幕:[UI待建] snapshot_ui：save 返 409 时弹 `.gw-modal` 含『历史已在别处更新，先刷新再保存』+ 两个 `.gw-modal-opt`(『刷新历史』重新 GET / 『仍用本端覆盖』带最新 mtime 重 save)；本地草稿气泡不丢。
  - ② 存储:★对应 PC：409 时 thread.json 字节原样不动(stale save leaves file untouched)；只有 base_mtime==current 的 save 才写入并推进 mtime。
  - ③ 截图:[UI待建] screenshot：冲突提示弹窗，背后对话流仍是用户刚打的草稿(未被吞)。
- **契约底座**:mobile/parity/golden/thread__save_stale_409.response.json(status:409,conflict:true,message 'stale base_mtime…') + thread__save_stale_409.history_untouched.json(文件=真实最新历史不变)
- **负例/边界**:base_mtime==current(新鲜)→ 200 写入 count+1(golden thread__save_fresh_writes)；base_mtime 缺省/None(旧 client 没回传)→ 不误拒，放行写入(test_thread_cas T1)。history 不是 list → 400『history must be a list』(golden thread__save_non_list)，不得 try/except 静默改成 200 不写。

### `thread__point_entry_into_chat`

**用户故事**:我在日记页把某条日记『指给 AI 看』，它作为引用进对话流，我接着就能问它。

- **前置 seed**:journal 当天有 ≥1 条 entry(`.gw-entry`)；当前在『日记』tab。
- **操作(真 click)**:1) 在日记 timeline 对某 `.gw-entry` 触发『指给 AI 看』动作(gw-app.js L334 监听 bus 'point'；交互入口为 entry 长按菜单/动作项，文案含『指给 AI 看』) 2) 自动切到对话 tab
- **预期效果**:
  - ① 屏幕:snapshot_ui：tab 切到 chat(`.gw-nav-item[data-tab="chat"].on`)，对话流末尾出现 `.gw-ref`(含 `.rk`『日记 · <time>』+ `.rt`<title/摘要 22 字>)；whisper『已拉进对话 ✦ 指给 AI 看』。
  - ② 存储:ref 进 GW.thread；下一次 sendChat 时随 history 一起 postJson /api/thread/save 持久化(ref kind 原样存读，shim JSON.stringify roundtrip)。
  - ③ 截图:screenshot 对话流出现一个引用样式块(区别于普通气泡)，注明来自哪条日记。
- **契约底座**:mobile/parity/golden/thread__save_fresh_writes.history.json(验 thread save roundtrip 含非 msg kind 不丢)
- **负例/边界**:对只读/历史日的 entry 触发 point → 仍可指给 AI 看(只读限制写操作，不限引用)；ref 不应误产生写日记副作用。

### `thread__attach_image_then_send`

**用户故事**:我在对话框附一张图连同文字发出去，AI 能看到图并回我。

- **前置 seed**:已配 key；当前 chat tab。
- **操作(真 click)**:1) tap `.gw-chat-attach`(回形针 icon) 2) 选图(走原生图片选择)→ chatbar 出现待发缩略 chip(send 由 disabled→可点) 3) (可选)type 文字 4) tap `.gw-chat-send`
- **预期效果**:
  - ① 屏幕:snapshot_ui：发送后 `.gw-msg.me` 含 `.gw-msg-imgs img`(缩略)，随后磨墨 + AI 流式回复；待发 chip 区清空、send 回 disabled。
  - ② 存储:图随 message 进 thread，sendChat 结束 postJson /api/thread/save 把含 imgs 的 user 条 + ai 条写 thread.json。
  - ③ 截图:screenshot 用户气泡内嵌图片缩略 + AI 文本回复。
- **契约底座**:mobile/parity/golden/thread__save_fresh_writes.history.json(thread save 含 msg 条 roundtrip)
- **负例/边界**:只附图无文字 → 允许发送(sendChat: text 空但 imgs 非空仍发，gw-chat L62)；附件上传失败 → 错误以 `.gw-msg.ai` 错误条提示，不得把空历史写盘。

### `thread__tool_chip_three_states`

**用户故事**:我让 AI 改某条日记，它执行工具时我能看到一个工具小标，从『进行中』变成『完成』，失败能点开看原因。

- **前置 seed**:已配 key；当前 chat tab。
- **操作(真 click)**:1) tap `.gw-chat-input` 2) type 『把今天 9:00 那条改成…』(触发 patch_journal_block tool) 3) tap `.gw-chat-send`
- **预期效果**:
  - ① 屏幕:snapshot_ui：对话流出现 `.gw-chip-tool.doing`(含 `.ink-pulse`)→ 变 `.gw-chip-tool.ok`(含 `.seal-dot`)；失败时为 `.gw-chip-tool.fail`，tap 它展开 `.gw-chip-fail-reason`(显示错误文案)，再 tap 收起。chip 永久留存不可点成面板。
  - ② 存储:tool chip(kind:'tool')随 thread 一起 save 进 thread.json(shim roundtrip 保留 tool kind)。
  - ③ 截图:screenshot 一个带印章点的工具小标 + AI『改好了』回复。
- **契约底座**:mobile/parity/golden/thread__save_fresh_writes.history.json(验非 msg kind tool 不被 save 丢弃)
- **负例/边界**:工具失败 → chip 为 fail 态且可展开原因；失败不得阻断后续 AI 文本回复，也不得把半截/错误状态当成功历史污染。

---

## image 簇(图片/附件/抠图/AI看图/贴纸)— PC: image_routes.py(/attachments/{date}/{name} · /api/attachments[list] · /api/attachments/search · /api/attachments/delete · /api/attachments/reindex · /api/cutout · /api/vision/classify) ↔ mobile-api.js(同名 + /api/uploads/{list,search,delete} 别名 + /api/attachments/get + /api/chat/upload-image + /api/scrapbook/{,/upsert,/delete})

> **UI 概况**:★关键现状:image 簇的移动 UI 几乎全是 demo 脚手架,真前端触发器基本未建。证据 grep mobile/m/:
(1) 贴纸/sticker:gw-journal.js:111 长按 entry → action sheet 有「贴张图」按钮(data-act="sticker"),但点了只 GW.whisper('选张图贴上来…（端侧抠图）', true)——无 file picker、无 cutout 调用、无 sticker 落到 entry。L229 打卡管理 sheet「换图标」同理只 whisper '(demo)'。
(2) chat 传图/看图:gw-chat.js:69 sendChat 里若 imgs 非空就 pushChip('vision_classify',{attachment_url:'cap_x.jpg'})——硬编码假文件名 + 假三态动画,不调真 /api/vision/classify;gw-real-bridge.js:273 才是真桥(userMsg.attachments=imgs.map dataUrl),但没有 file-input/相机/拖图 UI 把图喂进来。
(3) 正文贴图:gw-journal.js openCard 编辑器 footer 有「贴张图」(.gw-card-attach),点了只 whisper '选张图贴进正文…'。
(4) 附件列表/搜/删:m/ 里完全无「我的图」浏览页/搜索框/删除按钮——uploads/list·search·delete 在 shim 里有 handler 但前端零入口。
(5) 钥匙页(gw-app.js:198)文案「看照片、抠图、贴纸都走这把钥匙」是唯一明确提到图能力的真 UI,但它是配 key 不是图操作。
→ 因此本簇绝大多数 case 的 tap_sequence 标 [UI待建] 并写出该长啥样;少数(sticker sheet 项、chat 传图链、配 key)有半成品可定位。
持久层(plist 等价 = Capacitor Preferences/Filesystem):图本体 attachments/<date>/<stem>(dataURL)、图标 taskimg/<name>、补剂 meta taskmeta/<name>(JSON,total_pills)、上传 index setting/uploads_index/<date>/<stem>(JSON,vision_result 缓存)、贴纸 setting/scrapbook/<date>(items[])。
★parity 洞(必须在 case 里盯):① 移动 /api/cutout 自动写 total_pills 时**无「仅当 meta 未填过 total 才写」guard**(PC image_routes.py:146 cur.get('total_pills') 才不覆盖),mobile-api.js:1534 无条件 meta.total_pills=pillCount → 会抹掉用户手填颗数;② 删除端点 key 分叉:PC /api/attachments/delete{date,filename} vs mobile /api/uploads/delete{attachment_url};③ path-traversal 校验 PC 在 attachments_delete + get_attachment 都拦 '..'/'/'，mobile uploads/delete 只靠 regex `^/attachments/([^/]+)/(.+)$` 兜,(.+) 会吞 '..',需测越权;④ mobile search 只搜 vision_result.description/kind/brand,PC search 还搜 filename/original/raw ocr_text;⑤ PC 空 q 是空结果非错误,mobile 缺 query 返 400。

### `cutout__writes_image_map_meta_and_ocr_pill_count`  ★Cannot-break:★cutout OCR 自动填 total_pills(数据正确性);抠图三层兜底链不阻塞(native 失败→云端 vision→不崩)

**用户故事**:用户长按某打卡项→换图标→选一张补剂瓶照片,系统端侧抠图存为该 task 图标,并自动 OCR 出整瓶颗数填进 meta

- **前置 seed**:设备已配阿里云 key(dashscope_key 有值);存在 task「鱼油（Swisse）」且 taskmeta/鱼油（Swisse） 尚未填 total_pills;一张瓶身印「60 粒」的图已通过 chat 上传 → attachments/2026-06-25/yuyou.jpg 存在(Filesystem 有 dataURL)。NativeOcr plugin 在真机可用
- **操作(真 click)**:[UI待建] 现状:gw-journal.js:229 打卡管理 sheet「换图标」点了只 whisper '(demo)'。应有:长按打卡 chip(.gw-task-chip,文案=task.name 如「鱼油」)→ action sheet 出现 → tap「换图标」(glyph=sticker)→ 弹系统相册/已上传图选择器 → tap 选中 yuyou.jpg 缩略图 → 端侧抠图等待态(纸做法,非 spinner) → 落定。底层 POST /api/cutout {task_name:'鱼油（Swisse）', attachment_url:'/attachments/2026-06-25/yuyou.jpg'}
- **预期效果**:
  - ① 屏幕:snapshot_ui:打卡 chip 的图标区从默认 glyph 变成抠好的 PNG(<img> 或 background-image 出现,src 指 taskimg);若该 task 显示「还能吃 N 天」,N 应按 total_pills=60 重算(days_left 文案变化)。抠图期间应有可断言的等待态元素(label 含「抠图」)且无 iOS spinner
  - ② 存储:Preferences taskimg/鱼油（Swisse） = '/attachments/2026-06-25/yuyou.jpg'(或 'inline');taskmeta/鱼油（Swisse） JSON 含 total_pills:60。对齐 PC:image_map[task]=rel + meta total_pills 自动写
  - ③ 截图:打卡条上该项图标从线描占位变成真实抠图贴纸(透明背景瓶子);hover/diff 看到颗数推算的天数更新
- **契约底座**:mobile/parity/golden/cutout__writes_image_map_meta_and_ocr_pill_count.response.json {ok:true,task_name:'鱼油（Swisse）',ocr_pill_count:60} + cutout__imgmap_after.json {has_key:true} + cutout__metamap_after.json {'鱼油（Swisse）':{total_pills:60}}
- **负例/边界**:缺 task_name 或缺 attachment_url/image → POST /api/cutout 返 400(shim:{ok:false,error:'缺 task_name'} / '缺 attachment_url 或 image');UI 上不能静默吞掉,应提示;attachment_url 格式错(非 /attachments/d/n)→ 400;attachment 读不到 → 404 且 UI 不能把空图当成功写进 taskimg

### `cutout__respects_existing_total_pills_PARITY_HOLE`  ★Cannot-break:★cutout OCR 自动填 total_pills 必须尊重用户已有手填(PC 注释:尊重用户已有手填)

**用户故事**:用户已手填某 task 一瓶颗数,之后换图标触发 OCR,OCR 抽到的颗数不该覆盖用户手填值

- **前置 seed**:task「南非醉茄」taskmeta 已有用户手填 total_pills:30;一张瓶身印「120 粒」的图已上传 attachments/2026-06-26/ashwa.jpg
- **操作(真 click)**:[UI待建] 长按「南非醉茄」打卡 chip → action sheet →「换图标」→ 选 ashwa.jpg → 抠图。底层 POST /api/cutout {task_name:'南非醉茄', attachment_url:'/attachments/2026-06-26/ashwa.jpg'}
- **预期效果**:
  - ① 屏幕:snapshot_ui:图标更新成 ashwa 抠图,但「还能吃 N 天」仍按 total_pills=30 算,不能跳成 120 推算值
  - ② 存储:★parity 红线:taskmeta/南非醉茄 total_pills 必须仍 == 30(PC image_routes.py:146 仅当 not cur.get('total_pills') 才写)。当前 mobile-api.js:1534 无此 guard,会写成 120 → 此 case 故意暴露洞,GREEN 要求 shim 补上「仅当未填才写」
  - ③ 截图:图标变了但天数文案不变(对比换图前后截图,天数同值)
- **契约底座**:mobile/parity/golden/ [缺] 需新增 cutout__respects_existing_total_pills.metamap_after.json {'南非醉茄':{total_pills:30}};响应 ok:true,ocr_pill_count 可返 120(响应回 OCR 值)但 persist 不变
- **负例/边界**:若 shim 仍覆盖成 120 = parity 洞复现 = 测试 RED;UI 上天数被静默改写而用户没动过 = 数据丢失等价物

### `vision_classify__delegates_and_echoes_question`  ★Cannot-break:vision-pre-router 缓存模式(不重复 load+save 避免 OCR race);单 API 入口(只阿里云 key)

**用户故事**:用户在对话里发一张图并问「这是啥牌子」,AI 看图返回分类+回答,带上用户的问题语境

- **前置 seed**:已配 key;chat 输入栏可附图;一张补剂图已 attachments/2026-06-25/p.png
- **操作(真 click)**:半成品可定位:chat 页(底栏 ☰·日记·对话 的「对话」)→ [UI待建 file/相机 入口] 现状 gw-chat.js:69 仅在 imgs 非空时假装调用且硬编码 cap_x.jpg;应有:对话输入框旁附件按钮(gw-real-bridge.js:273 已能收 imgs)→ 选 p.png → 输入「这是啥牌子」→ tap 发送(回车/发送钮)。底层 POST /api/vision/classify {attachment_url:'/attachments/2026-06-25/p.png', extra_question:'这是啥牌子'}
- **预期效果**:
  - ① 屏幕:snapshot_ui:对话流出现 user 气泡含图缩略图 + 文字「这是啥牌子」;随后 AI 区出现 tool chip(name=vision_classify,label 含文件名,三态 doing→ok 带 seal-dot,gw-chat.js buildChip);AI 回复文本含分类描述。chip 必须是真调用结果不是硬编码 cap_x.jpg
  - ② 存储:setting/uploads_index/2026-06-25/p.png 的 vision_result 被缓存(meta.vision_result=分类 JSON,meta.vision_at 时间戳),供后续搜图复用
  - ③ 截图:对话里图 + AI 看图 chip 点亮 + 文本答复;眼睛 glyph(gw-mock.js:73 vision→eye)
- **契约底座**:mobile/parity/golden/vision__classify_delegates_and_echoes_question.response.json {kind:'supplement',description:'desc q=啥牌子'} — extra_question 必须回灌进 description/答复
- **负例/边界**:缺 attachment_url → POST 返 400;attachment_url 格式错(非 /attachments/d/n)→ 400(PC 两条都 400,见 vision__classify_missing_url.response.json {missing:400,bad_format:400});未配 key → 应给可见错误({error:'vision_failed'} 或提示去配钥匙),不能静默无回复

### `attachments__delete_removes_file_and_index_DATALOSS`  ★Cannot-break:★delete 数据丢失防护:只删目标条目,不连带删别的图/不清空索引;撤回窗内不真删

**用户故事**:用户在「我的图」里删掉一张不要的图,文件和索引条目都清掉,别的图不动

- **前置 seed**:attachments/2026-06-25/a.png 与 keep.png 都存在;uploads_index 含两条;删 a.png
- **操作(真 click)**:[UI待建] m/ 无附件浏览页。应有:☰ 抽屉或设置里「我的图」入口 → 网格列出已上传图(每张缩略图 + 日期)→ 长按 a.png 那张 → 出现删除项(纸做法,禁垃圾桶 icon,如「撕掉这张」)→ tap → N 秒撤回窗(复用 gw-journal.js showUndo 习语) → 过窗才真删。底层 mobile POST /api/uploads/delete {attachment_url:'/attachments/2026-06-25/a.png'}(注意 PC 是 /api/attachments/delete {date,filename}—端点 key 分叉)
- **预期效果**:
  - ① 屏幕:snapshot_ui:删除并过撤回窗后,图网格里 a.png 缩略图节点消失,keep.png 仍在(节点数 -1);撤回窗出现期间有「撤回」按钮 + 5s 进度条;tap 撤回则 a.png 复原
  - ② 存储:Filesystem attachments/2026-06-25/a.png 被 remove;Preferences setting/uploads_index/2026-06-25/a.png 删除;keep.png 两者都留。对齐 PC:file unlink + 索引数组过滤该条
  - ③ 截图:图网格少一张;撤回 toast 纸条 5s 倒计时
- **契约底座**:mobile/parity/golden/attachments__delete_removes_file_and_index_entry.response.json {ok:true,removed:'a.png'} + attachments__delete.asserts.json {file_deleted:true} + attachments__delete.index_after.json [{date:'2026-06-25',filename:'keep.png'}]
- **负例/边界**:path-traversal:attachment_url 含 '../../etc/passwd'(如 /attachments/2026-06-25/../../etc/passwd)→ 必须拒(PC attachments__delete_traversal_rejected.response.json {status:400})。★mobile shim 隐患:正则 (.+) 会吞 '..',若仅靠 regex 通过则越权——UI/handler 必须额外拦 '..'/'/',表现为删除请求被拒 + 提示「非法路径」,绝不删到 attachments 目录外

### `get_attachment__serves_bytes_and_path_guard`  ★Cannot-break:★path-traversal:date 必须 ^\d{4}-\d{2}-\d{2}$,name 不含 '/' '..'(PC get_attachment 双拦)

**用户故事**:用户打开「我的图」或日记里贴的图,缩略图/大图能正常显示出来

- **前置 seed**:attachments/2026-06-25/a.png 存在(dataURL);该图被某 entry 引用或在图网格
- **操作(真 click)**:[UI待建] 任意展示图的位置:① 图网格缩略图 ② 日记 entry 里贴的图 ③ 对话气泡里的图。tap 缩略图 → 放大查看。底层 mobile GET /api/attachments/get?url=/attachments/2026-06-25/a.png(返 {ok,dataURL})供 <img>;PC 是 GET /attachments/2026-06-25/a.png 直接返 bytes
- **预期效果**:
  - ① 屏幕:snapshot_ui:<img> 元素 src/dataURL 非空且渲染出像素(image 节点 width/height>0);放大视图出现可关闭的图层
  - ② 存储:无写入(纯读取);不改 attachments / index
  - ③ 截图:图真实显示,不是 broken-image 占位
- **契约底座**:mobile/parity/golden/get_attachment__serves_bytes.response.json {status:200,body_matches:true} + get_attachment__statuses.response.json {bad_date:400,missing:404}
- **负例/边界**:date 非法格式(not-a-date)→ 400;请求不存在的图(missing.png)→ 404 且 UI 显空态/占位不崩;name 带 '..' 越权读 → 拒,绝不读到 attachments 外文件

### `attachments__list_sorted_desc_with_limit`

**用户故事**:用户进「我的图」浏览已上传的所有图,最新的排最前,翻页有数量上限

- **前置 seed**:uploads_index 有 3 条(2026-06-20/a.png, 06-25/b.png, 06-22/c.png)
- **操作(真 click)**:[UI待建] ☰/设置 →「我的图」入口 → 进入图浏览页(默认拉一屏)。底层 mobile GET /api/uploads/list?n=20(返 {ok,n,uploads[]});PC 等价 GET /api/attachments?limit=N(返 {items,total})
- **预期效果**:
  - ① 屏幕:snapshot_ui:图网格首项是 2026-06-25/b.png(date 降序);列出条数 ≤ limit;每个缩略图 cell 可定位(含 date 文案或 data-date 属性);页面有 total 计数文案(如「共 3 张」)
  - ② 存储:无写入(纯读)
  - ③ 截图:网格按日期新→旧排列,最新在左上
- **契约底座**:mobile/parity/golden/attachments__list_sorted_desc_limit.response.json {items:[{date:'2026-06-25',filename:'b.png',ocr_text:''},{date:'2026-06-22',...}],total:3}(limit=2 时只 2 条但 total=3)
- **负例/边界**:空相册(无 uploads)→ 返 total:0 + UI 显空态文案(如「还没有图」),不能白屏/报错;limit=0 或负 → 走默认上限不崩

### `attachments__list_date_filter`

**用户故事**:用户在「我的图」按日期范围筛选,只看某天之后的图

- **前置 seed**:uploads_index 含 2026-06-10/a 与 2026-06-25/b
- **操作(真 click)**:[UI待建] 图浏览页应有日期筛选器(date_from / date_to 输入或月份切换)→ 设 date_from=2026-06-20 → 列表刷新。底层 GET /api/attachments?date_from=2026-06-20(PC);mobile uploads/list 当前无 date_from 入参——[parity 缺口] shim 需补 date_from/date_to
- **预期效果**:
  - ① 屏幕:snapshot_ui:筛选后只剩 06-25/b 那张缩略图(a 节点消失);筛选条显示当前范围
  - ② 存储:无写入
  - ③ 截图:网格只剩范围内的图
- **契约底座**:mobile/parity/golden/attachments__list_date_from_filter.response.json {items:[{date:'2026-06-25',filename:'b'}],total:1}
- **负例/边界**:date_from > 所有图日期 → 空结果 + 空态文案;date_from 格式非法 → 不崩(按字符串比较或忽略)

### `attachments__search_filename_original_ocr`

**用户故事**:用户在「我的图」搜索框输入关键词(如「鱼油」或「维生素」),按文件名/原名/OCR文本命中

- **前置 seed**:uploads_index 两条:x.png(original=鱼油瓶.jpg) 与 y.png(ocr_text/vision_result.description=维生素 D3 60 粒)
- **操作(真 click)**:[UI待建] 图浏览页顶部搜索框 → 输入「鱼油」→ 实时/回车搜。底层 mobile POST /api/uploads/search {query:'鱼油'}(匹配 vision_result.description/kind/brand);PC GET /api/attachments/search?q=鱼油(还匹配 filename/original/ocr_text)——[parity 缺口:mobile search 只搜 vision_result,不搜 filename/original/raw ocr_text]
- **预期效果**:
  - ① 屏幕:snapshot_ui:搜「鱼油」结果网格只剩 x.png;搜「维生素」只剩 y.png;结果区显示 query 与命中数
  - ② 存储:无写入
  - ③ 截图:搜索框有词 + 网格过滤到 1 张
- **契约底座**:mobile/parity/golden/attachments__search_q_yuyou.response.json {items:[{filename:'x.png',original:'鱼油瓶.jpg',...}],query:'鱼油',total:1} + attachments__search_q_weishengsu.response.json {filename:'y.png',ocr_text:'维生素 D3 60 粒',query:'维生素',total:1}
- **负例/边界**:空 q → 返 {items:[],query:''}(PC attachments__search_empty_q.response.json),mobile 当前缺 q 返 400——[parity 分叉:PC 空 q 是空结果非错误];UI 上清空搜索框应回到全量列表不报错;无命中词 → 空结果态

### `attachments__reindex_missing_skips_existing`

**用户故事**:用户首次启用图管理或索引丢了,点「重建索引」,把没进索引的图补 OCR,已在的跳过

- **前置 seed**:attachments/2026-06-25/ 下 new.png 与 old.png 都在;uploads_index 只有 old.png
- **操作(真 click)**:[UI待建] 设置/诊断里「重建图索引」按钮 → tap → 等待态 → 完成提示。底层 PC POST /api/attachments/reindex(返 {ok,indexed,skipped});mobile shim 当前未见 reindex handler——[parity 缺口,需补]
- **预期效果**:
  - ① 屏幕:snapshot_ui:完成后 toast/提示含「补了 1 张,跳过 1 张」;图浏览页 new.png 现身(之前不在索引)
  - ② 存储:setting/uploads_index 新增 new.png 条目;old.png 条目不动(已存在跳过)
  - ③ 截图:诊断行显示索引结果计数
- **契约底座**:mobile/parity/golden/attachments__reindex_index_missing_skip_existing.response.json {ok:true,indexed:1,skipped:1}
- **负例/边界**:attachments 目录不存在/空 → 返 {ok:true,indexed:0,skipped:0} 不崩;非日期格式子目录(如 _tmp)跳过;以 '_'/'.' 开头的文件跳过(PC reindex 逻辑)

### `chat_upload_image__dedup_and_logical_url`  ★Cannot-break:vision-pre-router 是 upload-side(上传时跑一次分类缓存进 index),AI 端不再调 vision_classify

**用户故事**:用户在对话里附一张图发出去,图被存进本机并去重,得到逻辑 URL 供后续看图/贴纸引用

- **前置 seed**:已配 key;chat 页可附图;同一张图第二次发应命中去重
- **操作(真 click)**:[UI待建] 真附件入口缺失。应有:对话输入框旁「+附件/相机」按钮 → 选图 → 预览 chip → tap 发送。底层 POST /api/chat/upload-image {image:dataURL}(返 {ok,url:'/attachments/<date>/<stem>',deduped})。gw-real-bridge.js:273 已能把 imgs 挂 userMsg.attachments,缺的是喂图 UI
- **预期效果**:
  - ① 屏幕:snapshot_ui:发送后 user 气泡含图缩略;第二次发同图,响应 deduped:true 但 UI 仍正常显示(不重复占存储);上传中有可断言等待态
  - ② 存储:Filesystem attachments/<todayIso>/<sha短hash> 写入 dataURL(首次 deduped:false);setting/uploads_index/<date>/<stem> 写 {uploaded_at,size,mime};同图二次发 → 不新增本体(sha 去重)
  - ③ 截图:对话里图显示;两次发同图存储不翻倍
- **契约底座**:mobile/parity/golden/ [缺] 需新增 chat_upload_image__dedup.response.json {ok:true,url:'/attachments/<date>/<stem>',deduped:false} 与 _second {deduped:true};对齐 PC /api/chat/upload-image sha256 去重契约
- **负例/边界**:非图片/坏 dataURL → 应返错误不写本体;空 image → 拒;超大图 → 不应让 Preferences 写爆(边界:dataURL 体积限制)

### `scrapbook_place_sticker__anchor_to_entry`  ★Cannot-break:anchor_time 是语义标签不当视觉定位用;MD 真源不被贴纸写动;等比缩放 size_pct 换分辨率不漂

**用户故事**:用户把上传的图作为浮动贴纸贴到日记某个时间块附近(AI 帮放或用户长按 entry 贴),换设备/换分辨率不漂位

- **前置 seed**:已配 key;某 entry(如 09:00)存在;attachments/2026-06-25/cat.png 已上传
- **操作(真 click)**:[UI待建] 现状 gw-journal.js:111「贴张图」只 whisper。两条路:① 长按 entry → sheet「贴张图」→ 选图 → cutout → 落为该 entry 锚定贴纸;② chat 里 AI 调 place_scrapbook_image tool(mobile-api.js:890,anchor 到时间块)。底层 POST /api/scrapbook/upsert {date,attachment_url,anchor_time:'09:00',cutout:true,size_pct,...}
- **预期效果**:
  - ① 屏幕:snapshot_ui:09:00 entry 附近出现浮动贴纸 <img>(可定位,带 anchor_time data 属性);size 按 size_pct 占 layer 宽度的百分比(换宽度不漂,实测锁 ~18.3%);贴纸非卡片化
  - ② 存储:setting/scrapbook/2026-06-25 items[] 新增一条 {attachment_url,anchor_time,size_pct,cutout,x/y 或锚点};MD 真源不动(贴纸是旁路 JSON layer)
  - ③ 截图:日记 09:00 块旁贴着一张抠好的猫贴纸,等比缩放正确
- **契约底座**:mobile/parity/golden/ [缺,image 簇暂无 scrapbook golden] 需新增 scrapbook__upsert.items_after.json 对齐 PC server.py:1647 place_scrapbook_image contract(anchor_time 是语义挂点,size_pct 占 layer 宽 %)
- **负例/边界**:anchor_time 指向不存在的时间块 → 应有兜底放置不崩;attachment_url 无效 → 拒;cutout 失败 → 走原图兜底不阻断贴纸落地

### `scrapbook_delete_sticker`  ★Cannot-break:MD 真源不被贴纸删动

**用户故事**:用户撕掉贴在日记上的某张贴纸

- **前置 seed**:setting/scrapbook/2026-06-25 已有 1 条贴纸 item
- **操作(真 click)**:[UI待建] 长按浮动贴纸 → 出「撕掉」(纸做法,禁垃圾桶) → 撤回窗 → 过窗真删。底层 POST /api/scrapbook/delete {date,id 或 attachment_url}
- **预期效果**:
  - ① 屏幕:snapshot_ui:贴纸 <img> 节点从 entry 附近消失;撤回窗 5s
  - ② 存储:setting/scrapbook/2026-06-25 items[] 移除该条;MD 真源不动
  - ③ 截图:日记块旁贴纸消失
- **契约底座**:mobile/parity/golden/ [缺] 需新增 scrapbook__delete.items_after.json [](或剩余项),对齐 PC /api/scrapbook/delete
- **负例/边界**:删不存在的贴纸 id → 幂等不崩;撤回窗内不真删

### `uploads_search_via_chat_curator`

**用户故事**:用户在对话里说「上周拍的那张瓶子」,AI 通过 photo curator 找出对应的图

- **前置 seed**:已配 key;uploads_index 有若干图带 vision_result.description(含「瓶子」等词)
- **操作(真 click)**:对话页 → 输入「上周拍的那张瓶子在哪」→ 发送 → AI 调 ask_photo_curator/search_my_uploads tool(mobile-api.js:978/971,内部走 /api/uploads/search {query:'瓶子'})
- **预期效果**:
  - ① 屏幕:snapshot_ui:对话出现 tool chip(name=search_my_uploads,eye glyph) doing→ok;AI 回复列出命中图(缩略图或链接)
  - ② 存储:无写入(纯搜 vision_result 缓存)
  - ③ 截图:对话里 curator chip + 命中图回显
- **契约底座**:mobile/parity/golden/ [缺] 需新增 uploads__search_curator.response.json {ok:true,query:'瓶子',hits:[...]} (mobile search 只匹配 vision_result.description/kind/brand,非 raw ocr——记录 parity 分叉)
- **负例/边界**:缺 query → 400;无命中 → hits:[] + AI 说没找到不编造;未配 key/无 vision_result 缓存 → 搜不到要诚实回不能假装

### `config_key_unlocks_image_powers`  ★Cannot-break:单 API 入口是核心 UX 杠杆(只填一把阿里云 key 解锁全部);双钥匙文案=设定不是门槛

**用户故事**:用户在设置/钥匙页填入阿里云百炼 key,解锁看图/抠图/贴纸全部能力(单 API 入口)

- **前置 seed**:设备未配 key(dashscope_key 空);看图/抠图此时应不可用或降级
- **操作(真 click)**:gw-app.js:198 钥匙页(文案「看照片、抠图、贴纸都走这把钥匙。可选，填了才长出眼睛」)→ tap 输入框填 key → tap 保存/落定按钮
- **预期效果**:
  - ① 屏幕:snapshot_ui:钥匙行状态从未配(灰/降级)变成已配(朱印/绿);看图相关入口由禁用变可用
  - ② 存储:Preferences dashscope_key 写入用户填的值;dashscope_base_url/vision_model 等保持默认(mobile-api.js:1312)
  - ③ 截图:钥匙页显示已激活态(双钥匙文案:阿里云=眼睛)
- **契约底座**:mobile/parity/golden/ [缺,属 setup 簇但 gating image 能力] 配 key 后 /api/vision/classify 与 /api/cutout 不再返「未配置」;对齐单 API 入口契约
- **负例/边界**:key 填错/空 → 看图调用返 {error:'vision_failed'} 或明确「钥匙没填对」提示,不能静默无反应让用户以为坏了

---

## 接现有制品

- **范式**:本文件是 `TEST_FIRST_MIGRATION.md` 五步工作流里第②步「写交互 self-test」的具体清单。
- **契约底座**:每个 case 的「契约底座」指向 `mobile/parity/golden/`(跑 `capture-golden.py` 产/刷新)。
- **进度**:case 名 = endpoint key,跟 `PARITY_LEDGER.md` 行对齐;一个 case 真 simulator 跑过 → ledger 标 PASS + 附截图。
- **跑法**:`XcodeBuildMCP` `build_run_sim` → `tap`/`swipe` 走操作序列 → `snapshot_ui` 断言①屏幕 → 读 plist 断言②存储 → `screenshot` 比③ → 比 golden 验底座。
