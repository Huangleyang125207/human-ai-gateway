# WebView Parity TDD — "浏览器跑得通、进了壳就坏" 回归清单

> **为什么有这份文件**：gateway 前端在 Chrome 里开发,但发布是套进 Tauri 壳跑在
> 系统 webview 里。两者**不是同一个运行时**——webview 渲染/网络/原生交互都可能跟
> Chrome 分歧。每分歧一个 bug,而且**多半静默**(不报错,功能就是没了)。
>
> 跨平台移植时这类 bug 会**逐平台重现**(每个平台一个不同 webview),所以这里把已撞到的
> 攒成一份 **TDD 回归清单**:移植到新平台前,先把这些 case 写成 RED 测试跑一遍。
>
> 创建:2026-05-27(撞了 float/CDN + drag-drop 两连击之后)· 葱鸭 × claude-opus-4.7

---

## 三种 webview(移植矩阵的列)

| 平台 | webview 引擎 | 网络栈 | 跟 Chrome 的关系 |
|------|--------------|--------|------------------|
| **macOS** | WKWebView | 系统 (Secure Transport) | WebKit,非 Chromium —— CSS/JS/网络都可能分歧 |
| **Windows** | WebView2 | 系统 (WinHTTP) | **Chromium 内核** —— 渲染最接近 Chrome,但原生交互层仍是 Tauri 的 |
| **Linux** | WebKitGTK | 系统 (libsoup) | WebKit,且版本散(distro 给的) —— 最容易踩"老 WebKit 缺 API" |

**关键直觉**:
- **渲染/JS API 分歧** 主要打 WKWebView + WebKitGTK(非 Chromium),WebView2 基本免疫。
- **网络栈分歧**(远程依赖取不到)打**所有**走系统栈的(三个都是);Chrome 自带 BoringSSL 栈,代理/拦截行为不一样,所以"Chrome 能取 ≠ webview 能取"。
- **原生交互拦截**(拖放/右键/文件选择)是 **Tauri 壳**那一层,跟引擎无关,**三个平台都要单独验**。

---

## 测试手段:用真 webview 探针,别只信 Chrome

Playwright(系统 Chrome)只能测"逻辑对不对",**测不出 webview-only 的 bug**。要复现 Tauri-only bug,得在**真 webview** 里跑断言:

- **macOS**:`swiftc` 写个极简 WKWebView,load `http://127.0.0.1:<port>/`,`evaluateJavaScript` 跑断言。WKWebView 跟 Tauri 同款引擎,A/B 一目了然。模板见本仓 git 历史里 5.27 用过的探针(`typeof window.pretext` A/B)。
- **Windows**:WebView2 的 `CoreWebView2.ExecuteScriptAsync`(C#/PowerShell)同理。
- **Linux**:`webkit2gtk` 的 `webkit_web_view_evaluate_javascript`(C/Python-gi)。

> 原则:**每条 case 的 GREEN 判据必须能在真 webview 里跑出来**,不是"Chrome 里过了就算"。

---

## 已知 case(移植前逐条写 RED)

### CASE-1 · 远程 CDN 依赖在 webview 静默失效

- **症状**:某功能依赖一个从 CDN(esm.sh/unpkg/jsdelivr)`import` 的库;Chrome 里好,壳里那功能整个不工作、无报错。(5.27:文字绕图引擎 pretext 从 esm.sh import → `window.pretext` undefined → 绕排从不运行。)
- **根因**:webview 走系统网络栈,被本机代理(Clash 等)的 TLS 拦截掐断;Chrome 自带网络栈恰好能穿。
- **影响平台**:WKWebView(mac)+ WebKitGTK(linux)高危;WebView2(win)走系统栈也可能中招(看代理配置)。
- **RED 测试**:
  - 静态:`grep -rE "https?://[^\"']+\.(js|mjs)|esm\.sh|unpkg|jsdelivr|cdn\." index.html shared/` → **必须零命中**(注释除外)。这条能在 CI 纯文本跑,最省。
  - 运行时:真 webview 里断言 `typeof window.<lib> === 'object'`(对 gateway 是 `window.pretext`)。
- **FIX(已落)**:把库 dist 收进 `vendor/`,改本地相对路径 import。**铁律:gateway 前端零远程 CDN 依赖,全本地 vendor。** 见 `vendor/pretext/` + `vendor/marked.min.js` + `vendor/dompurify.min.js`。
- **GREEN**:断网/挂代理都能用;真 webview 里 `window.pretext` 是 object,3 个 API(prepareWithSegments/layoutNextLineRange/materializeLineRange)在。

### CASE-2 · Tauri 原生拖放拦截吞掉 HTML5 drop

- **症状**:拖文件进窗口没反应;Chrome 里 dragover/drop 正常。(5.27:thread.js 的拖图上传在壳里失灵。)
- **根因**:Tauri 默认在 webview 注册原生拖放处理器,把 OS 文件 drop 截走、emit `tauri://drag-drop` 事件,**不转发给网页**,所以 HTML5 `drop` 永不触发。
- **影响平台**:**三个都中**(这是 Tauri 壳层,非引擎)。Tauri 官方 doc 明说 Windows 必须禁;mac/linux 同理(wry 源码:handler 返 false 才 `super` 走原生 HTML5)。
- **RED 测试**:
  - 静态:`grep "disable_drag_drop_handler" src-tauri/src/lib.rs` → 建窗链里**必须有**。
  - 手动(暂无法脚本模拟 OS drop):真 webview 里拖一张图 → 侧栏弹开 + dropzone 高亮 + 上传成功。
- **FIX(已落)**:`WebviewWindowBuilder` 链加 `.disable_drag_drop_handler()` → Tauri 传 `None` → wry 装 `|_| false` → 每个拖放事件落到 webview HTML5。**前端零改、不碰 JS 桥**。
- **GREEN**:壳里拖图 = 浏览器里拖图,行为一致。

### CASE-3 · 原生 JS 弹窗(confirm/alert/prompt)在 webview no-op

- **症状**:依赖 `confirm()` 的删除/确认全失灵(点删除没反应);`prompt()` 拿不到输入;`alert()` 不弹。(5.27:照片删不掉 —— `if(!confirm(...))return;` 里 confirm 返 false → 删除分支永不跑。)
- **根因**:嵌入式 webview 默认**抑制**原生 JS 对话框。`confirm()` 直接返回 false,`prompt()` 返回 null,`alert()` 静默。
- **影响平台**:**三个都中**(壳层默认行为)。
- **RED 测试**:
  - 静态:`grep -rE "[^.](confirm|alert|prompt)\s*\(" shared/ index.html` → 除注释外**零命中**(全走 gatewayConfirm/Prompt/Alert)。
  - 运行时:真 webview 里 `typeof gatewayConfirm==='function'` + 触发一次 confirm 流断言 resolve。
- **FIX(已落)**:`shared/dialog.js` 自画页内弹窗(promise 版),替换全部 native 调用。**铁律:不依赖 webview 原生对话框,自己画。**
- **附带 UX 升级**:删除类不做确认、改做**撤回**(`gatewayUndo`)——乐观隐藏 + 真删推迟到撤回窗口过后才发。点完即走、误删可救、零摩擦,且'没撤回前没真删'省掉所有恢复逻辑。
- **GREEN**:真 webview 里删/确认/输入都弹得出、走得通;删除有 5s 撤回。

### CASE-4 · webview 缓存 API 响应 → 内容不刷新

- **症状**:人/AI 写完,页面不显示最新;轮询在跑也没用。(5.27:留言板/journal 最新内容不刷新,浏览器按 Cmd+R 能救、壳里没 Cmd+R。)
- **根因**:webview 走系统网络栈,会缓存 `GET /api/*` 响应;若 server 没发 no-store,轮询每次命中缓存拿旧数据。
- **影响平台**:**三个都可能**(取决于各栈缓存策略)。
- **RED 测试**:
  - 静态:server 中间件给 `/api/*` 设 `Cache-Control: no-store`。
  - 运行时:`curl -D- /api/<某 GET>` 头里有 `no-store`;或真 webview 里隔窗口写一条 → 轮询周期内出现。
- **FIX(已落)**:no-cache 中间件覆盖范围加 `/api/*`(原只 .html/.js/.css)。
- **GREEN**:写入后 3-15s 轮询自动显示最新,无需手动刷新。

### CASE-N · _模板(撞到新的就照这个加)_

- **症状**:_Chrome 好 / 壳坏的具体表现_
- **根因**:_引擎分歧 / 网络栈 / 原生拦截 哪一类_
- **影响平台**:_WKWebView / WebView2 / WebKitGTK_
- **RED 测试**:_静态 grep + 真 webview 运行时断言_
- **FIX**:_守铁律(壳侧配置 / 本地 vendor,前端零改、不碰 JS 桥)_
- **GREEN**:_真 webview 判据_

---

## 移植到 Win / Linux 前,重点预排的分歧(还没撞,先挂着)

- **Intl.Segmenter**(pretext 绕图依赖):WebKitGTK 老版本可能没有 → 绕图崩。移植 linux 先在真 WebKitGTK 验 `typeof Intl.Segmenter`。
- **`caretRangeFromPoint` / `caretPositionFromPoint`**(绕图点击落 caret):各 webview 支持的是哪个 API 不一,代码已双分支兜底,移植时验两条都走得通。
- **CSS `backdrop-filter`**(右键菜单/lightbox 毛玻璃):老 WebKitGTK 可能不支持 → 退化成不透明,验视觉。
- **文件选择 `<input type=file>` accept / 多选**:各平台原生选择器行为差。
- **流式 fetch(SSE / chunked)**:thread streaming 在不同 webview 的 buffer 行为,验"字一个一个弹"不被整段缓冲。
- **localStorage 配额 / 持久化**:webview 清缓存策略不同,验 thread mtime / MTIME_KEY 跨重启还在。

每条移植时验到了 → 升级成 CASE-N 写进上面。

---

## 跟其他文档的关系

- 装机/onboarding 冒烟(干净机器首装跑通)→ `MIGRATION-TEST.md`(不同关注点)。
- 跨平台**发版/签名**矩阵 → `agents/human-ai-schedule/RELEASE_TEMPLATE.md`。
- 本文件只管**运行时 webview 行为分歧**的 TDD。
