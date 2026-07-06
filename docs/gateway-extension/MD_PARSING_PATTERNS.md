# MD Parsing Patterns

> v0.3 widgets 都用 demo data。这份文档描述 **v0.4 开始** widget 怎么从 MD 抽数据。
> 先记下来作 reference，免得 v0.4 重新发明。

## 数据源 3 类

| type | 形态 | 例子 |
|------|------|------|
| `frontmatter` | 每个日记顶部 YAML | `mood: 平` / `steps: 8366` |
| `md-pattern` | 散文中的固定模式 | `vivo 步数 ~3,700` / `- [x] 鱼油` |
| `static` | 写死在 widget.json | （目前无） |

推荐次序：**frontmatter > md-pattern > static**。frontmatter 结构化稳定，md-pattern 脆弱但兼容已写散文，static 是最后手段。

## frontmatter 抽取（推荐姿势）

每个日记顶部加 YAML：

```yaml
---
date: 2026-05-12
day_n: 10
mood: 平                  # 单值
steps: 8366               # 数值
steps_goal: 8000
supplements:              # 嵌套
  鱼油: true
  Mg-LT: true
  KSM-66: true
  D3+K2: true
water_ml: 2100
sleep_hours: 7.2
---
```

parse 单文件：

```js
async function parseFrontmatter(mdPath) {
  const text = await fetch(mdPath).then(r => r.text());
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return {};
  const fm = {};
  m[1].split('\n').forEach(line => {
    const kv = line.match(/^(\w+):\s*(.+)$/);
    if (kv) fm[kv[1]] = kv[2].trim();
  });
  return fm;
}
```

跨日数据（如 9 日 sparkline）：枚举 `半小时复盘/*.md` → 各自 parse frontmatter → 按 date 排序。

## md-pattern 抽取（已有散文兼容）

不动散文也能抽数据。例子：

```
inline:    "vivo 步数 ~3,700"
checklist: "- [x] 鱼油（Swisse）"
tag:       "## #yanpai #协作 ..."
```

正则：

```js
// 步数：vivo 步数 ~XXX 或 ~X,XXX
const STEPS = /vivo 步数 ~?([\d,]+)/g;

// 补剂：每行 - [x] 或 - [ ] 接名字（去括号）
const SUPP = /^- \[([ x])\] (.+?)(?:（|$)/gm;

// project tag：H2 line 第一个 # 后到空格
const TAG = /^## #(\S+)/gm;
```

抽完返回 `{date, value}` 数组。

## 跨日合并

```js
async function loadSeries(field, days = 9) {
  const today = new Date();
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today); d.setDate(d.getDate() - i);
    const dateStr = `26.${d.getMonth()+1}.${d.getDate()}`;
    const file = `../数据库/valut/半小时复盘/${dateStr}.md`;   // 文件命名带"(第N天)"会更难，待定
    try {
      const fm = await parseFrontmatter(file);
      out.push({ date: dateStr, value: fm[field] });
    } catch (e) {
      out.push({ date: dateStr, value: null });
    }
  }
  return out;
}
```

注：当前日记文件命名是 `26.5.10(第八天).md`，正则要匹配 prefix。v0.4 实装时统一约定。

## 边界与陷阱

1. **空日**：用户某天没写 → null，sparkline 留空白格不要画 0
2. **格式漂移**：用户写"v8366 步"或"步数 8,366"，正则要兼容 → md-pattern 写宽松一点
3. **frontmatter 缺失**：旧日记没 yaml → 优雅 fallback 到 md-pattern 或 demo
4. **缓存**：v0.4 可以加 IndexedDB cache，今天已 parsed 的不重 parse
5. **跨月**：5.31 → 6.1 文件命名差异，date 计算要靠 Date 对象不靠字符串

## v0.4 实装清单

- [ ] frontmatter parser
- [ ] md-pattern parser
- [ ] series loader（按日期生成文件名）
- [ ] 每个 widget 把 demo data 替换成真 parse
- [ ] 给所有日记顶部加 frontmatter（一次性迁移）

## v0.5 写回

写回是 server 端的活，不在前端 parser 范围。HTML widget 用 fetch POST：

```js
await fetch('/api/frontmatter', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    file: '26.5.12(第十天).md',
    field: 'mood',
    value: '好'
  })
});
```

server 端用 `gray-matter` 或 sed 改 frontmatter。详见 v0.5 spec（未写）。
