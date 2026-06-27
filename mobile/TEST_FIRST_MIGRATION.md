# Test-First Mobile 迁移工作手册

> gateway 桌面 → iOS 移动端迁移的可执行范式。
> 读者：接手移动迁移的任何协作者（人或 AI）。
> 心智模型一句话：**代码搬不动，契约搬得动。我们迁移的是真相，不是实现。**

---

## 1. 一句话范式 + 为什么"代码搬不动、契约搬得动"

**范式**：移动端不是桌面 `server.py` 的翻译；它是同一份**产品契约**在 JS/iOS 环境下的**重新实现**，由 self-test 钉死正确性。

**为什么代码搬不动**：桌面和移动是三对根本性不兼容的运行时——

| 维度 | 桌面 | 移动 |
|------|------|------|
| 语言 | Python | JavaScript（shim 层）|
| I/O 模型 | 同步阻塞 | 异步 Promise |
| 持久化 | filesystem（`.md` 真文件 + flock + fsync）| Capacitor Preferences / plist |

逐行翻译 Python 到 JS 是负成本：你会带进同步假设、文件锁语义、`os.path` 路径约定，全在移动端是错的，还得反向 debug。

**为什么契约搬得动**：上面三对差异都在**实现层**。再往上一层——「同一个输入，系统该产出什么字节 / 什么响应形状 / 什么副作用」——是**运行时无关**的。这一层就是契约，它由五样东西承载（见 §2），代码本身基本扔掉。

**最硬的那块契约 = golden 实例**：桌面对某个输入真跑出来的字节，就是移动端必须复刻的真相。不是"参考桌面怎么写的"，是"复刻桌面产出了什么"。md 是 single source 这条 invariant 决定了：只要 md 字节一致，两端就是同一本日记，git 才能合并。

---

## 2. "有用的 5 类 / 没用的 4 类"对照表

迁移时，桌面侧的产物分两堆。**只许参考左边，右边一律不看**（看了就会被实现细节污染）。

### ✅ 有用的 5 类（迁移的输入）

| # | 类别 | 是什么 | 移动端怎么用 |
|---|------|--------|--------------|
| 1 | **PC 测试 oracle** | pytest characterization 断言（catalog shape / 补卡窗口 403 / clamp / authorship 拒写）| 翻译成 mobile self-test 的 assert 语义；oracle 说"该拒"，mobile 也必须拒 |
| 2 | **产品 spec** | DESIGN_BRIEF / PULSE 的 Cannot-break / 业务铁律（只补昨天、次日 12:00 截止）| 定 self-test 要覆盖哪些场景，定边界值 |
| 3 | **PC golden 实例** | 同一输入桌面真跑出的字节 / JSON 响应（见 §3）| **字节比 / JSON 形状比** 的左操作数，最硬的真相 |
| 4 | **edge-case 知识** | 全角冒号 `：`、sha256 dedup、past_boards 注入、H2 rename gate | self-test 必须显式覆盖的"已知雷区"清单 |
| 5 | **架构 invariant** | md 是 single source；shim 在 fetch 层 hijack；anchor_time 是语义不是像素 | 实现时不可违反的红线；self-test 验副作用落在 md/plist |

### ❌ 没用的 4 类（一律不看）

| # | 类别 | 为什么扔 |
|---|------|----------|
| 1 | **Python 实现代码** | 同步 / 文件锁 / `os.path` 全在移动端是错的；翻译 = 引入 bug |
| 2 | **filesystem 持久化细节** | flock / fsync / uuid tmp 名 / parent dir fsync 是桌面磁盘语义；移动是 plist，无对应物 |
| 3 | **桌面并发 / 锁机制** | `_WRITE_GUARD_LOCKS` / sha256 baseline lock 解决的是 Obsidian 多进程并发；移动单 webview 不存在该 race |
| 4 | **uvicorn / HTTP 传输层** | 移动端 fetch 被 shim 在内存里 hijack，没有真网络栈；端口 / CORS / SSE 帧细节无关 |

> 灰色地带：sha256 dedup 的**行为**（同内容不重复写）是 edge-case 知识（有用，类别 4）；它的**实现**（Python hashlib + flock）是没用类别 3。**永远迁行为，不迁实现。**

---

## 3. golden 实例机制

golden 实例是 §2 类别 3 的载体：桌面对一组固定输入真跑一遍，把输出冻成文件，移动端 self-test 拿它做断言基准。

### 3.1 怎么产：`capture-golden.py`

桌面侧一次性脚本，**不是测试代码，是真相提取器**。流程：

```
对每个 golden case（如 cutout__writes_image_map_meta_and_ocr_pill_count）：
  1. 起一个隔离的桌面 server（HUMAN_AI_HOME 指向临时 vault，绝不碰真 vault）
  2. seed 固定 fixture（已知的 md / 已知的图 / 冻结的"今天"日期）
  3. 用固定输入打真端点（如 POST /api/cutout，带固定 bytes）
  4. 冻结三样产物：
     - response.json     ← HTTP 响应体（JSON 形状 + 值）
     - status.txt        ← HTTP 状态码
     - side_effects/     ← 写盘后的 md 字节、image_map.json、meta.json
  5. 全部写进 mobile/parity/golden/<case_name>/
```

关键纪律：
- **冻结时间**：所有日期锚点（"今天"、"昨天"、补卡窗口）必须用注入的固定 now，否则 golden 隔天就失效。
- **冻结随机**：tmp 名 / uuid 之类不进 golden（那是没用类别 2）；只冻**语义产物**。
- **保真字节**：md 里的全角冒号 `：`（U+FF65/FF1A）、换行、缩进逐字节存，用二进制写避免编码漂移。

### 3.2 放哪：`mobile/parity/golden/`

**扁平命名**（实际产出 109 个文件,`<case_name>.<artifact>` 同目录平铺,不开子目录）:

```
mobile/parity/golden/
  journal__insert_stamps_user.md                  # ★写后 md 字节(single source 真相,字节比)
  journal__insert_stamps_user.response.json       # HTTP 响应稳定子集(JSON 形状比)
  journal__patch_ai_refuses_user.result.json      # helper 层返回(error 键)
  journal__patch_ai_refuses_user.md               # 拒写后 md == 原文(authorship 真相)
  daily_tasks__check_clamp.md                     # dose=2 子 box 字节: - [x] 1 / - [x] 2
  daily_tasks__check_clamp.response.json
  daily_tasks__delete_cascade.{day.md,template.md,images.json,meta.json}  # 多副作用各一文件
  cutout__metamap_after.json                      # OCR 自动填 total_pills=60
  thread__save_stale_409.history_untouched.json   # CAS 拒后文件未动
  ... 共 57 case / 109 文件
```

约定:`<case_name>` = endpoint key(与 self-test case 名、PARITY_LEDGER 行三者对齐,见 §7)。
`.md` = 字节比真相;`.response.json` = JSON 形状比;`.<sideeffect>.json` = plist/map 副作用;
`.asserts.json` = 非确定字段(mtime/含 ts 文件名)归一化后的布尔断言。
**重跑 `capture-golden.py` 全部重产 + 不碰真 vault**;桌面契约一改重跑刷新即可。

### 3.3 mobile self-test 怎么消费

两种比法，按产物类型选：

**A. JSON 形状比**（用于 response / 结构化副作用）
不做整字符串相等——做**形状 + 关键值**断言，容忍无关字段顺序：

```js
// self-test: cutout__writes_image_map_meta_and_ocr_pill_count
const golden = loadGolden("cutout__writes_image_map_meta_and_ocr_pill_count");
const resp = await callApi(golden.input);          // 走 shim hijack
assertStatus(resp, golden.status);                  // 200
assertShape(resp.body, golden.response);            // 形状 + pill_count 值一致
// plist 副作用：meta 真写进去了
const meta = await Preferences.get({ key: imageMetaKey });
assertShape(JSON.parse(meta.value), golden.side_effects.meta);
```

**B. 字节比**（用于 md —— single source，必须字节级一致）
md 是 git 合并的对象，差一个字节两端就分叉，所以 md 走**精确字节相等**：

```js
// self-test: journal__insert_block_http_stamps_user
const golden = loadGolden("journal__insert_block_http_stamps_user");
await callApi(golden.input);
const mdBytes = await readMobileMd(golden.targetDate);   // 从 plist 取出 md 字节
assertBytesEqual(mdBytes, golden.side_effects.md);       // 含全角冒号、@commit 批注、时间戳逐字节相等
```

判据：**md 用字节比，响应/plist 用形状比**。md 字节不一致 = single source 破了 = 直接 FAIL，不许"看起来一样"放过。

---

## 4. Test-First 五步工作流

新功能（或迁一个簇）一律按这五步，**self-test 先于代码**：

```
① 抓 PC oracle
   找到对应 pytest 断言 + golden case，明确"输入→该产出什么"。
   没有 golden? 先回桌面 capture-golden.py 补产一个，再继续。

② 写 mobile self-test（此时必然 RED）
   - fetch 端点（走 shim）
   - assert response 形状/状态（JSON 形状比）
   - assert plist 副作用（Preferences.get 后形状比）
   - assert md 副作用（字节比，若该 case 写 md）
   先跑一遍，确认 RED（端点还没实现 → 失败）。

③ 写代码服务 self-test 通过
   在 shim 层实现该端点的 JS handler，目标只有一个：让 ② 的 self-test 转 GREEN。
   不照抄 Python；照着 oracle + golden 的"该产出什么"重新实现。

④ 真跑 simulator
   build_run_sim → 端点真被触发 → plist verify（真存进去了）→ screenshot（真渲染出来了）。
   self-test GREEN 但 simulator 没渲染/没存 = 没完成（移动比 pytest 多这一层，见 §5）。

⑤ PASS = feature done
   self-test GREEN + plist 真有副作用 + screenshot 真渲染 → 三者齐 = feature 存在。
```

### 完整例子：迁 `journal__insert_block_http_stamps_user`（行内插入并给用户块盖时间戳）

**① 抓 oracle**
- pytest 断言：`POST /api/journal/insert-block` 在指定时间块插入用户内容，server 给该块盖时间戳 + `@user` authorship 标记；缺 time → 400；当天无 journal → 404（对应 case `insert_block_missing_time_400` / `insert_block_no_journal_404`）。
- golden：`mobile/parity/golden/journal__insert_block_http_stamps_user/`，`side_effects/26.6.27(...).md` 是写后字节真相（含全角冒号、时间戳行）。
- edge-case 知识：时间块标题用全角冒号 `7：30`；body placement 规则见 `insert_block_body_placement`。

**② 写 self-test（RED）**
```js
test("journal__insert_block_http_stamps_user", async () => {
  await loadShim();
  await seedGolden("journal__insert_block_http_stamps_user");   // seed input md
  const golden = loadGolden("journal__insert_block_http_stamps_user");

  const resp = await callApi(golden.input);                     // POST insert-block
  assertStatus(resp, 200);

  const md = await readMobileMd(golden.targetDate);
  assertBytesEqual(md, golden.side_effects.md);                 // 字节比：时间戳 + @user 标记逐字节一致

  // 配套负例
  const bad = await callApi({ ...golden.input, body: { ...golden.input.body, time: undefined } });
  assertStatus(bad, 400);                                       // missing time → 400
});
```
跑 → RED（handler 不存在）。

**③ 写代码**
shim 加 `/api/journal/insert-block` handler：定位当天 md → 找全角冒号时间块 → 插入 body → 盖时间戳 + `@user` → 写回 plist。照 golden 字节对齐，**不抄 Python 的 flock/fsync**。跑 self-test → GREEN。

**④ 真跑 simulator**
`build_run_sim` → app 内触发插入 → `Preferences.get` 验 md 真写进 plist → screenshot 验该条 entry 真渲染在时间线上、时间戳可见。

**⑤ PASS**
self-test GREEN + plist 有新 md + screenshot 渲染正确 → done。

---

## 5. self-test = executable spec 的三条判据

self-test 不是"测试代码"，是**可运行的产品定义**。三条判据回答三个问题：

| 判据 | 问题 | 标准 |
|------|------|------|
| **① feature 存在** | 这个功能真的有吗？ | self-test 真跑通 + **plist 真有副作用** + **screenshot 真渲染**。三者缺一 = feature 不存在（不是"差一点"，是不存在）|
| **② refactor 不破坏** | 改了实现还对吗？ | 重构后 self-test 仍全 PASS。PASS = 行为没变；任何一条 RED = 重构引入回归 |
| **③ bug 解决** | 这个 bug 真修了吗？ | 先写一条 self-test **真复现**该 bug（RED）→ 修 → **真不复现**（GREEN）。没复现过的修复不算修复 |

为什么移动端**不能 mock、必须真跑**：桌面 pytest 验到 response + 文件字节就够；移动比 pytest 多一层「真渲染 / 真存 / 真 LLM」——

- **真渲染**：JSON 对了不等于 UI 画对了（PULSE 教训：UI 改动验收必看截图）。
- **真存**：plist 写入有 Capacitor 异步 / 序列化坑，mock 测不到。
- **真 LLM**：past_boards 注入、tool loop、流式 SSE 这些只在真 LLM 往返里暴露，mock 的固定响应盖不住。

所以本地 dev 必须真 simulator，发版前必须真 LLM。

---

## 6. 三层测试平衡表 + 成本

不是每次都全套真跑——按场景分三层，各取 deterministic / 真实性 / 成本的不同平衡：

| 层 | 跑什么 | LLM | 数据源 | 副作用验证 | 成本 / 速度 | 何时用 |
|----|--------|-----|--------|------------|-------------|--------|
| **本地 dev** | 全套 self-test | 真 LLM 可选 | seed golden | **真 simulator + plist + screenshot** | 单轮 15–20 分钟；真 LLM ~0.5 元/轮 | 每写一个 feature / 修一个 bug |
| **CI** | self-test（deterministic 子集）| **mock LLM** | **YAML fixture** | plist 形状比（无 simulator）| 免费、秒级、可重复 | 每次 push / PR gate |
| **发版前** | 全套关键路径 | **真 LLM 1–2 轮** | 真 vault 副本 | 真 simulator + 真 LLM 往返 | ~0.5–1 元 + 30–40 分钟 | 打包出 .ipa 之前 |

trade-off 说明：
- CI 用 mock LLM + YAML fixture 拿 **deterministic 且不花钱**——它的职责是挡回归，不是验真实性。
- 发版前真 LLM 1–2 轮的职责相反：挡 mock 盖不住的真实集成坑（past_boards / tool loop / 流式）。
- 本地 dev 是主力：feature 的"存在性"在这一层用真 simulator 钉死，CI 只是把它的 deterministic 部分自动化复跑。
- 别在 CI 里跑真 LLM（不稳定 + 花钱 + 慢，污染 gate 信号）；别在本地 dev 只跑 mock（漏掉真渲染/真存）。

---

## 7. 接现有制品

本范式不是从零搭，接到两个已存在的制品上：

### 7.1 PARITY_LEDGER —— 用 endpoint key 索引

- PARITY_LEDGER 以 **endpoint key** 为主键登记每个端点的迁移状态。
- golden 目录名（§3.2）、self-test case 名、PARITY_LEDGER 行 **三者用同一个 endpoint key 对齐**，例如 `journal__insert_block_http_stamps_user`。
- 一个 case 走完 §4 五步 → 在 PARITY_LEDGER 把该 key 标 PASS（附 golden 路径 + self-test 路径 + 最近一次真 simulator 截图引用）。
- ledger 是"哪些契约已迁、哪些没迁"的单一真相；新增 golden 必须同步登一行。

### 7.2 harness.mjs —— 待接 `loadShim` / `callApi`

self-test 跑在 `harness.mjs` 上，当前缺两个钩子，**这是落地本范式的前置工程任务**：

| 钩子 | 职责 | 契约 |
|------|------|------|
| `loadShim()` | 在测试进程里加载 fetch-层 shim，使 `callApi` 的请求被内存 hijack（不走真网络）| 调用后 shim 就位；可重复调用幂等；每个 test 前重置 plist 隔离状态 |
| `callApi(input)` | 用 golden 的 `input.json`（method / path / body）打被 hijack 的端点，返回 `{status, body}` | 与桌面 HTTP 语义同形，便于 status/形状直接对 golden |

配套建议 helper（harness 一并提供，self-test 直接用）：
- `loadGolden(caseName)` → 读 `mobile/parity/golden/<caseName>.*`(扁平),按后缀映射成 `{response, md, result, sideEffects}`
- `seedGolden(caseName)` → 把 golden 的 input md / fixture 写进隔离 plist
- `readMobileMd(date)` → 从 plist 取 md 字节，给 `assertBytesEqual`
- `assertShape(actual, expected)` / `assertBytesEqual(a, b)` / `assertStatus(resp, code)`

harness 钩子接通前，self-test 无法运行——所以 **接 `loadShim`/`callApi` 是第 0 号迁移任务**，先于任何 feature case。

---

## 附：本批 golden 实例清单（按簇）

下列 case 即 §3.2 `mobile/parity/golden/` 的初始填充，也是 PARITY_LEDGER 的初始行。

**journal**（17）：new_day_create_then_idempotent · insert_block_http_stamps_user · insert_block_missing_time_400 · insert_block_no_journal_404 · delete_block_clears_to_placeholder · delete_block_unknown_time_404 · patch_routes_by_date_not_today · patch_missing_new_md_400 · patch_ai_refuses_user_block · patch_ai_allows_ai_block · patch_h2_rename_gate · insert_block_body_placement · append_comment_preserves_body · tag_register_appends_and_commits · tag_register_rejects_dup_and_subtag · tag_aggregate_get_sections · tag_stats_default_for_new_user

**daily_tasks**（19）：catalog_fresh · check_clamp · check_default_dose1 · check_decrement_unchecks · check_backfill_yesterday_ok · check_backfill_yesterday_closed_403 · check_rejects_future_and_two_days_ago · catalog_is_writable_window · meta_set_and_clear · meta_non_int_400 · check_non_int_500 · history_oldest_first · water_cup_roundtrip · water_cup_missing_url_400 · delete_cascade · backfill_progress_idempotent · template_task_add_edit · vault__audit_orphans · vault__repair_then_catalog_sees_image

**thread**（11）：history_empty_no_file · history_happy_returns_list · history_corrupt_modal_payload · history_corrupt_no_baks · restore_from_bak_roundtrip · restore_bad_index_low_400 · restore_bad_index_high_400 · restore_missing_bak_404 · save_stale_409_file_untouched · save_fresh_writes · save_non_list_400

**image**（12）：attachments__list_sorted_desc_limit · attachments__list_date_from_filter · attachments__search_filename_original_ocr · attachments__search_empty_q · attachments__delete_removes_file_and_index_entry · attachments__delete_traversal_rejected_400 · attachments__reindex_index_missing_skip_existing · vision__classify_delegates_and_echoes_question · vision__classify_missing_url_400 · cutout__writes_image_map_meta_and_ocr_pill_count · cutout__missing_args_400 · get_attachment__serves_bytes_and_bad_date_400

---

> 维护：新增端点 → 桌面 capture-golden → 落 `mobile/parity/golden/` → 写 self-test（RED）→ 实现（GREEN）→ 真 simulator → PARITY_LEDGER 登 PASS。每一步缺位都不算 feature done。
