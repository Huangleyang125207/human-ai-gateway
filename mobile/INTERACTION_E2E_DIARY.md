# 移动端 E2E 招牌用例 · 写日记的 5 条核心旅程

> 以 `INTERACTION_E2E_PHOTO.md`(药瓶/水杯照片→图标)为标准的同深度 E2E 用例,覆盖"用户通过 AI 交互写日记"的 5 条核心旅程。属三层测试的**真 simulator + 真 LLM** 层(跨簇链 + 真 AI,不进确定性 golden CI;底层由 INTERACTION_TEST_CASES 原子 case + golden 钉死)。
> 两层模型见 `TEST_FIRST_MIGRATION.md` §0;跑法见 `parity/interaction/run-cases.md`。

---

## `e2e_chat__spoken_event_to_timeline_entry`

**招牌一句话**:用户在对话流口述"记一下我下午跟设计师聊了原型" → AI 一步 emit insert_journal_block(time/tag/title/body 一次写全 §H5)→ 经 /api/chat SSE tool loop 落 md(_insert_block append/新建 H1,新 H2 末尾 @ai stamp)→ 时间线出现该 entry(楷体=AI 笔迹)+ claim 审计确认未撒谎。

**★Cannot-break 触及**:
- insert 一步写全 H2 标题+正文(§H5;tool_specs body required + tool_insert_journal_block 空 body 注 warning;test_insert_block_body J-CB3 锁)——禁标题-only entry
- authorship boundary:写日记 tool 路径 stamp @ai(server.py:1399 author='ai');HTTP endpoint 默认 @user(journal_routes.py:115 user-trust)——两路 author 不可混(test_insert_block_stamps_{ai,user}_marker / test_insert_block_http_stamps_user)
- 全角冒号时间块:H1 存 `# 13：30`(全角),TIME_H1_RE 兼容半/全角读、写恒全角(server.py:4850 new_h1 = f'# {hh}：{mm:02d}')——海外 Obsidian 兼容 + day.md 命名约定
- claim 审计红线(5.22):_audit_unauthorized_claim 仅 last_actions 非空才放行;AI 没真 emit tool 却说'已记下' → 自动加 disclaimer 暴露(chat_routes.py:280/837/875;mobile _auditUnauthorizedClaim L1153)
- DSML 泄漏闸:synthetic tool_calls 抠出前绝不把 raw <｜｜DSML｜｜tool_calls> yield 进聊天(chat_routes.py:214/378-383)
- vault md sha256 baseline + lock:_insert_block 读 baseline → _get_vault_md_lock 内重读不一致返 conflict(server.py:4840-4844)——堵 Obsidian 并发静默覆盖
- vault_git.commit_after_write:insert 后必 commit(server.py:4846/4864)否则丢 audit chain
- _safe_write_text lock+uuid tmp+fsync 三件套(rotate=True)

**前置/环境**:seed 初态:今天 md 已由 new-day.sh 建好(find_today_journal 返非空;否则 insert 返 404 — 见负例)。下午时间块(如 # 13：30 / # 14：00)可存在可不存在:存在→append 新 H2,不存在→按时序新建 H1。需真 LLM(DeepSeek chat,AI 决定 emit insert_journal_block 那个大脑)+ 真 key(config 单 API 入口);此链不需 vision/OCR/抠图(纯文字旅程)。E2E 真链层不进确定性 CI(真 LLM 输出非确定);底层 _insert_block/authorship 由 INTERACTION_TEST_CASES + test_authorship/test_insert_block_* characterization 在 CI 钉死。

### PC 链(完整可跑)

| # | 操作(真 tap/drag/说话) | 机制 | ①屏幕 | ②落账 | 契约/golden |
|---|---|---|---|---|---|
| 1 | 在侧栏对话流输入框打『记一下我下午跟设计师聊了原型』回车 | thread.js → POST /api/chat(chat_routes.py:584);body={history, message, context.refs=[]};_chat_stream_generator 进 tool loop(chat_routes.py:421) | user 气泡(宋体=人笔迹)出现该句;下方磨墨/等待态 | —(本步不落 md) | chat SSE 契约;无 vision hint(refs 空,_refs_to_vision_hints 返空 chat_routes.py:132/610) |
| 2 | (server 自动)AI 读系统提示『用户明说记一下→可调 insert_journal_block』,决定一步写全 | 非最后轮 client.chat.completions.create(tools=_active_tools, tool_choice=auto)(chat_routes.py:444);需先 load 'schedule' 组(server.py:1211 写型 tool 前置) | AI 区开始出 tool chip(doing) | — | §『不写默认』(server.py:1190)用户明示『记一下』才触发写;write_journal 组含 insert_journal_block(server.py:1228) |
| 3 | AI emit insert_journal_block(time=13:30/当前半小时, tag='探索'/'工作', title='跟设计师聊原型', body='下午和设计师过了一版原型…(result+significance)') | _dispatch_tool('insert_journal_block')(chat_routes.py:398)→ TOOL_IMPL['insert_journal_block']=tool_insert_journal_block(server.py:1384/2181);内部 _insert_block(f, time, tag, title, author='ai', body)(server.py:1399→4769) | tool chip doing→ok;SSE {type:'action', name:'insert_journal_block', result}(chat_routes.py:400) | 当天 md:存在同时间 H1→append 新 H2 到块尾(server.py:4813-4848);不存在→按时序插 `# 13：30`(全角冒号 server.py:4850)。新 H2 = `## #探索 跟设计师聊原型 @ai`(server.py:4795 末尾 @ai stamp)+ 空行 + body 散文。vault_git commit(server.py:4846/4864) | ★body required(tool_specs.py:101/105);空 body → out['warning'] nag 补正文(server.py:1401);★author='ai'(tool 路径,非 HTTP @user);★全角冒号;★sha256 baseline+lock(server.py:4840);对齐原子 case insert_journal_block / test_insert_block_body J-CB3 / test_insert_block_stamps_ai_marker |
| 4 | (server 自动)AI 出收尾文字,claim 审计兜底 | 最后轮 _stream_final_reply(单一 chokepoint chat_routes.py:435/298)+ _audit_unauthorized_claim(chat_routes.py:280) 查 last_actions | AI 文本(楷体=AI 笔迹)『记下了,放在下午 13:30 那格』;last_actions 含 insert action → 无 disclaimer | — | ★claim 审计:last_actions 非空才放行;若 AI 谎称已记却没 emit → 加『server audit:本回合未触发任何 tool』(chat_routes.py:414-415);DSML 泄漏闸 suppress(chat_routes.py:214) |
| 5 | 前端收 action 事件 → 刷新当天 day 视图时间线 | thread.js 消费 SSE {type:'action'};day.html 重读 /api/journal/today 渲染时间块 + H2 entries | 截图:单日页/时间线 13：30 那格出现新 entry『跟设计师聊原型』,作者标记 @ai(AI 笔迹楷体),tag #探索 | done payload {type:'done', actions:[...]}(chat_routes.py:416) | read_today_schedule 解析(server.py:2788 find_today_journal + 2803 TIME_H1_RE 全/半角兼容);H2 author 由 _check_author 解析(server.py:2782) |

### mobile 链(现状 / 缺口)

| # | 操作 | 机制 | 现状 | 契约 |
|---|---|---|---|---|
| 1 | 切到『对话』tab,在 chatbar 输入『记一下我下午跟设计师聊了原型』点发送 | gw-app.js:145 chatbar() → .gw-chat-input/.gw-chat-send;send → GW.sendChat(gw-real-bridge.js:264)真 fetch POST /api/chat {history, message}(L299-302) | 已建:chatbar UI(gw-app.js:148-151)+ sendChat 真 SSE 桥(gw-real-bridge.js:264)全通,非 mock | 对齐 PC POST /api/chat;mobile-api chatViaDeepseek 期望 {history, message}(mobile-api.js:294) |
| 2 | (shim 自动)AI tool loop emit insert_journal_block | mobile-api.js chatViaDeepseek callRound(L1206 真打 DeepSeek)→ toolCalls(L1226)→ events.push tool_call(L1244)→ dispatchTool('insert_journal_block')(L1003)注入 author='ai'(L999)→ POST /api/journal/insert-block shim(mobile-api.js:1781)→ Store.writeJournalMd;tool_result(L1247) | 已建:mobile TOOL_SPECS 含 insert_journal_block + body required + J-CB3 空body warning(mobile-api.js:868/1004-1013);shim insert-block 复刻 _insert_block(append/新建 H1 全角冒号 L1799/1812、@ai stamp L1795、404 no-file、400 缺time);_auditUnauthorizedClaim(L1153) | ★对齐 PC tool 路径 @ai(dispatchTool L999);★body required;★全角冒号 L1812;claim 审计;但 mobile chat 批量 callRound 后一次性 sseResp(mobile-api.js:1279),非真增量流——桥端 firstChunkSeen/磨墨仍工作但语义是 batch |
| 3 | 桥渲染 tool chip(doing→ok)+ AI 楷体回复 | gw-real-bridge.js sendChat pump 解析 SSE:ev.type==='tool_call'→push kind:tool state:doing(L347-354);'tool_result'→state ok/fail(L355-361);'delta'→AI msg 楷体 | 已建:tool chip 三态 + claim 审计后的 delta 渲染全通(gw-real-bridge.js:347-388) | 对齐 cd gw-chat.js .gw-chip-tool 三态;mobile 事件名 tool_call/tool_result(自洽,PC 用 action——mobile-api 内部翻译,两端各自一致) |
| 4 | 切回『日记』tab 看时间线新 entry | renderTimeline 读 GW.journal[dayKey](gw-app.js:74/337);entry 数据来自 bridgePrefetch /api/journal/today(gw-real-bridge.js:110-131,author 'ai'→'@ai' L121) | AI链断(出口未刷新):★sendChat(gw-real-bridge.js:264-402)tool_result/done 后**不重跑 bridgePrefetch、不 fire reloadDay/renderTimeline** → AI 写的 entry 落进 md(shim 真写),但内存 GW.journal[dayKey] 不更新、时间线不重渲;用户须切 tab/重载 app 才看见。且 bridge 的 reloadDay 监听器跑的是 syncJournalDiff(UI→md 反向 L174-177/205),即便 fire 也方向错(会把过期内存当新增再 POST)——缺『AI 写后 pull md→刷时间线』正向链路 | PC 收 action 即刷 day 视图;mobile 出口 [UI待建/链断]:需在 sendChat done 后补 await bridgePrefetch() 重拉 today + renderTimeline。snapshot_ui 能断 .gw-entry,但当前断不到 AI 新写那条(未上屏) |
| 5 | 看 entry 作者笔迹 | renderTimeline 按 author 切笔迹字体(components.css:7 AI=--font-kai 楷 / 用户=--font-serif 宋) | 已建:笔迹身份机制在(components.css:7),前提是上一步时间线先刷出该 entry——当前因出口链断,AI 新 entry 不上屏,笔迹也看不到 | 笔迹即身份(DESIGN_BRIEF 双 register);author '@ai' 来自 bridge map(L121) |

### 负例(必须可见,不静默)

| 负例 | 触发 | PC 预期 | mobile 预期 |
|---|---|---|---|
| AI 只写标题不写正文(违反 §H5) | AI emit insert_journal_block 漏 body | _insert_block 仍落盘(老路径兼容 server.py:4775),但 tool result 注 out['warning']『只写了标题没写正文…请立即用 patch 补正文』(server.py:1401);tool_specs body required 先在 schema 层挡 | 对齐:shim insert 成功但 dispatchTool 注 result.warning『缺正文(body)…§H5』(mobile-api.js:1006-1013);TOOL_SPECS body required(mobile-api.js:868) |
| AI 没真 emit tool 却在文字里说『已经记下了』 | 模型幻觉/DSML 抠失败 → last_actions 为空但 reply 含 claim 短语 | _audit_unauthorized_claim 追加 disclaimer 暴露(chat_routes.py:414-415/837/875);md 不变 | 对齐:_auditUnauthorizedClaim(mobile-api.js:1153/1262)同样追加;lastActions 仅 ok=true 累积(L1250) |
| 今天 md 文件不存在 | new-day.sh 未跑,find_today_journal 返 None | tool_insert_journal_block 返 {error:'no journal file for <date>'}(server.py:1397-1398);HTTP endpoint 返 404(journal_routes.py:110-111) | 对齐:shim readJournalMd 返 null → 404 {ok:false,error:'no journal file for <date>'}(mobile-api.js:1791);UI 不能静默吞,应提示 |
| 时间格式非法 / 缺 time | AI 传 time='下午' 或漏 time | _insert_block 正则不匹配返 {error:'时间格式必须是 HH:MM…'}(server.py:4781-4783);tool 漏 time 兜底当前半小时(server.py:1390-1392);HTTP 漏 time→400(journal_routes.py:99-100) | shim 漏 time→400 {ok:false,error:'缺 time'}(mobile-api.js:1789);tool 路径 mobile 未见当前半小时兜底——[parity 待核] 若 AI 漏 time 直打 shim 会 400 而非兜底 |
| 撞已存在的 @user 块 | AI 想往用户自己写的同时间块加内容 | insert 是 append 新 H2 不覆盖(server.py:4813 append_to_existing),不触发 authorship 拒绝(那是 patch 的事);@ai 新块与 @user 旧块并存 | 对齐:shim 找现有 H1 append H2(mobile-api.js:1800-1806),不覆盖旧块 |
| vault md 在 insert 期间被 Obsidian 改动 | baseline sha 与 lock 内重读不一致 | 返 {error:'…在 insert 期间被外部修改,拒绝覆盖', conflict:true}(server.py:4842-4844/4860-4862),不静默覆盖 | [parity 洞]:mobile shim insert 走 Store.readJournalMd→writeJournalMd(mobile-api.js:1790-1815)**无 sha256 baseline+lock guard**;单端 local store 并发风险低但与 PC 契约不对齐 |

**PC 最终态**:PC 跑完(must 全中):
① 当天 md 出现新 H2 `## #<tag> 跟设计师聊原型 @ai`(append 到现有同时间 H1 块 或 按时序新建 `# 13：30` 全角冒号块)
② 新 H2 下有正文散文(result+significance,非标题-only)
③ 新 H2 末尾 @ai stamp(tool 路径 author='ai';非 HTTP @user)
④ vault_git 留一条 `insert <stem> 13:30 #<tag>` commit(audit chain 不断)
⑤ chat 流:1 个 insert_journal_block tool chip ✓ + 一句确认文字,无 claim disclaimer
⑥ 截图:单日页时间线 13：30 那格显示该 entry,作者 @ai,楷体笔迹,tag 正确
⑦ _safe_write_text lock+fsync 真到盘,sha256 baseline 校验通过(无 conflict)

**验收判据**:整条链跑通 = 6 真全中:① 话真进(user 气泡显示口述句)② AI 真决策(真 DeepSeek emit insert_journal_block,非 mock dispatch)③ AI 真写(last_actions 含 insert action,claim 审计不加 disclaimer)④ md 真落账(新 H2+body+@ai stamp+全角冒号,vault_git commit)⑤ 协议真守(body 非空 §H5、author=@ai 非 @user、sha256 无 conflict)⑥ 时间线真渲染(截图:13：30 那格出现 entry + @ai 楷体笔迹)。
PC:6 真全中 → 招牌链活。
mobile:①②③④⑤ 可达(chatbar+sendChat 桥+tool loop+insert shim+@ai stamp+全角冒号+claim 审计全建);**⑥ 红 → 整链未通**:sendChat done 后不重拉 today/不刷时间线(gw-real-bridge.js:264-402),AI 写的 entry 落 md 但不上屏。追平 PC 须补:sendChat 完成后 await bridgePrefetch()+renderTimeline 正向刷新(+ 可选 shim insert 补 sha256 baseline+lock guard 对齐 negatives⑥)。

**对齐**:原子 case(INTERACTION_TEST_CASES):本 E2E 串起 insert_journal_block(一步写全 §H5)、read_today_schedule(时间线读回)、claim 审计 三段;每段在 CI 由确定性原子 case + characterization 钉死,E2E 跑挂时先排除它们缩小爆炸半径。
golden/characterization:test_insert_block_body(J-CB3 空 body 锁)、test_insert_block_stamps_ai_marker / test_insert_block_http_stamps_user(authorship 双路 @ai/@user)、test_authorship(patch boundary 守)、test_claim_audit(直调 _audit_unauthorized_claim);mobile golden insert_stamps_user.md(字节对齐,mobile-api.js:1808 注释引)。
PARITY_LEDGER:/api/journal/insert-block(insert-block key,authorship + 全角冒号契约);chat /api/chat(SSE tool loop;PC emit action vs mobile emit tool_call/tool_result 各端自洽,内部翻译);claim 审计端口(5.22 msg5/7 事故等价防御,mobile-api.js:1153 注)。
已兜底子步:insert 落 md + @ai stamp + 全角冒号 + body required + 404/400 负例 + claim 审计——mobile shim 全建(CI 契约层绿)。
未兜底/parity 洞:① mobile 出口『AI 写后刷时间线』链断(本 E2E 独有,原子 case 兜不到,标 [UI待建/AI链断])② mobile shim insert 无 sha256 baseline+lock(negatives⑥ parity 洞,与 PC server.py:4840 不对齐)③ mobile tool 漏 time 是否兜底当前半小时 [parity 待核]。这些是追平 PC 的施工清单。

---

## `e2e_daily_tasks__checkin_today_and_backfill_yesterday_closed_set`

**招牌一句话**:用户今天 tap 鱼油 chip 打卡(写今天 md+intake_log),再切 date-band 到昨天 tap 补打卡 → 命中补卡窗口闭集{today, yesterday if hour<12}:11:00 可补(写昨天)、13:00 拒(400+只读);整条链最终态 = 当天 md `- [x] 鱼油` + intake_log[today]=1,且昨天仅在 hour<12 时落 intake_log[yesterday]=1,过点零写入。

**★Cannot-break 触及**:
- 补卡窗口闭集 {today, yesterday-if-hour<12} —— server `_writable_dates_set`(server.py:3156)真源,前端/shim 不自算时区(catalog `is_writable` 一律 mirror server;mobile `isWritableDate` mobile-api.js:504 复刻闭集,L454 旧 date>=today 反向 bug 已修)
- intake clamp [0, daily_dose] + dose>=2 子格 —— `_bump_intake`(server.py:3187 `new=max(0,min(new,daily_dose))`)+ `_ensure_md_progress_children`(3250);intake=0 从 intake_log pop 当日 key
- /check 非 int(intake/increment)→ 500 而非 400/静默 —— `int(body["intake"])`(daily_tasks_routes.py:110)无 try/except 故意 500(test_check_non_int_intake_is_500_not_400 锁;/meta 反而 400,不对称不能统一)
- md 写盘 atomic 三件套 —— `_set_md_checkbox`/`_ensure_md_progress_children` 经 `_safe_write_text`(path-keyed lock + uuid tmp + fd/dir fsync)
- 补卡只补昨天、打卡严格次日 12:00 截止 —— 过点让数据保持当时样子,别倒填污染(PULSE Cannot-break)

**前置/环境**:seed 初态:当天 journal/<today> md 存在且顶部段有 `- [ ] 鱼油`(daily_dose 默认 1);昨天 journal/<yesterday> md 存在且有 `- [ ] 鱼油`;Preferences/meta-map 无 taskmeta/taskintake/鱼油 key(全新)。**不需要真 LLM/key**——本旅程是确定性 daily-tasks HTTP/shim 链,纯打卡数学 + 时区窗口,无 vision/chat;唯一"非确定"输入是系统时钟,故必须能注入假时间:PC 侧测试用 `dt.set_now(...)`(test_daily_tasks_routes.py:153/160 已有 fixture);mobile 侧 golden 用 `__now__` 注入(daily_tasks__check_rejects_future.response.json `__now__: 2026-06-26T10:00`),真机/simulator 需改设备日期到 11:00 vs 13:00 两档跑两遍。

### PC 链(完整可跑)

| # | 操作(真 tap/drag/说话) | 机制 | ①屏幕 | ②落账 | 契约/golden |
|---|---|---|---|---|---|
| 1 | 主页/单日页今天,tap『鱼油』打卡 chip(默认 dose=1) | 前端 → `POST /api/daily-tasks/check`(daily_tasks_routes.py:63);body `{task_name:'鱼油', checked:true}`(无 date = 今天);内部 `_bump_intake`(server.py:3187)set_to=daily_dose=1 → `_set_md_checkbox`(3322) | 鱼油行 chip 勾上(done 态);catalog 返 is_writable=true、is_today=true | 当天 md 顶部 `- [ ] 鱼油` → `- [x] 鱼油`;meta-map[鱼油].intake_log[<today>]=1(经 `_save_task_meta_map`) | `daily_tasks__check_default_dose1`(golden check_default_dose1.response.json + .md);T3 test_check_intake_increment_clamp_and_md_box(test_daily_tasks_routes.py:172-176);PARITY D3 |
| 2 | (同 task dose=2 场景)对『维生素D』连点想加超 2 粒,POST intake=5 | `POST /api/daily-tasks/check` `{task_name:'维生素D', intake:5}`;先 `/meta {daily_dose:2}`;`_bump_intake` `new=max(0,min(5,2))=2`(clamp);dose>=2 → `_ensure_md_progress_children`(server.py:3250)展 N 子 box 前 K 个 [x] | chip dose 角标『2/2』done;md 顶部展开两个进度子格全勾 | intake_log[<today>]=2(clamp 后非 5);md `- [x] 维生素D` + `  - [x] 1` `  - [x] 2` | ★`daily_tasks__check_clamp`(golden check_clamp.response.json today_intake=2 非 5);T3(test:180-183);PARITY D3/check_clamp |
| 3 | 切到昨天补打卡 —— 设备时钟今天 11:00(hour<12),切 date-band 昨天 pill,tap 鱼油 | `POST /api/daily-tasks/check` `{task_name:'鱼油', date:<yesterday>, checked:true}`;date_arg 进 `_writable_dates_set()`(server.py:3156:now.hour<12 → 加 yesterday)校验通过 → `_bump_intake(for_date=yesterday)` + `_set_md_checkbox(target_date=yesterday)` | 先 GET catalog?date=yesterday 返 is_writable=true → care 区可写态(无 readonly);tap 后昨天鱼油 chip done | 昨天 md 鱼油 → `- [x]`;meta-map[鱼油].intake_log[<yesterday>]=1 | ★`daily_tasks__check_backfill_yesterday_ok`(golden ..ok.response.json + .meta.json intake_log[yesterday]=1);test_check_backfill_window 11:00 分支(test:152-157,assert 200 + intake_log[yesterday]==1);PARITY D2/D8 check_backfill_yesterday_ok |
| 4 | 过点拒绝 —— 设备时钟今天 13:00(hour>=12),再试补昨天 | `POST /api/daily-tasks/check` `{task_name:'鱼油', date:<yesterday>, checked:true}`;date_arg NOT in `_writable_dates_set()`(13:00 不加 yesterday)→ `raise HTTPException(400, 'date ... 不在补卡窗口内')`(daily_tasks_routes.py:85-87),`_bump_intake` 根本不调 | GET catalog?date=yesterday 返 is_writable=false → care 区 readonly(八杯水 whisper『历史日只读』);tap 鱼油 chip 状态不变 | 零写入:昨天 md 字节不变、intake_log 不新增 yesterday key(若 step3 已写则保持 1,本步不再叠加) | ★`daily_tasks__check_backfill_yesterday_closed`(golden ..closed.response.json status 400);test_check_backfill_window 13:00 分支(test:159-163,assert 400);PARITY 行9 check_backfill_yesterday_closed ✅PASS |
| 5 | 未来日闭合 —— 试给明天打卡(date-band 明天 pill 应 locked) | `POST /api/daily-tasks/check` `{task_name:'鱼油', date:<tomorrow>, checked:true}`;tomorrow 永不在 `_writable_dates_set`(只含 today + 条件 yesterday)→ 400;GET catalog?date=tomorrow is_writable=false | 明天 pill locked(灰不可选);care 区维持今天 | 零写入:tomorrow 无 md 创建、无 intake_log 写明天 key | ★`daily_tasks__check_rejects_future` + `daily_tasks__catalog_writable_tomorrow`(golden check_rejects_future.response.json `__now__` 10:00 status 400);test_check_rejects_future_and_catalog_is_writable_window(test:410);PARITY 行10/12 + check_rejects_two_days_ago golden |
| 6 | (契约锁,UI 不可达)非 int intake 进 check | `POST /api/daily-tasks/check` `{task_name:'鱼油', intake:'abc'}`;`int(body['intake'])`(daily_tasks_routes.py:110)ValueError 未捕 → FastAPI 500 | N/A(正常 UI toggle 只发整数,该路径不可达) | 无写入(请求 500 失败,md/meta 不变) | ★`daily_tasks__check_non_int_intake`(golden ..non_int_intake.response.json status 500 + check_non_int_increment.response.json);test_check_non_int_intake_is_500_not_400(test:398);PARITY 行28 ✅PASS |

### mobile 链(现状 / 缺口)

| # | 操作 | 机制 | 现状 | 契约 |
|---|---|---|---|---|
| 1 | 今天 tap『鱼油』打卡 chip | gw-widgets.js:91-95 pointerup(无 longpress、未移动、!readonly)→ toggle()(96)本地 `t.today_intake+=1` + 重画 chip + `GW.bus.emit('pulse')`;bridge gw-real-bridge.js:168 防抖 250ms → `syncPulseState`(180)→ `POST /api/daily-tasks/check {date:todayIso(), task_name, intake:t.today_intake}` → mobile-api.js:1657 check handler(复刻 _bump_intake) | 已建(今天打卡全链路通)。shim check L1657 字节级对齐 _bump_intake(intake/increment/checked/toggle + clamp + 500 + 400);PARITY D3 ✅PASS、case_6_check_default_dose1.png 真截 | `daily_tasks__check_default_dose1`;mobile-api.js:1657 ↔ server.py:3187 _bump_intake;golden check_default_dose1.md |
| 2 | 切 date-band 到昨天 → 期望 care 区重拉昨天 catalog + 可写/只读态对 | gw-app.js:118 pickDay:`st.dayKey=yesterday; render()`;`st.readonly=dayState(st.dayKey)==='past'`(gw-app.js:62);care 区据 st.readonly 渲染(gw-widgets.js:26/69) | [UI待建]/AI链断:pickDay **只 set dayKey + render,不重新 prefetch 后端 catalog**——bridge.bridgePrefetch(gw-real-bridge.js:64)只在冷启动拉 `iso=todayIso()` 一次(91 行 GET daily-tasks?date=iso),切天后 GW.tasks 仍是今天数据(stale);且 past 日 `st.readonly=true` → chip tap toggle() 在 gw-widgets.js:94 `!st.readonly` 处早 return,**根本无『补昨天可写态』路径**(即便 hour<12 server 说可写,前端把所有 past 日一律当只读) | ★`daily_tasks__catalog_writable_yesterday`(应 is_writable=true when hour<12);PARITY D8;缺口 = 切天不重拉 + past 一律 readonly 与 server 闭集不一致 |
| 3 | 昨天 hour<12 补打卡(应写 intake_log[yesterday]=1) | 应:tap 昨天鱼油 chip → emit('pulse')→ syncPulseState POST check `{date:yesterday, ...}` | AI链断/[UI待建] 真 bug:`syncPulseState`(gw-real-bridge.js:182)**硬编码 `var iso=todayIso()`**,水杯+逐 task check 全用今天 date(186-191),切到昨天打卡 intake 仍写**今天** → 补卡写操作链未通(INTERACTION_TEST_CASES:403 ②号缺口『补卡日期没传进 check』原文)。即便绕过 readonly 让 chip 可点,落账日期也错 | ★`daily_tasks__check_backfill_yesterday_ok`;缺口 = syncPulseState 须用 st.dayKey 对应 iso 而非 todayIso() |
| 4 | 昨天 hour>=12 切过去 → care 只读、tap 不写 | GET catalog?date=yesterday is_writable=false → st.readonly → gw-widgets.js:50/57/94 早 return | 已建(只读 gating 正确,且恰好掩盖了上条 bug):past 日一律 readonly → tap 无效 → 不会误 POST。PARITY 行9 check_backfill_yesterday_closed ✅PASS(case_1_yesterday_readonly.png)。注:此『对』是 readonly 一刀切的副作用,非真按 server is_writable 分流;hour<12 该可写时也被一并锁死(见上上条) | ★`daily_tasks__check_backfill_yesterday_closed`;shim 端 400 已对,UI 只读已对 |
| 5 | 未来日 tap → locked 拦截 | gw-app.js:105/119 date-band 未来 pill `.future.locked`;pickDay locked → `whisper('最多只能建到明天')` 不进入 | 已建(MVP 锁未来):date-band 不放未来可写 pill;PARITY 行10 check_rejects_future ✅PASS(case_4)、shim check tomorrow→400(mobile-api.js:1664 isWritableDate) | ★`daily_tasks__check_rejects_future` + `catalog_writable_tomorrow`;mobile-api.js:504 isWritableDate |
| 6 | dose>=2 加到中间态(+1 / 子格) | 应:dose>=2 chip 上 +/− 子按钮或左滑减格 | [UI待建]:单 tap toggle()(gw-widgets.js:97)是 `0↔dose` 整体翻,dose>=2 时点一下直接满,**无 +1/中间态/decrement UI**(INTERACTION_TEST_CASES:403 ③号缺口)。shim 端 increment/clamp/decrement 齐(mobile-api.js:1682-1691),纯前端瓶颈 | `daily_tasks__check_clamp` / `check_decrement_unchecks`;PARITY 行34/35 (contract 绿,UI 待建) |

### 负例(必须可见,不静默)

| 负例 | 触发 | PC 预期 | mobile 预期 |
|---|---|---|---|
| 过次日 12:00 补昨天 | 设备/`__now__` 13:00,POST check date=yesterday | 400『不在补卡窗口内』(daily_tasks_routes.py:85),零写入,昨天 md 字节不变 | shim L1664 isWritableDate(yesterday)=false → 400;UI past 日 readonly → tap 不触发。两端一致拒绝 |
| 给未来日打卡 | POST check date=tomorrow(任意时刻) | 400(tomorrow 永不在 _writable_dates_set);catalog is_writable=false | shim 400;date-band 未来 pill locked 不可进入。一致 |
| 前天(超出 yesterday)打卡 | POST check date=<two_days_ago> | 400(闭集只到 yesterday);golden check_rejects_two_days_ago | shim isWritableDate 仅认 today+yesterday → 400。一致 |
| 非 int intake/increment | POST check intake='abc' 或 increment='x' | 500(int() 未捕,故意;非 400/静默)——锁住不被『好心』改成 400 | mobile-api.js:1680 `isNaN(iv)`→ jsonResp 500(对齐);PARITY 行28 ✅。★不对称:/meta 非 int 反而 400(daily_tasks_routes.py:159 try/except),抽出时不能统一掉 |
| intake 超 daily_dose | POST check intake=5,dose=2 | clamp 到 2(_bump_intake min(5,2));today_intake=2 非 5,md [x]+子格全勾 | mobile-api.js:1681 `Math.min(dose,iv)`=2(对齐);但 UI 无连点到中间态入口 → 真 clamp 仅机器层 POST 可验,[UI待建] |
| intake=0 减空 | POST check intake=0(从 1) | intake_log pop 当日 key(server.py:3207),md 退 `- [ ]` | mobile-api.js:1691 `delete log[date]` + 1698 removeSetting taskintake(对齐);UI 无 decrement 手势 → [UI待建] |
| 切昨天但 bridge 未重拉 catalog | date-band tap yesterday 后立即看 care 区 | N/A(桌面每次按 date 实时 GET catalog,无 stale) | ★缺口:pickDay(gw-app.js:118)不重 prefetch,GW.tasks 仍今天值;且 syncPulseState 硬编 todayIso() → 即便可点也写错日。整链断在前端切天数据流 |

**PC 最终态**:PC 跑完(11:00 档,must 全中):
① 当天 md 顶部 `- [x] 鱼油`(经 _set_md_checkbox + _safe_write_text)
② meta-map[鱼油].intake_log[<today>]=1
③ 昨天 md `- [x] 鱼油` + meta-map[鱼油].intake_log[<yesterday>]=1(hour<12 闭集放行)
④ dose>=2 的维生素D:intake_log=2(clamp 非 5)+ md 展两个进度子格全勾
⑤ catalog GET:today is_writable=true、yesterday is_writable=true(11:00)、tomorrow is_writable=false
⑥ 13:00 重跑同一补昨天请求 → 400 零写入,昨天 md/intake_log 字节不变(保持当时样子)
⑦ 非 int intake → 500,md/meta 不变
（13:00 档 must:③改为昨天零写入 + catalog yesterday is_writable=false；其余①②④⑤⑦同）

**验收判据**:整条链跑通 = 6 真全中(对齐 INTERACTION_E2E_PHOTO §5 口径,本旅程无 vision/抠图,故 3/4 替换为窗口判定真相):① 今天打卡真落账(md `- [x]` + intake_log[today]=1)② clamp 真生效(intake=5→2,不写 >dose)③ 补卡窗口真闭集(11:00 补昨天 200 落账 / 13:00 补昨天 400 零写入 / 未来恒 400 —— server `_writable_dates_set` 真源,前端不自算)④ 非 int 真 500(不被改成 400/静默)⑤ catalog is_writable 真 mirror server(today/yesterday-by-hour/tomorrow 三档对)⑥ 截图真渲染(chip done 态 + date-band 选中态 + 只读日灰态)。**判定**:6 真全中 = 该端链活;任一红回退看对应原子 case 缩爆炸半径。**当前**:PC 6/6 全中(daily_tasks_routes 已抽出 + 16/16 characterization GREEN);mobile **契约层(shim)6 真全绿**(PARITY D2/D3/D8 ✅、isWritableDate 闭集已修),但**交互层③/⑥两点红**——切天不重拉 catalog + syncPulseState 硬编 todayIso()(补昨天写错日)+ past 日一律 readonly(hour<12 该可写也锁)+ dose>=2 无中间态 UI → **mobile 补卡 UI 链未通**(后端能补、前端按不到/按了写错日)。

**对齐**:原子 case(INTERACTION_TEST_CASES):本 E2E 串起 `daily_tasks__check_default_dose1`(今天打卡)+ `daily_tasks__check_clamp`★(超量夹)+ `daily_tasks__check_decrement_unchecks`(减格)+ `daily_tasks__check_backfill_yesterday_ok`★(11:00 补)+ `daily_tasks__check_backfill_yesterday_closed`★(13:00 拒)+ `daily_tasks__check_rejects_future`★(未来锁)+ `daily_tasks__check_non_int_intake`★(500)+ `daily_tasks__catalog_writable_yesterday/tomorrow`★(is_writable 三档)+ `journal_days__date_band`(切天)+ `journal_readonly__past_day_no_write`(只读)。
golden(mobile/parity/golden/):check_default_dose1.{response.json,md} · check_clamp.{response.json,md} · check_decrement_unchecks.{response.json,md} · check_backfill_yesterday_ok.{response.json,meta.json} · check_backfill_yesterday_closed.response.json(400) · check_rejects_future.response.json(__now__ 10:00,400) · check_rejects_two_days_ago.response.json · check_non_int_{intake,increment}.response.json · catalog_writable_{yesterday,tomorrow}.response.json —— 全部已存在于 golden 目录(已 ls 确认)。
PARITY_LEDGER:行9 backfill_yesterday_closed ✅ / 行10 rejects_future ✅ / 行11-12 catalog_writable_yesterday+tomorrow ✅ / 行14 check_default_dose1 ✅ / 行28 non_int_intake(500)✅ / 行34 check_clamp ✅ / 行35 decrement_unchecks ✅ / 行52 backfill_yesterday_ok ✅;D2(test_check_backfill_window)L504 isWritableDate ✅ / D3(test_check_intake_increment_clamp)mobile-api.js:1657 ✅ / D8(test_check_rejects_future)✅。
已兜底子步:今天打卡 + clamp + 窗口 400 + non_int 500 + catalog is_writable —— 契约层(shim oracle)+ PC pytest(test_daily_tasks_routes.py:147/168/398/410)全确定性绿。
mobile 未兜(本 E2E 集中成追平 PC 的施工清单):[UI待建] pickDay 切天重拉 catalog;[bug] syncPulseState 用 st.dayKey 对应 iso 替 todayIso();[UI待建] past 日按 server is_writable 分流(hour<12 yesterday 可写)而非一律 readonly;[UI待建] dose>=2 的 +1/decrement 中间态控件。

---

## `e2e_water__tap_to_fifth_cup_subbox_clamp8`

**招牌一句话**:用户在八杯水 widget 连点/滑到第 5 杯 → 系统以 daily_dose=8 记账(防被当普通 task clamp 到 1)→ intake 落 5、md 顶部「喝水」行展开 8 个进度子 box 前 5 个 [x]、八杯水区前 5 杯填充 → 最终态 5/8 杯落进真 md + meta intake_log。

**★Cannot-break 触及**:
- 八杯水 daily_dose=8 防 clamp 到 1(caller 必须传 daily_dose=CUPS_TOTAL,否则 fresh meta 默认 dose=1 会把 intake=5 夹成 1;daily_tasks_routes.py:93-107 注释 + server.py:_bump_intake L3205 clamp [0,dose])
- 子 box 勾选态(daily_dose>1 → _ensure_md_progress_children 把「喝水」行下挂 8 个缩进子 box,前 K 个 [x];server.py:3250-3316;_read_daily_tasks_from_md L3243 只取顶层不把子 box 当独立 task)
- __water_cup__ 保留 key 不进 tasks 清单(WATER_CUP_KEY server.py:3348 只承载杯子图片,与「喝水」打卡 task 名是两件事;水杯图不勾 md box、不跑 OCR 颗数)
- intake clamp [0, daily_dose] 数学(_bump_intake set_to → max(0,min(new,dose));mobile 复刻 mobile-api.js:1681 Math.min(dose,iv),由 test_check_intake_increment_clamp_and_md_box / daily_tasks__check_clamp 锁)
- _safe_write_text path-lock + fsync(写「喝水」行 + 8 子 box 走原子写,断电内容真到盘)

**前置/环境**:seed 初态:今天 md 存在且顶部 daily-task 段含 `- [ ] 喝水` 一行(PC = find_today_journal 当天文件 / SCHEDULE_TEMPLATE 模板顶部;mobile = Store.readJournalMd(today) 非 null + parseSupplements 能解析出「喝水」)。meta-map 该 task 可为 fresh(无 taskmeta/喝水 key)——正是验「fresh meta 默认 dose=1 会 clamp 到 1,靠 caller 传 daily_dose=8 救」的关键初态;若已有 daily_dose=8 则验 init 不覆盖老值(ritual.js:177-178 注释)。**不需要真 LLM/key**:本旅程是纯 widget 真 tap → 端点确定性记账,不走 chat/vision/抠图;属交互层(可进确定性批次),非 E2E 真 AI 链。八杯水水位与水杯图片(__water_cup__/抠图/真 key)无关,本 case 不碰图片。

### PC 链(完整可跑)

| # | 操作(真 tap/drag/说话) | 机制 | ①屏幕 | ②落账 | 契约/golden |
|---|---|---|---|---|---|
| 1 | 打开单日页/总览,八杯水 widget 渲染 8 个空杯(ritual.js render L105-118 / index-paper-data.js L70-72 / day-paper-data.js L547) | 页面 init → GET /api/daily-tasks?date=today(daily_tasks_routes.py:catalog L28-59)读 md「喝水」行 + meta state;ritual.js refresh L74-75 取 wt=find(name=="喝水"),intakeFromMd=min(8, today_intake) | 8 个 .cup 全空(无 .filled);.care-count `0 / 8 杯`(ritual.js L118)/ paper `0 / 8` | 无写(纯读) | catalog shape D1/test_catalog_shape_and_is_writable;tasks[] 含「喝水」{daily_dose, today_intake};对齐 daily_tasks__catalog_fresh golden |
| 2 | tap 第 5 个杯子(data-k=4)——「连点到第 5 杯」= level-meter 点 k=4 一次直接置 5(也可 1→5 逐杯点) | ritual.js cup pointerup L150-188:k=4 → next=(k+1>prev)?(k+1):k=5 → state.cups=5 → 重渲 .filled → POST /api/daily-tasks/check {task_name:"喝水", intake:5, daily_dose:CUPS_TOTAL=8}(L179-183)。server daily_task_check(daily_tasks_routes.py:63):init_dose=8 → 仅当 meta 无「喝水」或无 daily_dose 时 seed daily_dose=8(L96-107,★防 clamp 关键)→ 走 intake 分支 _bump_intake(set_to=5)(L109-110)→ server.py:3187 clamp new=max(0,min(5,8))=5(L3205);md_checked=5>=8=False(L121);daily_dose>1 → _ensure_md_progress_children("喝水",8,5)(L126-129) | 前 5 个 .cup 加 .filled,第 5 杯 .just-filled 注水动画(L164-173);#cups-count=5;.care-count `5 / 8 杯`;widget 不出现顶层全勾(5<8 未满) | ① taskmeta「喝水」首记 daily_dose=8 + intake_log[today]=5(server.py:_bump_intake L3209-3213,_save_task_meta_map);② 当天 md 顶部 `- [ ] 喝水` 行下挂 8 个缩进子 box,前 5 个 `  - [x] 1..5`、后 3 个 `  - [ ] 6..8`,父行仍 `- [ ]`(5<8 未满,server.py:3297-3303);_safe_write_text lock+fsync(L3313) | daily_tasks__check_clamp ★(intake 不被夹成 1,因 dose=8)+ _bump_intake 数学;子 box = test_check_intake_increment_clamp_and_md_box / D3;golden daily_tasks__check_clamp.md + .response.json(today_intake=5,daily_dose=8,checked=false) |
| 3 | reload 单日页验持久化 | GET /api/daily-tasks → catalog 重读 md + meta:_task_meta_state 返 today_intake=5/daily_dose=8;catalog L50-52 对今天 _ensure_md_progress_children 幂等保持子 box | 八杯水区仍前 5 杯 filled、`5 / 8 杯`;reload 不回弹到 1(证 dose=8 落账成功) | 幂等:md 子 box + meta 不变(_ensure_md_progress_children 已 in-sync 直接 continue,server.py:3305-3306) | 幂等 = backfill-progress idempotent(daily_tasks_routes.py:175-200 family);roundtrip 对齐 catalog golden |

### mobile 链(现状 / 缺口)

| # | 操作 | 机制 | 现状 | 契约 |
|---|---|---|---|---|
| 1 | 在 .gw-cups 横滑/连点到第 5 杯 | gw-widgets.js renderCups L24-65:pointerdown/move apply(clientX)→ idxAt 取最近杯 i=4 → st.water=i+1=5 → paint() 前 5 杯填充(L49-55);pointerup end()→ GW.bus.emit('pulse')(L60) | 已建(UI + 手势真就绪);对齐 daily_tasks__water_drag_fill(PARITY_LEDGER 已 PASS,UI已建) | 水位滑动 UI = daily_tasks__water_drag_fill |
| 2 | (自动)pulse 防抖 250ms → 同步水位到后端 | gw-real-bridge.js bindWriteHooks L165-172 → syncPulseState L180-184:postJson('/api/daily-tasks/water', {date:today, filled:st.water=5}) | 已建,但走 mobile 自创 endpoint /api/daily-tasks/water(PARITY_LEDGER N3 标 OUT 架构分叉),**不走 /check 的 daily_dose=8 防 clamp 路径** | daily_tasks__water_drag_fill(contract);N3 /water 行为映射回 check |
| 3 | (后端)水位落账 | mobile-api.js POST /api/daily-tasks/water L1710-1718:filled=Math.max(0,Math.min(8,body.filled))内联硬编 8 → setWaterFilled(md, 5)写当天 md 八杯水段子杯勾选;**不经 _bump_intake、不读 taskmeta daily_dose、不存 taskintake/喝水** | 已建但语义分叉:① 硬编 min(8,..) 而非 caller 传 daily_dose=8 → PC 「防被当普通 task clamp 到 1」红线在 mobile 根本不触发(架构上绕开,非同一条防线);② 水位写 md「八杯水段」格式,与 PC「喝水」task + 8 个 _ensure_md_progress_children 子 box 是**两套 md 写法**;③ taskmeta/喝水 intake_log 不写(PC 写) | ★parity 洞:N3 /water OUT;mobile 八杯水 ≠ PC「喝水」task/check 链;clamp-to-8 是内联常量不是 dose 防线 → 「daily_dose=8 防 clamp」红线 mobile 无对等实装 |
| 4 | 八杯水图标(自定义杯子图)显示 | gw-widgets.js cupSVG L9-21 写死钢笔速写 SVG,renderCups L38 cup.innerHTML=cupSVG(i<st.water) 只按水位填充,不读 water_cup_img | [UI待建]:八杯水 widget 不读 __water_cup__/water_cup_img;即便 POST /api/water-cup 存了抠图杯子(mobile-api.js:1378 端点已建),8 杯永远 cupSVG —— 与本水位旅程正交,但确认水杯图与水位是两条独立链 | D6 daily_tasks__water_cup_post(端点已建 contract);renderCups 渲染缺 water_cup_img 分支 |
| 5 | AI 对话版「帮我喝水记 5 杯」 | mobile TOOL_SPECS check_daily_task(mobile-api.js:873)走 /api/daily-tasks/check;dispatchTool L1015 | AI 链:check_daily_task tool 存在 → 若 AI emit {task_name:"喝水",intake:5} 但**不传 daily_dose=8**,则 mobile-api.js:1675 dose=max(1,meta.daily_dose\|\|1),fresh meta 下 dose=1 → next=min(1,5)=1,**会 clamp 到 1 杯**;AI 须显式带 daily_dose=8 才对(无 vision-pre-router/WORKFLOW hint 提示 → 易漏) | ★parity 隐患:AI 走 /check 路径时缺 daily_dose=8 注入 → 复现「八杯水被 clamp 到 1」原 bug;PC 由 ritual.js 前端硬带 dose=8 兜住,mobile widget 走 /water 绕开、AI 走 /check 无兜底 |

### 负例(必须可见,不静默)

| 负例 | 触发 | PC 预期 | mobile 预期 |
|---|---|---|---|
| fresh meta 不传 daily_dose → 被当普通 task clamp 到 1(★本旅程核心红线) | POST /api/daily-tasks/check {task_name:"喝水", intake:5}(漏 daily_dose)且 meta 无「喝水」key | server init_dose=None 不 seed → _bump_intake 读 daily_dose 默认 1 → clamp new=min(5,1)=1 → today_intake=1(暴露:UI 不传 dose=8 就回 clamp-to-1 bug)。ritual.js 永远带 daily_dose=CUPS_TOTAL(L181)= 这条红线的兜底 | mobile widget 不走 /check 而走 /water(min(8,5)=5 落账正常);但 mobile AI 走 /check 漏 dose=8 → mobile-api.js:1675 dose=1 → next=min(1,5)=1 clamp 到 1(★parity 洞:AI 链无 dose=8 注入兜底) |
| 超量 intake 必夹到 8 不能写 >8 | POST /check {task_name:"喝水", intake:99, daily_dose:8} | _bump_intake clamp new=min(99,8)=8;md 8 子 box 全 [x] + 父行 [x];today_intake=8(daily_tasks__check_clamp ★) | /check:Math.min(8,99)=8(mobile-api.js:1681);/water:Math.min(8,99)=8(mobile-api.js:1712)。两路都夹到 8 |
| 降级:点回第 2 杯把 3-5 清空 | 已 5 杯,tap k=1(第 2 杯)→ ritual.js L160 next=k=1(降级) | state.cups=1;POST check intake=1 dose=8 → _ensure_md_progress_children 重写前 1 个 [x] 其余 [ ];intake=0 时 intake_log pop 当日 key(_bump_intake L3206-3207) | mobile widget apply 只升不降(st.water=i+1,L54 总是设为点击位+1)—— 降级语义与 PC 不完全一致(PC 点已填杯可降,mobile 点哪杯设到哪杯+1);属已知交互差异 |
| 补卡窗口外打卡昨天 12 点后 | POST /check {task_name:"喝水", intake:5, daily_dose:8, date:昨天}且 hour>=12 | date not in _writable_dates_set → 400「不在补卡窗口」(daily_tasks_routes.py:85-87) | /check:isWritableDate=false → 400(mobile-api.js:1664,D2/D8);但 /water 路径 syncPulseState 永远用 todayIso() 不传历史 date(gw-real-bridge.js:182-184)→ 切历史日滑水仍写今天(INTERACTION_TEST_CASES 缺口②:backfill 写操作链未通) |
| 非整 intake | POST /check {task_name:"喝水", intake:"abc", daily_dose:8} | int("abc") raise → 500(故意无 try/except,daily_tasks__check_non_int_intake ★锁住不被改静默) | isNaN(iv) → 500「intake 必须是整数」(mobile-api.js:1680);对齐 |
| 「喝水」task 不该和 __water_cup__ 图片 key 混淆 | 水位记 5 杯后查 image-map | image-map[__water_cup__] 与「喝水」打卡互不影响:不写水位、水位不写图;「喝水」是 tasks 清单内 task,__water_cup__ 是保留 key 不进 catalog tasks[] | taskimg/water_cup_img(图)与 八杯水水位(/water filled)两套 setting key,互不串 |

**PC 最终态**:① 当天真 md 顶部 daily-task 段:`- [ ] 喝水` 父行下挂 8 个缩进子 box,前 5 个 `  - [x] 1..5`、后 3 个 `  - [ ] 6..8`(父行未勾,5<8)— PC 经 _ensure_md_progress_children
② taskmeta「喝水」:daily_dose=8(首记 seed,不覆盖老值)+ intake_log[today]=5 — PC 经 _bump_intake/_save_task_meta_map
③ 八杯水 widget:前 5 杯 filled、计数 `5 / 8 杯`;reload 不回弹(证 dose=8 落账,未被 clamp 到 1)
④ __water_cup__ / 水杯图片 key 不受影响、不进 tasks 清单、不写 total_pills(水位不跑 OCR)
⑤【mobile 现状】水位 5 经 /api/daily-tasks/water(filled=5,内联 min(8,..))落 md 八杯水段 — UI已建可达 5/8;但走的是 mobile 自创 endpoint(N3 OUT),**不经 daily_dose=8 防 clamp 路径**,与 PC「喝水」task+8 子 box+intake_log 三处落账非同一套;AI 走 /check 时缺 daily_dose=8 注入 → 会复现 clamp-to-1(★parity 洞,无兜底)

**验收判据**:整条链跑通 = 4 真全中:① 水位真进(tap/滑到第 5 杯,UI 前 5 杯真填充、计数真到 5)② 记账防 clamp 真生效(PC 经 daily_dose=8 落 intake=5 而非被夹成 1;reload 不回弹)③ md 子 box 真落账(8 个缩进子 box 前 5 [x] 后 3 [ ],父行未勾,字节级对齐 golden)④ meta 真持久(taskmeta daily_dose=8 + intake_log[today]=5)。PC 端 4 真全中 = 链活;mobile 端水位 UI已建可达 5(真①),但记账走 /water 内联 min(8) 而非 dose 防线(真②架构分叉、非同一红线实装)、md 写法是「八杯水段」非 PC「喝水」task 子 box(真③不对齐)、AI 链 /check 缺 dose=8 注入有 clamp-to-1 隐患 → mobile 整链未与 PC 对齐(标 ★parity 洞 N3 + AI dose 注入缺口)。

**对齐**:原子 case(INTERACTION_TEST_CASES):本旅程串起 `daily_tasks__check_clamp` ★(intake 不被夹成 1,因 dose=8 + clamp [0,dose])+ `daily_tasks__check_default_dose1`(check 落账+md box)+ `daily_tasks__water_drag_fill`(mobile 八杯水滑动 UI)+ `daily_tasks__catalog_fresh`(catalog shape/roundtrip)。golden(mobile/parity/golden/):daily_tasks__check_clamp.response.json(today_intake clamp、本 case 验 dose=8→intake=5)+ daily_tasks__check_clamp.md(子 box 字节)+ daily_tasks__catalog_fresh.response.json;水位走 /water 无独立 golden(contract,/water 返 {ok,filled})。PARITY_LEDGER key:D3 test_check_intake_increment_clamp_and_md_box(_bump_intake 数学 + dose>=2 子 box,mobile-api.js L1262/L634/L646,✅)、daily_tasks__check_clamp(★Cannot-break,clamp 到 dose,✅ contract)、daily_tasks__check_non_int_intake(500 锁,✅)、daily_tasks__water_drag_fill(UI已建,✅)、★N3 /api/daily-tasks/water(标 **OUT** 架构分叉 — mobile 八杯水单走 /water 快路径,行为映射回 check;= 本 case mobile 链「不经 daily_dose=8 防 clamp」的根因)。已兜底子步:catalog/check clamp/non-int/water-drag 端点确定性绿;未兜底/parity 洞:mobile 八杯水水位与 PC「喝水」task 走两套 md+endpoint(N3 OUT)、mobile AI 走 /check 缺 daily_dose=8 注入兜底(无 vision-pre-router/WORKFLOW hint 提示带 dose=8)。

---

## `e2e_journal__ai_refused_then_append_comment`

**招牌一句话**:用户在对话里让 AI 改写自己亲手写的某条 @user entry → authorship 8 层防御拒(403,@user 块字节零变化)→ AI 改走 append_journal_comment,在原 body 末尾追加 *AI:* 评论(原 H2 + 原散文一字不动)→ 收尾文字被 claim 审计放行(因有真 append action,不加 disclaimer)。

**★Cannot-break 触及**:
- AI 字节级不可覆盖 @user 块(_patch_block author='ai' 撞 @user owner → 403;8 层防御 + test_authorship pytest 守门;失败安全:无 @marker 默认 owner=user 也受保护)
- _append_comment_to_block 只在 block end 前插入,绝不改原 H2 / 原 body(authorship 合法旁路)
- claim 审计(Path X / 5.22 msg5-7 事故):AI 文本声称『已改/已加』但 last_actions 空 → 自动加 server-audit disclaimer 暴露;本链因真 append 成功故不触发 disclaimer
- patch H2-mismatch guard(5.29 联想 entry 被吃事故反向防御):author='ai' + new H2 strip ≠ existing H2 strip + 无 allow_h2_rename → 409,原段不被整段替换
- _safe_write_text lock+fsync + sha256 baseline 锁内重读(C5,防 Obsidian 并发静默覆盖)
- vault_git.commit_after_write(append-comment 也必经此 hook,否则丢 audit chain)

**前置/环境**:seed 初态:今天 md 已有一条由用户亲手写的 entry,块时间锚 16:30,块内首条 H2 形如 `## #思考 长江电力复盘 @user`(@user marker 是 authorship owner 来源;失败安全下即便漏 marker 也按 user 保护),body 是一段散文。PC 走 uvicorn localhost:4321 真 server.py;mobile 走 simulator + mobile-api.js shim(/api/chat 被 shim 劫持,不打 PC chat_routes)。**需真 LLM**(DeepSeek v4-pro chat 大脑):本链招牌点 = AI 真自主决策「patch 被拒 → 改走 append」,mock dispatch 兜不到这个跨步衔接;authorship 403 / append 落账 / claim 审计本身可由原子 case 用确定性 mock 覆盖(见 alignment),E2E 补真 AI 真撞墙真转弯那一段。无 vision/OCR/抠图需求(纯文字链),dashscope_key 非必需。

### PC 链(完整可跑)

| # | 操作(真 tap/drag/说话) | 机制 | ①屏幕 | ②落账 | 契约/golden |
|---|---|---|---|---|---|
| 1 | 用户在侧栏对话流输入「把今天 16:30 那条长江电力复盘改写一下,口气更乐观点」,回车 | POST /api/chat(chat_routes.py:584);body 带 message + history;[time-block]/[view-date] hint 注入(chat_routes.py:602-605,date 默认当前浏览日) | user 气泡出现含该文字;AI 区开始磨墨 | —(本步不写盘) | chat SSE 契约;_initial_groups 自动 load journal 组(server.py:2236) |
| 2 | (AI 自主)AI 先 emit read_today_schedule 确认 16:30 块存在 + 是 @user 所有 | _dispatch_tool('read_today_schedule')(chat_routes.py:506)→ tool_read_today_schedule → _journal_for_date;SSE yield {type:'action',name,args,result}(chat_routes.py:509/481/400) | 第 1 个 tool chip doing→ok(read_today_schedule) | —(read 类,无写) | read quota=5;action 事件 shape {type:action,id,name,args,result}(chat_routes.py:192 注释) |
| 3 | (AI 自主)AI emit patch_journal_block(time=16:30,new_md=改写后的整段)企图覆盖原 entry | _dispatch_tool('patch_journal_block')→ tool_patch_journal_block(server.py:1366,固定 author='ai')→ _patch_block(server.py:4977)扫块内首条 H2 → _check_author(server.py:2782)返 'user' → 撞 authorship boundary(server.py:5010-5016) | 第 2 个 tool chip 进入 fail 态(patch 返 error);AI 区无『已改写』文字直冒(下一步才决策) | ★今天 md 字节零变化 —— _patch_block 在 boundary check 处 early-return error,根本没走到 _safe_write_text;16:30 块 @user H2 + 原 body 完整保留 | ★`journal_authorship__ai_refuses_user_block`(PARITY_LEDGER L15)+ golden journal__patch_ai_refuses_user.result.json 断 error 串 `block @ 16:30 是 @user 所有,AI 不能 patch。想加评论用 append_journal_comment;想新加 entry 用 insert_journal_block。`;test_patch_block_ai_refuses_user_block |
| 4 | (AI 自主)AI 读到 error 文案里的指引 → 改 emit append_journal_comment(time=16:30,comment_md='*AI:* 换个乐观视角…') | _dispatch_tool('append_journal_comment')→ tool_append_journal_comment(server.py:1407,读 args['comment_md'])→ _append_comment_to_block(server.py:5071)在 block end 前插入 comment,sha256 锁内重读 + _safe_write_text(rotate)+ vault_git.commit_after_write | 第 3 个 tool chip doing→ok(append_journal_comment);单日页 16:30 块底部出现 *AI:* 评论段,原散文在其上方不动 | 今天 md:16:30 块**原 H2 `## #思考 长江电力复盘 @user` + 原 body 一字不动**,块末尾新增一空行 + `*AI:* …` 评论;git commit `append-comment <stem> 16:30` author=ai | ★golden journal__append_comment.result.json 断 {appended:'16:30',file:…};`journal_append__add_content_to_block`(PARITY_LEDGER L23)『md 含原 body + 新批注』;test_append_comment_preserves_original_body(原文一字不动语义) |
| 5 | (AI 自主)AI 出收尾文字「这条是你自己写的,我不能直接改 —— 在底下加了一段 AI 注,给了个更乐观的角度」 | _stream_final_reply(chat_routes.py:298,单一 chokepoint)+ _audit_unauthorized_claim(chat_routes.py:280)查 last_actions | AI 文本正常显示,**无 server-audit disclaimer**(因 last_actions 含 read+append 真 action,claim 审计放行) | — | ★claim 审计红线(chat_routes.py:270-285):last_actions 非空 → _audit 直接 return content 不加 disclaimer;反例(若 AI 谎称『已改写』但 actions 空)才注入 _CLAIM_DISCLAIMER;DSML 泄漏闸同 chokepoint suppress |

### mobile 链(现状 / 缺口)

| # | 操作 | 机制 | 现状 | 契约 |
|---|---|---|---|---|
| 1 | 用户在对话 tab(底部 ☰·日记·对话 的『对话』)chatbar 输入「把今天 16:30 那条长江电力复盘改写一下」,tap 发送 | gw-app.js:167 chatbar fire → GW.sendChat(gw-real-bridge.js:264)→ fetch('/api/chat')(被 mobile-api.js shim 劫持,L1174 chatViaDeepseek 多轮 tool loop) | 已建:对话 UI + 真 SSE 流式 + 磨墨等待态(gw-real-bridge.js:282)+ tool chip 三态(.gw-chip-tool doing/ok/fail)全在;真机经原生 HTTP 桥连 DeepSeek(浏览器直连受 CORS,会 emit『真机经原生 HTTP 桥即可』提示,mobile-api.js:1268) | 对齐 PC POST /api/chat;注意 mobile /api/chat 是 shim 自实现非 PC chat_routes |
| 2 | (AI 自主)read_today_schedule → patch_journal_block(撞 @user)→ 403 | chatViaDeepseek dispatchTool(mobile-api.js:993):writeJournalTools 注入 author='ai'(L998-999)→ POST /api/journal/patch shim(mobile-api.js:2097)→ checkAuthor(L548)返 'user' → 403 + error 串(L2135-2136);events.push tool_result ok=false(L1247) | 已建:authorship 403 防御完整复刻;tool chip 转 fail 态(bridge L355-360 听 tool_result ok=false)。**SSE 事件名分叉(parity 真相)**:mobile shim emit {type:tool_call}+{type:tool_result}(mobile-api.js:1244/1247),PC chat_routes emit 单个 {type:action}(chat_routes.py:509);bridge 只听 tool_call/tool_result(L347/355),不认 PC 的 action —— 两端 SSE 协议未对齐(功能等价但事件 schema 不同) | 对齐 `journal_authorship__ai_refuses_user_block`(PARITY_LEDGER L15)+ golden journal__patch_ai_refuses_user.result.json;mobile shim error 串与 PC 字节一致(403) |
| 3 | (AI 自主)改走 append_journal_comment(time=16:30,…) | dispatchTool case 'append_journal_comment'→ POST /api/journal/append-comment shim(mobile-api.js:2067)→ 读 body.comment → block end 前插入 prefix `*AI:* `+comment → Store.writeJournalMd | 已建,但有 **param 名分叉(parity 真相)**:PC tool 读 args['comment_md'](server.py:1411)、mobile tool spec + shim 都用 `comment`(tool_specs vs mobile-api.js:906/2070);mobile 内部自洽(spec↔shim 同名),但与 PC tool 入参名 comment_md 不对齐 —— 若 AI 按 PC schema emit comment_md,mobile shim 读 body.comment 会拿到 undefined → 400『缺 time 或 comment』。需对齐 param 名或在 shim 双读 comment\|\|comment_md | 对齐 golden journal__append_comment.result.json {appended,file};`journal_append__add_content_to_block`(L23) |
| 4 | 原 body 不动 + 评论上屏 + claim 审计放行 | append 后 thread.save(bridge L321);_auditUnauthorizedClaim(mobile-api.js:1153)last_actions 非空 → 放行不加 disclaimer | 已建:claim 审计端口完整(mobile-api.js:1146-1157)+ DSML strip(L1165);但 **append-comment 后单日页不会自动刷新评论上屏** —— bridge 走对话 tab,16:30 块的 *AI:* 评论需切回日记 tab 触发 reloadDay 重渲才可见([UI待建]:对话内 append 后无 cross-tab 日记 widget refresh 信号) | 对齐 test_append_comment_preserves_original_body(原文一字不动);snapshot_ui 在日记 tab 能断 16:30 块含原文,但断不了『评论实时上屏』 |

### 负例(必须可见,不静默)

| 负例 | 触发 | PC 预期 | mobile 预期 |
|---|---|---|---|
| AI 谎称已改写却没真调任何 tool(claim 审计真兜) | AI 直接回『已经帮你改写成更乐观的版本了』但 last_actions 空(未 emit patch/append) | _audit_unauthorized_claim 命中 _CLAIM_PHRASE_RE『已…/改写』+ actions 空 → 追加 _CLAIM_DISCLAIMER『server audit:本回合未触发任何 tool…日记没改』;md 字节零变化 | _auditUnauthorizedClaim(mobile-api.js:1153)同款追加 disclaimer;md 零变化 |
| AI 误用 patch 当 insert(H2-mismatch guard,5.29 反向防御) | AI 对一个 @ai 自有块 emit patch,但 new_md 第一个 H2 与现存 H2(去 @marker)不同,且无 allow_h2_rename | _patch_block(server.py:5040-5052)返 error『…patch 会整段替换,原 H2+body 会被吃掉…想加新 H2 用 insert』;原段不被替换 | mobile patch shim(mobile-api.js:2144-2152)返 409 + conflict:true;原段保留;对齐 `journal_h2guard__ai_rename_blocked`(L17) |
| append-comment 漏 time 或漏 comment | AI emit append_journal_comment 缺 time 或缺 comment_md | tool_append_journal_comment(server.py:1412-1415)返 {error:'need time HH:MM'} / {error:'need comment_md'};不写盘 | shim(mobile-api.js:2072)返 400 {error:'缺 time 或 comment'};UI tool chip fail 不静默吞 |
| patch 漏 new_md | AI emit patch_journal_block 缺 new_md | journal_patch HTTP 端点 raise 400『need {time,new_md}』(journal_routes.py:174-175);LLM tool 路径 args['new_md'] KeyError 兜底 | mobile patch shim(mobile-api.js:2109)body.new_md==null → 400 {ok:false,error:'缺 new_md'}(J12 test_patch_missing_new_md_400) |
| 目标时间块不存在 | AI patch/append 一个今天 md 里没有的时间块(如 25:00) | _patch_block(server.py:5000)/_append_comment_to_block(server.py:5087)返 error『time block # … not found』;不写盘 | mobile shim 返 404『time block … not found』(mobile-api.js:2082/2123) |
| 用户自己经 UI 改自己的块(对照:user 路径合法,不撞 authorship) | 用户在日记 tab 长按 16:30 → 『改一块』编辑信笺改 body 落笔(非对话 AI 路径) | POST /api/journal/patch author='user'(journal_routes.py:188-189)→ _patch_block author='user' 跳过 authorship boundary → 200 真改;证明红线只拦 AI 不拦本人 | reloadDay → syncJournalDiff → POST /api/journal/patch {author:'user'}(gw-real-bridge.js:240);mobile shim 默认 author='user'(mobile-api.js:2111)放行;对齐 `journal_edit__tap_entry_patch`(L22)+ test_patch_http_user_can_patch_ai_block |

**PC 最终态**:① 今天 md 的 16:30 块:原 H2 `## #思考 长江电力复盘 @user` + 原散文 body **字节零变化**(authorship 红线兑现:AI 没能覆盖一个字节)
② 同块 body 末尾新增一空行 + `*AI:* …` 评论段(append 旁路落账)
③ git 多一条 commit『append-comment <stem> 16:30』author=ai(audit chain 完整),且**无**『patch … 16:30』commit(patch 被拒未写盘)
④ chat 流三个 tool chip:read_today_schedule ✓ / patch_journal_block ✗(fail)/ append_journal_comment ✓
⑤ AI 收尾文字正常显示,**无 server-audit disclaimer**(last_actions 含真 action,claim 审计放行)
⑥ 单日页 16:30 块视觉:原散文在上、*AI:* 评论在下,人宋体/AI 文楷两位作者可辨

**验收判据**:整条招牌链『活着』= 5 真全中:① AI 真撞墙(patch 真返 403,非 mock)② @user 块真零变化(md 字节 diff = 空)③ AI 真转弯(自主改 emit append_journal_comment,非脚本)④ 原 body 真不丢 + 评论真追加(append 落账 + 原文一字不动)⑤ claim 审计真放行(有真 action → 不加 disclaimer;且反例下真撒谎能被加 disclaimer)。任一红 → 标 [UI待建]/[链断] 并回退看对应原子 case 缩小爆炸半径。PC:5 真全中,整链通。mobile:authorship 403 + append 落账 + claim 审计三个原子契约全绿,AI 对话 tool loop 已真接 /api/chat SSE,但 ① SSE 事件 schema 与 PC 分叉(tool_call/tool_result vs action)② append 入参名 comment vs comment_md 分叉 ③ 对话内 append 后日记 widget 不自动刷新评论上屏([UI待建])—— 三处 parity/UI 缝补完才算与 PC 完全追平。

**对齐**:原子 case(INTERACTION_TEST_CASES):`journal_authorship__ai_refuses_user_block`(★Cannot-break,403 + md 零变化)钉 patch-被拒段;`journal_append__add_content_to_block`(L23,md 含原 body + 新批注)钉 append 段;`journal_h2guard__ai_rename_blocked`(L17)+ `journal_edit__tap_entry_patch`(L22,user 路径合法)做边界对照;claim 审计无独立原子 case,靠 test_claim_audit(chat_routes 自测,_audit_unauthorized_claim re-export L9)。golden:journal__patch_ai_refuses_user.result.json(403 error 串字节)、journal__append_comment.result.json + journal__append_comment.md(appended 响应 + 原文保留 md)、journal__patch_h2_rename_blocked.result.json(409)。PARITY_LEDGER keys:L15 ai_refuses_user_block ✅PASS(contract)、L16 ai_allows_ai_block ✅、L17 h2guard_rename_blocked ✅、L23 append__add_content ✅、L22 edit__tap_entry_patch ✅。已兜底子步:authorship 403 / append 落账 / H2-guard / claim 审计 —— CI 确定性绿,E2E 跑挂先排除它们;E2E 独有兜不到的:真 LLM 自主『patch 被拒 → 改 append』跨步决策、claim 审计在真 AI 真撒谎时是否真兜。新增缺口待补:① mobile SSE 事件名对齐(tool_call/tool_result ↔ action)② append 入参 comment_md↔comment 对齐或 shim 双读 ③ 对话内 append 后 cross-tab 日记刷新(均标 [UI待建]/parity 洞,入本 E2E 施工清单)。

---

## `e2e_board__nightly_note_cross_night_memory`

**招牌一句话**:21:30 到点 → cron/手动触发 /api/eval/run → AI 读 past_boards(过去7晚自己的纸条)+ 今天 md → 写一张当晚复盘纸条落 eval-log;次日打开 → 纸条用文楷渲染在留言板/单日页 21:30 块,且内容跟进昨晚的 tomorrow_question(跨夜人格连续)。

**★Cannot-break 触及**:
- past_boards 跨夜注入(_eval_build_messages pulse_eval.py:298 调 _eval_load_past_boards;改这函数不能漏注入 — PULSE 'Cannot break: 留言板 past_boards 注入')
- 段次序固定 today_md → recent_md → past_boards → pulse → claude_md(pulse_eval.py:292-301,T4 顺序契约)
- 笔迹即身份:人=宋体(--font-serif)/ AI 纸条=文楷(--font-kai);PC slip + mobile .gw-note-body 都必须落 AI 楷体(DESIGN_BRIEF 铁律 + tokens.css:15-16)
- AI 人格连续(侧栏高效 / 纸条慢写同一个存在,不切客服感;past_boards 注入是这条的技术实现)
- claim 审计:AI 收尾不许谎称已写(chat 路径 _audit_unauthorized_claim chat_routes.py:280;mobile _auditUnauthorizedClaim mobile-api.js:1146)
- _eval_load_past_boards 严格 stem < target 升序取最近 N(pulse_eval.py:265)— 不能把今天本身或未来日拉进 past_boards

**前置/环境**:seed 初态:vault 里有过去 ≥2 天的 eval-log md(EVAL_LOG_DIR/YYYY-MM-DD.md,且至少一条含 tomorrow_question,用于验"跨夜跟进")+ 今天有 schedule md(find_today_journal 命中)。**需真 LLM/key**:这是 E2E 招牌链,/api/eval/run 走真 deepseek(get_client 非 None,否则 503 — 见 board_routes.py:124/219);past_boards 注入对不对要看真 AI 有没有被推动跟进昨晚。确定性 CI 走 test_board_routes.py(11)mock 不进本链。mobile 侧需 deepseek_key 存进 Store(setting/deepseek_key)否则 note/check-lazy 直接 skip。

### PC 链(完整可跑)

| # | 操作(真 tap/drag/说话) | 机制 | ①屏幕 | ②落账 | 契约/golden |
|---|---|---|---|---|---|
| 1 | 到 21:30(cron 路径,用户无感)或在留言板 tab 点「立刻跑一次」 | cron 路径:launchd → ~/.human-ai/bin/gw-cron.sh 读 .gateway-port 再 curl /api/eval/run(server.py:5208-5218 写端口给 cron 发现);手动路径:notes-board.js runEvalNow → POST /api/eval/run(notes-board.js:59-76 → board_routes.py:198 eval_run) | 留言板空态显示「还没有任何复盘 / 日程跑到 21:30 自动出」+「立刻跑一次」按钮(notes-board.js:48-57);点后按钮变「AI 在写⋯ (可能要 1-2 分钟)」(notes-board.js:64) | 尚未落账(call 前) | test_board_routes eval_run 契约;client is None → 503(board_routes.py:218) |
| 2 | (server 自动)构造 messages,把过去7晚的纸条注入 user payload | _eval_build_messages(pulse_eval.py:277)调 _eval_load_past_boards(target,7)(pulse_eval.py:298 → 256);files = stem < target_str 升序取最近7(pulse_eval.py:265);payload 段次序 today_md→recent_md→past_boards→pulse→claude_md(pulse_eval.py:292-301) | —(后台) | —(内存 messages;past_boards 段含过去7晚 eval md 原文,用 \n\n---\n\n 拼) | ★Cannot-break:past_boards 注入 + 段次序 T4 守;_eval_load_past_boards 严格 < target 不含今天 |
| 3 | (server)真 deepseek 跑 2-call:主 eval + feature_intro | board_routes.py:263 _call_json(_eval_build_messages(...)) + 264 _call_json(_eval_build_feature_intro_messages);sync SDK 丢 asyncio.to_thread 防阻塞 event loop(board_routes.py:226 注释 — 21:30 整 server 失联的旧锅);异常按子类型分桶 _classify_eval_err + _report_silent_failure(board_routes.py:232-245) | — | —(返 raw + parsed merged,feature_intro 合并 board_routes.py:266-270) | 2-call 编排;JSON parse 失败 → _report_silent_failure('eval_json_parse_failed') 只送长度元数据不送 LLM 评议原文(board_routes.py:256,consent 红线) |
| 4 | (server)持久化纸条 + macOS 通知 | _eval_persist(target,merged)(board_routes.py:272 → pulse_eval.py:351)写 EVAL_LOG_DIR/YYYY-MM-DD.md(rendered md:🌱今天值得肯定/🧭战略建议/🪟还缺什么/tomorrow_question/feature_intro,pulse_eval.py:365+);_eval_notify(board_routes.py:273) | — | ②EVAL_LOG_DIR/<today>.md 真落盘(走 _safe_write_text lock+fsync,pulse_eval.py:355);**不进 vault**(vault-reading AI 看不到,故意,pulse_eval.py 注释) | 返 {ok:true, persisted_to, parsed, eval_parse_ok}(board_routes.py:275-284) |
| 5 | 留言板 tab 刷新显示今晚纸条 | loadBoard → GET /api/eval/list?n=14&include_missing=1(notes-board.js:35 → board_routes.py:27 eval_list);renderStack 垂直 stack 降序(notes-board.js:78);单日页另一入口 renderSlip → GET /api/eval/list?n=30(day-paper-data.js:471)取 item.date==today | ①留言板出现今晚卡片(4 段);单日页 21:30 块出现 <aside class=slip> + 「—— 鲸 留🦭印」(day-paper-data.js:481-482);**AI 文本用文楷渲染**(slip / .gw-note 楷体) | —(读路径) | eval_list clamp n 1..60(board_routes.py:39);include_missing 只补昨天(board_routes.py:53-65) |
| 6 | (次日招牌验证)用户对昨晚纸条「回一句」→ 次日 AI 读到 | 单日页 composer Enter → POST /api/journal/insert-block {time:21:30,tag:回鲸,body}(day-paper-data.js:505-508);次日 eval 跑时该回复在 today_md(find_today_journal)+ 过去纸条在 past_boards → AI 跟进昨晚 tomorrow_question | composer 提示「已夹进今天的 md。明早它会读到。」(day-paper-data.js:510);次日纸条内容真的回应了用户昨天回的那句 | ②今天 md 21:30 块新增 #回鲸 entry;次日 eval-log 纸条体现跨夜跟进(非重复鼓励) | ★人格连续 + past_boards 闭环(写回 md → 次日 today_md/recent_md/past_boards 三处可被读到) |

### mobile 链(现状 / 缺口)

| # | 操作 | 机制 | 现状 | 契约 |
|---|---|---|---|---|
| 1 | 到 21:30 / 打开 app — 期望 AI 自动留当晚纸条 | shim 已建:POST /api/note/check-lazy(mobile-api.js:1986)— 当天 21:30 H2 块是占位 ## 时,扫过去7天 vault 提 21:30 body 当 past_boards(mobile-api.js:2008-2017)→ _evalLazyNote(mobile-api.js:314)真调 deepseek(简化版桌面 _eval_build_messages,past_boards 跨夜连贯 mobile-api.js:312-322)→ patch 写 '## 纸条 @ai' 进 21:30 占位块(mobile-api.js:2023-2025) | **AI链断(UI 未触发)**:grep 全 mobile/m/ + shared/ 对 note/check-lazy 零调用方 → 这个端点永不被触发。即便手动调通,缺啥 = 没有任何 UI 在 app 打开/到点时 fire 它。past_boards 提取逻辑(过去7天 vault 21:30 body)在 shim 里**真实现了**,但死在没有 caller | 对齐 PC _eval_build_messages past_boards 注入(PARITY_LEDGER:283 'note/check-lazy↔eval past_boards 按行为映射');PARITY_LEDGER:331 board/eval 整体判 OUT(desktop-only 不渲染),mobile 用 in-md 纸条形态替代而非 eval-log |
| 2 | 在总览看「21:30 已写/待写」状态 | gw-widgets.js:129 渲 '21:30 ${st.noteWritten?已写:待写}';st.noteWritten 源 = gw-app.js:49 硬编码 false | **[UI待建] + 数据假**:noteWritten 永远 false(gw-app.js:49 硬编码,无任何真数据喂入)→ 状态行永久卡「21:30 待写」,即便 shim 真写了纸条进 md 也不反映。缺啥 = noteWritten 没接 note/check-lazy 结果或 _extractNoteBody 真读 | 无对等 PC 契约(PC 用 eval-log 文件存在性判定;mobile 该读 md 21:30 H2 占位 vs 有 body) |
| 3 | 在对话流看 AI 当晚纸条(note 折页) | gw-chat.js:19-25 buildMsg kind=='note' → .gw-note 折页,body 走 GW.gatewayMd 文楷(components.css:310 .gw-note-body var(--font-kai));note 数据来自 GW.thread/journal | **[UI待建] + mock**:gw-chat.js sendChat(L61)整个是脚本化 mock — reply 是硬编码字符串(L71-73),从不调真 deepseek shim、从不调 note/check-lazy;note 折页目前只由 gw-mock.js:144/160 假数据喂(『昨夜的纸条』);gw-real-bridge.js:127 有 isNote 探测真 md(21:30 + 标题含纸条)但依赖纸条已被 shim 写进 md(而那条 AI 链没 UI 触发)。缺啥 = 真 deepseek 对话桥 + check-lazy 触发 | font-kai 笔迹身份**已就位**(components.css:293 .gw-msg.ai 文楷 / 310 note 文楷 / tokens.css:16);断的是数据链不是渲染层 |
| 4 | (跨夜)看今晚纸条是否跟进昨晚 tomorrow_question | _evalLazyNote sys prompt 已含『过去几晚你给他的纸条』+ past_boards(mobile-api.js:315-318) | **AI链断**:逻辑齐全(past_boards 拼接 mobile-api.js:2017 + prompt 注入)但因首环 check-lazy 无 UI 触发,整条跨夜连贯在 mobile 跑不起来。_auditUnauthorizedClaim(mobile-api.js:1146)防谎称已写的守门**在**,但对话链本身是 mock 不触发它 | 对齐 PC past_boards 跨夜;mobile 简化(不注入 PULSE/CLAUDE.md,mobile-api.js:313 注释) |

### 负例(必须可见,不静默)

| 负例 | 触发 | PC 预期 | mobile 预期 |
|---|---|---|---|
| 首次跑(无任何历史 eval) | EVAL_LOG_DIR 不存在 / target 之前无纸条 | _eval_load_past_boards 返 '(没有历史 eval — 这是第一次)' / '(target 之前没有历史 eval)'(pulse_eval.py:262/267)— 不崩,AI 正常写第一张纸条 | past = dates filter < today 为空 → pastBoards='';_evalLazyNote pastBoards 分支不拼(mobile-api.js:317);若曾触发则正常写第一张 |
| past_boards 注入被误删/段次序被改 | 改 _eval_build_messages 漏掉 _eval_load_past_boards 或换段次序 | ★Cannot-break:AI 看不到昨晚说过啥 → 重复鼓励 / 不跟进 tomorrow_question(跨夜人格断裂);T4 顺序契约 + PULSE 红线守 | mobile-api.js:2017 pastBoards 拼接被改同样断;且 mobile 本就没 UI 触发,二次失守不可见 |
| deepseek 返空 / JSON parse 失败 | LLM 返空文本或非 JSON | 留言板落 _(empty)_ 卡(board_routes.py:163 注释 — 用户次晨看 AI『啥都没说』最高 UX 影响);_report_silent_failure('eval_json_parse_failed') 只送长度元数据不送评议原文(board_routes.py:166,consent 红线) | _evalLazyNote noteText 空 → return jsonResp({skip:'empty eval'})(mobile-api.js:2019)不写占位块,21:30 保持 ## 待下次 |
| 未配 key | deepseek 未配 | client is None → 503 'API client not configured'(board_routes.py:218);不静默 | Store.getSetting('deepseek_key') 空 → skip:'no key'(mobile-api.js:2007)不静默崩,但用户也看不到(无 UI) |
| 21:30 块已有真纸条(非占位) | 当天已写过 | eval-log 文件已存在;再点「立刻跑一次」会重新生成覆盖(runEvalNow 走 eval/run,notes-board.js:59) | firstH2 非占位 ## → skip:'already has note'(mobile-api.js:2005)不重复覆盖用户/已有纸条 |
| AI 谎称已留纸条但实际没写 | 对话里 AI 说『纸条留好了』但 last_actions 为空 | _audit_unauthorized_claim(chat_routes.py:280)兜:加 disclaimer 暴露『本回合未触发任何 tool』 | _auditUnauthorizedClaim(mobile-api.js:1146)端口在;但 mobile 对话是 mock(gw-chat.js:71 硬编码 reply)不经此守门 → 守门空转 |

**PC 最终态**:PC 跑完(must 全中):
① EVAL_LOG_DIR/<today>.md 真落盘(4 段 + feature_intro,经 _safe_write_text lock+fsync),**不进 vault**
② messages 构造时 past_boards 段含过去7晚纸条原文,段次序 today_md→recent_md→past_boards→pulse→claude_md
③ 留言板 tab 显示今晚卡片(降序 stack);单日页 21:30 块出现 slip + 「—— 鲸 留🦭」
④ AI 纸条文本用文楷(--font-kai)渲染,人写的用宋体(--font-serif)— 笔迹即身份
⑤ 今晚内容跟进昨晚 tomorrow_question / 不重复昨晚鼓励(跨夜人格连续 = past_boards 注入的活体证明)
⑥ 用户 composer「回一句」→ insert-block #回鲸 进今天 md → 次日 eval 经 today_md/recent_md/past_boards 读到 → 闭环

mobile 跑完(现状):
① shim note/check-lazy + past_boards 提取 + _evalLazyNote 真 deepseek **全实现**,但**零 UI 调用方** → AI 链不触发
② 总览「21:30 待写」永久卡死(noteWritten 硬编码 false,gw-app.js:49)
③ note 折页渲染层 + 文楷笔迹身份**就位**(components.css:310),但喂的是 gw-mock 假数据
④ 对话流 sendChat 是脚本化 mock(硬编码 reply),从不调真 deepseek / check-lazy
⑤ 跨夜连贯逻辑写好(prompt 含 past_boards)但因首环无触发跑不起来 → 整链在 mobile 未通

**验收判据**:整条链跑通 = 6 真全中(对齐 INTERACTION_E2E_PHOTO §5 口径):1)纸条真写(eval-log md 真落盘,非占位)2)past_boards 真注入(messages 含过去7晚原文 + 段次序对)3)AI 真跟进(今晚内容回应昨晚 tomorrow_question,非重复鼓励 — 真 LLM 被 past_boards 推动)4)笔迹真身份(AI 纸条文楷 / 人宋体,截图人验)5)留言板/单日页真渲染(slip + 🦭印,snapshot/截图)6)跨夜闭环真通(composer 回一句 → 次日 AI 读到)。任一红 → 标 [UI待建]/[AI链断],回退看 test_board_routes.py(11)缩小爆炸半径。**mobile 当前判定:整链未通** — 端点/past_boards 逻辑/文楷渲染全建好(检查点 1/2/4 的零件在),但检查点 3/5/6 因『note/check-lazy 零 UI 触发 + noteWritten 硬编码 false + 对话 mock』红 → AI 链 + 跨夜闭环跑不起来。

**对齐**:原子 case(INTERACTION_TEST_CASES):本链无直接 board 原子 case(board/eval PARITY_LEDGER:331 整体判 OUT desktop-only);最近邻 = X1 chatViaDeepseek(mobile-api.js:1036,含 _auditUnauthorizedClaim + _stripDsml,JS oracle 10/10)— 守对话链的 claim/DSML,本链的 AI 收尾守门复用它。golden:board 簇无 mobile golden(OUT,不进确定性 CI);PC 侧确定性由 test_board_routes.py(11,board_routes.py:14 注释)兜 eval_list/eval_today/eval_run shape + 2-call 编排,但 past_boards 真注入 + 跨夜跟进质量是 E2E 独有(真 LLM,test 兜不到)。PARITY_LEDGER 对齐:283 行『note/check-lazy↔eval past_boards 按行为映射不按端点名』+ 331 行『board/留言板 eval desktop-only 移动不渲染』+ X1(L289)mobile chat tool loop 状态修正。已兜底的子步:eval_list/today/run shape(test_board_routes 11)、claim 审计(test_claim_audit + X1)、DSML strip(X1)、authorship patch(X4,note 写 21:30 占位块走 patch 路径 mobile-api.js:2024 复用此守门)。未兜底(E2E 独有):past_boards → 真 AI → 真跟进的跨步衔接、文楷笔迹截图层、composer 跨夜闭环。mobile 永远兜不到(直到补 UI):note/check-lazy 的 UI 触发器 + noteWritten 真数据 + 对话流去 mock 接真 deepseek 桥。

