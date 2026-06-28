# E2E 招牌场景 · 对话框贴图 → 抠图 → 浮动贴纸落到日记 entry

> **这是端到端(E2E)场景用例,不是原子 case。** 它把多个跨簇交互(upload → vision-pre-router →
> cutout → place_scrapbook_image → scrapbook persist → 渲染浮动贴纸)串成一条"用户在对话框丢一张图、
> AI 把它贴到日记某条 entry 旁边浮起来"的招牌链,且**带真照片 + 真 LLM/vision + 真抠图**。
> 配套:[`INTERACTION_E2E_PHOTO.md`](INTERACTION_E2E_PHOTO.md)(姊妹 E2E:照片→打卡图标,同结构同深度)·
> [`INTERACTION_TEST_CASES.md`](INTERACTION_TEST_CASES.md)(原子 case,确定性)·
> [`TEST_FIRST_MIGRATION.md`](TEST_FIRST_MIGRATION.md)(两层范式)·
> [`PARITY_LEDGER.md`](PARITY_LEDGER.md)(endpoint key/oracle)· `mobile/parity/golden/`(契约底座)。

---

## 0. 这一层在测试金字塔的哪一格

`TEST_FIRST_MIGRATION.md §0` 定了两层模型(契约层 golden 底座 + 交互层 case 本体)。
**本文件是第三层 —— 比交互层更上,且打破"确定性"前提**(与 `INTERACTION_E2E_PHOTO.md` 同格):

```
E2E 真链层   真照片 + 真 LLM/vision + 真抠图 + 真贴纸 → 全链路落账 + float 截图    ← 本文件(不进 CI)
    ↑ 串起 ↑
交互层       单个真 tap → 屏幕效果 + plist 落账 + 截图(mock 引擎/seed dataURL)     ← INTERACTION_TEST_CASES
    ↑ 撑在 ↑
契约层       callApi(golden.input) → scrapbook json 字节比                          ← golden 底座,CI 能跑
```

三层职责分工:

| 层 | 在哪 | 输入 | 验什么 | 进 CI? |
|---|---|---|---|---|
| **契约层** | `mobile/parity/golden/` + `capture-golden.py` | 固定 bytes/JSON | scrapbook item 字节 == golden | ✅ 确定性 |
| **交互层** | `INTERACTION_TEST_CASES.md` + `parity/interaction/` | seed dataURL / mock | 单 tap → snapshot_ui + plist | ✅ status graceful |
| **E2E 真链层(本文件)** | 本地 simulator + 真 key | **真照片(早餐/猫/风景)** | **整条链跑通**:图真进对话→AI 真识别→抠图真出→`place_scrapbook_image` 真 emit→scrapbook json 真落账→贴纸真浮在 entry 旁 + float 动画真播 | ❌ 手动/本地 only |

**为什么 E2E 不进确定性 CI**:真 LLM(deepseek)是否 emit `place_scrapbook_image` + emit 对的 `anchor_time`
非确定;真 vision(qwen3-vl)对真照片的 kind/描述非确定;真抠图 alpha 框逐次微抖;float 动画是时间相关的
观感(只能截图/录屏人验,断言断不了"浮起来好不好看")。这些在 CI 里早被降级成 mock/seed/`status graceful`
(见 PARITY_LEDGER `scrapbook upsert` 那批"contract only")。E2E 是补"原子 case 各自绿了,但串起来 + 真 AI 时
**用户那条招牌路径是否真的从头通到尾、贴纸是否真浮在对的 entry 旁**"的最后一公里。

**它跟原子 case 互补,不替代**:原子 case 钉死每一段引擎对(确定、快、CI);E2E 钉死整条用户故事活着
(真、慢、人验)。E2E 跑挂时,先看哪段原子 case(`scrapbook__upsert` / `cutout__*`)也挂 → 缩小爆炸半径。

---

## 1. 招牌场景的全貌(为什么这条 flow 是招牌)

产品一句话 = "让普通人也能跟 AI 共写日记"。其中最有"魔法感"、最贴 DESIGN_BRIEF "网页是 AI 的载体、
多设计动画"那条铁律的动作是:

> 用户在对话框丢一张**早餐照片**,说一句"贴到今天早上那条旁边",
> AI 自己看懂"这是一份早餐"、自己把它抠成透明 PNG、自己锚到 9:30 那条 entry,
> 照片就**浮**在那条日记旁边,带白边、微歪、像手贴上去的,鼠标悬停还会抬起来 ——
> 用户一张照片一句话,AI 把它变成一张贴在日记本上的浮动便签。

这条链横跨 **4 个簇**(chat upload · vision-pre-router · image/cutout · scrapbook),涉及
**真 vision LLM + 真端侧抠图 + 浮动渲染层**,是整个产品"AI 是协作者不是按钮 + 网页是 AI 的载体"
主张的活体证明。它跟 `INTERACTION_E2E_PHOTO.md`(照片→打卡图标)是姊妹链:都从对话框丢图 + 抠图开始,
但**落点不同**(那条落 daily-task 图标 + 勾 md;这条落 scrapbook JSON 旁路 + 浮在 entry 旁、**MD 真源不动**)。

**★Cannot-break 触及(先记住,这条链的红线)**:

- **MD 真源不动 / 贴纸纯 JSON 旁路** —— scrapbook 只读写 `data/scrapbook/{date}.json`(PC)/
  `setting/scrapbook/<date>`(mobile Preferences),**从不进 vault MD**(出处:`scrapbook.py` docstring +
  `human-ai-schedule/CLAUDE.md` "远期 viewer sticker:JSON 旁路存 sticker URL+x/y,MD 真源不动")。
- **anchor_time 是语义挂点不是像素定位** —— 定位走 `x_pct`/`y_px` + `auto_y` + `computeYFromAnchor`
  二次校准,严禁拿 anchor 当视觉坐标(出处:PULSE "不要让 anchor_time 当视觉定位用";`scrapbook.js:8`)。
- **size_pct/x_pct 等比缩放真源** —— 占 `.sb-layer` 宽 %,换分辨率 CSS 自动跟随;`w/h` 仅纵横比 +
  旧数据迁移,绝不用绝对 px 当尺寸真源(出处:`scrapbook.js:9-10,39-43,135-137`;PULSE 6.15 "18.3% 不漂")。
- **auto_y 单向清除不可逆** —— 用户一旦拖/upsert 带 `y_px` 即 `auto_y=false`,reload/resize 永不再
  按 anchor 覆盖用户手动位置(出处:`scrapbook.js:218,340-352`;`server.py:1659-1662`)。
- **抠图三层兜底不阻塞** —— macOS Subject Lift → rembg → 百度 → 原图,任一层失败 silent degrade
  落原图,绝不抛错断上传链(出处:`cutout.py:253-316`;PULSE "端侧抠图三层兜底链")。
- **创建只走 AI 中介 `place_scrapbook_image`** —— 对话框丢图**不直连**落贴纸,经 thread → AI 判
  pin/discuss 意图 → tool;`day-paper-data.js:120,697` 明示"拖图贴纸暂缓走 AI 中介,不另造直连"。
- **`place` 的 date 必传 view_date 非 today** —— 跨午夜不刷新时拿浏览日,server 兜底 today 会落错天
  (出处:`chat_routes.py` view_date_hint;`thread.js` view_date 兜 todayLocalISO)。
- **claim 审计** —— AI 不许谎称"已贴",`_audit_unauthorized_claim` 查 last_actions(PC)/
  `_auditUnauthorizedClaim`(mobile)兜底。

**双端落差(本文件最重要的 parity 真相,先记住)**:

| 能力 | PC(桌面 server.py / shared) | mobile(mobile-api.js shim + m/) |
|---|---|---|
| 对话框图入口 UI | ✅ thread.js 三触发(全文档拖图 drop / 📎 附件 / 粘贴)→ upload | ❌ chatbar 附件按钮只 `pending.push('data:image/svg+xml,…灰方块')`(gw-app.js:206 demo 桩);无 file picker、无 Camera |
| upload-image 端点 | ✅ `POST /api/chat/upload-image` | ✅ shim 已建(走 dataURL),但前端不喂真图 |
| vision-pre-router 注入 | ✅ `_refs_to_vision_hints` + pin/discuss WORKFLOW(chat_routes.py:630-660) | ❌ grep 零命中,AI 收不到 scrapbook WORKFLOW hint |
| `place_scrapbook_image` tool | ✅ `TOOL_IMPL`(server.py:1647) | ✅ schema(mobile-api.js:891)+ dispatch(L1021 → `/api/scrapbook/upsert`)都在 |
| 抠图(cutout) | ✅ 三层兜底链(cutout.py:253) | 🟡 `Cutout` plugin(iOS Vision)就绪,但**贴纸链不调**(只 `/api/cutout` 给打卡图标用) |
| scrapbook 三端点(shim) | ✅ server.py:3008-3082 | ✅ mobile-api.js:1339-1378(GET/upsert/delete 全建好) |
| scrapbook item 持久化 | ✅ `data/scrapbook/{date}.json`(原子写+rotate) | ✅ `setting/scrapbook/<date>`(Preferences,Store.read/writeScrapbook mobile-api.js:156-164) |
| **贴纸渲染到 entry** | ✅ classic `scrapbook.js`(.sb-layer/.sb-wrap absolute 浮)+ paper `day-paper-data.js:699 renderStickers`(float:right 内联) | ❌ **`grep -rn 'scrapbook' m/` 返 0 命中**;timeline 渲染层无 sticker layer,store 只写不读 |
| **float 浮动效果** | ✅ classic = `.sb-wrap-inner` drop-shadow 三态(style.css:3054-3061);paper = `@keyframes sticker-land` 落纸 0.7s + `wait-breath` 抠图等待(components.css:606,602) | ❌ m/components.css 无 `.sb-*`/`.sticker` class,无 drop-shadow,无 float keyframe |
| 拖/旋转/缩放/删除 | ✅ classic `bindDrag/Rotate/Scale/Delete`(scrapbook.js:179-323);paper 双击取下 + folding(day-paper-data.js:717) | ❌ m/ 无任何 pointerdown 绑到 sticker,无 size_pct 消费,无 handle |
| chat 气泡显图 | ✅ user 气泡含缩略图 | 🟡 字段不一致:真 SSE 路径存 `m.attachments`(gw-real-bridge.js:292),但 `renderThread` 只读 `m.imgs`(gw-chat.js:33)→ 真路径下用户发的图在气泡里不显示 |

> **结论**:PC 端整条 E2E 招牌链**完整可跑**(两套皮肤:classic 自由拖 + paper 内联浮);mobile 端
> **后端 shim + tool schema + dispatch 全建好,scrapbook json 真能落账**,但**首尾 UI 全空 + 渲染层 0 行**
> —— 入口=对话框附件是 demo 灰方块桩,出口=`m/` 完全不读 scrapbook、无任何浮动渲染。本文件的 mobile
> 步骤大量标 `[UI待建]`,既是测试用例也是追平 PC 的施工清单。

---

## 2. 前置 / 环境

### 2.1 真照片 fixture(seed 进哪)

| fixture | 内容 | 放置位置 | 用途 |
|---|---|---|---|
| `breakfast.jpg` | 一份早餐(咖啡 + 吐司,主体清晰可抠) | `mobile/parity/fixtures/photos/` | 主链主照(贴到早上某条 entry) |
| `cat.jpg` | 一只猫(主体清晰、背景杂,验抠图前景 mask) | 同上 | "discuss vs pin" 意图分流照 |
| `doc.jpg` | 一张含文字的便条/收据(kind=doc + ocr_likely) | 同上 | 负例:doc 应走 patch_journal_block **不**落贴纸 |
| `nonpin_chat.txt` | 纯文字消息(用户只说"哈哈"无 pin 触发词) | — | 负例:ambiguous → ask path,不静默落贴纸 |

**seed 路径分两种**(同 PHOTO §2.1):
- **simulator 相册**(真机/真原生 picker 路径):`xcrun simctl addmedia <UDID> mobile/parity/fixtures/photos/breakfast.jpg`,
  让用户在原生相册选择器里能选到(**前提:mobile 先把 picker 入口建出来**,见 §3 缺口)。
- **直接进 attachment**(跳过 UI 入口,只验中后段):把照片转 dataURL `POST /api/chat/upload-image`
  存成 `attachments/<date>/<stem>`,后续让 AI dispatch `place_scrapbook_image` 直接用该 url。
  这是 mobile UI 未建时**唯一能跑到端点的方式**(对应 mobile-api.js:3018 那个 S6 自测的手法)。

### 2.2 真 key(E2E 必须配真,这是它跟原子 case 的本质差别)

- **阿里云百炼 dashscope_key** —— vision-pre-router 的 `_qwen_classify_image`(qwen3-vl-flash)给图分类
  出 kind/描述,AI 靠它判 pin/discuss + 匹配 entry。**配在 config(单 API 入口红线,只这一把)**。
- **DeepSeek key** —— chat 主对话 LLM(emit `place_scrapbook_image` 的那个大脑)。
- 没配 key → vision/chat 退化成可见错误(提示去配钥匙),**不能静默无回复**(这本身是负例检查点,见 §3.3)。

### 2.3 iOS native 引擎(真机 / simulator)

- **抠图**:`window.Capacitor.Plugins.Cutout`(CutoutPlugin.swift,`VNGenerateForegroundInstanceMaskRequest`
  = 相册"拷贝主体"同引擎,iOS 17+)。浏览器无 plugin → `BrowserStub` 返空不阻断(engine=BrowserStub)。
  ★注意:mobile 当前 `Cutout` 只接在 `/api/cutout`(打卡图标),scrapbook 链**尚未接抠图**(缺口)。
- **simulator**:`boot_sim` + `install_app_sim` + `launch_app_sim`;UI 自动化用 XcodeBuildMCP
  `tap`/`long_press`/`drag`/`snapshot_ui`/`screenshot`/`record_sim_video`(float 动画必须录屏才看得到)。
- **PC 侧**:uvicorn `localhost:4321`,真 server.py(非 shim),三层抠图 macOS Subject Lift → rembg → 百度 → 原图。

### 2.4 验账工具

- **PC**:直接读 `data/scrapbook/{date}.json`(item 列表 + 字段)+ `data/scrapbook-images/{date}_{id}.png`
  (抠图后的贴纸字节)+ `attachments/<date>/_index.json`(vision 缓存)。**确认当天 md 不变**(MD 真源不动红线)。
- **mobile plist/kv**:`xcrun simctl get_app_container <UDID> com.humanai.gateway data` →
  `defaults read .../com.humanai.gateway.plist` 看 `setting/scrapbook/<date>` 这个 key(JSON 字符串,
  解出 item 列表);贴纸图本体在 Filesystem `Directory.DATA` 的 `gw/kv/*.txt`(attachment dataURL)。
  **确认补剂段/journal md 不变**。
- **webview 内断言**:PC classic 用 `document.querySelectorAll('.sb-wrap')`;paper 用 `.sticker[data-id]`;
  mobile 待 UI 建出后用 `__GW_TEST_API__` 的 `querySelectorInfo` / `waitForSelector` 断 sticker DOM。
- **float 观感**:`record_sim_video` / headless Chrome 录屏 → 人验"落纸动画 / 悬停抬起 / 微歪白边"。

---

## 3. 场景:早餐照片 → 浮动贴纸锚到 9:30 那条 entry(AI 交互版)

**E2E case 名**:`e2e_scrapbook__chat_photo_to_floating_sticker`
**招牌一句话**:对话框丢早餐照 + 说"贴到今天早上那条旁边" → AI 判 pin 意图 → vision 看懂"早餐" →
三层抠图成透明 PNG → `place_scrapbook_image(anchor_time=9:30)` 落 scrapbook JSON 旁路(MD 不动)→
贴纸**浮**在 9:30 那条 entry 旁,带白边微歪 + 落纸动画 + 悬停抬起。
**★Cannot-break 触及**:MD 真源不动(纯 JSON 旁路)· anchor_time 语义挂点非像素 · auto_y 单向清除 ·
抠图三层兜底不阻塞 · 创建只走 AI 中介 · place 的 date 必传 view_date · claim 审计 · float 动画受
`prefers-reduced-motion` + `[data-motion=off]` 双门 gate。

### 3.1 PC 链(完整可跑)

| # | 操作(真 drag/说话) | 机制 | 预期 ① 屏幕(snapshot/截图/录屏) | 预期 ② 落账(scrapbook json / 图字节) | 底层契约 / golden |
|---|---|---|---|---|---|
| 1 | 把 `breakfast.jpg` 拖进侧栏对话流输入区(或 📎 / 粘贴,三触发等价) | thread.js 三入口汇到 `uploadImage()` → `POST /api/chat/upload-image`(chat_routes.py:519) | 对话输入区出现图缩略图 chip | `attachments/<date>/HHMMSS-rand.jpg`;sha256 去重(同字节复用 url);`_index_upsert` 写最小 record;background_tasks 排 `_index_attachment` | 响应 `{url,filename,original,size,deduped}`;dedup = 5.16 重复客厅照根治点;走 chat_routes characterization |
| 2 | (server 自动,用户无感)upload 后台跑 vision 分类缓存 | `_index_attachment → _qwen_classify_image` | — | `_index.json[url].vision = {kind:object/food, description:'一份早餐…', ocr_likely:false}` | ★红线:不改回 load+save(触发 OCR race);vision-pre-router 缓存模式 |
| 3 | chip 默认 `cutout:true`(可点"抠/原"切),输入"贴到今天早上那条旁边",回车 | `POST /api/chat`,body 带 `context.refs=[{kind:image,payload:{url,original,cutout:true}}]` + `context.view_date` | user 气泡含图 + 文字 | — | chat SSE 契约;refs schema `{kind,payload}`;★view_date 必带 |
| 4 | (server 自动)vision-pre-router 把 hint + WORKFLOW hoist 到 user_msg 之前 | `_refs_to_vision_hints`(chat_routes.py);cache hit;hoist `<vision-pre-router 已分类>` + WORKFLOW(chat_routes.py:630-660:STEP A 判 pin/discuss/ambiguous;pin path 通用图走 place_scrapbook_image) | — | — | ★WORKFLOW hint 存在(pin/discuss 分流)由 chat characterization 守;消息含"贴" → explicit-pin |
| 5 | AI 读 hint(消息含"贴"=explicit-pin)→ 决定走 pin path,**不调 vision_classify** | LLM 收到"已有 hint 不要再 vision_classify;消息无 entry ref → read_today_schedule 匹配早餐 entry → place_scrapbook_image" | AI 区开始出 tool chip | — | WORKFLOW pin path 第 1-4 步;view_date 注入强制 date 用浏览日 |
| 6 | AI emit `read_today_schedule(date=view_date)`,按"早餐"描述匹配出 9:30 那条 | `_dispatch_tool('read_today_schedule')` → SSE `{type:action}` | 第 1 个 tool chip doing→ok | — | read 类 quota=5 |
| 7 | AI emit `place_scrapbook_image(attachment_url, date=view_date, anchor_time='9:30', cutout=true)`(没给 y_px) | `TOOL_IMPL['place_scrapbook_image']`(server.py:1647);`_pick_attachment_url`(别名容错)→ 校 url 匹配 `^/attachments/x/y$` + 文件存在 → `cutout._get_or_create_processed_attachment(url, cutout=True)`(三层抠图)→ 写 `SCRAPBOOK_IMAGES_DIR/{date}_{id}.png` → 组 item → `_load_scrapbook` append `_save_scrapbook` | 第 2 个 tool chip ok | `data/scrapbook/{date}.json` 追加一项 `{id, src:'/.../{date}_{id}.png', anchor_time:'9:30', x_pct:75, y_px:0, w:220, h:220, rotation:随机±4°, auto_y:true}`;`data/scrapbook-images/{date}_{id}.png` 真透明 PNG;**当天 md 一字不动** | ★`scrapbook__place_writes_json_not_md`:scrapbook json 有项 + md 无 diff;`auto_y==true`(没给 y_px);`x_pct==75`(默认右上);抠图后 src 指 scrapbook-images |
| 8 | SSE done 后前端拉 scrapbook 渲染浮动贴纸 | `needScrapbookRefresh`(thread.js:805 SCRAPBOOK_MUTATING 正则命中且无 error)→ done 后 `window.gateway.scrapbook.refresh()`(thread.js:850)= `scrapbook.js:356 fetchAndRender` → GET /api/scrapbook → `normalizeItem`(auto_y 项跑 `computeYFromAnchor('9:30')` 找 `.entry[data-time='9:30']` 算 y)→ `render` → `placeWrap` 建 `.sb-wrap` 插进 `.sb-layer` | **贴纸浮在 9:30 那条 entry 旁**(classic:absolute 叠加;paper:float:right 内联进该块)；文字 pretext 绕图重排 | — | ★`computeYFromAnchor` 二次校准:render 后 +200ms/+600ms repositionPass 等 pretext 稳定再 reposition auto_y 图 |
| 9 | float 效果(观感,录屏验) | classic:`.sb-wrap-inner` 常驻 drop-shadow(style.css:3054)+ hover 加深(:3056)+ dragging 更深(:3059),`will-change:left,top,transform`,`transition:filter 0.2s` —— **阴影深浅模拟"浮高"**,无位移 keyframe。paper:`.sticker.landing` 触发 `@keyframes sticker-land 0.7s`(微歪+下沉-6px→回正)一次性落纸(components.css:606)+ 抠图等待期 `.sticker.processing .sticker-wait → wait-breath 2.2s`(慢呼吸,components.css:598) | classic:鼠标悬停贴纸抬起(阴影变深);paper:贴纸落纸 0.7s 动画播一次 | — | ★float 受 `@media (prefers-reduced-motion: no-preference)` + `body:not([data-motion=off])` 双门 gate(components.css:597);classic drop-shadow 无 gate(纯 CSS transition) |
| 10 | (可选)用户手动拖贴纸到别处 | `bindDrag`(scrapbook.js:179)pointerdown/move/up + setPointerCapture;pointerup 把 px 落回 `x_pct`(0~95 clamp)+ `y_px`,**`auto_y=false`**,`inferAnchorByY` 重算 anchor_time → `scheduleSave`(600ms debounce)→ POST /api/scrapbook/upsert | 拖动时文字 liveRewrap(rAF 节流)实时绕排;落定回 % 表达式(响应式) | upsert 带 `y_px` → server.py 清 `auto_y`;之后 reload/resize 不再按 anchor 覆盖 | ★auto_y 单向清除;size_pct 缩放(bindScale)/rotation(bindRotate)同样 pointerup → scheduleSave |
| 11 | (可选)删除贴纸 | classic `bindDelete`(scrapbook.js:297)乐观隐藏 wrap + rewrap 文字回填 → `gatewayUndo` 撤回窗 → onCommit 才 POST /api/scrapbook/delete;paper `removeSticker`(day-paper-data.js:721)`folding` 600ms | 贴纸先隐藏 + 文字回填,撤回窗内可还原 | 过窗才真删 json 项;删失败 whisper + 复原 | ★删除走撤回窗 + 乐观隐藏 |

**场景 · PC 最终态(must 全中)**:
① `data/scrapbook/{date}.json` 含一项 `{id, src, anchor_time:'9:30', x_pct:75, y_px:0, w:220, h:220, rotation, auto_y:true}`
② `data/scrapbook-images/{date}_{id}.png`(三层抠图后透明 PNG)
③ `attachments/<date>/_index.json` 该图 `vision.description` 含早餐语义
④ **当天 vault md 一字不动**(MD 真源不动红线——这是本链与 PHOTO 链的关键分野)
⑤ chat 流两个 tool chip(read_today_schedule + place_scrapbook_image)全 ✓ + 一句"贴到 9:30 早餐旁边了"(无 claim disclaimer)
⑥ 截图/录屏:贴纸浮在 9:30 那条 entry 旁,classic 带 drop-shadow 悬停抬起 / paper 播一次落纸动画 + 白边微歪

### 3.2 mobile 链(残缺 —— 入口=demo 桩,出口=渲染层 0 行,float 完全缺位)

| # | 操作 | 机制 | 现状 / 预期 | 落账 | 契约 |
|---|---|---|---|---|---|
| 1 | tap chatbar 📎 附件 → 选 breakfast.jpg | gw-app.js:204 `.gw-chat-attach` click | **[UI待建]** click 只 `pending.push('data:image/svg+xml,…灰方块')`(gw-app.js:206,注释自承 `// demo:贴一张占位图(真机走 Capacitor Camera)`)。**grep 全 m/ 零 file picker / 零 Camera**。snapshot_ui:`.gw-attach-chip` 出现但 img 是硬编码灰方块 | — | PC thread.js uploadImage;mobile 无真 picker |
| 2 | **[UI待建]** 应弹相册/拍照,选真图 → 上传 attachment | 应接 `@capacitor/camera getPhoto` 或 `<input type=file accept=image/* capture>` → dataURL → `POST /api/chat/upload-image` | 完全缺失:无 picker DOM、无 change 监听、无 dataURL 产出、不上传 attachment | — | 后端期望拿 attachment_url(/attachments/...) |
| 3 | 用户发"贴到今天早上那条旁边" | gw-real-bridge.js:283 真 SSE sendChat;`imgs` 存 `userMsg.attachments`(L292) | **[潜在 bug]** `renderThread`(gw-chat.js:33)只读 `m.imgs`,**不读 `m.attachments`** → 真 SSE 路径下用户发的图**在对话气泡里不显示**(demo 路径才用 m.imgs) | — | chat SSE;字段 parity 洞 |
| 4 | **[缺注入]** vision-pre-router hoist scrapbook WORKFLOW | 应同 PC `_refs_to_vision_hints` + pin/discuss 分流 | **grep 零命中**:AI 收不到 scrapbook WORKFLOW hint,不知道该判 pin/discuss、不知道 place 流程 | — | 已知 parity 缺口:需补 vision-pre-router 注入 |
| 5 | **[应触发]** AI emit `place_scrapbook_image(anchor_time, cutout)` | schema 在(mobile-api.js:891)；dispatch `case 'place_scrapbook_image'`(L1021)→ `fch('/api/scrapbook/upsert')`;upsert(L1343)校 `attachment_url`+`anchor_time` 缺则 400 → 组 item → `Store.writeScrapbook` | shim 路由真存(mobile-api.js:3018 S6 自测验过:chatRetry 逼 AI 调此 tool → items.length 增 + anchored15:00)。**但 cutout 不在链里**:upsert 直接把 `attachment_url` 当 src,**不抠图**(PC 会先 `_get_or_create_processed_attachment`) | plist `setting/scrapbook/<date>` JSON 追加一项 | ★`scrapbook__upsert_roundtrip`;★parity 洞 A:mobile upsert **不抠图**(PC 抠);parity 洞 B:item **不存 size_pct**(只 w/h,mobile-api.js:1356)→ 等比缩放契约无落点 |
| 6 | **[UI待建]** 贴纸浮到 entry | done 分支(gw-real-bridge.js:397-431)只 `bridgePrefetch+reloadDay` 刷 journal **文字** entries,**无 scrapbook.refresh 等价物** | **`grep -rn 'scrapbook' m/` 返 0 命中**:`m/` 无任何文件读 /api/scrapbook;timeline 渲染层无 sticker layer;store 写了但前端永不读取渲染。即便 json 落了,日记页**看不到贴纸** | — | PC 三方联动(thread→refresh→scrapbook.js);mobile 0 行对应物 |
| 7 | **[UI待建]** float 浮动效果 | — | m/components.css **无** `.sb-layer`/`.sb-wrap`/`.sticker` class,无 drop-shadow 三态,无 `sticker-land`/`wait-breath` keyframe。自测 overlay(mobile-api.js:2455)用 `pointer-events:none` 固定贴片注入调试 panel,既无浮动也无交互,且仅自测用非生产 UI | — | 需复刻 PC drop-shadow 或 sticker-land 落纸动画(双门 gate) |
| 8 | **[UI待建]** 拖/缩放/删除贴纸 | — | m/ 无 pointerdown 绑到 sticker,无 size_pct 消费,无 rotate/scale/del handle/双击取下。对照 PC scrapbook.js:179-323 + paper 双击 folding 全部缺位 | — | 拖完应 upsert 带 y_px 清 auto_y;mobile 无落点 |

**场景 · mobile 最终态(现状)**:真机经端点最多达成 `setting/scrapbook/<date>` JSON **落账**
(S6 自测验过 AI 真调 place_scrapbook_image + items 真增);但 **入口(附件=demo 灰方块桩 + 无 picker)+
出口(`m/` 完全不读 scrapbook、无 sticker DOM、无 float)两头全 `[UI待建]`**;AI 链因**缺 vision-pre-router
注入**收不到 pin/discuss WORKFLOW hint,且 **shim upsert 不抠图、不存 size_pct**。当天补剂/journal md 不变
(这条本就该不变,跟 PC 一致——MD 真源不动是双端共守的红线,不是缺口)。

### 3.3 场景负例(必须可见,不能静默)

| 负例 | 触发 | PC 预期 | mobile 预期 |
|---|---|---|---|
| 抠图三层全失败 | 三层 cutout 都挂 | silent degrade 落**原图**(不抛错,贴纸照样贴上、只是没去背);每层失败 `_emit_failure` 进 silent-failure 通道 | 端侧失败→云端→仍失败→不崩;**当前 mobile upsert 本就不抠图,等价"永远落原图"**(待补抠图后对齐) |
| **doc 图误落贴纸**(★) | `doc.jpg` kind=doc + ocr_likely=true | WORKFLOW 特例:走 `patch_journal_block` 把 OCR 文本**写进当前块**,**不调** place_scrapbook_image(chat_routes.py 特例段) | 缺 WORKFLOW 注入 → AI 不知道该分流;若误 emit place → 会把文档当贴纸贴(parity 洞,需补 hint) |
| **ambiguous 静默落贴纸**(★) | 用户只发图 + "哈哈"(无 pin 触发词) | WORKFLOW STEP A:ambiguous → **ask path**(反问"贴到哪段?"),**不静默落贴纸** | 同缺 hint;需补 vision-pre-router pin/discuss/ambiguous 三分流 |
| **place 落错天**(★) | 跨午夜浏览昨天但 date 漏传 | view_date_hint 强制 `date=view_date`;server 兜底 today 会落错天 → 必须传 view_date(thread.js view_date 兜 todayLocalISO) | mobile upsert `body.date || todayIso()`(L1345)同样兜 today → **若前端不传 view_date 会落错天**(待 UI 建时传对) |
| **anchor_time 当像素用**(★) | — | 严禁:y 走 computeYFromAnchor 二次校准,anchor 只是语义挂点 + inferAnchorByY 反查 | mobile 待建渲染层时**不得**拿 anchor_time 直接当 top px(守 5.19 红线) |
| **贴纸写进 MD**(★) | — | 严禁:scrapbook 只读写 json 旁路,md 一字不动;若 md 出现图链接 = 致命 bug | mobile 同:只写 `setting/scrapbook/<date>`,不碰 journal md |
| 缺 attachment_url 或 anchor_time | 直打 `/api/scrapbook/upsert` 漏参 | server 校验返错;tool 内 `need attachment_url + date + anchor_time` | 同 400(mobile-api.js:1346-1347 `缺 attachment_url`/`缺 anchor_time`);UI 不能静默吞 |
| attachment 读不到 | url 指向不存在文件 | tool 返 `attachment not found: <url>`(server.py:1678);不把空图当成功 | mobile 待补(当前 shim 不校文件存在,直接存 url)|
| bad attachment_url 格式 | url 不匹配 `^/attachments/x/y$` | tool 返 `bad attachment_url`(server.py:1675) | mobile 待补同款格式校验 |

---

## 4. 验收判据(整条链跑通 = 6 真全中)

E2E 招牌链"活着"的定义 = **真照片真进对话 + AI 真识别 + 抠图真出 + place 真 emit + scrapbook json 真落账
+ 贴纸真浮在对的 entry 旁(float 真播)**,且 **MD 真源全程不动**。逐个 must-pass 检查点:

| # | 检查点 | 怎么验 | PC 通过线 | mobile 通过线 |
|---|---|---|---|---|
| 1 | **照片真进** | upload-image 返真 url(非占位);attachment 文件真存在 | `attachments/<date>/<stem>` 有真 bytes,非灰方块 SVG | `[UI待建]` 真 picker → 真上传,非 gw-app.js:206 灰方块 |
| 2 | **AI 真识别**(非硬编码) | vision hint kind/描述来自真 qwen3-vl,非 `cap_x.jpg` 假文件 | `_index.json` vision.description 含早餐语义来自真照片 | `[缺注入]` 补 vision-pre-router 后,hint 来自真 vision |
| 3 | **AI 真 place**(非只建议) | last_actions 含真 `place_scrapbook_image` action;claim 审计不加 disclaimer | read_today_schedule + place_scrapbook_image 真 emit;anchor='9:30' 对 | `[缺注入]` 补 WORKFLOW 后 AI 真 emit(S6 自测已证 dispatch 通) |
| 4 | **抠图真出** | 输出 PNG 有 alpha 通道、主体居中 | `{date}_{id}.png` 真透明 PNG(三层抠图) | `[缺抠图]` mobile upsert 当前不抠图 → 补 Cutout plugin 进 scrapbook 链 |
| 5 | **json 真落账 + MD 不动** | 读 scrapbook json + 比 md | `data/scrapbook/{date}.json` 有项 + 当天 md **零 diff** | `setting/scrapbook/<date>` 有项(S6 已证)+ journal md 零 diff |
| 6 | **贴纸真浮 + float 真播**(录屏) | snapshot_ui 断 sticker DOM + 录屏人验浮动 | classic `.sb-wrap` 浮在 9:30 entry 旁 + 悬停 drop-shadow 抬起;paper `.sticker.landing` 播落纸动画 | `[UI待建]` `m/` 渲染 scrapbook + 复刻 float(否则检查点 6 永远不过) |

**mobile 额外门槛(追平 PC 前必绿的 UI / 工具施工项)**:
- `[UI待建]` chatbar 附件按钮真接相册/Camera(不再 push demo 灰方块 SVG,gw-app.js:206)
- `[UI待建]` file picker / Capacitor Camera 入口 → 真上传 attachment
- `[缺注入]` 补 vision-pre-router 注入 + pin/discuss/ambiguous WORKFLOW(否则 AI 链检查点 3 永断)
- `[缺抠图]` mobile scrapbook upsert 链接 Cutout plugin(否则贴纸永远不去背)+ 存 `size_pct`(对齐等比缩放)
- `[UI待建]` `m/` 新建 scrapbook 渲染层(读 /api/scrapbook → 按 anchor_time 浮进对应 timeline 块)+ 复刻 float(drop-shadow 或 sticker-land,双门 gate)
- `[UI待建]` 拖/缩放/删除 + done 分支加 scrapbook.refresh 等价物(对齐 thread.js:850)
- `[潜在 bug]` 修 `renderThread` 读 `m.attachments`(gw-chat.js:33,否则真路径用户发图气泡不显示)

> **判定口径**:6 真全中 = 该端 E2E 招牌链活;任一红 = 标 `[UI待建]`/`[缺注入]`/`[缺抠图]`,回退看对应
> 原子 case 缩小爆炸半径。mobile 当前:契约层端点 + tool dispatch 全绿(S6 自测证 AI 真调 + 真落账),但
> 检查点 1/2/4/6 因 UI+注入+抠图缺口红 → **整链未通**,贴纸"存了但永不上屏、永不浮起"。

---

## 5. 接现有制品(对齐表)

### 5.1 E2E case ↔ 原子 case ↔ golden ↔ PARITY_LEDGER

| E2E 子步骤 | 对齐的原子 case(INTERACTION_TEST_CASES) | golden(mobile/parity/golden/) | PARITY_LEDGER key | 已兜底? |
|---|---|---|---|---|
| 上传去重 | `chat_upload_image__dedup_and_logical_url` | 无独立(chat_routes characterization) | — | ✅ 原子已建 |
| vision 缓存 | `vision_classify__delegates_and_echoes_question` | `vision__classify_delegates_and_echoes_question.response.json` | `/api/vision/classify` ✅ | ✅ contract |
| place 落 json(★) | `scrapbook__upsert_roundtrip` ★ | `scrapbook__upsert.response.json` + `scrapbook__items_after.json` | `/api/scrapbook/upsert` 🟡(待真机) | 🟡 端点绿,真机+真AI 待验 |
| place 不写 MD(★) | `scrapbook__place_writes_json_not_md` ★ | **[缺]** 需新增 `scrapbook__md_unchanged.before==after` | — | ❌ golden 待补 |
| 抠图三层(共用 PHOTO) | `cutout__writes_image_map_meta_and_ocr_pill_count`(同 cutout 引擎,不同落点) | `cutout__*.json` | `/api/cutout` 🟡 | 🟡 端点绿,scrapbook 链未接 |
| auto_y 单向清除(★) | `scrapbook__drag_clears_auto_y_PARITY_HOLE` ★ | **[缺]** 需新增 `scrapbook__after_drag.items.json {auto_y:false}` | — | ❌ golden 待补(mobile 无拖拽 UI) |
| size_pct 等比缩放(★) | `scrapbook__size_pct_present_PARITY_HOLE` ★ | **[缺]** mobile upsert 不存 size_pct → 断 item 含 size_pct | — | ❌ parity 洞,待补 |
| GET 回读 | `scrapbook__get_returns_items` | `scrapbook__get.response.json` | `/api/scrapbook` GET ✅ | ✅ |
| delete 撤回 | `scrapbook__delete_removes_item` | `scrapbook__delete.response.json` | `/api/scrapbook/delete` ✅ | ✅ contract(撤回窗 UI 待建) |

### 5.2 哪些子步骤已有原子 case 兜底 / 哪些是 E2E 独有

- **已被原子 case 钉死(E2E 只是串起来再加真 AI)**:upload dedup、vision classify、scrapbook upsert/get/delete
  roundtrip —— 这些 CI 里确定性绿,E2E 跑挂时先排除它们。
- **E2E 独有、原子 case 兜不到的**:① 真 LLM 自己判 pin/discuss/ambiguous + 决定 emit place(非 mock dispatch)
  ② 真 vision 对真照片识别质量(kind/描述是否真对)③ vision-pre-router → AI → tool 的**跨步衔接**
  (hint hoist 位置、AI 有没有被 pin path 推动、anchor_time 匹配对不对)④ claim 审计在真 AI 真撒谎时是否真兜住
  ⑤ **float 浮动观感**(snapshot_ui 断不了"是否浮起来好看",只能录屏人验落纸/悬停/微歪白边)
  ⑥ **MD 真源不动**(整条 AI 链跑完当天 md 必须零 diff —— 这是本链区别 PHOTO 链的核心断言)。
- **mobile 永远兜不到(直到补 UI/注入/抠图)**:对话框真图入口、vision-pre-router 注入、scrapbook 链抠图、
  `m/` 贴纸渲染 + float、拖/缩放/删除。这些在 PARITY_LEDGER 标 `[UI待建]`/parity 洞,本 E2E 文件把它们
  集中成"追平 PC 的施工清单"。

### 5.3 命名约定

- E2E case 名前缀 `e2e_scrapbook__`,跟原子 case(`scrapbook__` / `cutout__` / `vision_classify__`)区分;
  跟姊妹 E2E `e2e_photo__`(→打卡图标)平级。
- 进 `parity/interaction/run-cases.md` 时,E2E 走**真 key + 真 simulator** 分组,**不进**确定性 golden CI 批次
  (对应 PARITY_LEDGER "需 iOS Vision Framework / 需真 qwen3-vl / float 需录屏人验"那批"待真机"标记)。

### 5.4 与姊妹 E2E(`INTERACTION_E2E_PHOTO.md`)的分野

| 维度 | PHOTO(照片→打卡图标) | 本文件(对话框贴图→浮动贴纸) |
|---|---|---|
| 落点 | daily-task 图标 + **写 md `- [x]`** | scrapbook JSON 旁路,**MD 一字不动** |
| 核心 tool | `set_daily_task_image` / `check_daily_task` | `place_scrapbook_image` |
| 共用 | upload-image · vision-pre-router · 抠图三层兜底 · claim 审计 · chip demo 桩 | 同左(共用前半链) |
| mobile 工具状态 | ❌ 缺 `set_daily_task_image` shim | ✅ `place_scrapbook_image` schema+dispatch 都在(后端比 PHOTO 全) |
| mobile 渲染状态 | ❌ renderTasks 不读 image_url | ❌ `m/` 完全不读 scrapbook(比 PHOTO 更空,0 行) |
| 独有红线 | OCR 颗数尊重手填 | **MD 真源不动** · anchor 语义非像素 · auto_y 单向 · size_pct 等比 · **float 动画双门 gate** |
