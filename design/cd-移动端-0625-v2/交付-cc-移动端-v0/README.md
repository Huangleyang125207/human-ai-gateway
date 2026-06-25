# 交付 · Gateway 移动端 v0(cd → CC)

> 出稿:claudedesign · 2026-06-25 · 配 7 份反向 brief(`mobile-v0/`)
> 分工:**cd 出样子 + 手势 + 组件 css,CC 接真数据 / 写操作 / 红线守门。**
> 一句话:样子和手感在这,功能、数据、文案、AI 人格照桌面源码 1:1 落地,别为移动端重新发明它的逻辑。

---

## 0 · 怎么读这个包

1. 浏览器直接开 **`gateway.html`** —— 可跑原型,日记 ⇄ 对话 ⇄ ☰,右上角切日间/夜间。把 5 件套的**手感**先走一遍。
2. 开 **`规范.html`** —— 静态对照表:chip 三态 + 18 tool 自然句、4 widget 双模式、5 套写操作、token 色板。**"每一态长什么样、接哪个 endpoint"** 看这页。
3. 这两页都是 **vanilla HTML/CSS/JS,无 build**,双击即开(`?still=1` 关过渡,截图/PDF 用)。

**这是设计参考实现,不是生产代码** —— 但 `tokens.css` / `components.css` 可直接进 repo;`gw-*.js` 是骨架,CC 把 mock 换成真 `window.api.*` / `gatewayMd` 即可。文件结构刻意对齐真机 `agents/human-ai-schedule/mobile/m/`,能直接 lift。

---

## 1 · 五件套对应文件

| # | 交付物 | 在哪 |
|---|---|---|
| 1 | **单日页**(关怀区 4 widget + 时间线 + chatbar + 悬浮提笔) | `gateway.html` 日记 tab + `gw-app.js` / `gw-journal.js` |
| 2 | **关怀区 4 widget**(八杯水/今日打卡/今日 PULSE/今天心情) | `gw-widgets.js` · 视觉态见 `规范.html` #2 |
| 3 | **AI tool chip 视觉**(三态 doing/ok/fail + 18 自然句) | `gw-chat.js`(`GW.toolLabel`)· 目录见 `规范.html` #3 |
| 4 | **5 套写操作习语**(行内编辑/长按/提笔/横滑/撤回) | `gw-journal.js` · 图见 `规范.html` #4 |
| 5 | **tokens + components.css**(双模式,零裸色值,字体 vendor) | `tokens.css` + `components.css` |

---

## 2 · 红线(违反 = 稿没法用)

- **MD 是真相 · 无 build** —— 正文一律走 `window.gatewayMd()`(marked+DOMPurify,vendor 锁版)。`gw-mock.js` 里的 `GW.gatewayMd` 是**极简 stub**,落地删掉换真的,别在视觉层手写第二个 md 解析。
- **不卡片化 · 不 dashboard** —— 关怀区是竖向小报栏目,墨线分隔,没有白底圆角阴影一刀切。
- **AI 是空气,不是按钮** —— AI 的常驻在场只有顶栏那颗呼吸点;真出手时在对话流留 chip、每晚留 21:30 纸条。没有"AI 助手"按钮、没有 robot icon。
- **写操作禁四样**:删除→撕痕+撤回(不用垃圾桶 icon)· 新增→提笔钢笔尖(不用 Material FAB+)· 等待→磨墨墨石(不用 spinner)· 对话→宋/楷双笔迹(不用纯气泡)。
- **双模式 day/night** —— 同一套语义 token,组件层**零裸色值**。夜间不是反色,是棕墨提成琥珀、朱砂提亮(深夜 11 点开灯不刺眼)。
- **字体只 vendor 不走 CDN** —— stack 在 macOS/iOS 落到系统 Songti/Kaiti;真机把同名 woff2 vendor 进 repo,变量名不动(`--font-serif` 人/正文 · `--font-kai` AI · `--font-sans` UI)。

---

## 3 · 三类笔迹即作者(零成本世界观)

| 作者 | 字体 | 哪里 |
|---|---|---|
| 用户 | `--font-serif`(宋体) | entry 正文/标题、对话流"我"的气泡 |
| AI | `--font-kai`(楷体) | 夹批 commit、对话流 AI 消息、21:30 纸条、磨墨文案 |
| commit 夹批 | 小字 + 朱砂"批"印 | entry 下方 `<commit>` 注解(`@user` 段 AI 不可覆盖) |

---

## 4 · 数据 / endpoint 映射(CC 接线)

视觉层不写数据访问,但每个动作落哪都标了。`gw-mock.js` 顶部 `GW.toolLabel` 是 18 tool 的自然句翻译(交付 #3 核心),新增 tool 加一条即可。

**读**:`gatewayMd(raw)` · `api.taskmeta(name)` / `api.taskintake(name)` · `api.threadHistory()`(corrupt → 走 modal,不可"返空当空")· `api.widgetStates()` · `gatewayConfirm(msg)`(替 `window.confirm`)

**写**:
- 八杯水滑点亮 → `POST /api/daily-tasks/water`(当天 md 子杯前 N 个 `[x]`)
- 打卡 toggle → `POST /api/daily-tasks/check`(intake clamp 0..daily_dose;≥dose 时父行 `[x]`)
- 换图标 → `/api/daily-tasks/set-image` · 改 meta → `/api/daily-tasks/meta` · 删 → `/api/daily-tasks/delete`
- 换喝水图 → `/api/water-cup` · 贴纸抠图 → `/api/cutout/<sha16>`
- 新建 entry → `POST /api/journal/insert-block`{date,time,tag,title,body}
- 编辑 entry → `POST /api/journal/patch`{date,time,new_md,author:"user"} —— **new_md 末尾必须拼回 existing commits,否则 @user/@ai 批注丢**(6.16 坑)
- 删除 → `/api/journal/delete-block`;撤回 → `/api/journal/patch` **同位回填**(不是 insert 到末尾)
- 对话 → `POST /api/chat`(stream)· 贴图 → `/api/chat/upload-image`(返 url 才写盘;dataURL 只本地预览不发)
- 21:30 纸条 → **lazy**:每次 app 启动检查,当天 21:30 块仍占位且有 deepseek key → 调 DeepSeek 写入 `## 纸条 @ai`,author=ai。**不在前台显示生成过程**(纸条出现像"她写完离开了")
- mood → `localStorage` 本机 only,**不进 md**

**契约**:author 分 user/ai 走两套路径;时间块步长 30 分;建天最多 +1;chip 三态是数据真值不可合并;chip 永久留存不消失;chip 不可点开成面板(fail 可展开一行)。

---

## 5 · iOS 真机(落地 checklist)

- `--safe-top`/`--safe-bot` → 真 `env(safe-area-inset-*)`;背景铺到屏幕边,可点元素在安全线内。
- 390×844 基线,320 不崩,414+ 只留白。**单一视觉,无宽度断点**。
- 长按 480ms(`gw-journal.js` 已是此阈值);iOS 无 `navigator.vibrate` → 走 Capacitor Haptics。`-webkit-user-select/touch-callout:none` 已在 `.gw` 关掉系统长按气泡。
- 键盘:`visualViewport` 顶高 viewport,底栏跟键盘走;数字输入用 `inputmode="numeric"`(已设)。
- 图:缩略图渲染 ≤200px(防 base64 OOM);不鼓励图墙/相册 grid;HEIC 由 Camera plugin 强转 jpeg。
- http 链接走 https 升级 + 失败降级 hint,不画"已验证"绿勾。
- 信号采集 fire-and-forget(`GW.scanIntent` 是 stub),走 `realFetch` 不经 `/api/*` shim,永不 throw,无 PII。

---

## 6 · 文件清单

```
交付-cc-移动端-v0/
├── README.md                  ← 本文件
├── gateway.html               ← 可跑原型(日记⇄对话⇄☰,日夜可切;?still=1 关过渡)
├── gateway-自包含单文件.html   ← 同上,CSS+JS 全内联,双击即开/无依赖(给非 dev 看)
├── 规范.html                  ← 静态对照:chip三态+18自然句 / 4 widget双模式 / 5写操作 / token
├── tokens.css                 ← 双模式语义 token(组件层零裸色值的唯一色源)
├── components.css             ← 纸感组件库(.gw 之内全部组件;产品样式,可直接进 repo)
├── gw-mock.js                 ← mock 数据 + gatewayMd stub + toolLabel(18 自然句)+ 图标
├── gw-widgets.js              ← 关怀区 4 widget + 动态 widget 默认外观
├── gw-journal.js              ← 时间线 + 5 套写操作(模态/sheet/openCard/撤回 helper)
├── gw-chat.js                 ← 对话流 4 类消息(msg/ref/note/tool)+ 磨墨 + 流式
└── gw-app.js                  ← 装配入口:GW.mount · 顶栏/日期带/tab 路由/抽屉/设置/主题/连线
```

> **JS 加载顺序(gateway.html 已固定)**:`gw-mock → gw-widgets → gw-journal → gw-chat → gw-app`。
> `gw-app.js` 必须最后(它定义 `GW.bus`/`GW.root`/`GW.whisper` 再 `GW.mount`);其余四个被它在运行时调用。
> `规范.html` 只用前四个(无 `gw-app.js`,它不装壳只做静态展示)。

## 7 · 落地顺序(建议)

1. `tokens.css` + `components.css` 进 `mobile/m/`(先把骨架误链的旧 paper token/朱砂/裸色值换成这套)。
2. `--safe-*` → `env()`;确认 Kaiti/Songti vendor woff2 就位、离线不白屏。
3. 按屏替换视觉:顶栏+日期带 → 关怀区 → 时间线 → 底栏。正文接真 `gatewayMd`。
4. `gw-*.js` 的 mock 换真 `api.*`;手势逻辑(pointer + `touch-action:pan-y` + 480ms)可直接参照。
5. chip 接 thread 的 tool_call 生命周期;openCard 接 insert/patch(记得拼回 commits);21:30 lazy 接 DeepSeek。
6. 真机截图验收:动画常驻,headless 用 `?still=1` 或 `--virtual-time-budget`,别动原件。

---

**注意**:`gw-mock.js` 里的数据/文案是设计气味用的占位(自由意志、演牌、KS、鱼油…),落地全部由真 vault + 真 AI 替换。
