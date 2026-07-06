# Widget Authoring

## File contract

Every widget is a folder under `gateway/widgets/<name>/` with exactly 3 files:

```
widgets/<name>/
├── manifest.json        必填（schema 见下）
├── widget.html          必填（含 <style> + DOM）
└── widget.js            可选（无脚本时 manifest.script = false）
```

## manifest.json schema

```json
{
  "name": "supplements",                  必填: 同文件夹名
  "title": "补剂打卡",                    必填: 用户可见标题
  "description": "...",                   必填: 一句话说这个 widget 干什么
  "audience": "anyone (default core)",    必填: 适合谁用（诚实）
  "slot": "top-strip",                    必填: 进哪个 slot（见下）
  "script": true,                         必填: 是否有 widget.js
  "data_source": {                        可选 v0.3: 如何从 MD 抽数据
    "type": "md-pattern | frontmatter | static",
    "...": "..."
  },
  "writeback": {                          可选 v0.5+: 写回方案
    "v0.3": "demo-only (toast)",
    "v0.5_planned": "POST /api/checkbox → patch md"
  }
}
```

## Slot 清单

当前可用 slot（在 index.html 里以 `<div data-slot="X">` 形式存在）：

| slot 名 | 在哪 | 适合什么 |
|---------|------|----------|
| `top-strip` | 报头下方横排 | checklist / streak / 1-2 行轻量 tracker |
| `sidebar` | 右侧栏 | 数字 + sparkline / picker / 趋势带 |
| (未来 v0.4) `inline-margin` | 文章右侧浮动边注 | 跟 entry 关联的小注释 |
| (未来 v0.4) `footer-stats` | 页脚上方 | 跨日跨项目 summary |

加新 slot 需要改 index.html 模板 + 跟用户确认 layout 影响。

## widget.html 模板

```html
<style>
  .widget-<name> { /* scoped 样式，class 与 widget 名匹配 */ }
  .widget-<name> .xxx { /* 用 var(--ink-soft) var(--vermillion) 等共享 var */ }
</style>

<div class="widget-<name>">
  <div class="slot-label">显示给用户的标题</div>
  <!-- 内容 DOM -->
</div>
```

要点：
- `<style>` 内联，scoped 到 `.widget-<name>` 类（避免污染其他 widget）
- 不引用 `shared/style.css` 之外的样式来源
- 用共享 CSS vars，不引入新色 / 新字体
- DOM 干净简短，最好不嵌深度 > 3 层

## widget.js 模板

```js
(function() {
  const root = document.querySelector('.widget-<name>');
  if (!root) return;

  // demo data 占位 / fetch / parse / render
  // ...

  // 交互
  root.querySelectorAll('.opt').forEach(el => {
    el.addEventListener('click', () => {
      // 改 UI 状态
      window.gatewayToast('操作反馈');
    });
  });
})();
```

要点：
- IIFE 包裹避免污染全局
- 用 `window.gatewayToast(msg)` 反馈（loader 已提供）
- v0.3 写回都用 toast 模拟，不动 MD（writeback v0.5 才上）
- demo data 硬编码 OK，注释里写"v0.4 接真 parser"

## 注册 widget

编辑 `gateway/.user-widgets.json`:

```json
{
  "active": [
    "supplements",
    "steps",
    "mood",
    "<new-name>"
  ]
}
```

顺序 = 渲染顺序（在同一 slot 内）。

## 加完 checklist

```
□ 文件夹 3 个文件齐
□ manifest.json 字段全 + slot 指向真实 slot
□ widget.html 用 .widget-<name> 类 scope 样式
□ widget.js 用 IIFE + 用 gatewayToast 反馈
□ 共享 CSS vars 没引入新色
□ .user-widgets.json 加进 active 数组
□ 浏览器 reload 看见 widget
□ toast 反馈正常
□ 报告给用户：copy from / adapted / new pattern? (50 words)
```
