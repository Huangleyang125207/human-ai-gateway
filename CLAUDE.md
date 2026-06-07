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
      tauri.conf.json endpoints 双轨 (HTTPS CDN 优先 + HTTP yanpai 兜底);yanpai latest.json 二进制 url 字段改 https 让现役 v0.1.16-22 也走 CDN
- [ ] v0.1.24+: 关 dangerousInsecureTransportProtocol + 只留 HTTPS endpoint(等 CDN 稳定 1-2 周后)
- [ ] keyring (3 平台,2-3 天) — 留 v0.1.24+
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
- 不要在 tauri.conf.json 改 updater endpoint 为 HTTPS 之前没确认 `https://feedback.{domain}/updates/latest.json` 在 yanpai 是 200(否则所有自动更新链断)
- 不要在客户端 silent-failure 后做"假装写本地兜底再回灌"——撤回 consent 之后本地也不写(v0.1.20 C-#4)
