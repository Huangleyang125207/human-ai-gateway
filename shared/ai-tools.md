# Gateway AI Tools (v0.4)

> 给后端 DeepSeek 看的工具清单（实际 schema 在 server.py 的 TOOLS 常量里维护）。
> 本文件是给人类阅读 + AI agent 自检的对照。新增 tool 时同时更 server.py 和这里。

## 当前 3 个 tool（v0.4，widget 维度）

### 1. `list_widgets()`

枚举 `gateway/widgets/` 下所有 widget folder + 标注哪些已在 `.user-widgets.json` active。

返回：`{widgets: [{name, active}], user_widgets_file: <path>}`

何时调用：用户问"装了哪些 widget" / "有什么 widget 可用"

### 2. `add_widget(name, title, audience, slot, manifest_json, widget_html, widget_js)`

新建 widget folder 并写 3 文件 + 追加 `.user-widgets.json` active。

参数：
- `name` (string, kebab-case): 文件夹名
- `title` (string): 用户可见标题
- `audience` (string): 适合谁用（诚实说）
- `slot` ("top-strip" | "sidebar"): 挂哪个 slot
- `manifest_json` (string): 完整 manifest.json 内容
- `widget_html` (string): 完整 widget.html 含内联 `<style>`
- `widget_js` (string): 完整 widget.js（IIFE + 用 `window.gatewayToast`）

返回：`{created, active}` 或 `{error}`

何时调用：用户说"加 X widget" / "我想追踪 X" / "把 Y 装上"

注意：
- 必须遵守 STYLE_GUIDE.md 视觉规则（无卡片 / 用 CSS vars / 衬线字 / 朱砂节制）
- 必须遵守 WIDGET_AUTHORING.md 文件结构（3 文件 / scoped class / IIFE / no external imports）
- v0.4 写回都用 toast 模拟（不操作 MD），v0.5 后实装

### 3. `patch_widget(name, file, new_content)`

修改已存在 widget 的 manifest / html / js（视觉微调或行为改）。

参数：
- `name` (string): widget folder 名
- `file` ("manifest.json" | "widget.html" | "widget.js")
- `new_content` (string): **完整**新文件内容（替换式，不是 diff）

返回：`{patched}` 或 `{error}`

何时调用：用户说"把这个 widget 改成 X" / "换个颜色" / "加一档选项"

注意：
- 不要 patch 完全无关的文件（如把 manifest 当 html 写）
- patch 前如果不确定，可先 `list_widgets()` 看清楚再动手
- 改 widget.html 必须保持 scoped class `.widget-<name>`，否则样式会泄露到别的 widget

## 未来 tool（v0.5+）

| Tool | 干啥 | 何时上 |
|---|---|---|
| `patch_md_frontmatter` | 改某日记 frontmatter 字段 | v0.5 写回路径 |
| `read_journal(date)` | 读取某日记内容 | v0.5 让 AI 跨日检索 |
| `list_pulse_files` | 列项目 PULSE 状态 | v0.6 PULSE 模块 |
| `propose_pulse_refresh` | 提议 PULSE refresh（不直写） | v0.6 |
| `search_journals(query)` | 跨日全文 / 语义检索 | v0.7 嵌入 |
| `add_module` | 装 module（非 widget 维度的更大功能块） | v0.7 module 系统 |
| `install_preset(name)` | 一键装 ctrl-c-v+schedule+pulse 等闭环 | v0.8 preset 系统 |

## 调用纪律（给 AI 看的）

1. **能少调就少调**：用户说"hi"不要 list_widgets。聊天就聊天。
2. **conservative**：不确定就先 list_widgets() 看清楚，再 add/patch。
3. **失败就报**：tool 返回 `error` 字段就老实说"这步失败了 X"，不要硬试第二次。
4. **action 串行**：一次回复里多个 tool 串行调用 OK，但不要超过 3 个（避免失控）。
5. **不动 MD**：v0.4 没有 patch_md tool。用户问"改我的日记 prose"要回答"v0.5 上线"。
6. **用户语言**：用户用中文你用中文，用户用英文你用英文。
