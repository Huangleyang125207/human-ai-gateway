# 03 · AI 工具集 + 对话流四类消息

> 这一份给的是"AI 在 mobile 端能做的所有动作"以及"动作发生时,用户在对话流里看到什么"。
>
> 18 个 AI tool 不是 UI——它们是 AI 的手脚。但只要 AI 调了任何一个,用户都会在对话流里看到一颗 chip(小标签)。chip 是这一份的视觉主体。
>
> 你不需要为每个 tool 单独画一张脸——它们共用同一种"AI 在做事"的视觉习语。重点在:用户能不能一眼看懂 AI 在干嘛、做完了没、成没成。

---

## 工程铁律(动手前先记)

1. **chip 三态不可合并**:`doing` / `ok` / `fail` 是数据层的真值,任何视觉都得能区分这三种,缺一不可——用户问"刚才那条改了吗"全靠 chip 状态回答。
2. **chip 文案是自然句不是 raw JSON**:每个 tool 都有一个翻译函数把参数变成中文短句(如 `patch_journal_block({time:"14:00"})` → "改 14:00 那条")。**禁止**把 `{"time":"14:00","new_md":"..."}` 这种东西暴露给用户。
3. **chip 不可点开成大面板**:它是"AI 在做事"的痕迹,不是操作入口;用户想看做了啥的细节,看上面那条 entry 的真改动即可。最多允许 `fail` 态点一下展开一句错误原因。
4. **tool 工具集合是会增加的**:今天 18 个,半年后可能 25 个,所以**别为每个 tool 画专属图标**——做一套能容纳新 tool 的视觉容器。

---

## A. 18 个 AI Tool 一览

> 每个 tool 给:① 它干嘛 ② 参数(简版,只列出会进 chip 文案的) ③ 用户视角看到啥 ④ 失败时的提示语来源
>
> 视觉设计师只需要关心 ③ 和 ④——你不需要懂它怎么调到后端的。

### A.1 日记写操作(5 个)

这一组是 AI 最高频的动作。用户跟 AI 聊"把 14:00 那条改成 xxx",AI 就调下面这些。

| Tool | 干嘛 | 关键参数 | chip 自然句示例 |
|---|---|---|---|
| `patch_journal_block` | 改某个时间块的内容 | `time` (14:00) | "改 14:00 那条" |
| `insert_journal_block` | 在某时间块**新建**一条 | `time`, `title` | "加 14:00 · 跟 X 喝茶" |
| `append_journal_comment` | 给某时间块附 AI 评论(authorship 合法旁路) | `time`, `comment` | "给 14:00 加评论" |
| `read_today_schedule` | 读今天的日记全文(纯读取,无写操作) | `date` | "看今天日记" |
| `list_recent_days` | 列最近 N 天文件名 | `n` (默认 7) | "看最近 7 天" |

**用户场景**:
- 用户:"把刚才 14:00 那段改成『跟客户开会确认产品方向』" → 对话流弹出 chip "改 14:00 那条" 转 doing → AI 后端真改 md → chip 转 ok → 用户切回日记页发现 14:00 已经更新。
- 用户:"我 19:00 去打了篮球" → AI 调 `insert_journal_block(time:"19:00")` → chip "加 19:00 · 打篮球" doing → ok。
- 用户:"帮我看看今天上午都写了啥" → chip "看今天日记" 一闪而过(读操作很快)。

**失败提示**:
- "改 14:00 那条 · 没找到这个时间块"
- "改 14:00 那条 · 这条是你自己写的,AI 改不了(可以追加评论)"
- "加 14:00 · 没找到时间块占位"

### A.2 打卡管理(4 个)

补剂/吃药/喝水这类"每天勾一下"的动作。AI 跟用户聊"我刚吃了鱼油",AI 自动勾。

| Tool | 干嘛 | 关键参数 | chip 自然句 |
|---|---|---|---|
| `check_daily_task` | 打卡(支持"吃了 N 粒" / "+1" / 直接勾) | `task_name`, `intake`/`increment`/`checked` | "打 鱼油 卡" |
| `set_daily_task_meta` | 改一项 task 的设置(每天几粒 / 一瓶几粒) | `task_name`, `daily_dose`, `total_pills` | "改 鱼油 的设置" |
| `set_daily_task_image` | 换某项 task 的图标 | `task_name`, `image` | "换 鱼油 的图标" |
| `manage_daily_task` | 加/删一项 task | `action` (add/delete), `task_name` | "加 维 C 打卡" / "删 鱼油 打卡" |

**用户场景**:
- 用户:"我刚吃了鱼油" → chip "打 鱼油 卡" doing → ok → 打卡 widget 那一格圈住。
- 用户:"以后我每天吃 2 粒鱼油" → chip "改 鱼油 的设置" → ok。
- 用户拖图给 AI 看:"这是我新买的维 C" → AI 调 `vision_classify` 看图 → 再调 `manage_daily_task(add, "维 C")` → 两颗 chip 接连出现:"看图 · cap_xxx.png" 然后 "加 维 C 打卡"。

**失败提示**:
- "打 鱼油 卡 · 这个 task 不在你的清单里(要先加)"
- "改 鱼油 的设置 · 一瓶颗数不能是负数"

### A.3 喝水(1 个)

| Tool | 干嘛 | 参数 | chip |
|---|---|---|---|
| `set_water_cup_image` | 换喝水图标(8 杯水的图) | `image` (base64) | "换喝水图标" |

**用户场景**:用户拖一张可爱杯子图过来:"用这个当喝水图标" → AI 调 `vision_classify` 先看图确认是杯子 → 调 `set_water_cup_image` → 两颗 chip:"看图 · cup.png" 然后 "换喝水图标"。

### A.4 搜索(1 个)

| Tool | 干嘛 | 参数 | chip |
|---|---|---|---|
| `search_journal` | 在本机 vault 全部日记里搜关键词 | `query`, `days` (默认 30, 最大 365) | "搜 \"鱼油\"" |

**用户场景**:用户:"我上个月哪天提过那个客户来着" → chip "搜 \"客户\"" doing → ok → AI 回话引用搜到的几个日期。

**失败提示**:"搜 \"客户\" · 30 天内没搜到(要不要扩到 365 天)"

### A.5 联网(2 个)— 三层降级链

这一组是 mobile 端从 PC 端移植过来的能力。降级链:360 → 阿里云百炼 → 拒答。

| Tool | 干嘛 | 参数 | chip | 频次上限 |
|---|---|---|---|---|
| `web_search` | 联网搜信息+真实 URL | `query`, `max_results` (默认 5) | "搜 \"M2 芯片对比\"" | **每对话最多 3 次** |
| `fetch_url` | 拉某 URL 正文(stripped → text, 最多 3000 字) | `url` | "看 example.com/foo 正文" | **每对话最多 5 次** |

**用户场景**:用户:"今天有啥关于 OpenAI 的新闻" → chip "搜 \"OpenAI\"" doing → 拿到 5 条结果 → AI 决定看其中一条 → chip "看 techcrunch.com/xxx 正文" doing → 拿到正文 → AI 综合回答。

**失败提示**(关键设计):
- 频次封顶:`web_search 已达上限 (3 次/对话),停止继续调,基于已搜到的信息直接回答用户` → chip 文案 "搜 \"xxx\" · 已封顶 3/对话"。这条要让用户看得到——是 AI 容易踩的死循环坑,用户看到 chip 才知道为啥 AI 不继续搜了。
- 降级:`360 不可用,降到百炼` → chip 仍是 ok 但可以视觉上有一道"降级中"的小标签(可选)。
- 拒答:三层都不可用 → chip fail · "联网都试过了,这次没拿到"。

### A.6 视觉/OCR(2 个)— 阿里云百炼 qwen3-vl-flash

这一组是 mobile 端的"眼睛"。用户拖图进 chat,AI 用这两个 tool 看图。

| Tool | 干嘛 | 参数 | chip |
|---|---|---|---|
| `vision_classify` | 看图分类+描述,返 `{kind, description, ocr_likely, suggested_action, brand?, pill_count?}` | `attachment_url`, `extra_question` (可选问具体问题) | "看图 · cap_xxx.png" |
| `ocr_image` | 提取图里所有文字(底层走 vision_classify + OCR prompt) | `attachment_url` | "OCR · cap_xxx.png" |

**用户场景**:
- 用户拖了一张补剂瓶子的照片:"这是啥" → chip "看图 · pic.jpg" doing → AI 拿到 `{kind:"supplement_bottle", brand:"Now Foods", description:"鱼油 1000mg"}` → 自然语言回话。
- 用户拖了一张菜单照片:"帮我抄一下" → chip "OCR · menu.jpg" doing → AI 拿到全文 → 回话。

**失败提示**:
- "看图 · pic.jpg · 没填阿里云钥匙"(空 key)→ 这一类失败要引导到设置页填 key,**chip 本身要能引导**(类似可点的提示)。
- "看图 · pic.jpg · 这张图坏了"(损坏图片)。

### A.7 Widget(4 个)— 动态注册

mobile 端有 widget 体系:cups/tasks/pulse/mood 是核心,AI 可以 add 新的纯展示型 widget。

| Tool | 干嘛 | 参数 | chip |
|---|---|---|---|
| `list_widgets` | 列当前装了哪些 widget(返 `[{id, title, slot, enabled}]`) | — | "看当前装的 widget" |
| `set_widget_enabled` | 启用/停用某个 widget | `id`, `enabled` | "启用 cups widget" / "停用 mood widget" |
| `add_widget` | 装新 widget(纯展示型,HTML 模板) | `id`, `title`, `slot` (care), `template` | "装新 widget · 步数追踪" |
| `remove_widget` | 卸 widget(只能删 AI 加的,不能删核心) | `id` | "卸 widget · steps" |

**用户场景**(这一组是最能体现"AI 帮你长出自己版本"的能力):
- 用户:"我想加一个显示今天写了几条 entry 的小卡片" → AI 调 `add_widget(id:"entries", title:"今日条数", template:"<div>{{entries_count}} 条</div>")` → chip "装新 widget · 今日条数" → ok → 用户切回总览发现多了一个 widget。
- 用户:"把 mood 那个去掉吧不爱用" → chip "停用 mood widget" → ok。

**模板可用变量**(在 `template` 字符串里用 `{{var}}` 插值):
- `tasks_done` / `tasks_total`(今天打卡数)
- `water_filled`(喝水杯数 0-8)
- `entries_count`(今天 entry 数)
- `date`(今天日期)
- `minutes_to_2130`(离 21:30 还多久,负数=已过)
- `note_state`(`waiting` / `ready` / `done`,21:30 纸条状态)

**失败提示**:
- "装新 widget · cups · 这个 id 已经被核心 widget 占了"
- "卸 widget · cups · 不能删核心 widget"

### A.8 工具集总表(给 cd 的速查表)

| 分组 | 数量 | 是否高频 | chip 出现频率 |
|---|---|---|---|
| 日记写操作 | 5 | ★★★ 最高频 | 每次聊天可能 1-2 颗 |
| 打卡管理 | 4 | ★★☆ | 用户提到补剂/吃药时 |
| 喝水 | 1 | ★☆☆ | 很低 |
| 搜索 | 1 | ★★☆ | 用户问"上次什么时候"时 |
| 联网 | 2 | ★★☆ | 用户问近期新闻/外部信息 |
| 视觉/OCR | 2 | ★★☆ | 用户拖图时 |
| Widget | 4 | ★☆☆ | 用户要"加个新追踪"时 |

**密度提示**:重度对话场景下,一条用户消息可能触发 3-5 颗 chip 接连出现(典型:拖图 → 看图 → 改打卡 → 加评论,4 颗)。视觉容器要扛得住 chip 密集出现而不显得喧闹。

---

## B. 对话流四类消息

mobile 端的对话流 `state.thread` 是一个数组,每条 item 有一个 `kind` 字段,有四种值:

| kind | 含义 | 出现频率 |
|---|---|---|
| `msg` | 普通对话气泡(用户或 AI) | 最高频,占 70%+ |
| `ref` | 用户从日记拉一条 entry 进来"指给 AI 看" | 中频 |
| `note` | 21:30 AI 留的纸条(仪式) | 每天最多 1 条 |
| `tool` | AI 调 tool 时的 chip | 中高频,跟 msg 交错 |

下面逐类给数据 schema + 渲染需求。

### B.1 `msg` · 普通对话气泡

```json
{
  "kind": "msg",
  "who": "me" | "ai",
  "text": "string (AI 的可能含 markdown)",
  "streaming": true,     // 仅 AI 流式输出时,渲染时显示光标
  "err": true,           // 仅失败时(网络异常),气泡变错误态
  "attachments": [       // 仅 user 发图时
    { "url": "/attachments/...", "dataUrl": "data:image/..." }
  ]
}
```

**渲染要显示的**:
- 谁说的(我 / Gateway 这种身份标签)
- 文字本体(AI 端 markdown 要渲染,user 端纯文本要 escape)
- 流式输出时的"正在打字"指示(光标 / 呼吸点 / 任何"还没写完"的语义)
- 失败态(网络挂了,AI 那条的气泡要可识别为"失败"——比如灰掉、加一行小字"失败")
- 用户发图时,气泡下方要出现缩略图条(可多张并排)

**不允许的**:
- 不允许 markdown 渲染漏到 user 那一侧(用户发什么就是什么,不要把 `**foo**` 渲成粗体——会误伤代码片段和讨论)
- 不允许把 streaming 状态写进 localStorage(只在内存里,刷新就消失)

### B.2 `ref` · 拉日记进对话

用户在日记页长按某条 entry → "指给 AI 看" → 这条 entry 的标题/摘要被推进对话流,提示 AI 接下来要聊这条。

```json
{
  "kind": "ref",
  "who": "me",
  "refKind": "日记 · 14:00",    // 来源标签
  "refText": "跟客户开会确认..." // 标题或前 24 字摘要
}
```

**渲染要显示的**:
- 这是"引用"不是"用户发言"——视觉上跟 `msg` 要明确区分(不是气泡)
- 两行:来源标签(`日记 · 14:00`)+ 内容摘要
- 一眼能看出"这是我刚拉进来的一条日记"

**不允许的**:
- ref 不能点开变成大面板看全文——视觉是"小卡片提示"不是"嵌入式 viewer"
- ref 没有 `state`——它就是一个静态推送,推完就在那

**场景提示**:用户拉了 ref 进来后,下一句通常是"帮我把这条改一下" → AI 就会调 `patch_journal_block(time:"14:00")` → 下面会接一颗 `tool` chip。所以 `ref` 和后面的 `tool` chip **视觉上要有承接感**(用户的眼睛从 ref 滑到 tool chip 是同一个动作链)。

### B.3 `note` · 21:30 AI 纸条(仪式)

这是 mobile 端最被珍视的一类消息。每晚 21:30,AI 给用户留一段纸条——是仪式不是功能。

```json
{
  "kind": "note",
  "time": "21:30",
  "body": "今天你提了 3 次「累」,但 17:00 那条你说『跟 X 聊完轻松了』。要不要明天提前安排一次跟 X 的咖啡?",
  "sig": "Gateway · 6.25 晚"
}
```

**渲染要显示的**:
- 时间戳(21:30)
- 纸条正文(支持 markdown,AI 偶尔会用斜体或引用)
- 落款(像信尾签名)
- **视觉要明确不同于 `msg`**——它不是对话,它是"留下来的字"

**场景提示**:
- 用户白天打开 app,对话流里可能有昨晚的纸条停在那——纸条不会消失,会一直留在对话流里(用户可以往上翻回去看)
- 这是 design brief 里反复强调的"深夜 11 点低光下舒服"的核心载体——视觉权重应该比 `msg` 高,但不能高到喧宾夺主
- 用户**不能编辑**纸条,但可以追加 `msg` 回应(对话继续)

**不允许的**:
- 纸条不能跟 AI 的普通 `msg` 视觉一样——用户分不清"这是仪式 vs 这是普通回话"是大事故
- 纸条没有 streaming 状态(它不是实时打出来的,是一次性出现的)

### B.4 `tool` · AI 调 tool 的 chip

这是这份 brief 的视觉主角。每次 AI 调 18 个 tool 中任意一个,对话流里就 push 一颗 chip。

```json
{
  "kind": "tool",
  "id": "tc_abc123",              // 唯一 id,doing → ok/fail 时按 id 找 chip 更新
  "name": "patch_journal_block",  // tool 名(用于翻译成自然句)
  "args": { "time": "14:00" },    // 调 tool 的参数(用于翻译成自然句)
  "state": "doing" | "ok" | "fail",
  "result": { ... },              // 仅 ok 态,tool 的返回值
  "error": "string"               // 仅 fail 态,错误原因
}
```

**生命周期**:
1. AI 决定调 tool → 对话流 push 一颗 `state:"doing"` 的 chip + 显示自然句("改 14:00 那条")
2. tool 跑完 → 找到这颗 chip 按 id 把 `state` 改成 `"ok"` 或 `"fail"`
3. chip 留在对话流里**永久不会消失**(用户翻历史能看见"那天 AI 改了这条")

**渲染要显示的**:
- 一个状态指示(doing / ok / fail 三态可区分)
- 自然句标签(`toolLabel(name, args)` 的结果,前面 A 节的"chip 自然句"列就是了)
- 简洁——chip 不是主角,是"AI 在做事的痕迹"

**fail 态的特殊处理**:
- chip 颜色/质感要能传达"出问题了"
- **可以**点 fail chip 展开一行错误原因(可选交互,不强制)
- 错误句应该是人话:"没找到这个时间块" / "AI 改不了你写的内容" / "钥匙没填" 而不是 HTTP 500

**密度提示**:用户聊一句话,AI 可能连调 3 颗 tool——chip 会在 1-2 秒内连续 push 进对话流。视觉上要扛得住"突然冒出 3 颗"而不眩晕。

**示例场景**(连续 3 颗 chip):
```
用户:"我刚吃了鱼油,你看下这是不是上次那瓶"  [附图]
─────────
[chip] 看图 · pic.jpg   doing → ok
[chip] 打 鱼油 卡       doing → ok
[AI msg] "对,是 Now Foods 那瓶。已经帮你打卡了。"
```

---

## C. Chip 视觉自由度

> 这一节明确画线:cd 设计 chip 时哪些可以自由发挥,哪些是数据/产品契约不能动。

### 你可以自由设计的

- **chip 的形状**(胶囊 / 矩形 / 信纸折角 / 印章 / 别的非按钮形态都行)
- **chip 的动画**(doing 时呼吸 / 墨晕 / 转一圈 / 别的"AI 在做事"语义都行)
- **chip 的颜色**(三态色板自由定,符合 design tokens 即可)
- **chip 的密度**(连续 3 颗 chip 时怎么排——堆叠 / 错位 / 一条流——你定)
- **chip 的图标**(每分组可以用一个示意性的小图标,但要克制——见下条)
- **chip 跟 `msg` `ref` `note` 之间的视觉对位**(怎么让用户一眼区分四类消息——你定)

### 不能动的(产品契约)

- **`doing` / `ok` / `fail` 三态必须能区分**——一个 chip 在用户视野里所处的态,是用户能否信任"AI 真的做了这事"的唯一线索。三态合一 = 对话流失去状态意义。
- **chip 文案必须是自然句不是 raw JSON**——`toolLabel()` 翻译表已经给了 18 条样板。新加 tool 时新加一条翻译,但不能跳过这一层让 `{"time":"14:00"}` 漏到用户面前。
- **chip 不能可点击成大操作面板**——它是痕迹,不是入口。最多 `fail` 态点开一行错误原因。
- **chip 永久留在对话流**——用户翻历史能看见所有 chip。chip 不能"消失" / "自动收起" / "做完就 fade out"。这条是审计语义,不是品味。
- **18 个 tool 都共用同一种 chip 视觉容器**——别为每个 tool 单独画一种 chip,会让对话流变成五颜六色的功能徽章墙。分组之间最多用一个非常克制的小图标暗示(比如视觉/OCR 那两个可以共用一个眼睛形,联网那两个共用一个地球形),但整体仍是同一种 chip。
- **半年后新增的 tool 必须能放进同一套视觉**——这条意味着你的 chip 设计要"为未知 tool 留位置",而不是"为这 18 个量身定制"。同 widget 体系的"长出来"哲学。

---

## D. 对话流整体节奏(给 cd 的全景图)

一个典型的下午,用户的对话流可能长这样:

```
13:00  [note]    昨晚 21:30 AI 留的纸条 — "今天的早晨..."
13:05  [msg me]  "看看我上午写了啥"
       [tool]   看今天日记 · ok
       [msg ai] "上午你..."
14:00  [msg me]  "把 14:00 那条改成『跟客户开会确认产品方向』"
       [tool]   改 14:00 那条 · ok
       [msg ai] "改好了。"
15:30  [ref]    日记 · 15:00 · "想了想下周的演示..."
       [msg me]  "帮我加点细化"
       [tool]   给 15:00 加评论 · ok
       [msg ai] "加了评论。"
19:00  [msg me]  "我刚吃了鱼油" [附图]
       [tool]   看图 · pic.jpg · ok
       [tool]   打 鱼油 卡 · ok
       [msg ai] "是 Now Foods 那瓶。打卡了。"
21:30  [note]    今晚的纸条 — "今天你提了 3 次..."
```

**这一片对话流应该看起来像什么**:
- 像翻一页杂志,不是刷一个聊天软件
- 不同 kind 之间要有节奏感——`note` 是停顿,`msg` 是节拍,`ref` 是引文,`tool` 是页边批注
- 时间不需要每条都打——但分段时间锚(下午到傍晚到夜晚)的视觉过渡可以做出"一天在流动"的感觉

这是 design brief 里"翻一本自己的杂志"那条铁律,在对话流这个面上的落地。

