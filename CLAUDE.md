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

- [ ] (next)

更新这个 list 每次 commit 后。

---

## Do not(gateway 本地补充 — 跟 PULSE 红线不重复)

- 不要在 gateway/ 加 `npm` / `build` 依赖(纯 vanilla JS + python single-file)
- 不要把数据写进 gateway/ 子树(走 APP_STATE_DIR / VAULT_DIR)
- 不要在 `--add-data` 漏新 .html / .py 时还 ship DMG(test-bundle 会抓但别赌)
