# E2E 招牌场景 · 真照片 → AI 识别 → 抠图 → 打卡图标

> **这是端到端(E2E)场景用例,不是原子 case。** 它把多个跨簇交互(upload → vision → cutout →
> set-image → check)串成一条"用户通过 AI 交互写日记"的招牌链,且**带真照片 + 真 LLM/vision**。
> 配套:[`INTERACTION_TEST_CASES.md`](INTERACTION_TEST_CASES.md)(原子 case,确定性)·
> [`TEST_FIRST_MIGRATION.md`](TEST_FIRST_MIGRATION.md)(两层范式)·
> [`PARITY_LEDGER.md`](PARITY_LEDGER.md)(endpoint key/oracle)· `mobile/parity/golden/`(契约底座)。

---

## 0. 这一层在测试金字塔的哪一格

`TEST_FIRST_MIGRATION.md §0` 定了两层模型(契约层 golden 底座 + 交互层 case 本体)。
**本文件是第三层 —— 比交互层更上,且打破"确定性"前提:**

```
E2E 真链层   真照片 + 真 LLM/vision + 真抠图 + 真 tap → 全链路落账 + 截图    ← 本文件(不进 CI)
    ↑ 串起 ↑
交互层       单个真 tap → 屏幕效果 + plist 落账 + 截图(mock 引擎/seed dataURL)  ← INTERACTION_TEST_CASES
    ↑ 撑在 ↑
契约层       callApi(golden.input) → md/plist 字节比                          ← golden 底座,CI 能跑
```

三层职责分工:

| 层 | 在哪 | 输入 | 验什么 | 进 CI? |
|---|---|---|---|---|
| **契约层** | `mobile/parity/golden/` + `capture-golden.py` | 固定 bytes/JSON | 字节 == golden | ✅ 确定性 |
| **交互层** | `INTERACTION_TEST_CASES.md` + `parity/interaction/` | seed dataURL / mock | 单 tap → snapshot_ui + plist | ✅ status graceful |
| **E2E 真链层(本文件)** | 本地 simulator + 真 key | **真药瓶/水杯照片** | **整条链跑通**:照片真进→AI 真识别→抠图真出→图标真显示→plist 真落账→截图真渲染 | ❌ 手动/本地 only |

**为什么 E2E 不进确定性 CI**:真 LLM(qwen3-vl/deepseek)输出非确定、真 iOS Vision OCR 受图像质量影响、
真抠图 alpha 框逐次微抖。CI 里这些早被降级成 mock/seed/`status graceful`(见 PARITY_LEDGER
`cutout case_53 注释"contract,no NativeOcr"`)。E2E 是补"原子 case 各自绿了,但串起来 + 真 AI 时
**用户那条招牌路径是否真的从头通到尾**"的最后一公里。

**它跟原子 case 互补,不替代**:原子 case 钉死每一段引擎对(确定、快、CI);E2E 钉死整条用户故事
活着(真、慢、人验)。E2E 跑挂时,先看哪段原子 case 也挂 → 缩小爆炸半径。

---

## 1. 招牌场景的全貌(为什么这两条 flow 是招牌)

产品一句话 = "让普通人也能跟 AI 共写日记"。其中最有感染力、销售页第一屏要演的动作是:

> 用户随手拖一张**药瓶照片**进对话,说一句"帮我设成鱼油打卡图标",
> AI 自己看懂"这是鱼油 60 粒"、自己把它抠成透明 PNG 贴成补剂打卡图标、自己勾上今天的打卡 ——
> 用户一张照片一句话,三件事 AI 全干完。

这条链横跨 **5 个簇**(chat upload · vision-pre-router · image/cutout · daily-tasks · journal md),
涉及 **真 vision LLM + 真 OCR + 真端侧抠图**,是整个产品"AI 是协作者不是按钮"主张的活体证明。
水杯链(场景 B)是它的姊妹,走保留 key `__water_cup__`,八杯水 widget 用它。

**双端落差(本文件最重要的 parity 真相,先记住)**:

| 能力 | PC(桌面 server.py) | mobile(mobile-api.js shim) |
|---|---|---|
| 照片入口 UI | ✅ thread.js 拖图 → upload | ❌ chatbar 附件按钮只 push 硬编码灰方块占位(gw-app.js:160);换图标只 whisper '(demo)' |
| vision-pre-router 注入 | ✅ `_refs_to_vision_hints`(chat_routes.py:132) | ❌ grep 零命中,AI 收不到 supplement WORKFLOW hint |
| `set_daily_task_image` tool | ✅ TOOL_IMPL(server.py:1531) | ❌ mobile TOOL_SPECS 无此工具,dispatch default 返 unknown tool |
| `set_water_cup_image` tool | ✅ 照片抠图设杯(server.py:1514) | 🟡 有,但 spec 说"优先 emoji 🥤",**语义分叉**(非照片抠图) |
| `/api/cutout` 端点(shim) | ✅ image_routes.py:102 | ✅ mobile-api.js:1491(端点建好,UI 不调) |
| `/api/water-cup` 端点(shim) | ✅ daily_tasks_routes.py:290 | ✅ mobile-api.js:1378(端点建好) |
| chip 渲染 image_url | ✅ 显示抠图 PNG | ❌ renderTasks(gw-widgets.js:87)只渲 emoji glyph,不读 t.image_url |

> **结论**:PC 端整条 E2E 招牌链**完整可跑**;mobile 端**后端 shim 全建好,但首尾 UI 两头空**
> (入口=换图标按钮是 demo 桩;出口=chip 不渲染 image_url),且 AI 链因缺 `set_daily_task_image`
> tool + 缺 vision-pre-router 注入**根本走不通**。本文件的 mobile 步骤大量标 `[UI待建]`,既是测试
> 用例也是追平 PC 的施工清单。

---

## 2. 前置 / 环境

### 2.1 真照片 fixture(seed 进哪)

| fixture | 内容 | 放置位置 | 用途 |
|---|---|---|---|
| `yuyou.jpg` | 鱼油药瓶,标签含"60 粒 / softgels",品牌可见(Swisse) | `mobile/parity/fixtures/photos/` | 场景 A 主照 |
| `ashwa.jpg` | 南非醉茄瓶,标签含"120 粒"(用于"OCR 抽到 120 但用户已手填 30,须尊重手填"负例) | 同上 | 场景 A 负例 |
| `cup.jpg` | 用户自己的水杯(陶瓷/玻璃,主体清晰可抠) | 同上 | 场景 B 主照 |
| `nonpill.jpg` | 一盆绿植或随手客厅照(非补剂、非水杯) | 同上 | 两场景共用负例(vision kind ≠ supplement/水杯) |

**seed 路径分两种**:
- **simulator 相册**(真机/真原生 picker 路径):`xcrun simctl addmedia <UDID> mobile/parity/fixtures/photos/yuyou.jpg`,
  让用户在原生相册选择器里能选到。
- **直接进 attachment**(跳过 UI 入口,只验中后段):把照片转 dataURL `POST /api/chat/upload-image`
  存成 `attachments/<date>/<stem>`,后续 dispatch `/api/cutout` 直接用该 url。
  这是 mobile UI 未建时**唯一能跑到端点的方式**(对应 PARITY case_53 的 seed 手法)。

### 2.2 真 key(E2E 必须配真,这是它跟原子 case 的本质差别)

- **阿里云百炼 dashscope_key** —— vision-pre-router 的 `_qwen_classify_image`(qwen3-vl-flash)+
  mobile native OCR 失败后的 `_ocrViaCloud` 兜底都靠它。**配在 config(单 API 入口红线,只这一把)**。
- **DeepSeek key** —— chat 主对话 LLM(AI emit tool 的那个大脑)。
- 没配 key → vision/chat 退化成可见错误(`{error:'vision_failed'}` / 提示去配钥匙),**不能静默无回复**
  (这本身是负例检查点,见各场景负例)。

### 2.3 iOS native 引擎(真机 / simulator)

- **抠图**:`window.Capacitor.Plugins.Cutout`(CutoutPlugin.swift,`VNGenerateForegroundInstanceMaskRequest`
  = 相册"拷贝主体"同引擎,iOS 17+)。浏览器无 plugin → `BrowserStub` 返空不阻断(engine=BrowserStub)。
- **OCR**:`NativeOcr` plugin(iOS Vision,`native-ocr` swift/kotlin 都在)→ 失败走 `_ocrViaCloud`(百炼)。
- **simulator**:`boot_sim` + `install_app_sim` + `launch_app_sim`;UI 自动化用 XcodeBuildMCP
  `tap`/`long_press`/`snapshot_ui`/`screenshot`/`gesture`。
- **PC 侧**:uvicorn `localhost:4321`,真 server.py(非 shim),三层抠图 macOS Subject Lift → rembg → 百度 → 原图。

### 2.4 验账工具

- **PC**:直接读 `DAILY_TASK_IMAGES_DIR/*.png` + `daily-task-images.json` + `daily-task-meta.json` +
  当天 md + `attachments/<date>/_index.json`。
- **mobile plist**:`xcrun simctl get_app_container <UDID> com.humanai.gateway data` →
  `defaults read .../com.humanai.gateway.plist` 看 `taskimg/<name>` `taskmeta/<name>`
  `taskintake/<name>` `water_cup_img`;attachment 本体在 Filesystem `Directory.DATA` 的 `gw/kv/*.txt`。
- **webview 内断言**:`__GW_TEST_API__` 的 `querySelectorInfo` / `waitForSelector` / `syntheticTap`。

---

## 3. 场景 A:药瓶照片 → 鱼油补剂打卡图标(AI 交互版)

**E2E case 名**:`e2e_photo__pill_bottle_to_supplement_icon`
**招牌一句话**:拖鱼油药瓶照 + 说"设成鱼油打卡图标" → AI 识别 60 粒 → 三层抠图 → 落 image+meta(OCR 自动填 total_pills=60) → 勾今日打卡 → 单日页出现彩色鱼油图标。
**★Cannot-break 触及**:vision-pre-router 缓存模式(不重做 load+save 避 OCR race)· cutout 三层兜底不阻塞 · cutout OCR 自动填 total_pills 须尊重用户已手填 · claim 审计(AI 不许谎称已设) · `_resolve_task_name` 模糊解析(5.28 键对不上坑)。

### 3.A.1 PC 链(完整可跑)

| # | 操作(真 drag/说话) | 机制 | 预期 ① 屏幕(snapshot/截图) | 预期 ② 落账(plist/md/json) | 底层契约 / golden |
|---|---|---|---|---|---|
| 1 | 把 `yuyou.jpg` 拖进侧栏对话流输入区 | thread.js → `POST /api/chat/upload-image`(chat_routes.py:519) | 对话输入区出现图缩略图 chip | `attachments/<date>/HHMMSS-rand.jpg`;sha256 去重(同字节→deduped:true 复用 url);`_index_upsert` 写最小 record;background_tasks 排 `_index_attachment` | 响应 `{url,filename,original,size,deduped}`;dedup = 5.16 重复客厅照 bug 根治点;无独立 golden(走 chat_routes characterization) |
| 2 | (server 自动,用户无感)upload 后台跑 vision 分类缓存 | `_index_attachment → _qwen_classify_image`(server.py:1787) | — | `_index.json[url].vision = {kind:supplement, brand:Swisse, description, pill_count:60, ocr_likely:true, suggested_action}` | ★红线:不改回 load+save(触发 OCR race);`chat_upload_image__dedup_and_logical_url` 原子 case |
| 3 | 输入"帮我设成鱼油打卡图标",回车 | `POST /api/chat`(chat_routes.py:584),body 带 `context.refs=[{kind:image,payload:{url,original,cutout}}]` | user 气泡含图 + 文字 | — | chat SSE 契约;refs schema `{kind,payload}` |
| 4 | (server 自动)vision-pre-router 把 hint hoist 到 user_msg 之前 | `_refs_to_vision_hints`(chat_routes.py:132);cache hit;chat.py:614 hoist `<vision-pre-router 已分类>`(kind=supplement)+ WORKFLOW 三步 | — | — | ★`vision_classify__delegates_and_echoes_question` golden;WORKFLOW hint 存在由 `test_day_one_and_water_cup` 守 |
| 5 | AI 读 hint(kind=supplement)→ 决定三步连做,**不调 vision_classify** | LLM 收到 brand=Swisse + 指令"① read_today_schedule 匹配 task ② set_daily_task_image ③ check_daily_task";`_initial_groups` 已自动 load images 组 | AI 区开始出 tool chip | — | tool description"vision_classify 通常不必调";`_initial_groups`(server.py:2236)见 image ref 自动 load images 组 |
| 6 | AI emit `read_today_schedule`,按 brand/描述匹配出全名"鱼油（Swisse）" | `_dispatch_tool('read_today_schedule')` → SSE `{type:action}` | 第 1 个 tool chip doing→ok | — | read 类 quota=5 |
| 7 | AI emit `set_daily_task_image`(去背) | `TOOL_IMPL['set_daily_task_image']`(server.py:1531);内部 `_resolve_task_name`(模糊→全名)+ `cutout._get_or_create_processed_attachment`(三层抠图) | 第 2 个 tool chip ok;单日页晨课带出现彩色鱼油图标 | `DAILY_TASK_IMAGES_DIR/鱼油（Swisse）.png`(normalize 1024 方图);`daily-task-images.json[鱼油（Swisse）]=rel`;OCR(原图非抠图)`_ocr_text→_parse_pill_count_from_ocr` 取最大 1..9999 匹配=60,**仅当 meta total_pills 空才写** | ★`cutout__writes_image_map_meta_and_ocr_pill_count`(N2):image_map 有 task + meta total_pills==60 + ocr_pill_count==60;`_resolve_task_name` 三级兜(5.28);`_pick_attachment_url` 别名容错(5.27 deepseek 用 image_path) |
| 8 | AI emit `check_daily_task`(三步最后一步) | `TOOL_IMPL['check_daily_task']`(server.py:1483)→ `_set_md_checkbox` / `_bump_intake` | 第 3 个 tool chip ok;打卡区鱼油行勾上 | 当天 md 顶部 `- [ ] 鱼油（Swisse）` → `- [x]`;`daily_dose>1` 时 `_ensure_md_progress_children` 展子 box | `daily_tasks__check_default_dose1` / T3 check intake/clamp + md box;`_safe_write_text` lock+fsync 红线 |
| 9 | AI 出收尾文字,claim 审计兜底 | `_stream_final_reply`(单一 chokepoint)+ `_audit_unauthorized_claim`(L280)查 last_actions | AI 文本"鱼油图标设上了,今天也帮你勾了";无 disclaimer | — | ★claim 审计红线(5.22):last_actions 非空才放行;若 AI 没真调 tool 却说"已设" → 自动加"server audit:本回合未触发任何 tool"暴露;DSML 泄漏闸 suppress |

**场景 A · PC 最终态(must 全中)**:
① `DAILY_TASK_IMAGES_DIR/鱼油（Swisse）.png`(三层抠图后方形居中 PNG)
② `daily-task-images.json[鱼油（Swisse）]=rel`
③ `daily-task-meta.json[鱼油（Swisse）].total_pills=60`(OCR 自动填,仅当未手填)
④ 当天 md 顶部 `- [x] 鱼油（Swisse）`
⑤ `attachments/<date>/_index.json` 该图 `vision.kind=supplement`
⑥ chat 流三个 tool chip 全 ✓ + 一句确认文字(无 claim disclaimer)
⑦ 截图:单日页/总览晨课带显示彩色药瓶图标 + 勾选态

### 3.A.2 mobile 链(残缺 —— 首尾 UI 空 + AI 链断)

| # | 操作 | 机制 | 现状 / 预期 | 落账 | 契约 |
|---|---|---|---|---|---|
| 1 | 长按打卡 chip"鱼油"(pointerdown hold 480ms)→ task sheet → tap"换图标" | gw-widgets.js:91 LP_MS → `GW.openTaskSheet`(gw-journal.js:224)→ `.gw-sheet-item`"换图标"(229) | **[UI待建]** 点"换图标"只 `m.close()+whisper('（demo）这一项接 daily-task API')`(gw-journal.js:239)。snapshot_ui:`.gw-sheet` 出现含 4 个 `.gw-sheet-item`,但"换图标"无真 handler | — | PC 对应 `/api/cutout`;mobile shim 端点已建(mobile-api.js:1491)但前端不调 |
| 2 | **[UI待建]** 应弹相册/拍照,选 yuyou.jpg | 应接 `@capacitor/camera getPhoto` 或 `<input type=file accept=image/* capture>`;**grep 全 mobile/m/ 零 file picker** | 完全缺失:无 picker DOM、无 change 监听、无 dataURL 产出 | — | 后端期望拿 dataURL 或 attachment_url |
| 3 | **[UI待建]** 抠图等待态(端侧 iOS Vision 前景 mask) | `Cutout.cutout({image:dataUrl})`(VNGenerateForegroundInstanceMaskRequest,iOS17+)→ `{png:透明dataUrl}` | 无等待 UI(brief 要求:禁 spinner,要磨墨/墨迹晕开纸习语);native plugin 本身就绪 | — | ★端侧抠图三层兜底 PULSE Cannot-break;移动只 iOS Vision 一层 + 云端兜底 |
| 4 | **[应触发]** 抠好 PNG + task_name 发 `/api/cutout` | `POST /api/cutout`(mobile-api.js:1491)→ `NativeOcr.recognize`(iOS Vision OCR)→ `extractPillCount` 正则("\d+粒/片/颗/softgels")→ setSetting taskimg/鱼油 + taskmeta.total_pills | shim 返 `{ok:true, ocr_pill_count:60, engine:'AppleVision'/'CloudVision_fallback'/'BrowserStub', ocr_text}`;浏览器无 plugin → engine=BrowserStub,pill_count=null | plist `taskimg/鱼油`=PNG、`taskmeta/鱼油={total_pills:60}` | ★`cutout__writes_image_map_meta_and_ocr_pill_count` oracle;parity case_53 只验 status graceful;★**parity 洞**:mobile cutout 写 total_pills 无"仅当未填过才写"guard(mobile-api.js:1534 无条件覆盖) → 会抹用户手填,见 `cutout__respects_existing_total_pills_PARITY_HOLE` |
| 5 | 图标显示在 chip | `GET /api/daily-tasks`(mobile-api.js:1445)拉 taskimg/鱼油 灌 t.image_url → renderTasks 重渲 | **[UI待建]** renderTasks(gw-widgets.js:87)只渲 `<span class=gw-task-glyph>{t.glyph}</span> emoji,**不读 t.image_url**;即便 plist 存了 PNG,chip 上看不到 | — | PC chip 显示抠图 PNG;mobile 渲染层缺 image_url 分支;snapshot_ui 能断 `button.gw-task[aria-label="打卡 鱼油 {intake}/{dose}"]` 但断不了"显示的是抠图" |
| — | **AI 链(对话版)在 mobile 直接断** | mobile TOOL_SPECS(L860)+ dispatchTool(L1001)**无 set_daily_task_image**(只 set_water_cup_image,且 emoji-based);**无 vision-pre-router 注入**(grep 零) | AI 收不到 supplement WORKFLOW hint;若强行 emit set_daily_task_image → dispatch default 返 `{error:'unknown tool'}`;`_auditUnauthorizedClaim`(mobile L1146)防 AI 谎称已设 | — | 已知 parity 缺口:需补 set_daily_task_image shim + vision-pre-router 注入才追平 |

**场景 A · mobile 最终态(现状)**:真机经端点最多达成 `taskimg/鱼油`+`taskmeta.total_pills`**落账**;
但**入口(换图标按钮=demo 桩)+ 出口(chip 不渲染 image_url)两头 [UI待建]**;AI 对话链因缺工具+缺 hint
**走不通**,AI 只能识别+文字描述,不能真设图标。md 补剂段不变(换图不动勾选)。

### 3.A.3 场景 A 负例(必须可见,不能静默)

| 负例 | 触发 | PC 预期 | mobile 预期 |
|---|---|---|---|
| 抠图三层全失败 | 三层 cutout 都挂 | silent degrade 落**原图**(不抛错,日记照样能用);每层失败 `_emit_failure` 进 silent-failure 通道(cutout_local_exception / cutout_local_failed_baidu_saved / cutout_all_failed_fallback_original) | 端侧失败→云端 vision→仍失败→不崩;engine 字段暴露降级路径 |
| OCR 没抽到颗数 | 标签糊/无数字 | `ocr_pill_count=null`,**不阻断 cutout**;total_pills 保持空 | 同;`extractPillCount` 返 null;`taskmeta` 不写 total_pills |
| **OCR 抽到但用户已手填**(★) | ashwa.jpg OCR 抽 120,但 meta 已有 total_pills=30 | 响应可回 `ocr_pill_count:120`,但 **persist 不变**(尊重手填,image_routes.py:136-149 `仅当 total_pills 空`) | ★**parity 洞**:mobile 无 guard,会覆盖成 120 → 必测 `cutout__respects_existing_total_pills_PARITY_HOLE`,golden 断 `taskmeta.total_pills 仍 30` |
| 非药瓶图(nonpill.jpg) | vision kind ≠ supplement | AI 不触发 supplement 三步 WORKFLOW;回文字询问/拒绝乱设;不该静默把绿植设成补剂图标 | AI 走通用识别;无 set_daily_task_image 可调 |
| 缺 task_name 或缺 attachment_url | 直打 `/api/cutout` 漏参 | 400 `{ok:false,error:'缺 task_name'/'缺 attachment_url 或 image'}` | 同 400;UI 不能静默吞,应提示 |
| attachment 读不到 | url 指向不存在文件 | 404;不能把空图当成功写进 taskimg | 404;同 |

---

## 4. 场景 B:水杯照片 → 八杯水图标

**E2E case 名**:`e2e_photo__water_cup_to_eight_cups_icon`
**招牌一句话**:拖水杯照 + 说"这是我的水杯" → AI 走特殊分流(一步 set_water_cup_image,不先 vision_classify) → 三层抠图 → 落保留 key `__water_cup__` → 八杯水 widget 用这只杯。
**★Cannot-break 触及**:water-cup reserved key roundtrip(验 lazy-import io-map resolve)· 水杯不进 daily-tasks 清单/不勾 md box · 不跑 OCR 颗数(无颗数语义)。

### 4.B.1 PC 链(完整可跑)

| # | 操作 | 机制 | 预期 ① 屏幕 | 预期 ② 落账 | 契约 / golden |
|---|---|---|---|---|---|
| 1 | 拖 cup.jpg 进对话 | `POST /api/chat/upload-image` | 输入区图缩略图 | `attachments/<date>/`,sha256 去重,`_index_upsert`,后台 `_index_attachment` | 同 flow A upload |
| 2 | (server)vision 分类缓存(kind 可能 object) | 后台 `_qwen_classify_image` | — | `_index.json` vision.description='水杯'等 | — |
| 3 | 输入"这是我的水杯",回车 | `POST /api/chat` + `_refs_to_vision_hints`;消息含**水杯/我的杯/喝水图标/打卡水杯**关键字 → 命中特殊分流 | user 气泡含图 | — | ★WORKFLOW 特殊分流(chat_routes.py:671-674)"水杯关键字 → 一步 set_water_cup_image(直接调,不先 vision_classify)" |
| 4 | AI emit `set_water_cup_image`(去背,走保留 key) | `TOOL_IMPL['set_water_cup_image']`(server.py:1514);`_get_or_create_processed_attachment` 三层抠图 | tool chip ok;八杯水区杯子换成用户的杯 | `DAILY_TASK_IMAGES_DIR/_water_cup.png`(固定名);`daily-task-images.json[__water_cup__]=rel`(WATER_CUP_KEY=server.py:3348);**不跑 OCR 颗数** | ★`daily_tasks__water_cup_post` T6 roundtrip:WATER_CUP_KEY 落 images map + 缺 url 400;`test_day_one_and_water_cup` T7:set_water_cup_image 在 TOOL_GROUPS['images']+TOOL_IMPL+spec required attachment_url |
| 5 | AI 收尾 + claim 审计 | `_stream_final_reply` + `_audit_unauthorized_claim` | AI 文本"水杯设上了,8 杯水打卡区会用你这只杯" | — | claim 审计 |
| 6 | 前端读回水杯图渲染八杯水区 | `GET /api/water-cup`(daily_tasks_routes.py:281)用 WATER_CUP_KEY 反查 image_map | 八杯水 widget:灰度=未喝/彩色=已喝,用这只杯 | — | T6 GET 回读断言非空;喝水进度另由 `/api/daily-tasks/check`(caller 传 daily_dose=8/CUPS_TOTAL 防 clamp 到 1,daily_tasks_routes.py:96 注释) |

**场景 B · PC 最终态**:① `DAILY_TASK_IMAGES_DIR/_water_cup.png`(三层抠图后)
② `daily-task-images.json['__water_cup__']=rel`(保留 key,**不进 daily-tasks 清单、不进 md box**)
③ **不写 total_pills**(水杯不跑 OCR 颗数)。前端 GET /api/water-cup 返非空 image_url → 八杯水区用这只杯;
喝水进度走 `/api/daily-tasks/check`(daily_dose=8)单独记。

### 4.B.2 mobile 链(比药瓶链更空 —— 八杯水 widget 连"换图"入口都没有)

| # | 操作 | 机制 | 现状 | 落账 | 契约 |
|---|---|---|---|---|---|
| 1 | 想给八杯水换图标 | renderCups(gw-widgets.js:23-65)只有横滑填杯手势(pointerdown/move apply clientX) | **[UI待建]** 无任何"换水杯图标"入口(无长按 sheet、无设置按钮);8 杯子是写死的钢笔速写 SVG(cupSVG),不读 water_cup_img | — | PC 有"换图+指给AI看水量"右键项;移动零对应 UI |
| 2 | **[UI待建]** 选照片 + 端侧抠图 | 应同走 Cutout plugin + upload-image | 无 picker、无抠图等待 UI | — | — |
| 3 | **[应触发]** 存水杯图 | `POST /api/water-cup`(mobile-api.js:1378)`{attachment_url\|image}` 缺则 400 → setSetting water_cup_img;GET(1327)返 image_url_present | shim 返 `{ok:true}`;parity case_45 验过 POST `{image:'🥤'}`→200+plist 真存 | plist `water_cup_img=<dataURL/emoji>` | `daily_tasks__water_cup_post`;D6 roundtrip;★parity:mobile GET 返 `{image_url}` 不对齐 PC `{image_url_present}`(PARITY_LEDGER 139) |
| 4 | 水杯图渲染八杯水区 | renderCups | **[UI待建]** renderCups 不读 water_cup_img,8 杯永远 cupSVG;存了的图不上屏 | — | 无渲染契约;snapshot_ui 只能断 `.gw-cup × 8` + `.gw-cups-foot` "{n}/8 杯"文案,断不了自定义水杯图 |
| — | mobile set_water_cup_image 语义分叉 | mobile spec"优先 emoji 🥤,不要生成 SVG/dataURL" | 跟 PC 照片抠图设杯**完全分叉** | — | 已知 parity 缺口 |

**场景 B · mobile 最终态(现状)**:`water_cup_img` 可经端点写入(parity case_45 验过);但八杯水 widget
**既无"换图"入口、也不读 water_cup_img 渲染** —— 首尾全 `[UI待建]`,仅中段 endpoint 落账可达,且 AI tool
是 emoji 语义非照片抠图。

### 4.B.3 场景 B 负例

| 负例 | 触发 | 预期 |
|---|---|---|
| 缺 attachment_url/image | 直打 `/api/water-cup` 漏参 | 400(PC + mobile 一致);UI 不静默 |
| 抠图全失败 | 三层挂 | silent degrade 落原图,不崩 |
| 把水杯误进 daily-tasks 清单 | — | 必须**不**出现在 catalog tasks[]、不进 md box(保留 key 语义) |
| OCR 跑了颗数 | — | **不该跑**(水杯端点 + AI tool 路径都不跑 OCR sidecar);若 total_pills 被写 = bug |

---

## 5. 验收判据(整条链跑通 = 6 真全中)

E2E 招牌链"活着"的定义 = **真照片真进 + AI 真识别 + 抠图真出 + 图标真显示 + plist 真落账 + 截图真渲染**。
逐个 must-pass 检查点:

| # | 检查点 | 怎么验 | A 通过线 | B 通过线 |
|---|---|---|---|---|
| 1 | **照片真进** | upload-image 返真 url(非占位);attachment 文件真存在 | `attachments/<date>/<stem>` 有真 bytes,非灰方块 SVG | 同 |
| 2 | **AI 真识别**(非硬编码) | vision hint kind/brand/pill_count 来自真 qwen3-vl,非 cap_x.jpg 假文件 | `_index.json` vision.kind=supplement、pill_count=60 来自真照片 | vision.description 含"水杯" |
| 3 | **AI 真设置**(非只建议) | last_actions 含真 tool action;claim 审计不加 disclaimer | set_daily_task_image + check_daily_task 真 emit | set_water_cup_image 真 emit |
| 4 | **抠图真出** | 输出 PNG 有 alpha 通道、主体居中 1024 方图(normalize) | `鱼油（Swisse）.png` 真透明 PNG | `_water_cup.png` 真透明 PNG |
| 5 | **plist/json 真落账** | 读 image_map + meta_map + md | image_map[鱼油（Swisse）] 非空 + meta total_pills=60 + md `- [x]` | image_map[__water_cup__] 非空 + 不写 total_pills + 不进 md box |
| 6 | **图标真渲染**(截图) | snapshot_ui + 截图 diff | 单日页晨课带彩色鱼油图标 + 勾选;chat 三 chip ✓ | 八杯水区用这只杯 |

**mobile 额外门槛(追平 PC 前必绿的 UI 施工项)**:
- [UI待建] 换图标按钮真接相册/cutout(不再 whisper demo)
- [UI待建] file picker / Capacitor Camera 入口
- [UI待建] renderTasks 渲染 t.image_url(否则检查点 6 永远不过)
- [UI待建] 八杯水 widget"换图"入口 + renderCups 读 water_cup_img
- [缺工具] mobile 补 set_daily_task_image shim + vision-pre-router 注入(否则 AI 链检查点 3 永断)

> **判定口径**:6 真全中 = 该端 E2E 招牌链活;任一红 = 标 `[UI待建]`/`[缺工具]`,回退看对应原子 case
> 缩小爆炸半径。mobile 当前:契约层端点全绿,但检查点 3/6 因 UI+工具缺口红 → **整链未通**。

---

## 6. 接现有制品(对齐表)

### 6.1 E2E case ↔ 原子 case ↔ golden ↔ PARITY_LEDGER

| E2E 子步骤 | 对齐的原子 case(INTERACTION_TEST_CASES) | golden(mobile/parity/golden/) | PARITY_LEDGER key | 已兜底? |
|---|---|---|---|---|
| A 上传去重 | `chat_upload_image__dedup_and_logical_url` | 无独立(chat_routes characterization) | — | ✅ 原子已建 |
| A vision 缓存 | `vision_classify__delegates_and_echoes_question` | `vision__classify_delegates_and_echoes_question.response.json` | N4 `/api/vision/classify` ✅ | ✅ UI已建/contract |
| A 抠图+OCR填颗数 | `cutout__writes_image_map_meta_and_ocr_pill_count` ★ | `cutout__writes_image_map_meta_and_ocr_pill_count.response.json` + `cutout__imgmap_after.json` + `cutout__metamap_after.json` | N2 `/api/cutout` 🟡(待真机) | 🟡 端点绿,真机待验 |
| A OCR 尊重手填(负例) | `cutout__respects_existing_total_pills_PARITY_HOLE` ★ | **[缺]** 需新增 `cutout__respects_existing_total_pills.metamap_after.json {total_pills:30}` | — | ❌ golden 待补 |
| A 勾打卡 | `daily_tasks__check_default_dose1` / `daily_tasks__check_clamp` | `daily_tasks__check_*.response.json` | D3/check | ✅ |
| A set-image(直调) | `daily_tasks__task_set_image` | 无独立(参 `cutout__imgmap_after.json`) | `daily_tasks__task_set_image` ✅ contract | ✅ |
| B 水杯保留 key | `daily_tasks__water_cup_post` ★ | `daily_tasks__water_cup_post.response.json` + `..water_cup_get..` + `..water_cup.images.json` | D6 ✅ | ✅ |
| B 喝水填杯 | `daily_tasks__water_drag_fill` | 无独立 water golden response | N3 `/water` OUT(行为映射 check) | ✅ |
| 贴纸(关联簇,非本链但同 cutout) | `scrapbook_place_sticker__anchor_to_entry` ★ | **[缺]** image 簇暂无 scrapbook golden | — | ❌ |

### 6.2 哪些子步骤已有原子 case 兜底 / 哪些是 E2E 独有

- **已被原子 case 钉死(E2E 只是串起来再加真 AI)**:upload dedup、vision classify、cutout 写 map+meta+ocr、
  check 打卡、water-cup roundtrip —— 这些 CI 里确定性绿,E2E 跑挂时先排除它们。
- **E2E 独有、原子 case 兜不到的**:① 真 LLM 自己决定 emit 哪些 tool(三步连做是否真触发,非 mock dispatch)
  ② 真 vision 对真照片的识别质量(kind/pill_count 是否真对)③ vision-pre-router → AI → tool 的**跨步衔接**
  (hint hoist 位置对不对、AI 有没有被 hint 推动)④ claim 审计在真 AI 真撒谎时是否真兜住
  ⑤ 截图层的图标真渲染(snapshot_ui 断不了"是不是抠图 PNG",只能截图人验)。
- **mobile 永远兜不到(直到补 UI/工具)**:场景 A 的 AI 对话链(缺 set_daily_task_image + vision-pre-router);
  两场景的图标真渲染(renderTasks/renderCups 不读 image_url)。这些在 PARITY_LEDGER 标 `[UI待建]`/parity 洞,
  本 E2E 文件把它们集中成"追平 PC 的施工清单"。

### 6.3 命名约定

- E2E case 名前缀 `e2e_photo__`,跟原子 case(`cutout__` / `daily_tasks__` / `vision_classify__`)区分。
- 进 `parity/interaction/run-cases.md` 时,E2E 走**真 key + 真 simulator** 分组,**不进**确定性 golden CI 批次
  (对应 PARITY_LEDGER 128-129 行"需 iOS Vision Framework / 需真 qwen3-vl"那批"待真机"标记)。
