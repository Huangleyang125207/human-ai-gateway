---
name: gateway-extension
description: |
  Extension protocol for the personal gateway HTML viewer at `agents创作平台/gateway/`.
  Use this skill whenever the user wants to add, remove, or customize a daily-view
  widget — checklist, tracker, sparkline, picker, mood indicator, anything sitting
  in the sidebar or top strip. The gateway is intentionally a harness; the actual
  widget set is per-user and evolves through conversation.

  TRIGGER when:
  - user says "加一个 X widget" / "我想追踪 X" / "把 Y 装进 gateway"
  - user dictates a recurring metric they want to see daily (water intake, books
    read, gym sets, social interactions, sleep, weather, etc.)
  - user references the daily view and asks to extend it
  - user says "怎么扩展 gateway" / "怎么加 widget" / "module 商店"

  SKIP when:
  - user is editing actual diary prose (that's human-ai-schedule core)
  - user is changing the global aesthetic (that's DESIGN_BRIEF.md)
  - user is doing pure coding outside the gateway

  Examples that trigger: "把喝水量加上去", "加一个心情 widget", "怎么扩展这个 gateway",
  "我想看每天读了多少书", "module store 怎么用".
  Examples that skip: "把今天 11 点那段补完", "viewer 颜色换 sage 风", "重构 fetcher".
---

# Gateway Extension Protocol

You are extending a personal gateway (HTML viewer for a markdown-based diary
system) by adding small widgets. Each widget is copy-paste-friendly: pick the
closest reference, adapt minimally, register, done.

## Where things live

```
agents创作平台/gateway/
├── index.html                 总览页（widget slots: top-strip, sidebar）
├── day.html                   单日页（v0.2 monolith, 暂未 widget-ized）
├── shared/
│   ├── style.css              共享 CSS + CSS vars（颜色、字体、留白）
│   └── widget-loader.js       动态加载 .user-widgets.json 里的 active widgets
├── widgets/
│   ├── supplements/           ← reference: checklist 类型
│   ├── steps/                 ← reference: 数值 + sparkline 类型
│   └── mood/                  ← reference: enum + 颜色映射类型
└── .user-widgets.json         {"active": [<widget names>]}
```

## Adding a new widget — copy-paste-adapt workflow

### Step 1: Pick the closest reference

| Need | Copy from |
|------|-----------|
| 几个 checkbox 勾选 | `widgets/supplements/` |
| 一个数字 + sparkline | `widgets/steps/` |
| 几档枚举 + 颜色 | `widgets/mood/` |
| 长进度条（streak / progress） | 改 supplements 的 streak 部分 |
| 时间轴 / 时刻表 | 还没有 reference，告诉用户"这是第一个，需要新建 ref" |

### Step 2: Make a new folder

```bash
mkdir agents创作平台/gateway/widgets/<new-name>/
```

Filenames（每个 widget 必须有这 3 文件）：

```
widgets/<new-name>/
├── manifest.json       元信息：name / title / slot / data_source / writeback 计划
├── widget.html         <style> 内联 scoped 样式 + 视觉 DOM
└── widget.js           交互（toggle / pick / fetch / render）
```

See `WIDGET_AUTHORING.md` for the file structure detail.

### Step 3: Stay visually coherent

Don't introduce new colors, fonts, or shadow effects. Use the CSS vars in
`shared/style.css`：

```
--paper, --ink, --ink-soft, --ink-whisper, --rule
--vermillion (accent — 朱砂红，少用)
--moss, --amber (PULSE 状态色，更少用)
```

See `STYLE_GUIDE.md` for the visual rules.

### Step 4: Register the widget

Append to `.user-widgets.json`：

```json
{
  "active": ["supplements", "steps", "mood", "<new-name>"]
}
```

Reload the page → widget appears in its declared slot.

### Step 5: Tell the user

Toast or a single line：

> "已加 <widget title> 到 <slot>。reload 浏览器看效果。"

Don't run unnecessary git commits. Don't restart anything. The page just reads
the JSON on next load.

## Hard rules (do not break)

1. NO card containers anywhere (no box-shadow, no rounded corners > 4px)
2. Use existing CSS vars; do NOT introduce new colors without explicit user request
3. Widget files MUST be self-contained — no external script imports beyond what's in `shared/`
4. MD is canonical — widgets are READ-ONLY in v0.3 (writeback comes v0.5)
5. If the user's request doesn't match any reference type, ASK before inventing a new pattern
6. Don't touch `day.html` (it's the legacy v0.2 monolith; will be refactored separately)

## What to read next

- `WIDGET_AUTHORING.md` — file structure + manifest schema + checklist
- `STYLE_GUIDE.md` — visual coherence rules
- `MD_PARSING_PATTERNS.md` — how to extract data from MD（when ready for live data，v0.4）

After writing the widget, report in 50 words:
(1) which reference you copied from, (2) what you adapted, (3) whether you
needed a new pattern (red flag — ask user first if so).
