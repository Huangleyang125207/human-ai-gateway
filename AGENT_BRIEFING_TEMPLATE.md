# 子 agent briefing schema

> 每个 bug 修复 spawn 一个 subagent 时，传给它的 prompt 走这个模板。
> 目的：subagent 没有本对话上下文，必须自带"足够 do 一件事"的所有信息。

---

## 模板字段

```
## Goal (1 sentence)
[要修什么 bug + 修完什么效果。例:让 _save_outcomes 走 atomic write,中途崩不丢 DPO 指针。]

## Files in scope
- 主要文件 [path:line-range]
- 辅助文件 [path:line-range]

## Existing patterns to copy
- _safe_write_text 在 [server.py:209];已有 11+ 处 caller 示例
- _save_config 在 [server.py:273];helper 包装 atomic + rotate + chmod 模板
- _get_evolve_lock / _get_vault_md_lock 在 [server.py:6811/6837];锁 + sha256 guard 模板

## PULSE Cannot break
- [从 PULSE.md "Cannot break" 段抄相关条;不超过 3 条]
- 例: vault_git.commit_after_write 任何 schedule / aggregate / PULSE-mirror 写入必经
- 例: silent-failure 通道 fire-and-forget 自身永不 raise

## Authorship / safety boundaries
- AI 不能字节级覆盖 @user 块(8 层 + pytest 守门)
- patch_journal_block H2 mismatch guard 必须保留
- silent-failure context 走 _sanitize_sf_context 白名单(不能 bypass)

## Steps
1. Read 主要文件 [line-range] 理解现状
2. [具体改法]
3. python3 -c "import ast; ast.parse(open(...).read()); print('OK')" 语法检查
4. (可选)运行相关 pytest

## Verify
- [手动验证方法,例:启动 server, 触发 endpoint, 看 silent-failure 通道有信号]
- [自动验证方法,例:pytest tests/test_xxx.py::test_yyy]

## Commit
- 不 commit;统一 driver(本对话)收集 diff 后批量 commit + tag bump
- 仅返回 patch summary:改了哪些文件/行 + 为什么这样修

## Don't
- 不改 markdown 渲染分支(全走 window.gatewayMd)
- 不加 build / server / npm 依赖
- 不动 frozen-start..frozen-end 段
- 不在没说"记一下"时往日记里写
- 不改 .env / minisign / yanpai admin key
```

---

## Parallel safe vs serial

| Group | 内容 | 安全度 |
|---|---|---|
| **PARALLEL** 各改各文件 | A-H1 scrapbook/attachments_index/curator;A-H7 history_exporter;A-H8 outcome_tracker;A-H9 widgets;A-M3 HB+SF cursor;A-M4 PULSE mirror | 独立文件,无 server.py 大量改动,可同时 |
| **PARALLEL** Rust + Python 两侧 | A-H4 updater-pending 双侧改 | Rust .lib.rs + Python server.py 互不撞 |
| **SERIAL** server.py silent-failure 同区改动 | A-H5 / A-H6+H11 / C-#4 consent gate | 都改 _report_silent_failure / drain 附近,逐条来 |
| **SERIAL** vault_git daemon | A-H13 单独 agent | 涉及 daemon 错误处理 + 前端反馈链路 |
| **SERIAL** updater HTTPS | C-#2/#8 | Caddy + Tauri 配置 + manifest URL,环节多 |
| **SERIAL** keyring | C-#3+ | 3 平台分支,手动验证多 |

---

## driver(主对话)责任

1. 维护 [INTERNAL_TEST_BACKLOG.md](INTERNAL_TEST_BACKLOG.md) 状态
2. 收集 subagent diff,统一 syntax check
3. 决定哪些一起 commit (按修法相关性)
4. 跟 [CLAUDE.md](CLAUDE.md) / [PULSE.md](agents/human-ai-schedule/PULSE.md) 同步关键状态
5. Bump 版本 + 触发 CI + ship

---

## MD 同步清单(每个 commit batch 后做)

- [ ] [INTERNAL_TEST_BACKLOG.md](INTERNAL_TEST_BACKLOG.md) 勾对应行 + 注脚版本号
- [ ] gateway 根 [CLAUDE.md](CLAUDE.md) Progress 段加一行
- [ ] [agents/human-ai-schedule/PULSE.md](../../agents创作平台/agents/human-ai-schedule/PULSE.md) Cannot break 段如果有新红线 → 加;Can play 段如果项目状态变 → 改
- [ ] [agents/human-ai-schedule/CLAUDE.md](../../agents创作平台/agents/human-ai-schedule/CLAUDE.md) 待办段勾掉
- [ ] (重要架构变更)[README.md](README.md) Architecture 段 / [PRIVACY.md](PRIVACY.md) 数据收集段
