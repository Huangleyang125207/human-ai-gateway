# Style Guide

> Goal: widgets feel like they're cut from the same paper as the gateway main pages.
> Read DESIGN_BRIEF.md for the underlying aesthetic POV ("深夜桌灯下的私印小报").

## CSS vars 你能用（在 shared/style.css）

```
背景层
--paper       #f5efe1   主底色（米黄旧纸）
--paper-2     #ede5d2   略深一层

墨色
--ink         #2a221a   主文字
--ink-soft    #57463a   次级文字 / 边注
--ink-whisper #9c8b78   元数据 / 时间戳 / lede

分割
--rule        #d9cdb4   极细分割线（hairline）

强调（用得少）
--vermillion  #9f2d20   朱砂——勾选 / 标点 / 高亮
--moss        #6b7a3a   PULSE 绿
--amber       #b8852b   PULSE 黄
```

## 字体堆

正文：CJK 衬线
```
'Source Han Serif SC', 'Noto Serif CJK SC', 'Songti SC',
'STSong', 'Hiragino Mincho ProN', 'Cambria', Georgia, serif
```

数据 / metadata / 装饰小字：
```
'Times New Roman', serif
```

代码 / sparkline / 等宽：
```
ui-monospace, 'SF Mono', Menlo, monospace
```

不引入新字体。

## 视觉禁令

- ❌ `box-shadow` 任何值（私印小报无阴影）
- ❌ `border-radius > 4px`（卡片化）
- ❌ `linear-gradient` 用作背景（除 paper texture 已用的 radial）
- ❌ 引入新色——只用 CSS vars
- ❌ 引入 emoji 作 UI 元素（emoji 是日记内容，不是 chrome）
- ❌ Material / Tailwind / Bootstrap 套件感
- ❌ 全大写英文堆（除 small-caps lede 装饰）

## 视觉鼓励

- ✅ 大量留白（默认 padding 比想的大 1.5×）
- ✅ 行高 1.85 / 字距 0.04em（衬线呼吸）
- ✅ small-caps + 0.18em letter-spacing 作 lede
- ✅ 单 hairline (1px solid var(--rule)) 作分割
- ✅ 朱砂 var(--vermillion) 节制使用（每页 ≤ 3 处强调）
- ✅ 老 style 数字 (font-variant-numeric: oldstyle-nums) 在重要 metric 上
- ✅ 中英混排时用半角空格隔开

## widget 视觉模板

slot-label 风格（所有 widget 标题都用这个）：

```css
.slot-label {
  font-family: 'Times New Roman', serif;
  font-size: 0.68rem;
  color: var(--ink-whisper);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 0.25-0.4rem;
}
```

数值显示：

```css
.big-number {
  font-size: 1.6rem;
  color: var(--ink);
  font-variant-numeric: oldstyle-nums;
  line-height: 1.1;
}
```

## 测一下品味

写完 widget 在浏览器 reload 看。如果你的 widget：
- 跟旁边的 widget "格格不入" → 没用对 CSS vars
- 抢眼到比正文还显眼 → 颜色用错（默认 ink-soft 起步）
- 像 SaaS dashboard → 加了卡片 / 阴影 / 圆角

回到 vars，去掉装饰，重做。
