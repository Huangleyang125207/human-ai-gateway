# 02 · Widgets — 四块小器官 + AI 动态加新

> 给 cd 的视觉创作 brief。本文档只描述 **数据从哪来、用户怎么动、不许碰什么**;
> 视觉(色板/排版/动效/质感)由 cd 自由发挥,本档不约束。
> 本档涉及的 4 个核心 widget 都长在日记页顶部"关怀区"(slot = `care`),
> 排在日期带下方、时间线之前。
> 一句话心智:**这不是 dashboard。是 AI 跟用户共同照看一天的几张便签。**

---

## 0 · 总图

日记页打开后,关怀区里**顺序竖排**装着这 4 个 widget(默认显示哪些见各节):

```
顶栏 / 日期带
─── 关怀区(slot = care)──────────
  [八杯水]      默认开
  [今日打卡]    默认开
  [今日 PULSE]  默认关 · 用户/AI 可启用
  [今天心情]    默认关 · 用户/AI 可启用
─── 时间线 ─────────────────
  07:30 · ...
  09:00 · ...
  ...
─── 悬浮 + ──────────────
```

关怀区不是 4 张并排卡片(请抗住卡片化的肌肉记忆,DESIGN_BRIEF 铁律 #2);
是一段竖向流动的"早安栏目",每块有自己的呼吸节奏,不必齐高、不必同款边框、
不必有统一容器分隔。可以像翻一页报纸时**先看到天气栏,再看到运势栏,再看到星座栏**
的那种"段落感"。

cd 自由发挥的维度:
- 每块的视觉骨架(用什么质感,纸/墨/朱印/水彩,留白节奏)
- 每块的入场动效(滑入、墨晕、淡显,但要**安静**——不要 dashboard 弹跳)
- 块与块之间的分隔(留白?装饰线?ornament?都行,**禁卡片描边一刀切**)
- 各块"今天没事可做"的状态长什么样(全部完成 / 一片空白)

**禁触视觉之外的约束**(改这些 = md 真源对不上 = 系统死):
- 横滑/长按的**手势触发阈值**(后文每块标了)
- md 落盘的**字节位置**(补剂段、喝水子杯的 md 结构)
- AI 动态 widget 的 **6 个安全变量名 + XSS escape 入口**

---

## 1 · cups · 八杯水

### 用户场景

葱鸭睡前在床上想起来"今天好像水喝得不够";打开 app,日记页关怀区第二行就是
八杯水,他**用拇指从左往右轻轻一抹**,水位涨到 6 杯,放下手机继续睡。
他**从来不需要先点别的按钮再来打卡**——打开 app 就在那。

第二天他在外面拍了一个好看的玻璃杯(或他养的猫,或一颗药丸),想换掉默认杯子,
**长按这一排杯子**,系统选图器弹出,他选一张照片,前端跑端侧抠图(约 1-2 秒),
然后 **8 个杯子全变成这张图**(同一张,不是 8 张不同),下次打开还是这张。

历史日(不是今天)打开,八杯水**只读**——显示当天最终落了几杯,不能动。

### 数据 schema

- **`water_filled: int 0-8`** — 当天喝了几杯。从当天 md 顶部的"喝水"段
  子杯勾选数派生(`- [x]` 数 1)。今天可写,历史日只读。
- **`cup_image: string | null`** — 杯子图标的 base64 dataURL(端侧抠图后存)。
  全局只一张(不是每杯不同),无图时退回到默认杯子视觉。
- **`readonly: bool`** — 当前页是不是历史日(`date < today`)→ 全部交互失效。

### 交互合约

| 动作 | 触发 | 落盘语义 |
|---|---|---|
| 点亮第 N 杯 | tap 或滑过第 N 杯,水位变成 N(右往左滑可减少) | POST `/api/daily-tasks/water` → 当天 md 的"喝水"子杯前 N 个改成 `- [x]`,其余 `- [ ]` |
| 换杯图标 | **长按 480ms** 任意一杯 | 端侧抠图 → POST `/api/water-cup` 存 base64 dataURL → 8 杯全换 |
| 历史日 | — | 所有手势失效,只渲染状态 |

**允许**:
- 滑动时**实时**预览水位变化(松手才真落盘)。点亮的过渡可以有"墨晕涌起"那种慢动作。
- 视觉上区分"刚被点亮的那杯(刚 just)"vs"早就在那的杯",鼓励微动效。
- 长按时给"杯子在被注视"的视觉信号(微震 + 微提亮 + haptic vibrate 12ms 已在前端)。

**不允许**:
- 不能改成"按 N 次 +1"模式——滑动是核心动作,这是为了"在床上单手操作"。
- 不能把 8 杯拆分成两行——cd 可以调间距/尺寸,但是**横向单行**是肌肉记忆。
- 不能在杯子上叠数字、百分比、calorie 之类的"数据可视化"。
  正下方"<b>N</b> / 8 杯"那一行说明文字 cd 可以重做措辞和排版,但**总要有这行**(无视觉占位 = 用户不知道喝几了)。
- 不能把"长按换杯"换成右上小齿轮——隐喻就是"按住这个杯子,我想换"。

### 状态 / 启用

- **默认开**,用户/AI 可关。
- 关闭状态持久化在 `localStorage["gateway.mobile.setting/widget_states"]` 的 `{cups: false}`。
- 关掉后整块从日记页消失(不是淡灰)。

### 视觉自由度边界

cd 可以重做:杯子的形态(玻璃/陶瓷/搪瓷/茶杯/任何)、水的质感(液面/纹理/反光)、
点亮 vs 未点亮的对比、整排的间距和呼吸、"<b>6</b> / 8 杯"那行说明的字体和排印、
"长按换杯"小提示的位置和说法。

cd **不能改**:
- 横排单行 8 个
- "滑动 = 改水位"的手势(后端按 x 坐标算 idx)
- 长按 480ms 阈值(跟下面 tasks widget 共用同一肌肉记忆)
- md 落盘的子杯结构(子杯勾选数 = `water_filled`,这是 PC 跟 mobile 同源的契约)

---

## 2 · tasks · 今日打卡

### 用户场景

葱鸭每天吃 4 种补剂(鱼油、苏糖酸镁、南非醉茄、D3+K2)。早上一颗一颗吃,
吃完一个就 tap 一下对应那个圆 chip。**横排一行 chip 直接点亮**——不打开列表、
不进入二级页。

某天他想看南非醉茄还剩几粒,**长按那个 chip**,底部弹起一张 sheet,里面有:
换图标 / 改每天吃几粒(daily_dose)/ 改瓶装颗数(total_pills)/ 看本周完成率 /
想要新打卡项 / 删除。

如果他给某项设了瓶装总数(比如 60 粒)和每天剂量(2 粒),系统会自动算出**还能吃几天**
(`days_left = total_pills / daily_dose`),≤3 天时 chip 角上贴一个**红色徽标"3d"**
警示该买了。

某项每天要吃 2 粒以上(`daily_dose >= 2`)时,父行下面会展开 N 个**子 box**,
让用户分次打卡——吃了第 1 粒勾一个、吃了第 2 粒再勾一个。剂量 1 粒的项不展开子 box。

### 数据 schema

`GET /api/daily-tasks?date=<iso>` 返回:

```js
{
  tasks: [
    {
      name: "鱼油",                    // 显示名
      checked: bool,                    // 今日是否吃够
      image_url: string | null,         // 端侧抠图过的 PNG dataURL,无图时显示首字母
      total_pills: int | null,          // 瓶装总颗数(用户自填,可空 = 不追踪剩余)
      daily_dose: int,                  // 每天吃几粒,默认 1
      today_intake: int,                // 今天已吃几粒(从 intake_log 派生)
      days_left: int | undefined,       // 算出来的剩余天数,仅 total_pills && daily_dose 都有时存在
      remaining: null,                  // 占位,暂不用
    },
    // ... 4 项
  ],
  water_filled: int,
  date: "2026-06-25",
  is_today: bool,
  is_writable: bool,                    // 服务端判定的可写窗口(今天 + 昨天 12:00 前)
}
```

### 交互合约

| 动作 | 触发 | 落盘语义 |
|---|---|---|
| 打勾/取消 | tap chip | POST `/api/daily-tasks/check` → `today_intake` clamp [0, daily_dose],intake>=dose 时 md 父行 `[x]`,否则 `[ ]`;`daily_dose>=2` 时子 box 按 `today_intake` 个数勾 |
| 弹管理 sheet | **长按 480ms** chip | 弹底部 sheet,5 项动作见下 |
| 历史日 | — | chip 全部 disabled(显示但不可点) |

管理 sheet 五项动作:

1. **换图标** — 选图 → 端侧抠图(Capacitor Cutout 插件,失败回退原图)→ POST `/api/daily-tasks/set-image`
2. **改 meta** — 数字输入 `daily_dose` 和 `total_pills` → POST `/api/daily-tasks/meta`
3. **看本周完成率** — `GET /api/daily-tasks/history?days=14&name=` → 14 天小点矩阵 + 百分比 + 图例
4. **想要新打卡项** — 关 sheet + 切到 chat tab + 在输入框预填"我想加一个新打卡项:" + emit signal `want_new_task`(AI 接住接续追问)
5. **删除** — 确认页 → POST `/api/daily-tasks/delete` → 当天 md 补剂段删行 + 清 image + 清 meta

**允许**:
- 横滑 chip 行(`overflow-x: auto`),不限制项数(用户可能加到 6-8 项)
- 余量徽标 ≤3 红 / 4-7 暖色提示 / ≥8 不显示——cd 可自定 threshold 视觉(默认仅 ≤3 红警)
- 已勾 vs 未勾 chip 的视觉差(填色/边框/纹理任选)
- 子 box(`dose>=2` 时)cd 可自由设计——叠在父 chip 下、跟父平排的小点、刻度尺都行,但**总要表达"今日 N/M 粒"**

**不允许**:
- 不能把 chip 改成卡片(描边一刀切)
- 不能把"长按管理"换成"chip 上加齿轮 icon"(图标视觉污染补剂段)
- 不能改 5 项 sheet 的内容(删/加是 PC 对等契约,删它们就丢功能了)
- 不能让 chip "横滑直接删"——这跟时间线 entry 左滑删冲突。删 = 长按进 sheet 走"删除"路径
- 不能用红色圆圈数字徽标(像未读消息提醒)——`days_left` 徽标得是"药快没了"的隐喻而不是"未读"的隐喻

### 状态 / 启用

- **默认开**,用户/AI 可关。
- 关闭状态跟 cups 同源 localStorage。
- 关掉后只是"今日打卡"这块消失;打卡数据本身在 md 里,不会丢。

### 视觉自由度边界

cd 可以重做:chip 形态(圆/方/胶囊/药丸轮廓)、已勾/未勾的视觉对比方式、横滑容器的边
缘渐隐(fade-out 提示可继续滑)、徽标的视觉隐喻(数字、沙漏、月亮、药粒倒下都行)、
子 box 的形态、长按时的视觉反馈。

cd **不能改**:
- 横排单行 chip(可滚动),不能改成网格
- 长按 480ms 阈值
- "想要新打卡项"跳 chat 预填这条交互(是 AI 共写日记 DNA 的入口)
- md 补剂段的字节结构(`- [ ] 名字` 顶层 + `  - [ ]` 子 box,字节级 PC parity)

---

## 3 · pulse · 今日 PULSE 状态汇总

### 用户场景

葱鸭白天打开 app 想知道"今天到底过得怎么样",一眼看到这一行:
**4/4 打卡 · 6/8 水 · 5 entries · 21:30 · 待写**。
不用进任何页面,他立刻知道:补剂吃完了、水还差两杯、白天写了 5 段、晚上还没写纸条。

这行不是"过去"的总结,而是**当下进度**。它跟桌面 `.gw-pulse` 镜像同源但**计算
在本机**——mobile 端不联网就能派生,所以叫"本机 pulse"(区分桌面的项目级 PULSE 镜像)。

### 数据 schema

不是从 API 拉,是**纯本地派生**(在 widget render ctx 里实时算):

```js
{
  tasks_done:   int,    // ctx.tasks.filter(t => t.checked).length
  tasks_total:  int,    // ctx.tasks.length
  water_filled: int,    // ctx.water_filled
  entries:      int,    // ctx.j.blocks 中所有 h2 里"有标题或正文"的条目数
  note_state:   "已写" | "待写",  // ctx.j.has_note(当天 21:30 H2 段是否写过)
}
```

### 交互合约

| 动作 | 触发 | 行为 |
|---|---|---|
| (远期)tap 展开详细 | tap 整行 | 当前无实现,plan 里挂着 |

目前**只读**,不可点。视觉上不应该呈现"按钮感"——它是一行小报。

**允许**:
- 整行排印自由,可以用分隔符(`·` `|` `/` 装饰线,都行)
- 各 cell 之间的视觉权重可以错落(打卡 > 水 > entries > 21:30 也行)
- "21:30 · 待写"那个 cell 在过了 21:30 还没写时可以加视觉提示(变色/微动/小图标)
- 全部满项(4/4 + 8/8 + entries 多 + 已写)时给一种"今天圆满"的视觉印记

**不允许**:
- 不能改成图表/进度条/环——这是一行**文字**,不是数据可视化
- 不能加 sparkline、不能加 % 数字、不能加趋势箭头
- 不能改成"点击 cell 跳到对应 widget"(诱导误触,scope 外)

### 状态 / 启用

- **默认关**。用户在设置里启用 / AI 通过 `set_widget_enabled({id:"pulse", enabled:true})` 启用。
- 启用后位置固定在关怀区第 3 行(cups · tasks 之后)。

### 视觉自由度边界

cd 可以重做:整行的字体/字号节奏、cell 间分隔的视觉(竖线/点/装饰)、数字的强调方式
(粗体/异色/字号差)、"满项"时的视觉印记(朱印/星标/装饰)。

cd **不能改**:
- 4 个 cell 的内容和顺序(打卡 → 水 → entries → 21:30 状态)
- 必须是**单行**——不能拆两行(就算挤,也得挤;挤是隐喻)
- 不能加任何 chart/graph

---

## 4 · mood · 今天心情

### 用户场景

葱鸭打开 app,关怀区里有一行 7 个 emoji 横着:
😴 🙂 😐 😟 😣 🤔 🤩,他 tap 其中一个,这个变高亮。
**已选的 emoji 再 tap 一下就取消**(不是必填,是"今天想标就标")。

明天打开,昨天选的还在;后天打开,大前天没选的就空着。
**这条数据只在本机**(`localStorage`),不上传、不进 md。

### 数据 schema

本机 only:`localStorage["gateway.mobile.setting/mood/<iso-date>"] = "<emoji>" | absent`

固定 7 个 emoji,**顺序固定**:`["😴", "🙂", "😐", "😟", "😣", "🤔", "🤩"]`
(从沉睡 → 平静 → 中性 → 担忧 → 痛苦 → 思考 → 兴奋,非严格线性)

### 交互合约

| 动作 | 触发 | 落盘 |
|---|---|---|
| 选 mood | tap 任一 emoji | localStorage 写入对应日期 key |
| 取消 mood | tap 当前已选的 emoji | localStorage 删 key |
| 切换 | tap 另一个 emoji | localStorage 改写当前 key 的值 |
| 历史日 | tap | 同今天,可以补改任意一天的 mood |

**允许**:
- 已选 vs 未选 emoji 的视觉对比(大小/光晕/底色)cd 自由
- 容器形状/排列方式 cd 自由(但必须**单行 7 个**)
- 选中态可以加动效(微震、放大、墨晕)
- 提示文字"今天心情 · 点一下选"cd 可以重做措辞和位置

**不允许**:
- 不能改 emoji 本身——这 7 个是肌肉记忆。增减 emoji = 历史 mood 数据语义漂移
- 不能引入"打分滑条"(emoji 是隐喻不是评分)
- 不能让 mood 落进 md(这是肌肉记忆设计——mood 是**私人的、轻的、不留档的**,跟 entry 是两套语义)

### 状态 / 启用

- **默认关**。跟 pulse 一样需要用户/AI 启用。
- 启用顺序:cups → tasks → pulse(若启)→ mood(若启)

### 视觉自由度边界

cd 可以重做:emoji 容器(圆形 chip / 方形 / 无容器单 emoji)、间距、选中态的视觉、整块标题
("今天心情")的排印。

cd **不能改**:
- 单行 7 emoji
- 这 7 个 emoji 本身
- 数据落本机 localStorage(不进 md,不进 setting API)

---

## 5 · widget runtime + AI 动态 add_widget

### 这是什么

mobile 端有一个轻量的 widget 注册表(`window.gwWidgets`),负责:

1. **核心 widget 注册** — cups / tasks / pulse / mood 启动时注册进去
2. **slot 装载** — 日记页 render 时调 `gwWidgets.mountInto(container, "care", ctx)`,
   按注册顺序把所有 enabled + slot 匹配的 widget render 进容器
3. **enable / disable 持久化** — 切换状态存 localStorage,跨 reload 保留
4. **AI 动态 add** — AI 可通过 `add_widget` tool 注册一个**新 widget**(运行时活的,不进二进制)

### AI 动态 add_widget 工具

AI 在对话里可以调:

```js
add_widget({
  id: "lunch_log",                                    // 唯一 id,不能跟核心冲突
  title: "午饭打卡",                                  // 显示标题
  slot: "care",                                       // 当前只支持 "care"
  template: "<div>今天吃了 {{tasks_done}}/{{tasks_total}} 项 · 还有 {{minutes_to_2130}} 分到 21:30</div>"
})
```

执行后这个 widget **立刻出现在关怀区**(append 到末尾),持久化在
`setting/widgets/lunch_log`,下次打开 app 还在。

**对应工具**:`remove_widget({id})` 删一个 AI 加的(不能删核心 cups/tasks/pulse/mood)、
`list_widgets()` 看当前都装了什么、`set_widget_enabled({id, enabled})` 开关任一 widget。

### 模板的 6 个安全变量

`template` 字段里只支持 `{{var}}` 双花括号插值,**有且只有这 6 个变量**:

| 变量 | 类型 | 含义 |
|---|---|---|
| `tasks_done` | int | 今日已勾打卡数 |
| `tasks_total` | int | 今日打卡总项数 |
| `water_filled` | int | 今日喝水杯数(0-8) |
| `entries_count` | int | 今日时间线 entry 数(有标题或有正文的 h2) |
| `date` | string | 当前页日期,`YYYY-MM-DD` |
| `minutes_to_2130` | int | 距今天 21:30 还有几分钟(过点 = 0) |
| `note_state` | string | `"已写"` 或 `"待写"`(21:30 纸条状态) |

(变量集**只能在 mobile 端代码里扩**,AI 在对话里不能新增。)

### XSS 防御

`template` 是 AI 提供的字符串,**模板插值的每个变量都经过 HTML escape**
(`& < > "` 全转实体)。AI 在 template 里写的 HTML 标签**不 escape**——这是设计:
AI 可以写 `<div>`、`<span>`、`<b>`、内联 style 等结构标签。

cd 在这里要做一个判断:**给 AI 加的 widget 设计一个"默认外观"**——一个统一的
"AI 装上来的小器官"视觉容器,让任何没指定视觉的 dynamic widget 自动套用。
当前实现给了一个最小骨架:

```html
<div class="gw-care-block gw-widget-dyn">
  <div class="gw-care-label">{title}</div>
  <div class="gw-widget-body">{template 插值后的 HTML}</div>
</div>
```

cd 可以重做 `.gw-widget-dyn` 的视觉,让"AI 加的"有一种**可识别的来源感**——
区别于核心 widget 的"产品自带感"。隐喻方向(供 cd 参考,不限定):
- 朱印感(AI 盖了个章)
- 便签贴(AI 贴上来的纸条)
- 不同纸色(AI 用了另一种纸)
- 浮雕感(AI 的笔迹微微凸起)
- 任何能让用户 1 秒识别"这不是我装的,是 AI 装的"

**不允许的视觉方向**:
- "AI 字样"标签直接打上去(俗气)
- "delete this AI widget"删除按钮挂在 widget 上(应该走 sheet 或 chat 命令)
- 用 robot / 机器人 icon(违反 DESIGN_BRIEF 铁律 "AI 是空气不是按钮")

### 交互合约

| 动作 | 触发 | 行为 |
|---|---|---|
| AI add | chat 里 AI 调 `add_widget` | 注册 + 持久化 + 立刻 mount 进关怀区末尾 + flash 提示 |
| AI remove | chat 里 AI 调 `remove_widget` | 从 registry + 持久化里删,日记页重 render |
| 用户启用 / 停用 | (远期)设置页"小组件"列表 | `gwWidgets.setEnabled(id, on)` + 持久化 |
| AI 启用 / 停用 | chat 里 AI 调 `set_widget_enabled` | 同上 |

(本期 cd 不需要设计设置页的小组件列表——MVP 范围里那条入口被关了,但 runtime 的
启停状态是接好的,远期开。)

### 状态可见性

- AI 动态 add 一个 widget 时,关怀区**直接长出来一块**——视觉上让用户能感觉到
  "AI 刚刚伸手放了一张便签上去"
- 第一次出现可以有一段入场动画(滑入 / 淡入 / 墨晕),但**只在首次注册时**,
  之后 reload 直接静态出现(避免每次开 app 都演一遍)

### 视觉自由度边界

cd 可以自由设计:dynamic widget 的默认外观(`.gw-widget-dyn`)、首次注册的入场动效、
跟核心 widget 在视觉上的"作者差异"(核心是用户的、动态是 AI 的)。

cd **不能改**:
- 6 个安全变量(改了 AI tool 描述要同改,scope 外)
- `{{var}}` 插值的 escape 入口(改了开 XSS 洞)
- 核心 widget 4 个 id(`cups` / `tasks` / `pulse` / `mood`)受保护——AI 不能 add 同 id 也不能 remove
- 注册顺序 = 显示顺序(核心 4 个固定在前,AI 加的全部在后)

---

## 6 · 给 cd 的总览 checklist

设计这 4 块 + 动态 widget 默认外观时,自查一遍:

- [ ] 关怀区**不是 4 张并排卡片**,是**竖向流动的小报栏目**
- [ ] cups 是**横向单行 8 杯**,滑动/长按是核心动作
- [ ] tasks 是**横向单行 chip**(可滚动),打勾/长按 sheet 是核心动作
- [ ] pulse 是**单行文字小报**,不能图表化
- [ ] mood 是**单行 7 emoji**,不能数字打分化
- [ ] 长按阈值 480ms 不变(cups/tasks 共用)
- [ ] dynamic widget 有自己的"AI 来源感"视觉,但不出现 robot / "AI" 字样
- [ ] 所有 widget 都有"今天已圆满 / 一片空白 / 历史日只读"三种状态的视觉
- [ ] 不引入卡片描边一刀切;不引入 dashboard 弹跳动效
- [ ] 不污染 md 真源的字节结构(本档不涉及 css,但 cd 也别在 mock 里手写 md 结构)

