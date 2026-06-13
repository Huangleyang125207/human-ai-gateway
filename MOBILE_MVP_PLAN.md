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
- [ ] P0-1 Capacitor 工程脚手架（package.json + capacitor.config，webDir 指向前端）
- [ ] P1-5 存储后端换 @capacitor/filesystem（真机持久到文件，非 localStorage）
- [ ] P2-1 /api/chat → DeepSeek 直连（原生 HTTP 桥绕 CORS）+ 极简设置页填 key（现为 SSE stub）
- [ ] P3 窄屏 CSS 收口（thread 对话流抽屉的 touch / 字号 / 留白）
- [ ] P4 双端打包（iOS 走已有 Apple 签名；Android 签 APK）

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
