# Gateway 移动端 MVP 移植规划

> 创建 2026-06-13 · 葱鸭 × claude-opus-4.8 共写
> 状态：P0 起步中（分支 `mobile-mvp`）
> 这是 LARGE 任务的 spec，不进 CLAUDE.md 的 Active spec（那里被 paper 皮肤占着）。

---

## 决策（用户 6.13 定调）

1. **后端落点 = 手机本地独立跑**。脑（逻辑 + 日记）在手机上，不依赖你的 Mac、不上服务器。
2. **平台 = iOS + Android 一套壳**。
3. **范围 = 最小可行、只求能用、不求所有功能**。

## 关键 reframe：本地独立 ≠ 重写 server.py

server.py 是 9481 行 / 86 路由的 FastAPI 单体，PyInstaller 打成桌面 sidecar 二进制。
**手机上跑不了这个二进制**（iOS 禁止 spawn 二进制；Android 打包 Python 运行时极脆）。

但两个事实让"本地独立"的最小版**绕开重写**：
- 前端 34 个 JS 全用**相对路径** `fetch("/api/…")`——谁 serve 它就连谁；
- markdown 渲染 + UI 全在**客户端 JS**（`marked`+`dompurify` 已 vendor，webview 里直接跑）。

所以 MVP 真正要在手机本地落地的只有两类原子能力：**① 读写本地 MD 文件；② 直连 LLM**。
两者都能在 WebView 的 JS + 一个原生文件桥里完成，不需要 Python。

> **核心手法**：新增 `mobile-api.js`，最先加载，劫持 `window.fetch`。命中 MVP 名单的
> `/api/…` 本地服务掉（文件桥读写手机 vault + 原生 HTTP 桥直连 DeepSeek）；其余 80 个
> 端点返回"桌面版功能"占位。**现有前端 JS 尽量一行不改。**
> 重写的不是后端，是拦截层；且只重写 ~10 个端点。

## 目标形态

```
┌─ 一套壳 (Capacitor，iOS+Android 同一份) ────────────┐
│  WebView                                            │
│   ├─ 现有 gateway/ 前端 (index.html + 核心脚本)      │
│   ├─ mobile-api.js  ← 劫持 /api/*，本地服务 ~10 端点 │
│   │     ├─ 存储后端: 浏览器=localStorage/OPFS         │
│   │     │            设备=@capacitor/filesystem      │
│   │     └─ 原生 HTTP 桥 → api.deepseek.com (绕 CORS) │
│   └─ marked+dompurify (已 vendor, 客户端渲染)        │
└─────────────────────────────────────────────────────┘
        ⊗ server.py / uvicorn / sidecar 全部不上手机
```

**壳选型**：Capacitor（包 web + 文件桥 `@capacitor/filesystem` + 绕 CORS 的 `CapacitorHttp`
都现成，一份出双端）。备选 Tauri 2 mobile（贴现有 Rust 栈但更年轻）。
DNA 说明：「无 npm/无 build」指 **web app 本身**仍 vanilla、可浏览器直开；只有**壳**有构建，
这对任何可安装 APP 不可避免。

## MVP「能用」范围

**保留**（核心日记 loop）：
- 读今天 / 翻最近几天（journal/today, /days）
- 跟 AI 说话（chat → 直连 DeepSeek，当天 journal 当 context）
- 打卡（daily-tasks）
- 人写一条 / 编辑自己的块（insert/patch/delete-block，见风险③简化）
- 填 key + 启动自检（setup, health, init-status）

**砍掉**（shim 返回占位）：拖图抠图/scrapbook、vision/OCR、web_search、git audit、
PULSE/eval/tag-aggregate/history exporter/training corpus、widget 市场、自动更新、
telemetry/consent、AI tool-calling。

## 三个必须正视的坑

1. **数据分叉（最大后续债 → P5）**：手机本地 vault ≠ Mac Obsidian vault。建同步前两边日记分开。
2. **CORS**：WebView 直 fetch DeepSeek 大概率被拦 → LLM 调用走**原生 HTTP 桥**。流式经原生桥
   可能要降级为**阻塞返回**；只求能用可接受。
3. **authorship 守卫**：桌面那 8 层"AI 不覆盖 @user 块"+ H2 守卫不在 JS 全量重写。
   MVP 简化：**人直接编辑自己的块；AI 只往对话流落纸条、不直接改 MD。**

## 分阶段

- **P0 立壳**：Capacitor 包现有 `gateway/`，iOS+Android 各跑起能渲染的空壳。
- **P1 本地数据层**：`mobile-api.js` + 存储抽象 + seed 手机本地 vault。验收：**全离线**读今天/打卡/写一条/翻最近几天。
- **P2 AI 对话**：shim 接 /api/chat 直连 DeepSeek + 极简设置页填 key。验收：能跟 AI 说话、AI 知道今天写了啥。
- **P3 窄屏收口**：核心页窄屏 CSS + touch。验收：单手能用、深夜低光舒服。
- **P4 打包分发**：iOS 走已有 Apple 签名 → TestFlight/家人 iPhone；Android 签 APK 直发。
- **P5（非 MVP）**：Mac↔手机 vault 同步（解坑①）。

MVP 基座用 **classic 皮肤**（index.html，留存面、功能最全、已带窄屏断点）。

## Test plan

- [ ] T1 shim 契约：被劫持的每个端点返回形状与 server.py 逐字一致（先抓真 server 响应存为 golden，再比对 shim）
- [ ] T2 boot 不卡：浏览器加载 index.html 经 shim，无 console error、无卡死的 gate/modal
- [ ] T3 离线读写：读今天 + 打卡 + 写一条 + 翻最近几天，全程断网可用
- [ ] T4 窄屏定妆：390px viewport 截图核心三态可用
- [ ] T5 设备真机：家人 iPhone 装一遍跑通日记 loop

## Tasks

- [x] **P1-0 可行性 de-risk（最大未知，已验）** — 现有桌面前端 index.html 在本地 JS shim
  喂数据下，phone 390px 视口：init gate 自散、3 个日记块渲染、打卡挂载、无设置锁、
  无横向溢出、reload 后数据持久、**0 console error**。零 Python。
- [x] P1-1 fetch-shim 骨架 + 存储抽象（浏览器 localStorage 后端先行；EventSource 也劫持）
- [x] P1-2 journal/today、/days、daily-tasks 读路径（忠实复刻 parse_journal 切块）
- [x] P1-3 insert/patch/delete-block + new-day 写路径（验：打卡 [ ]→[x]、insert 真落 MD）
- [x] P1-4 boot 端点 stub 不卡 UI（关键：setup-status 必 configured:true，否则锁死）
- [x] P0-1 Capacitor 工程脚手架（mobile/app: package.json + capacitor.config + 6 依赖装好,
  CLI 6.2.1 可用）+ mobile/build-web.sh 组装 www（只含 webview 资源,不带 server.py）
- [x] P1-5 存储后端换 Capacitor Filesystem+Preferences（与 localStorage 双后端自动选；
  代码就绪,真机持久待 device 测）
- [x] P2-1 /api/chat → DeepSeek 直连（真机 CapacitorHttp 绕 CORS,浏览器 fallback；
  读今天日记当 context）+ setup/save 落 key（代码就绪,真机待测）
- [x] **iOS 工程生成** — 用户装好 Xcode 26.5(许可已接受)+ brew 装 CocoaPods；
  `cap add ios` 成功(filesystem/preferences pod 装上)、`cap sync` 干净。
  capacitor.config 开 CapacitorHttp → 原生 patch fetch,设备上 DeepSeek 直连自动绕 CORS。
- [x] **iOS 模拟器跑通验证** — BUILD SUCCEEDED,装+启动 iPhone 17 模拟器,日记 UI 完整
  渲染(报头/日期/3 时辰/水杯/打卡/补剂),系统 CJK 衬线、无横向溢出。两处真坑已修:
  ① index.html 的 Google Fonts CDN render-blocking → bundle 里 sed 去掉(白屏首帧根因);
  ② /api/vault/audit stub 缺 total_drift → 误报"undefined 处漂移",shim 补 0 漂移。
  另:平台运行时 CLI 安装踩"Duplicate"坑(删重复→清干净重装才成,boot 才正常)。
- [ ] iOS 真机:Xcode 已开 → 选签名 Team(L2QPVXA6DT)→ 连家人 iPhone → Run(用户做,需 Apple ID+设备)
- [ ] Android:brew 装 openjdk@17(许可已通,可重试)+ Android SDK → cap add android
- [ ] P3 窄屏 CSS 收口（thread 抽屉 touch / 字号 / 留白 / 换本地 vendor 字体）
- [ ] P4 双端真机验收（家人 iPhone 跑通日记 loop + 填 key 聊天）

## Findings

- **6.13 de-risk 一击命中**：整条"包现有前端 + 本地 shim、不重写 9481 行 Python"的赌注
  在浏览器里跑通。决定性发现来自契约侦察——**唯一硬 boot 锁是 `/api/setup-status`**
  （必须 `configured:true` 否则用户困在无关闭键的设置弹窗后），其余端点全 fail-open。
  shim 守卫（`?mobile=1`/Capacitor/localStorage flag）让同一份 index.html 桌面惰性、
  移动拦截，desktop server.py 零回归。
- **EventSource 也得劫持**：update-banner 的 migration/stream 走 EventSource 不走 fetch，
  漏了它 boot 有个 404。已在 shim 里把 /api/* 的 EventSource 也返惰性对象。
- **截图取证盲区**：Playwright MCP 存图到沙盒目录够不到。本轮靠 DOM 探针 + 交互断言取证；
  视觉定妆（深夜低光味）留 P3 真机/可达 headless 时补。
- **6.13 晚 大转向：结束「克隆桌面」MVP → 移动原生重做**。三个死症（日期随滚动消失 /
  + 按钮断 / 打卡卡片不可滑）证明 webview 包桌面 monolith 在触屏上是死路。克隆版没白做：
  验证了 iOS 构建管线（Capacitor→Xcode→模拟器渲染）+ 本地数据层 shim，新版直接继承。
  新前端 `mobile/m/`（index+css+js）走传统手机交互：顶栏 ☰·日记·对话（下滑收起/上滑唤回）
  + 渐变日期带（未来灰，滑或点 +1 建明天，最多 +1，跟 PC 一致）+ 打卡横滑 + 时间线 +
  底部常驻输入（点展开，记一笔→insert-block / 对话→chat）+ ☰ 底部抽屉（设置/聚合/小组件/
  历史/关于）。复用 shim + design-tokens（data-theme=day）+ gatewayMd，桌面 index.html
  在移动端弃用。Playwright 实测：渲染/零横向溢出/tab 切换/composer 展开/菜单开合/日期 kind
  （today=open·明天=creatable·+2=future）全绿。**剩：真机验证 + 触屏手势（左滑删/长按）
  + 对话流式真连 + ☰ 各页逐页接 + day/night 切换**。
- **6.15 P0 格式收敛 = 双端同步地基**。勘察发现两端半点块**内容字节兼容**（shim parser
  复刻 server.py），但**存储布局三处分叉**：① 文件名 iso(2026-06-15) vs 桌面 stem
  26.6.15(第44天) ② 补剂 独立文件 vs 内嵌当天 md 顶部 ③ chat 结构不同。P0 把 ①② 收敛成
  canonical（③ chat 暂留各端本地）：手机写的天文件桌面 parser 直接能读。**铁证：设备端手机
  生成的补剂段，归一化勾选态后 diff 桌面真文件 = 空（21 行字节一致）**。教训：同步前先验
  "格式是否字节兼容"别假设；归一化 diff 是最强验收（JSON 字段对 ≠ 字节对）。

## 双端同步方案（6.15 定调 + P0 落地）

桌面 vault 已是 git 仓、**每写必自动提交**（近 7 天 51 次，提交信息带 insert/patch + 日期 +
块 + #tag + @作者）。**核心思路：不自建 merger，git 就是合并引擎** —— 配远端 + 手机装 git
客户端，3-way merge 交给 git。日记的**时序分区**（一天一文件、一刻只在一处写）让真冲突极罕见。

- **传输层（用户定）：仅局域网直连**。桌面在家开小 git http 服务，手机同 wifi pull/push。最
  local-first，出门不同步是可接受代价。手机 git 客户端 = **isomorphic-git**（纯 JS、跑 WebView、
  无原生插件，守"无 build/无原生"DNA）。
- **合并语义**：不同天/历史天=不同文件永不冲突；今天不同半点块=git 自动合并；同块两端都改=
  块级"留哪个/都留"卡（不给原始 `<<<<` 标记）；补剂/水 checkbox=勾上者胜；keys 不同步。
- **红线**：裸 git 文本合并**绕过 8 层 authorship guard**（AI 不可覆盖 @user）→ P2 必须 merge
  后过同款校验器，过不了降级冲突卡。MVP 风险低（手机端=人类作者，改不动"AI 不可覆盖人"）。

### 同步 Tasks

- [x] **P0a 文件名 canonical**（6.15）— iso ↔ 26.6.15(第44天) 双向映射；dayNum 按日历天锚
  5.3=第1天（实测对齐 41/42/44）；capPath 写盘 iso→stem、keys 读盘 stem→iso，内部 iso 契约
  不变；LocalBackend(浏览器)不受影响。模拟器清装验：磁盘 canonical 文件名 + UI 透明无回归。
- [x] **P0b 补剂+八杯水内嵌当天 md**（6.15）— 弃独立 daily-tasks.md，补剂段收进 md 顶部
  '# 每日补剂打卡'（桌面同源：喝水8+鱼油Swisse+肌酸+苏糖酸镁+D3K2+南非醉茄）；八杯水接喝水
  8 子杯真持久化（原纯本地态）。timeline 解析天然忽略首块前补剂段。浏览器整链路验 + 设备端
  补剂段 diff 桌面**零差异**。
- [ ] **P1 单向拉取**（只读真相）— 桌面配 LAN git 远端 + push；手机 isomorphic-git clone/pull
  真 vault 替掉 seed。只读、零合并、不可能丢数据。
- [ ] **P2 双向 git merge** — 手机本地 commit → pull(3-way) → push；块级冲突卡 + merge 后
  authorship 复核。
- [ ] **P3 chat/二进制/打磨** — thread 转 append-only JSONL 按 msg-id union；抠图进 attachments；
  同步状态条；前后台自动触发。
