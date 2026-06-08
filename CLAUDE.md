# gateway · human-ai-schedule 项目 viewer

> 代码在这,但项目定义 + PULSE + 数据约定全在 agents创作平台 那边。
> session 进 gateway/ 时强制把项目 context 拉过来,防孤儿。

---

## 项目 context(强制 pre-load,别动)

@/Users/claudecodedezhuanshumac/agents创作平台/agents/human-ai-schedule/CLAUDE.md
@/Users/claudecodedezhuanshumac/agents创作平台/agents/human-ai-schedule/PULSE.md

---

## 这里是什么

`~/human-ai-dev/gateway/` = viewer / server / UI 的代码本体。
所有数据(日记 / 聚合 / PULSE 真源 / 设计 brief)在 `~/agents创作平台/`。

```
gateway/                ← 本目录
├── server.py
├── shared/             ← JS modules
├── widgets/
├── index.html · history.html · consent.html
├── history_exporter.py · outcome_tracker.py · vault_git.py
├── build-mac-pyinstaller.sh · release.sh
└── tests/
```

数据存哪 / 加载链路 / git auto-commit / consent 配置 — 看上方 @-load 的 human-ai-schedule CLAUDE.md + PULSE.md。

---

## Local progress(gateway 自己)

- [x] v0.1.20: 三轮 ultracode review 出的 P1+P2 22 条全部收口
      (atomic writes / writeguard 加 lock+fsync / silent-failure consent gate /
       /forget + X-Admin-Token / thread-history corrupt-recovery modal /
       vault_git index.lock 探测 + 连续失败通知;详 [INTERNAL_TEST_BACKLOG.md](INTERNAL_TEST_BACKLOG.md))
- [x] v0.1.21: B 补录 3 件 high(token cache 写错 key / vision config missing return / schema migration 接 silent-failure 通道)
- [x] v0.1.22: B 补录收尾 3 件(BaiduOCRError raise 不静默 + sink 4xx cursor 分桶 + ocr.py/cutout.py 上报针脚)
- [x] 沉淀子 agent 编排框架:[AGENT_BRIEFING_TEMPLATE.md](AGENT_BRIEFING_TEMPLATE.md) + [AGENT_ORCHESTRATION_PATTERNS.md](AGENT_ORCHESTRATION_PATTERNS.md)
- [x] v0.1.23 部分收 C-#2/#8 updater HTTPS:腾讯云 CDN cdn.yanpaidb.cn 接入(下载大文件 + LE 证书 + latest.json 不缓存规则)
      tauri.conf.json endpoints 双轨 (HTTPS CDN 优先 + HTTP yanpai 兜底);yanpai latest.json 二进制 url 字段改 http://cdn.yanpaidb.cn 让现役 v0.1.16-22 也走 CDN
- [x] v0.1.24: trivial version bump(为了真测 v0.1.23→v0.1.24 自更新触发)。commit + tag + CI + publish Latest 全完;**yanpai sync 卡住**因 VPN 当天抽风,二进制从 GitHub Release 国内拉一直截到 3.3M(正常 151M)
- [⚠️] **SSL HTTPS 死锁** — cdn.yanpaidb.cn 是 CDN 接入的 CNAME → `_dnsauth.cdn.yanpaidb.cn` 因 DNS CNAME exclusivity 永远 NXDOMAIN → 腾讯 TrustAsia DV 探针查不到 → 验证永远 stuck。解法:**v0.1.25 换 update.yanpaidb.cn 直 A 记录指 yanpai box + Caddy + LE**(绕开 CDN CNAME 死锁路径,自管 SSL)
- [⚠️] **自更新 UX 不对** — 现 v0.1.23 实际行为:5s 后 silent download_and_install 不问用户、不显进度、装完才弹 banner"重启生效"。要改:**v0.1.25 加询问 modal(检测到新版"现在更新? / 稍后 / 跳过") + 实时进度条**(详 [INTERNAL_TEST_BACKLOG.md](INTERNAL_TEST_BACKLOG.md))
- [ ] v0.1.25+: 同时收 ①update.yanpaidb.cn 直 A + Caddy + LE 启 HTTPS、②updater UX 询问+进度、③关 dangerousInsecureTransportProtocol、④保留 yanpai box :18080 作 HTTP fallback
- [ ] keyring (3 平台,2-3 天) — 留 v0.1.26+
- [ ] P4 服务端 deploy:feedback-sink 改动 + Caddy snippet 上 yanpai
      (ssh 命令在 [INTERNAL_TEST_BACKLOG.md](INTERNAL_TEST_BACKLOG.md) P4 段)

更新这个 list 每次 commit 后。

---

## Active spec — v0.1.25 updater 可视化 + 弹性 MD 迁移

> LARGE 任务，正在执行；提交完所有 T-A..T-G 后删掉这段。
> 上手前必读 PULSE.md "Cannot break"，特别是 silent-failure 反馈通道 + vault md sha256 baseline 不能被 MD 迁移绕过。

### What

把现行 silent updater 替换成「3 步 timeline banner」：
- Step 1 下载（Tauri 进度透传 → 前端进度条）
- Step 2 安装（Tauri 信号 → 显"安装完成，点击重启"）
- Step 3 重启后 MD 迁移（新版 sidecar 调 LLM，根据现实需求决定迁移范围，全自动、user 只看进度）

UI 装在 gateway HTML 顶部 banner，可收起成右上角圆点。LLM 走百炼 deepseek-v4（单 API 入口）。
done = v0.1.25 dmg 手装一次后，从 v0.1.25 升 v0.1.26 时三步 banner 全跑通 + 任意 MD 模板变化能自动迁移。

### Plan

| 文件 | 改什么 |
|---|---|
| `src-tauri/src/lib.rs` | `download_and_install` 进度 callback 装真，emit `updater://progress` Tauri events（chunk/total + step 标记） |
| `shared/update-banner.js` | 拓展成 3-step timeline + 收起态；listen Tauri events + SSE；render 当前 step + 进度 |
| `server.py` | sidecar startup hook 加 MD 迁移协程；`/api/migration/stream` SSE endpoint；`.last-migrated-version` 读写 |
| 新 `migration_plan.py`（或 server.py helper 段） | LLM 调用：① classify＋diff round 出 plan；② per-file 重写；user 内容保留 + 新结构 merge |
| `Contents/Resources/templates/`（构建侧） | binary bundle 自带 canonical templates；sidecar 用 `sys._MEIPASS / "templates"` 读 |
| `tauri.conf.json` | 不动 |

迁移失败兜底：每个被改 MD 留 `<file>.bak.before-v0.1.x`，错的跳，banner 显 "Step 3 部分失败"。LLM 5xx / 网断 → 同样跳 + 兜底。

### Known gap

v0.1.23 当前用户没法靠新 UI 拉 v0.1.25（接收的还是 silent updater）→ v0.1.25 首发走手动 dmg；v0.1.25 → v0.1.26 之后链路才走新 UI。

### Test plan

- [ ] T1 boundary：Tauri chunk callback 触发 emit → 前端能 listen 到事件
- [ ] T2 contract：sidecar `.last-migrated-version == APP_VERSION` 时迁移协程立即 return（idempotent）
- [ ] T3 effect：fake `templates/` + fake vault MD → LLM 返 plan → 真按 plan 重写 + 留 .bak
- [ ] T4 effect：LLM 5xx → user MD 保持原样 + .bak 不丢 + banner Step 3 显警告
- [ ] T5 effect：sidecar 启动时迁移协程在 background task 跑，不阻塞 `/` 路由

### Tasks

- [x] T-A SMALL: `lib.rs` chunk callback emit Tauri event（5 个 step：found/download/install/ready_restart/error；cargo check 通过）
- [x] T-B SMALL: `update-banner.js` timeline 骨架 + 收起态 + Step 1 渲染（listen `updater://progress` 重写整段，3 dot timeline + 进度条 + 收起到 24px 顶条；node --check 通过；visual smoke 推迟到 v0.1.25 build）
- [x] T-C MEDIUM: sidecar `/api/migration/stream` SSE 通道（log buffer + 多 client broadcast + replay；`push_migration_event` 入口给 T-D 用；`.last-migrated-version` 读写延后到 T-D 一起做）+ 31 existing tests 全绿无回归
- [ ] T-D MEDIUM: `migration_plan.py` LLM classify+rewrite，含 backup 兜底 → T3+T4 GREEN
- [ ] T-E MEDIUM: sidecar startup hook spawn 迁移协程 → T5 GREEN
- [ ] T-F SMALL: `update-banner.js` Step 2 + Step 3 渲染（listen SSE）
- [ ] T-G SMALL: banner 错误态 UI + 完成态收尾

### Findings

（执行中记 surprise）

---

## Do not(gateway 本地补充 — 跟 PULSE 红线不重复)

- 不要在 gateway/ 加 `npm` / `build` 依赖(纯 vanilla JS + python single-file)
- 不要把数据写进 gateway/ 子树(走 APP_STATE_DIR / VAULT_DIR)
- 不要在 `--add-data` 漏新 .html / .py 时还 ship DMG(test-bundle 会抓但别赌)
- 不要在 `_report_silent_failure` 绕过 `_sanitize_sf_context` 白名单 → 把用户原文塞 context(v0.1.19 C-#9 收口的硬合同)
- 不要在 `_report_silent_failure` 绕过 consent gate(v0.1.20 C-#4 收口:撤回期连本地都不写)
- 不要把 `_safe_write_text` 改回 `.tmp` 固定名(v0.1.20 A-H3 上了 uuid + path-keyed lock,改回去就重新撞)
- 不要去掉 fsync(fd+parent dir)(v0.1.20 A-M5:断电后 atomic rename 不保内容到盘)
- 不要让 patch_journal_block / insert_journal_block / append_comment 绕过 sha256 baseline + `_get_vault_md_lock`(v0.1.19 A-C5:Obsidian 并发会静默覆盖)
- 不要让 thread-history 读端损坏返 `[]` 后让前端直接 saveHistory(v0.1.20 A-H14:返 `status: 'corrupt'` + baks 列表,前端走 restore modal)
- 不要让 vault_git daemon 失败完全静默(v0.1.20 A-H13:连续 5 次 → push notification `vault-git-broken`;不报 = 用户审计链断了不知)
- 不要在 tauri.conf.json 改 updater endpoint 为 HTTPS 之前没确认 endpoint 在线 200(否则所有自动更新链断)
- 不要在客户端 silent-failure 后做"假装写本地兜底再回灌"——撤回 consent 之后本地也不写(v0.1.20 C-#4)
- 不要在 CDN 接入的子域(CNAME 类型)下面加 TXT/A 类记录——CNAME exclusivity 会让那些 record 永远 NXDOMAIN(v0.1.23 SSL DV 卡死的真因)
- 不要把 v0.1.x 客户端 hardcoded endpoint 当永久合同改回——v0.1.16 client 死磕 http://101.42.108.30:18080,即使 v0.1.23+ client 双 endpoint 看 CDN,yanpai box :18080 也要长期保持服务给历史客户端续命
- 不要让 updater silent download(违反"用户授权拉流量"基本契约)——v0.1.23 现状是 5s 后偷下,v0.1.25+ 必须加询问 modal + 进度条
