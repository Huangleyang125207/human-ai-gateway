# human-ai-schedule · INDEX

> 本项目散落在 platform 各处，本页是地图。

## 入口（按用途）

| 我想要... | 去哪 |
|---|---|
| 看今天写了啥 | `数据库/valut/半小时复盘/26.5.X(第N天).md` |
| 看某项目历史 | `数据库/valut/标签聚合.md` |
| 看项目氛围 | `数据库/valut/PULSE/` 或各项目根 `PULSE.md` |
| 浏览器看今日总览 | `gateway/index.html` |
| 浏览器看单日完整 entries | `gateway/day.html` |
| 加一个 widget | 跟 AI 说"加 X widget" → 触发 `gateway-extension` skill |
| 看 widget 怎么写 | [`gateway-extension/WIDGET_AUTHORING.md`](gateway-extension/WIDGET_AUTHORING.md) |
| 大改 viewer 视觉 | [`DESIGN_BRIEF.md`](DESIGN_BRIEF.md) → 交设计 agent |
| 改协议 / skill | `~/cltrc+v code/skills/human-ai-schedule/`（外部 repo） |
| 改时间戳 hook | `~/cltrc+v code/scripts/timeblock-stamp.sh` |
| 改 drift 检测 | `~/cltrc+v code/scripts/schedule-drift-check.sh` |
| 改 PULSE 镜像同步 | `scripts/sync-pulse-to-vault.sh`（本 platform） |
| 改日记模板顶部 | `~/.claude/skills/human-ai-schedule/templates/SCHEDULE_TEMPLATE.md` |
| 新建一天的骨架 | `bash scripts/new-day.sh [YYYY-MM-DD]` |

## 文件总览

```
agents创作平台/
├── agents/human-ai-schedule/      ← 你在这（meta + brief + pulse）
│   ├── CLAUDE.md                  项目规则 + tag vocabulary
│   ├── PULSE.md                   项目氛围快照
│   ├── DESIGN_BRIEF.md            viewer 设计 brief（v0.X 版本记录）
│   └── INDEX.md                   本文件
│
├── 数据库/valut/                  ← 数据本体（Obsidian vault）
│   ├── 半小时复盘/*.md            每日日记
│   ├── 标签聚合.md                项目维度横切
│   └── PULSE/                     PULSE 镜像（自动同步，不要手编）
│
├── gateway/                        ← HTML 实现
│   └── day.html                   v0.2 私印小报风
│
├── scripts/                       ← 本 platform 脚本
│   ├── new-day.sh                 新一天骨架
│   └── sync-pulse-to-vault.sh     PULSE 单向镜像（Stop hook）
│
└── PULSE.md                       平台 meta PULSE（聚 4 项目地图）

外部依赖（不在本 platform 内）：
~/cltrc+v code/                    ctrl-c-v-code-skills repo
├── skills/human-ai-schedule/      skill 源
├── scripts/timeblock-stamp.sh     UserPromptSubmit hook
└── scripts/schedule-drift-check.sh Stop hook

~/.claude/                         运行时
├── skills/human-ai-schedule/      sync-runtime 部署的副本
├── scripts/                       Stop / UserPromptSubmit hook 实际位置
└── settings.json                  hook 注册
```

## 改动应该改哪里

| 类型 | 改这里 | 注意 |
|---|---|---|
| skill 协议 / playbook | ctrl-c-v repo → push → cccv-sync | 改 runtime 副本会下次 sync 被覆盖 |
| viewer 视觉 | `gateway/day.html` 或 brief → agent | brief 改完先存进版本记录 |
| 模板 top section | runtime 模板（个人偏好）或 repo 模板（对外） | 看是否要分发 |
| hook 行为 | repo `scripts/` | sync-runtime 部署 |
| 标签 vocabulary | 本文件夹 `CLAUDE.md` | 注册新 project tag 才进聚合页 |
| 项目 PULSE 内容 | 各项目根 `PULSE.md`（不是 vault 镜像！） | 镜像会被下轮覆盖 |
