# 给 gateway 加新皮肤 · workflow

> **心智模型**：皮肤 = classic 引擎的第二个「视图」，不是第二个 app。真正新的只有
> ①布局 ②少数布局差太大、没法复用 classic JS 的「重写面」的数据层；其余全部复用。
> **方法**：contract-down —— 先锁三个契约（阶段 0），之后每页只是「消费」契约。
> 代码在 `~/human-ai-dev/gateway`，参考实物 = `*-paper.html` + `shared/*-paper.css`。

---

## 不变量（先记这 6 条）

1. **页面族，不是 CSS 换色**：classic monolith 一行不动，新皮是独立 `*-paper.html`。
2. **平庸 = 默认留存面；opinionated = opt-in，永不当默认**。
3. **复用引擎只换皮，绝不 fork**：对话/设置/圆环/右键菜单用 classic JS 原件，只给脚手架 ID +
   写 `*-paper.css`（streaming / past_boards 是红线）。
4. **classic 是移动基准，皮肤永远追平它**：新功能/改动先落 classic；皮肤的对等是**常驻 diff**，不是一次性阶段。
5. **落地页扛「主页全动作集」**：classic 主页 = 当天日记 **+ 常驻对话 + 设置 + 圆环** 一体，
   皮肤落地页必须挂齐这四样引擎。
6. **验收逐个按钮真点**：截图只验第一层，"长得像"不等于"点进去一样"。

---

## 阶段 0 · 锁三个契约（动 cd、动像素之前）

> 这一阶段只产出三份清单/决定，不产页面。锁死后，后面每步照着做即可。

### 0.1 环境契约

| 项 | 规则 |
|---|---|
| 字体 | vendor woff2、锁版本、**只本地永不 CDN**（弱网/离线下 CDN 会阻塞首屏） |
| `.venv-build` | **Python 3.11**（脚本 preflight 卡 3.10+；模块级 `X \| None` 注解需 3.10+ 才能 import） |
| 缓存 | server 对 `.html/.js/.css` 下 no-cache；**每改 paper JS bump `?v=`**（WKWebView 按 URL 缓存） |
| 打包 | 每个根 `*-paper.html` 进**三处 add-data**：`build-sidecar.sh` + `build-win.yml` + `build-win.bat`（`shared/`、`vendor/` 整目录自动含，根 html 逐个列） |
| 路由 | `theme.js` 的 `TWINS`（孪生映射）+ `PAPER_READY`（就位才跳）+ 落地规则；`classicTwin` 是反查，**想切回哪个 classic 页就把它排在 TWINS 前面** |

### 0.2 对等契约 —— 扫 classic，得「完整动作集」+「架构真相」

```bash
cd ~/human-ai-dev/gateway
grep -hoE 'label:\s*"[^"]+"' shared/journal.js shared/ritual.js shared/*.js | sort -u   # 右键动作集
grep -rohE 'fetch\("(/api/[a-z/_{}-]+)' shared/*.js | sed 's/fetch("//' | sort -u        # 写操作端点
grep -rohE 'addEventListener\("(click|dblclick|contextmenu|drop|keydown|blur)"|contenteditable' shared/*.js
```

- **动作集**：classic 全部右键项 + 写操作 + 绑定，就是皮肤必须凑齐的清单（阶段 2 给 cd、阶段 4 当 diff 基准）。
- **架构真相**：classic 主页是**一个面** = 日记 + 对话 + 设置 + 圆环。皮肤无论怎么拆页，落地页复刻这个面的全部能力（不变量 5）。

> 🚀 **开 ultracode 提速**：扫 classic 是广度活——一个 agent 一个引擎文件
> （journal / ritual / thread / marketplace / compact-ring）并行枚举动作+端点+handler，汇成总表。

### 0.3 复用契约 —— 逐面定「复用 vs 重写」

| 面 | 决定 | 对 cd 的约束 |
|---|---|---|
| 对话 / 设置 / 圆环 / 右键菜单 | **复用 classic JS 原件** | 不重设计，只换皮；**脚手架 ID 一字不改**（列给 cd） |
| 日记 / 晨课 布局 | **重写数据层** | cd 出排版稿 + 组件 reference，每个写操作配纸习语 |

---

## 阶段 1 · 定页面图

定哪页落地、哪页二级。**约束（来自 0.2 架构真相）：落地页必须挂齐对话/设置/圆环引擎。**
本项目：`index`/根 → `day-paper`（开门见当天），总览降二级「往日」→ 因此 day-paper 带对话面。

---

## 阶段 2 · cd 设计「重写面」

cd 交 3 样、只针对重写面：①排版稿 ②图标效果 ③组件 css reference（token + 组件 + 最小 HTML 片段）。
输入 = 0.2 的交互清单（**点名写操作**，要 NON-button 纸习语：删除禁垃圾桶、新增禁 FAB＋、
等待禁 spinner、对话禁纯气泡）+ 0.3 的脚手架 ID 约束。复用面 cd 不碰。**当轮归档进 `gateway/design/`**。

---

## 阶段 3 · 逐页组装：骨架 → 数据 → 皮

> 顺序即规则。引擎先装 → 页一开始就功能完整；再接数据；最后才上皮。一页验活了才走下一页。

1. **骨架**：复用面引擎的脚手架（0.3 原 ID）贴进页 → include 引擎 JS 原件 → 页**当场就是对等体**。
   落地页这步把对话/设置/圆环挂上（不变量 5）。垫全局 shim（`gatewayToast`/`gatewayAlert`）。
2. **数据**：重写面 `X-paper-data.js` fetch 真数据 → 按 components 语汇拼 DOM → 绑写操作
   （行内编辑走**整块 reconstruct**，删走 delete-block 整块；`anchor_time` 是语义挂点不是像素定位）。
3. **皮**：`X-paper.css` 换纸衣；**数据渲染完才调动画层**（`paperInit`）。
4. **验活**：这页所有按钮真点一遍，再走下一页。

---

## 阶段 4 · 对等 diff（常驻）

classic 是移动基准，重写面会漂移 → 三维对齐，每维拿 0.2 当基准：
- **排版**：落地一致（开门见当天）· 区块同序（morning→pulse→journal）· 切天习语（横向 day-pill 条）。
- **交互**：`diff` 两边 `label:` 全量，classic 每个右键项 paper 都要有（复用 `context-menu.js`，调同一 `menu.show`）
  → 0 迁移成本。业务铁律优先于盲镜像（如 capped-at-today 不给"创建明天"）。
- **完整性**：每个按钮都有活的 handler；没接的要么接要么删。

```bash
diff <(grep -hoE 'label: "[^"]+"' shared/journal.js shared/ritual.js | sort -u) \
     <(grep -hoE 'label: "[^"]+"' shared/X-paper-data.js | sort -u)
```

> 🚀 **开 ultracode 提速**：一个 agent 一个面（journal/晨课/对话/设置/水杯），各自
> 「枚举 classic 动作 → 比对 paper → 列缺口」并行出缺口表，再逐条补。

---

## 阶段 5 · 出包：验 → 打包 → build

- **验收**：沙盒 sidecar（隔离 `HUMAN_AI_HOME/STATE` + 真 vault **副本** + 真 config 拿 key；
  headless Chrome `--virtual-time-budget` 截图）；逐按钮真点 + 真写真查 md；破坏性操作验
  **撤回保住 md / 过窗才真删**两条路；确认 classic 无 `-paper.css` 泄漏。**管理态/写操作在「今天」那页验**
  （仅今天 `bindMorning`、可写）。**禁碰真 vault。**
- **打包**：核对三处 add-data 列了新根 html；一页一 commit；classic 零回归。
- **build**：版本两处 bump（`server.py` `APP_VERSION` + `tauri.conf.json`）→ `.venv-build` 3.11 +
  有 `rembg==2.0.61`/`rapidocr-onnxruntime` → `bash scripts/release-mac-local.sh`
  （**无 `--push`** = 只本地装、不碰云端；`--push` 才发版，受"一天一发"约束）。

> 🚀 **开 ultracode 提速**：截图验收并行（day/night × 各页 × 各状态一把截完）。

---

## 实现规则（组装时遵守）

- **复用引擎**：给齐它 `getElementById` 引用的**所有** ID；本皮肤布局不需要的，给隐藏占位元素
  （引擎绑不到会 null 崩、中断整个 IIFE）。`thread.js` 要 `#threadToggleTop`，`marketplace.js` 要 `#marketBtn`。
- **绑事件**：目标元素必须在 bind 时已存在；异步渲染的目标，**点击时再取**或用事件委托（别在 init 时缓存它）。
- **共享 vs 专用 UI**：瞬时提示（`whisper`/`toast`）多引擎共用一个元素，可被覆盖；**需要常驻的（撤回）建专用元素**。
- **破坏性操作**：乐观隐藏 → N 秒撤回窗 → 才发真删请求（撤回还原、过窗 commit）。paper 没装 `dialog.js`，自带撤回元素。
- **进页不弹**：直接打开某皮肤页 = 用户意图，不回弹；只「显式切换 / 跨标签页同步」才路由。
- **零裸色值 / reduced-motion gate / 字体只 vendor**：跟 components 同规矩。

---

## 成绩单（当前对齐基准）

paper 单日页 = classic 主页对等体（当天日记 + 常驻对话 + 设置⚙ + 压缩圆环）；右键菜单与 classic
全部活动 UI 动作对齐（加条目/改标题/删块+5s撤回/改删tag/批注/指给AI看/日级创建/水杯换图+指给AI看水量）；
排版三维对齐；classic 零回归。`rename 每日任务` 在 classic 也无 UI 触发，不算缺口。
