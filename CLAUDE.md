# gateway · human-ai-schedule 项目 viewer

> 代码 + 项目大脑(meta/brief/发版/皮肤工作流)现在同仓在 docs/。
> 只有 PULSE 真源 + vault 日记数据还在外部(runtime 耦合),session 进来把它俩拉过来。

---

## 项目 context(强制 pre-load,别动)

@./docs/PROJECT.md
@/Users/claudecodedezhuanshumac/agents创作平台/agents/human-ai-schedule/PULSE.md

---

## 这里是什么

`~/human-ai-dev/gateway/` = viewer / server / UI 的代码本体 + `docs/` 项目大脑。
- **项目大脑**(7.6 搬入)→ `docs/`(PROJECT.md meta · DESIGN_BRIEF · RELEASE_TEMPLATE · SKIN_WORKFLOW · USER_PULSE · INDEX · brand/spread/gateway-extension)
- **PULSE 真源** → `~/agents创作平台/agents/human-ai-schedule/PULSE.md`(runtime 耦合 sync/cron,未搬)
- **日记 / 聚合数据** → `~/.human-ai/vault/`(真源;`agents创作平台/数据库/valut` 是 5 月冻结镜像勿用)
- **移动端测试网** → `mobile/parity/`(109 golden oracle,别写即时脚本用固化)

> **加新前端皮肤(page-family skin,复用引擎只换皮)→ 看一眼就会做:**
> `docs/SKIN_WORKFLOW.md`
> 参考实物:`*-paper.html` + `shared/{theme,*-paper}.{js,css}`(纸与灯皮肤,6.13 落地)

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

## References(路由表 — 从 gateway cwd 进来先看这)

> 从 gateway/ 开 session 路由不到 agents创作平台/CLAUDE.md,所以在这自带一张。「我想干 X → 去哪」。

| 我想要... | 去哪 |
|---|---|
| 项目 meta / context(强制 pre-load) | [`docs/PROJECT.md`](docs/PROJECT.md) |
| 大改 viewer 视觉 → 交设计 agent | [`docs/DESIGN_BRIEF.md`](docs/DESIGN_BRIEF.md) |
| 发版流程 / release 模板 | [`docs/RELEASE_TEMPLATE.md`](docs/RELEASE_TEMPLATE.md) |
| 加新前端皮肤(复用引擎只换皮) | [`docs/SKIN_WORKFLOW.md`](docs/SKIN_WORKFLOW.md) |
| 用户视角的 PULSE / 定位 | [`docs/USER_PULSE.md`](docs/USER_PULSE.md) |
| 项目大脑地图(散落各处的总索引) | [`docs/INDEX.md`](docs/INDEX.md) |
| 品牌 logo / preview | [`docs/brand/`](docs/brand/) |
| 运营(小红书手册 / 云厂商外联) | [`docs/spread/`](docs/spread/) |
| 加一个 widget / widget 怎么写 | [`docs/gateway-extension/`](docs/gateway-extension/)(SKILL.md · WIDGET_AUTHORING.md) |
| **改移动端前端 → 别写即时脚本,跑固化测试网** | [`mobile/parity/`](mobile/parity/)(109 golden oracle;`run.mjs` / `harness.mjs` / `check-fe-be.sh`) |
| 移动端交互 E2E 规格(日记/拍照/剪贴簿/标签) | `mobile/INTERACTION_E2E_*.md` |
| 移动端 Android 构建 / OCR native | [`mobile/ANDROID_BUILD.md`](mobile/ANDROID_BUILD.md) · `mobile/OCR_NATIVE_PLAN.md` |
| parity 方法论(前后端一致性 TDD) | [`WEBVIEW-PARITY-TDD.md`](WEBVIEW-PARITY-TDD.md) · `mobile/PARITY_LOOP.md` |
| 桌面自更新 / SSL / 待办 backlog | [`INTERNAL_TEST_BACKLOG.md`](INTERNAL_TEST_BACKLOG.md) |
| 子 agent 编排 / briefing | [`AGENT_BRIEFING_TEMPLATE.md`](AGENT_BRIEFING_TEMPLATE.md) · [`AGENT_ORCHESTRATION_PATTERNS.md`](AGENT_ORCHESTRATION_PATTERNS.md) |
| PULSE 真源(外部,runtime 耦合勿搬) | `~/agents创作平台/agents/human-ai-schedule/PULSE.md` |
| 日记 / 标签聚合数据真源 | `~/.human-ai/vault/`(勿写;`agents创作平台/数据库/valut` 是 5 月冻结镜像勿用) |

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
- [⏳] v0.1.25: ②updater UX 可视化 + 弹性 MD 迁移 = **代码完成**(T-A..T-G 全 7 个子任务，T1-T5 全绿，132/133 总 + 1 pre-existing 与本次无关)。等手 dmg 装 + 真测自更新跳通 + ship v0.1.26 验新 UI 路径。①SSL update.yanpaidb.cn 直 A + Caddy + LE / ③关 dangerousInsecureTransportProtocol / ④yanpai :18080 HTTP fallback 仍待
- [ ] keyring (3 平台,2-3 天) — 留 v0.1.26+
- [ ] P4 服务端 deploy:feedback-sink 改动 + Caddy snippet 上 yanpai
      (ssh 命令在 [INTERNAL_TEST_BACKLOG.md](INTERNAL_TEST_BACKLOG.md) P4 段)

更新这个 list 每次 commit 后。

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
