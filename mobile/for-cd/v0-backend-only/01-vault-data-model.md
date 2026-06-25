# 01 · Vault 数据模型 —— md 长啥样,setting/ 里都藏了什么

> 给 cd 看这一份的目的:**理解"AI 在写什么、用户的笔在哪里、改一处会动哪几处"**。
> 不是让 cd 学 schema,是让 cd 知道**视觉上要为哪些数据形态留位置**。
> 一句话心智:**md 是真相 · setting/ 是 sidecar · attachments/ 是图床**。

---

## 1 · vault 在哪

真 vault 路径(开发机):`~/.human-ai/vault/`(注意:`agents创作平台/数据库/valut/` 是冻结在 5.15 的旧镜像,**只读** —— 现在演变全在前者)。

移动端运行时:在 iOS 应用沙箱里(`HUMAN_AI_HOME`),布局完全一致,只是路径前缀变。**cd 不需要关心路径**,只需要知道**目录结构稳定**。

```
vault/
├── 半小时复盘/            # 日记本体,一天一 md
│   ├── 26.5.12(第十天).md
│   ├── 26.5.13(第十一天).md
│   └── ...
├── 标签聚合.md            # #yanpai / #ESP32 / #配置系统 横切索引
├── setting/               # sidecar 配置 + meta + 历史
│   ├── taskmeta/          # daily-task 配置(每任务一 JSON)
│   │   ├── 鱼油.json
│   │   ├── 苏糖酸镁.json
│   │   └── 八杯水.json    # 八杯水是 reserved key,占这个槽
│   ├── taskintake/        # 打卡日志(每任务一 JSON)
│   │   ├── 鱼油.json
│   │   └── ...
│   ├── thread/            # 留言板对话历史
│   │   ├── history.json
│   │   ├── history.json.bak.1
│   │   ├── history.json.bak.2
│   │   ├── ... (.bak.5 共 5 份回滚链)
│   │   └── cursor.json
│   ├── widgets/           # widget manifest(每 widget 一 JSON)
│   │   ├── supplements.json
│   │   ├── steps.json
│   │   └── mood.json
│   ├── widget_states.json # widget enable/disable + 顺序
│   └── mood/              # 心情 emoji(每天一文件)
│       ├── 26.6.20.json
│       └── ...
├── attachments/           # 拖图 / 抠图 / scrapbook 真实文件
│   ├── 26.5.19/
│   │   ├── a3f2c8e1d0b4f5e6.png    # SHA16 命名
│   │   ├── a3f2c8e1d0b4f5e6_processed.png  # 抠图结果
│   │   └── _index.json    # vision-pre-router 缓存:文件 → 分类提示
│   └── ...
└── PROJECT_PULSE.md       # AI compact 出的项目 PULSE 镜像
```

---

## 2 · 半小时块 md schema(canonical)

一天一文件,文件名 `YY.M.D(第 N 天).md`(N 从 5.3 = 第 1 天数起)。

### 结构

```markdown
# 0：00
(空着没事)

# 7：30 #思考 自由意志的边界 @user
今早醒来突然觉得，所谓"自主选择"可能就是大脑后处理的故事...
<commit by=claude-opus-4.7 at=07:32:14> 笔记 #思考 + @user 段;首次"自由意志"主题
</commit>

# 9：00 #yanpai 演牌 backlog 收尾 @user
跑了一遍 v0.1.20 review，把 22 项 P1+P2 收口...
<commit by=claude-opus-4.7 at=09:14:02>
</commit>

# 14：00 #思考 散步随想 @user @claude
- [ ] 鱼油
  - [x] 1
- [ ] 苏糖酸镁
- [ ] 南非醉茄
- [ ] 八杯水
  - [x] 1
  - [x] 2
  - [x] 3

走在路上看到一只猫，想起 KS 测试在尾部漂移的现象...
```

### 解释

- **`# 7：30`** 是 H1(全角冒号 `：`)—— 时间块锚,半小时一格,floor 取整。**只创建当前块及之前,不预生成空块**(空 H1 不写)。补剂段是 reserved time block,放在 `# 0：00`(很多模板默认)或顶部 free-form;但**补剂的 H1 文本就是 "补剂打卡"**,见下面 § 4。

- **`## H2`** = `tag(s) + title + @author(s)` —— 一行,每个 H1 下面可以有多条 H2 entry。
  - tag 段:0+ 个 `#xxx`(本 vault § H3 vocabulary:`#yanpai / #ESP32 / #配置系统` 进聚合,其他不进)
  - title:自由文本,**就是 entry 的标题**,cd 在时间线视图就显示这一段
  - `@user` / `@claude` / `@deepseek`:1+ 个,作者签名 —— **`@user` 块字节级 AI 不可覆盖**(authorship boundary 硬合同)

- **body**:H2 下面到下一个 `# H1` 或 `## H2` 之间的全部内容。**纯 markdown** —— 可以含 bullet list、引用、代码块、内嵌图片(`![](attachments/.../xxx.png)`)、@引用、内嵌 emoji。

- **`<commit ...>`** 注解:AI 写完后落一行机器可读签名;视觉上 cd 可以选**显示或隐藏**,默认建议隐藏(小灰字、悬浮显)。`at=HH:MM:SS` 是真实时间戳,跟 H1 锚的"半小时块"不同。

### body 渲染

**统一走 `window.gatewayMd()`**(marked + DOMPurify,vendor 锁版本)—— cd 不写第二个 markdown 渲染器。要做的是 entry **容器**(纸感 / 留白 / 字号 / 行高),不是 `<p>` 怎么排。

---

## 3 · 补剂 / daily-task 段(双层结构)

每天 md 顶部有一段"打卡区",形如:

```
- [ ] 鱼油
  - [x] 1
- [ ] 苏糖酸镁
- [x] 南非醉茄
  - [x] 1
  - [x] 2
- [ ] 八杯水
  - [x] 1
  - [x] 2
  - [x] 3
  - [x] 4
```

### 解释

- 外层 `- [ ]` 是任务名 —— **打了 daily_dose 次的子 box 之后,外层自动勾上**(`- [x] 南非醉茄` 表示今天完成了)
- 内层 `  - [x] N` 是 intake 次序号 —— 每打一下加一个;`N` 是该剂量的次序(1, 2, 3...)
- **八杯水是 reserved**:外层默认就叫"八杯水",内层最多 8 个;打满 8 个外层勾上

cd 在视觉上**不必把这段渲染成 markdown 原文**(那是 md 真源)—— 在移动端关怀区里用 widget 形态展示(02 详细),md 是数据源,widget 是表现。

### 打卡的真值在哪

md 是事实,**但 widget 状态查询走 setting/taskintake/<name>.json**(性能 + 精确时间戳)。两边由后端保证同步,cd 只读不写。

---

## 4 · taskmeta —— 每任务的配置(给 widget 用)

`setting/taskmeta/<任务名>.json`:

```json
{
  "name": "鱼油",
  "icon": "fish-oil.svg",
  "total_pills": 60,
  "daily_dose": 2,
  "purchase_url": "https://...",
  "notes": "饭后服用",
  "created_at": "2026-05-12T10:00:00+08:00",
  "updated_at": "2026-06-20T14:30:00+08:00"
}
```

### 字段

- **`name`** —— 任务名,文件名同名(unicode 安全)
- **`icon`** —— 用户可在 widget 长按菜单"换图标"(从 sticker pool 选)
- **`total_pills`** —— 剩余/总量(用于"还剩 X 天"计算,可选)
- **`daily_dose`** —— 每天目标剂量,**就是子 box 上限**(超过 clamp);八杯水恒 8
- **`purchase_url`** —— 复购链接(用户长按"复购")
- **`notes`** —— 备注(AI 可以在留言板里念出来:"鱼油记得饭后")

### 移动端铁律(parity)

桌面 `mobile-api.js` 之前埋了几个 parity 洞 —— `daily_dose` 在移动 shim 里恒为 1,导致"打了一下就勾上"。**已修**,但 cd 设计 widget 时要假定 `daily_dose` 是任意正整数(常见 1-8)。

---

## 5 · taskintake_log —— 打卡时序日志

`setting/taskintake/<任务名>.json`:

```json
{
  "name": "鱼油",
  "entries": [
    { "date": "2026-06-25", "n": 1, "at": "2026-06-25T09:14:22+08:00" },
    { "date": "2026-06-25", "n": 2, "at": "2026-06-25T19:30:08+08:00" },
    { "date": "2026-06-24", "n": 1, "at": "2026-06-24T08:50:11+08:00" }
  ]
}
```

### 用途

- widget 状态查询(今天打了几次)
- 历史趋势 sparkline(过去 N 天连续打卡)
- AI 关怀语料("最近三天没打鱼油")

cd 不直接读这文件,但要知道**它存在 → 视觉可以表现"连续打卡 N 天"这种数据**。

---

## 6 · thread / 对话历史 + 损坏 detect

`setting/thread/history.json`:

```json
{
  "version": 3,
  "messages": [
    { "role": "user",     "content": "在吗", "at": "2026-06-25T20:14:00+08:00" },
    { "role": "assistant","content": "在的 ...", "at": "2026-06-25T20:14:02+08:00",
      "tool_calls": [
        { "name": "patch_journal_block", "args": {"time": "14:00", "new_md": "..."},
          "status": "ok" }
      ]
    }
  ]
}
```

### 5 份 bak 链 + corrupt 走 modal(硬合同)

读 `history.json` 失败 → server 返:

```json
{ "status": "corrupt", "baks": ["bak.1", "bak.2", "bak.3", "bak.4", "bak.5"] }
```

前端**绝对不可以"返空就当空"**(5.17 教训:那次直接覆盖了用户真聊天历史)。
必须走 modal:**"对话历史损坏,从 bak.1 / bak.2 / ... 恢复,或从头开始"** —— cd 设计这个 modal 的视觉(纸的做法,不是 alert)。

### cursor.json

记录"AI 上次读到哪里" —— 留言板跨夜连贯的锚点,past_boards 注入靠这个。cd 不碰。

---

## 7 · widget manifest schema

`setting/widgets/<id>.json`:

```json
{
  "id": "supplements",
  "name": "补剂打卡",
  "version": "1.2.0",
  "slot": "care",
  "default_enabled": true,
  "data_source": {
    "type": "taskintake",
    "tasks": ["鱼油", "苏糖酸镁", "南非醉茄"]
  },
  "ai_capabilities": {
    "can_add_task": true,
    "can_remove_task": true,
    "can_change_icon": true
  },
  "created_by": "ai",
  "created_at": "2026-06-20T21:30:00+08:00"
}
```

### 用途

- widget loader 读这个文件决定**装什么样子的 widget**
- AI 通过 `register_widget` tool 写这个文件 —— **跟用户一句话对话即可装出新 widget**
- cd 要为"未知 widget"留容器规范(详 02),不为 4 个已知 widget 各画一张脸

### slot

- `care` —— 关怀区(日记页顶部,日期带下方、时间线之前)
- 未来可能扩展 `header / footer / floating`,但 v0 只做 `care`

---

## 8 · widget_states.json —— 启用/排序

`setting/widget_states.json`:

```json
{
  "enabled": ["supplements", "water-cup", "pulse-today", "mood-today"],
  "order": ["water-cup", "supplements", "pulse-today", "mood-today"],
  "collapsed": ["pulse-today"]
}
```

- **`enabled`** —— 启用的 widget id 集合(默认值由各 widget manifest 的 `default_enabled` 决定)
- **`order`** —— 用户拖拽过的顺序(无序时按 manifest 顺序)
- **`collapsed`** —— 折叠状态(cd 设计折叠习语:纸的做法,不是 chevron `>`)

---

## 9 · attachments —— 图床

```
attachments/26.5.19/
├── a3f2c8e1d0b4f5e6.png           # 原图,SHA16 命名,夹在 entry 里
├── a3f2c8e1d0b4f5e6_processed.png # 抠图后(透明背景的贴纸)
├── b8d4e2c1a9f0e7d3.png
└── _index.json                    # vision 分类缓存
```

### dataURL 不存盘

**移动端 chatbar 贴图预览用 dataURL**(本地 base64,即时显示) —— 见 04 § 1。**dataURL 不写盘**,server 上传成功返回 `url` 才写盘。cd 设计预览态(贴了图但还没发) vs 发送态(写进 entry 了)的视觉区分。

### _index.json(vision-pre-router 缓存)

```json
{
  "a3f2c8e1d0b4f5e6.png": {
    "tag": "food",
    "hint": "一碗番茄牛肉面,葱花飘香",
    "ocr": "招牌 · 邓记面馆",
    "cached_at": "2026-05-19T14:22:00+08:00"
  }
}
```

用户拖图上传时 server 自动跑 vision 分类、缓存命中率 97%。cd 不关心,但**这是 AI 在 chat 时"看见图"的来源**。

---

## 10 · mood emoji

`setting/mood/<YY.M.D>.json`:

```json
{
  "date": "2026-06-25",
  "emoji": "🌧️",
  "note": "压抑但清醒",
  "set_at": "2026-06-25T22:14:00+08:00"
}
```

每天一个 emoji + 一句备注。心情 widget(02 第 4 块)的数据源。

---

## 11 · 移动端读这些数据的路径

cd 不写数据访问代码,但要知道"数据上屏"靠什么:

- **`window.gatewayMd(rawMarkdown)`** —— 唯一的 markdown 渲染器
- **`window.api.taskmeta(name)`** / **`window.api.taskintake(name)`** —— widget 数据 API
- **`window.api.threadHistory()`** —— 对话流读取 + corrupt detect
- **`window.api.widgetStates()`** —— 启用/排序
- **`window.gatewayConfirm(msg)`** —— 替代 `window.confirm`(后者在 Tauri/Capacitor 静默返 false)

**禁忌**:
- 不要在视觉层手写 markdown 解析
- 不要直接读 `setting/` 路径(走 API)
- 不要假定数据立刻到位(全部 await + 占位骨架态)

---

## 12 · 一句话总结

md 是真源 / setting 是 sidecar / attachments 是图床。**cd 设计的每一处"显示数据"的地方,在本档都找得到对应字段**;找不到 = 那个字段不存在,别画它。

---

---
