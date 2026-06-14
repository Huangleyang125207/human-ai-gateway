# 交付 · Gateway 移动端（cd → CC）

> 出稿：claudedesign · 2026-06-14 · classic（私印小报）单一日间
> 配套读：`MOBILE_DESIGN_BRIEF.md`（IA/规则）· `桌面DNA_DESIGN_BRIEF.md`（魂）· `classic-style.css`（桌面视觉源）
> 分工同桌面那轮：**cd 出样子 + 手势，CC 对着桌面源码 1:1 落地功能/数据/文案。**

---

## 一、这是什么

桌面 Gateway 的**手机版**（iPhone + Android 一套壳）的关键屏 + 触屏手势 + 移动组件 CSS。
本包交付三样（对应 brief 第六节）：

1. **关键屏静态稿 + 可跑原型** —— 日记页 / **+ 卡片编辑器**（重点，3 形态）/ 对话页 / ☰ 抽屉 / 设置页
2. **触屏手势与动效** —— 日期带滑动建明天、条目左滑删、长按拉进对话、+ 卡片弹出、磨墨等待、顶栏下滑收起
3. **移动组件 CSS reference** —— `mobile-tokens.css`，全用 classic token，可直接 lift 进 `mobile/m/`

## 二、关于本包里的文件（重要）

`原型/` 里是 **React + Babel 写的设计参考原型**，演示「长什么样 + 手指怎么动」，**不是要照搬的生产代码**。
你的活是把这些样子和手势，用 **vanilla HTML/CSS/JS** 在 `mobile/m/` 里重建，接 `window.gatewayMd()` 和 shim 数据层。
**`mobile-tokens.css` 例外**——它是纯 CSS、零依赖，可直接进 repo（按需重命名/合进现有 `style.css`）。

保真度：**高保真（hifi）**。颜色/字阶/间距/圆角/动效时长都已定死，照像素还原；只把 React 状态换成 vanilla。

## 三、硬约束（brief 第五节，落地红线，违反 = 稿子落不了地）

1. **vanilla，无 build/npm/框架**（web 层）。数据走本地 `/api/*` shim + 直连 DeepSeek。原型里的 React/Babel **删掉**。
2. **markdown 单一入口 `window.gatewayMd()`**（marked+DOMPurify）。正文别另造渲染——原型里的 `<Body>`/`<br>` 占位换成 gatewayMd。
3. **色板只用 classic**（米黄 `#f4ede2` + 4 粉彩 + 金棕 `#b4731e`）。**绝不引朱砂/oklch 夜色/`--paper-*`**（那是另一套 paper 皮肤）。classic 单一日间、无夜色。
4. **字体走系统 CJK，零 CDN**：人/正文 `--serif`（宋体）、UI `--sans`（系统）、**AI 笔迹 `--kai`（文楷 Kaiti）**。离线/代理下不许白屏。
5. **触屏优先**：热区 ≥44pt；无 hover 依赖；手势（滑/长按）必带视觉提示。
6. **safe-area**：刘海/灵动岛/底部 home 条让位 `env(safe-area-inset-*)`。原型用 `--safe-top/--safe-bot` 变量模拟，落地换成真 env()。
7. **动画安静**：呼吸/墨迹/纸页，不要 dashboard 闪跳；尊重 `prefers-reduced-motion`（CSS 末尾已 gate）。

---

## 四、屏 / 视图

### 1) 日记页（核心面）
- **顶栏（两行，sticky，下滑收起上滑唤回）**
  - 第一行：`☰`（最左，所有非日记非对话入口）+ `日记`/`对话` 平级切换（报头式，选中下方金棕 2px 墨线）+ 右侧呼吸墨点（AI 在场的隐形提示）。
  - 第二行：**渐变滑动日期带**。横向滚动，左右边缘 mask 渐隐（`28–34px`）。
    - 今天：金棕 `--gold`，数字放大到 27px、weight 500，下标「今天」。
    - 已创建过去日：墨阶常态。**滑/点过去日 = 只读浏览**（八杯水/打卡禁用，文案「历史日只读」）。
    - 明天（+1）：`creatable`，数字套 34×34 虚线框 + 右上角 `+`（tan 色）。**点它 = 创建那天**（落空骨架 + `born` 墨迹动画 1.1s + 轻提示）。
    - 后天起：`locked`，opacity .32，点击只弹提示「最多只能建到明天（+1）」。**这条是桌面硬规则，别放宽。**
- **care 区**（顶部边线包裹）
  - **八杯水**：8 个杯子，**滑过点亮**——手指/指针扫过，扫到第 N 个则填到第 N 杯，**触点那杯放大 1.7×、邻杯 1.3×**（touch 版 dock 放大，origin bottom）。新点亮的杯走 `gw-pour` 倒水动画。
  - **今日打卡**：横滑卡片，点击 toggle。未打卡 = 褪色（`filter:saturate(.18)`，呼应桌面 灰→彩），打卡后回彩 + 右上勾 + 抬起阴影。
- **时间线**：`grid 52px / 1fr`。左列时间（小时大字宋体 + 分钟小字）；右列 tag chips + 标题（宋体 500）+ 正文（宋体）+ 可选夹批 commits（人宋体 / AI 文楷）。

### 2) + 卡片编辑器（本轮重点 · 3 形态，原型顶部可切，落地三选一或都留）
点底部 `+` 弹出。字段统一：**#tag chips（含「+ 新标签」）· 时间块（HH:MM + 现在/整点/半 快捷）· 正文（含可选标题）· 落笔**。
- **A 底部 sheet**（`.gw-card.sheet`）：从底滑起，顶部抓手，圆角 24。最熟手机习语，推荐默认。
- **B 全屏信笺**（`.gw-card.full`）：占满，横格纸背景（`repeating-linear-gradient` 33/34px），像写一封信，沉浸长写。
- **C 居中便签**（`.gw-card.note`）：居中浮起、微旋 -0.6°、顶部一截胶带（`::before`），轻量速记。
- 弹出节奏：scrim `opacity .3s`；卡片 `transform .42s var(--ease)`。关闭反向，460ms 后卸载。

### 3) 对话页
- 消息流：**人=宋体气泡（暖色右对齐）/ AI=文楷气泡（纸色左对齐）**——「笔迹即身份」零成本两位作者。
- **@引用卡**（长按日记条目拉进来的）：左侧桃色竖线 + 标签「日记·HH:MM」。
- **21:30 纸条仪式**（低频慢场景）：折页卡片（顶部桃色描边 + 右下折角 `::after`），正文文楷手写，落款。
- **磨墨等待**（AI 处理态）：墨石旋转 `gw-grind-spin 2.6s` + 中心墨迹晕开呼吸 `gw-grind-bleed`，文案「磨墨中…」。**不要 spinner。**
- 流式出字：AI 气泡末尾朱砂游标 `gw-cursor` 闪烁，逐字填入。
- 底栏对话态 = 输入框 + 金棕发送圆钮（回车发、shift+回车换行）。

### 4) ☰ 菜单抽屉（底部）
从底滑起，抓手 + 「Gateway · 人和 AI 共写的一本日记」头。条目：**设置 · 聚合页 · 小组件 · 历史 · 关于**（图标 + 标签 + 描述 + chevron）。颗粒度见 brief 第四节。

### 5) 设置页（☰ → 设置）
- **双钥匙**：**DeepSeek · 说话的那个**（已连通态绿边 `--sage`）/ **阿里云百炼 · 看东西的那只眼**（可选，未填=暂无视觉）。每把：粘贴框 + 测试钮 + 状态行。
- **皮肤**：私印小报 classic（日/夜分段，夜灰显——夜色随另一套 paper 上线再说）。
- **呼吸暖光 / 减少动效** 开关；本地 vault 路径；云上报与撤回入口。

---

## 五、交互与动效（时长 / 缓动）

| 手势 / 状态 | 触发 | 视觉 | 时长·缓动 |
|---|---|---|---|
| 顶栏收起/唤回 | 滚动区 scrollTop 下增>6 且>70px 收起；上滑唤回 | `translateY(-100%)` + 渐隐 | 0.42s `var(--ease)` |
| 日期带建明天 | 点 `creatable` 格 | 落空骨架 + `gw-day-born` 暖色淡出 + 轻提示 | 1.1s ease |
| 条目左滑删 | 指针水平左拖（与纵向滚动区分：横位移>纵且<0 才进 swipe）| 跟手 translateX（clamp -96）；底层朱砂「删除」块；越过 -60px 松手 → 飞出删 + **撤回 toast（5s 倒计时进度条）** | 飞出 0.24s；toast bar 5s linear |
| 长按拉进对话 | 按住 480ms 未移动 | `gw-lp` 暖色环晕开 + 条目高亮 + vibrate(12)，420ms 后入对话 + 提示「已拉进对话 ✦」 | 环 0.6s |
| + 卡片弹出 | 点底部 `+`（图标 rotate 135°）| 见上「弹出节奏」 | 0.42s `var(--ease)` |
| 磨墨等待 | 发消息后 ~1.05s | 墨石旋转 + 墨迹呼吸 | 2.6s / 2.2s 循环 |
| 八杯水点亮 | 指针扫过杯子 | 倒水 + 触点放大 | pour 0.9s；scale 0.2s |
| 呼吸暖光 | 常驻 | 背景 radial 明暗缩放 | 7.5s 循环 |

**区分横滑与纵向滚动**：指针按下记起点，移动>8px 时判向——横向且向左→进 swipe（setPointerCapture）；否则交给原生纵向滚动。落地用 `touch-action: pan-y` + Pointer Events（原型已是此法，可直接参照 `gw-journal.jsx` 的 `Entry`）。

## 六、状态（落地需要的 state）

- `tab`：`journal` | `chat`；`subPage`：`null` | `settings` | …（抽屉项）
- `dayKey` + `days[]`（每天 `state`: past/today/creatable/locked）；`journal[dayKey][]`（条目，按 time 升序）
- `tasks[]`（id/name/glyph/on）；八杯水 `filled`（0–8）
- `thread[]`（kind: msg/ref/note；who: me/ai；msg 可带 `streaming`）；`grinding`（磨墨态）
- `cardOpen` + `cardVariant`；`menuOpen`；`topHidden`；`undo`（被删条目，5s 后清）；`hint`（轻提示，2.2s）
> 语义/数据/规则一律照桌面源码，别在移动端重定义（authorship 8 层守卫、建天 +1、打卡窗口等）。

## 七、设计 token（全部已在 `mobile-tokens.css` `:root`）

**色**（classic，照搬 `classic-style.css`）：
`--bg #f4ede2` · `--bg-2 #efe6d6` · `--bg-3 #e8dec9` · `--paper #fbf6ec` · `--paper-hi #fefaf2`
`--ink #3a342c` · `--ink-2 #5a4f42` · `--ink-3 #857a68` · `--ink-4 #a89c84`
`--peach #e9c7b4` · `--sage #cdd5b9` · `--mist #c8d0d8` · `--rose #ddb7b1`
`--gold #b4731e` / `--gold-2 #8a5712`（链接·今天） · `--tan #b87a4f`（@引用） · `--cinnabar #b14a2b`（仅删除/危险）
`--line rgba(58,52,44,.08)` · `--line-2 .14` · `--warm rgba(233,199,180,.22)` · `--warm-2 .42`

**字**：`--serif`（Songti/Noto Serif SC，人/正文）· `--sans`（系统 UI）· `--kai`（Kaiti，AI 笔迹）· `--mono`

**移动专属**：`--hit 44px`（热区）· `--r-card 16` · `--r-sheet 24` · `--r-pill 999` · `--ease cubic-bezier(.2,.7,.2,1)` · `--shadow-sheet` · `--shadow-float` · `--safe-top/--safe-bot`（落地换 `env(safe-area-inset-*)`）

**组件 class 速查**（`mobile-tokens.css` 内分节注释齐全）：
`.gw`（壳）`.gw-breath/.gw-grain`（纸 ambient）`.gw-top/.gw-tabs/.gw-dateband/.gw-day`（顶栏+日期带）
`.gw-care/.gw-cups/.gw-cup/.gw-tasks/.gw-task`（care 区）`.gw-stream/.gw-entry/.gw-tag/.gw-commits`（时间线）
`.gw-bottom/.gw-fab/.gw-chatbar`（底栏）`.gw-scrim/.gw-card(.sheet/.full/.note)/.gw-field/.gw-chip/.gw-time-*`（卡片编辑器）
`.gw-thread/.gw-msg/.gw-bubble/.gw-ref/.gw-note/.gw-grind`（对话）`.gw-drawer/.gw-menu-item`（抽屉）
`.gw-set/.gw-key/.gw-row/.gw-toggle/.gw-seg`（设置）`.gw-undo/.gw-hint-toast/.gw-empty`（反馈/空态）

## 八、桌面功能 → 移动 映射（落地顺序见 brief 第四节，本稿已覆盖的）

- 半小时块时间线 ← `journal.js/parse_journal`（🟢）；新建条目 ← `insert-block`（🟡 = 本稿 + 卡片编辑器）
- 行内编辑 ← `patch-block`（🟡 点条目进卡片/sheet 编辑，可后续接）；删除块 ← `delete-block`（🟡 左滑删，已做）
- 建今天/空白天 ← `new-day`（🟢 日期带落骨架）；夹批双签 ← `journal.js commit`（⚪ 条目内次级展开）
- 打卡/水杯 ← `ritual.js / water-cup`（🟢/🟡）；常驻对话流式 ← `thread.js`（🟢骨架/🟡真连）
- 21:30 纸条 ← `notes-board.js`（🟡）；双钥匙 onboarding/填测 ← `setup.js/consent.html`（🟡）
- 聚合页/历史/小组件 = 抽屉入口已留，按 ⚪ 批次往上加

## 九、文件清单

```
交付-cc-移动端/
├── README.md              ← 本文件（自足，不在现场也能照着落地）
├── mobile-tokens.css      ← 交付物 #3：移动组件 CSS reference（可直接进 repo）
└── 原型/                   ← 可跑的高保真交互原型（设计参考，非生产代码）
    ├── index.html         ← 入口：iPhone+Android 双壳并排 + 顶部切卡片形态/手势提示
    ├── mobile-tokens.css
    ├── frames/            ← 设备外壳（仅原型用，落地不需要：真机就是真壳）
    │   ├── ios-frame.jsx
    │   └── android-frame.jsx
    ├── gw-data.jsx        ← mock 数据 + 内联图标（落地换真数据/你们的 icon）
    ├── gw-journal.jsx     ← 日记页：八杯水/打卡/时间线 + 左滑删 + 长按（手势逻辑参考）
    ├── gw-card-editor.jsx ← + 卡片编辑器（3 形态）
    ├── gw-chat.jsx        ← 对话流/纸条/磨墨
    ├── gw-menu.jsx        ← ☰ 抽屉 + 设置页
    └── gw-app.jsx         ← 主壳：顶栏收起/日期带/状态机/底栏切换
```

## 十、落地清单（建议顺序）

1. `mobile-tokens.css` 进 `mobile/m/`（或并进 `style.css`），**先把骨架现暂误链的 paper `design-tokens.css`/朱砂/`--paper-*` 换成 classic 这套**（brief 第七节点名的第一件事）。
2. `--safe-top/--safe-bot` → 真 `env(safe-area-inset-*)`；`--kai` 确认 iOS Kaiti / Android 思源/系统楷体回退到位。
3. 按屏替换视觉：顶栏+日期带 → care → 时间线 → 底栏 +/输入；接 `gatewayMd()` 渲染正文。
4. 实现手势（参照 `gw-journal.jsx` 的 Pointer Events + `touch-action:pan-y`）：左滑删（接 delete-block + 撤回）、长按拉进对话、日期带建天（守 +1）。
5. + 卡片编辑器选定形态接 insert-block；对话接 thread streaming + past_boards；设置接 setup save/test。
6. 真机截图验收（动画常驻，Playwright 易超时——用 headless `--virtual-time-budget` 或注 URL 参数控状态，别动原件）。

---

**一句话**：样子和手势在这；功能、数据、文案、AI 人格照桌面源码 1:1，别为移动端重新发明它的逻辑。
