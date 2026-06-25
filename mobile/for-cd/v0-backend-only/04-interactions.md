# 04 · 移动端核心交互流程

> 这一份只描述「数据 + 行为 + 约束」,不规定视觉。颜色/字体/动画曲线/边距/语气词
> 都由你决定。每节末尾的「可重做但不能改的」是契约线 —— 越过那条线,行为就坏了。
> 写给 cd 这个角色看,不是 dev。
>
> 适用范围:本文 5 节都是「非 widget、非 tool 的纯前台交互流」。widget 的视觉
> 容器规范在 02,AI 工具调用气泡在 03,本篇专注用户的手指落在屏幕上之后,
> 那一段路怎么走。

---

## 1 · chat 输入区

### 这是什么

底栏的输入条。横向三件:**[贴图按钮] [textarea] [发送按钮]**。
贴了图之后会在 chatbar **上方**多出一行缩略图 chip(可叉),叫 **附件预览行**
(`gw-attach-chips`)。

只在 chat tab 出现。journal tab 时这一整条不存在 —— 那里是一个悬浮的 + 按钮
(见第 3 节)。

### 数据 schema

```
state.pendingAttachments = [
  { url: "/attachments/xxx.jpg", dataUrl: "data:image/jpeg;base64,..." },
  ...
]
```

- `url` 是 server 端 path(`POST /api/chat/upload-image` 返回),最终拼进
  user message 末尾交给 AI
- `dataUrl` 是本地 base64,用来即时显示缩略图,**不发送**
- 发送瞬间 `pendingAttachments` 复制一份给 `sendChat()`,然后清空

发出的 user message 长这样(text + 附件标记拼在一段里,不是两个 message):

```
我贴了张图,你看看

(我贴了 1 张图: /attachments/xxx.jpg)
```

### 用户场景

> 「我贴了张图,你看看」+ 点 [+] + 选张图 → 附件预览行长出一个缩略图 chip
> → textarea 里继续打字 → 点发送 → user 气泡里带着缩略图飞上去 → AI 开始回

整条路要顺得像「拍照发微信」那种肌肉记忆,但又得让人感觉这不是聊天软件,
是「跟一个一起写日记的同伴说话」。

### 交互合约 —— 允许什么 / 不允许什么

| 行为 | 状态 |
|------|------|
| 没图也能发(text 不空 → send 启用) | ✓ |
| 没字只有图也能发(`pendingAttachments` 不空 → send 启用) | ✓ |
| 字图都没 → send 禁用(灰着,不响应点击) | 强制 |
| textarea 高度自动撑(最高 96px,超了内部滚动) | 强制 |
| Enter 发送、Shift+Enter 换行 | 强制(键盘用户) |
| 同时贴多张图(多次点 [+] 累加 chip) | ✓ |
| chip 上有叉(×)可单独移除 | 强制 |
| 发送瞬间:textarea 清空、chip 行清空、附件预览行收起 | 强制 |
| 选图取消 / 上传失败 → 不阻塞输入,只 toast 提示 | 强制 |

### iOS 约束

- iOS Safari/WKWebView 的**键盘弹起会顶高 viewport**,你的底栏需要跟着键盘走
  (不能被键盘盖住)。已知:`visualViewport` API 是唯一可靠的拿键盘高度的方式
- 真机选图走 Capacitor Camera plugin(原生 picker);浏览器 fallback 是
  `<input type="file" accept="image/*">`。**视觉上你不知道是哪个**,picker UI 是
  系统给的,你管不到 —— 但点 [+] 按钮和拿到结果之间的等待视觉(loading)归你
- iOS 状态栏 + Home indicator 安全区:底栏要给 `env(safe-area-inset-bottom)` 留位
- WKWebView 长 textarea 滚动时**容易把整页一起滚走**,需要在 textarea focus 时
  锁住外层 scroll(已是 dev 责任,但视觉上要意识到键盘弹起后这一屏的可视区只剩
  一半)

### cd 视觉自由度

**可以重做的**:贴图按钮的形态(不限于 +)、send 按钮的形态(不限于纸飞机)、
chip 的形状(方/圆/角章/便签角)、附件预览行从下方长出来的动画(滑/淡/翻)、
textarea placeholder 文案、键盘弹起后底栏的过渡感。

**不能改的**:三件套的横向顺序([贴图] [输入] [发送]) —— 用户右手拇指的肌肉记忆;
chip 的叉(×)必须**永远在右上角且永远可点**(底层契约,不是视觉细节);
send 禁用态必须**视觉上明显是禁用**(不能只是淡一点 —— 用户会以为是 AI 在思考)。

---

## 2 · 日记 entry 长按 + swipe

### 这是什么

journal tab 时间线上每一块半小时 entry 卡片。每张卡上能做三件事:

| 手势 | 当前实现 | 目标形态(本 brief 描述的目标态) |
|------|----------|----------|
| **tap** | 进入编辑(openCard) | 同 |
| **swipe ←** | 左滑超 60px → 删除 + 5s 撤回 | 同 |
| **长按 ≥ 480ms** | 拉进对话(pullToChat,变成 chat ref) | 弹 sheet:加内容/改/划掉收纸/贴贴纸/管理 daily-task |

> 注:**长按当前**是「指给 AI 看」的捷径 —— 但和 PC 端右键菜单不对等。
> 本节描述的是**对等之后**的目标形态,长按 = 弹 sheet,sheet 里有
> 「✦ 指给 AI 看」也作为其中一项,保留原捷径不丢。

### 数据 schema

entry 的内部结构(从 mobile.js 的 `state.entries[]`):

```
{
  time: "14:30",
  h: {
    tags: ["gateway", "桌宠"],
    title: "把 vision pipeline 收口",
    body: "...markdown 原文...",
    commits: ["...@user 批注...", "...@ai 批注..."]   // 拼回保住协作签字
  }
}
```

删除走 `POST /api/journal/delete-block`;撤回走 `POST /api/journal/patch`
**同位回填**(把删时留下的占位 `##` H2 替换成原 H2 + body + commits 三件套)。
**不是** insert 到末尾 —— 那会跟原占位块共存,同一时间块出现两次。

### 用户场景

#### 场景 A · swipe 删除 + 撤回

> 看到一块写得很烂的 entry → 拇指从右往左滑卡片 → 卡片跟手左移 → 超过半屏宽
> 一半 → 松手 → 卡片从右侧飞出去 → 底部出现一条「已删除「xxx 标题」[撤回]」+
> 5 秒倒计时进度条 → **5 秒内点撤回** → 卡片从右侧滑回来,内容(含批注)完整还原

5 秒过了不撤回,**真删** —— md 文件层面会留一个占位 `##` 块(协议:占位 H2 表示
「这个时间块有人写过又删了」)。

#### 场景 B · 长按弹 sheet

> 觉得自己刚写完的那块还想加几句 → 长按卡片 → 轻微震一下(haptic) → 底部
> 升起一片 sheet → 选「加内容」→ 进 openCard 预填该 entry → 改完保存

sheet 里能做的事(对齐 PC 右键菜单,**按目标态**列):

1. **改一块** — 走 openCard 编辑(第 3 节)
2. **加内容(append)** — 给该块末尾 append 一段(append_journal_comment 路径)
3. **划掉收纸** — 「这块不要了但留个划掉痕迹」,不真删,只盖一层划痕。**纸的语义**,
   禁垃圾桶 icon
4. **贴贴纸 / 贴张图** — scrapbook 流(把图贴在 entry 上)
5. **指给 AI 看 ✦** — 等价当前 pullToChat:这块变成 chat 里的一个 ref bubble,
   AI 知道你在指哪一块
6. **管理 daily-task** —(只在这块包含打卡时长出)进入第 5 节 widget 的管理面板

sheet 必须**可以下滑关掉**、可以点空白关掉、可以 Esc/back 键关掉(iOS 没 back,
但 swipe-from-left-edge 算)。

### 交互合约 —— 允许什么 / 不允许什么

| 行为 | 状态 |
|------|------|
| swipe 阈值固定 60px(满意度 ≤ 5% 才会做出来) | 强制 |
| swipe 跟手只允许左 → 不允许右滑(右滑是 iOS 系统返回手势,会冲突) | 强制 |
| 长按阈值 480ms(实测出来的「不会误触」最低值) | 强制 |
| 长按 arming 时(指还按着,sheet 还没弹) → 卡片要有「正在 arm」的视觉反馈 | 强制 |
| 长按途中如果指头移动超 8px → 中止 arming(用户在 scroll,不是长按) | 强制 |
| swipe 进行中(`mode=swipe`)→ 长按 timer 必须立刻 clear | 强制 |
| swipe 没到阈值 → 卡片回弹原位 | 强制 |
| swipe 超阈值 → 卡片继续往左飞出屏幕(不是停在原地等动画) | 强制 |
| 删除 → 5s 内最多一个撤回 toast(再删一个,前一个 toast 直接被替换) | 强制 |
| 只读日(过去的、未来的)→ swipe 删除禁用(只剩 tap 进只读 viewer) | 强制 |
| 删除禁用「垃圾桶 icon」—— 用纸的语义(撕、揉、划) | DESIGN_BRIEF 铁律 |
| 撤回 toast 不能用 OK/Cancel 这种 SaaS 措辞 | 同上 |

### iOS 约束

- iOS 长按默认会触发「文本选择 + Lookup」气泡 —— **必须** CSS
  `-webkit-user-select: none; -webkit-touch-callout: none` 把它关掉,否则你设计的
  长按 sheet 还没弹,系统的选择气泡先弹出来盖住整块卡片
- `navigator.vibrate(12)` 在 iOS 上**不工作**(只 Android 有),haptic 走
  Capacitor `Haptics.impact` plugin 或者纯视觉震一下
- pointer event 跟 touch event 在 iOS WKWebView 里行为有差,长按手势必须用
  pointer 才能跟 Android/桌面 dev 调试统一(已是 dev 责任,但视觉上要意识到:
  你看到的「长按 → sheet 升起」的延迟,**其中 480ms 是产品决策,不是性能问题**)
- 撤回 toast 必须在 `safe-area-inset-bottom` 之上(否则被 Home indicator 遮住)

### cd 视觉自由度

**可以重做的**:卡片的形状/纸感/影子;swipe 跟手时的视觉反馈(露出底层一片「将要
被撕掉」的暗区?或者卡片本身染上痕迹?);卡片飞出屏的轨迹(直线?抛物线?转一下?);
撤回 toast 的形态(条?便签?折角?);撤回倒计时进度条的样式(墨迹?沙漏?);长按
arming 的视觉(微微浮起?四角发热?墨晕?);sheet 升起的动画(底部上推?纸卷展开?
便笺夹起?);sheet 里每一项的样式(列表?贴纸?印章?)。

**不能改的**:swipe 方向只能向左、阈值 60px、长按 ≥ 480ms 才弹(否则 scroll 误触);
sheet 必须**可下滑关、可点空白关**(没有这条 iOS 用户会被困住);删除流必须**先视觉
确认再 5s 撤回**(不是「弹个 confirm modal」—— 那是 SaaS 思路)。

---

## 3 · + 悬浮按钮 + openCard 编辑器

### 这是什么

journal tab **右下角悬浮一个圆形 + 按钮**(`gw-fab-float`,**不占底栏空间**)。
点它 → 从底部升起一片 sheet 形态的编辑器叫 **openCard**。

openCard 有两种 mode:**新建**(传入 nothing)+ **编辑**(传入 existing entry)。
唯一区别:编辑时锁时间块(不能改 HH:MM)、tag/title/body 预填、commits 在保存时
被客户端拼回保住批注。

### 数据 schema

openCard 表单里 6 个字段:

```
{
  date:   "2026-06-25",           // 锁(当天)
  time:   "14:30",                 // 编辑时锁,新建时可选
  tags:   ["gateway", "桌宠"],   // 6 个 SUGGEST chip(可点亮)+ 自由输入
  title:  "把 vision pipeline 收口",   // 可空
  body:   "...markdown 原文...",        // 含 ![](attachment_url)
  // commits 不在 UI 里,但编辑时客户端会从 existing.h.commits 取出来拼回 new_md 末尾
}
```

提交时走两条路:
- **新建** → `POST /api/journal/insert-block` { date, time, tag, title, body }
- **编辑** → `POST /api/journal/patch` { date, time, new_md, author: "user" }
  - `new_md` = `"## #tag title\n\n{body}\n\n{commits}"`(commits 是 user/AI 之前
    留的批注,**不拼回 = 协作签字丢**,这是 6.16 翻过的坑)

### SUGGEST tag 列表(本项目当前默认)

```
["#gateway", "#a股", "#身体", "#桌宠", "#杂", "#风险"]
```

这是**用户当前的 6 个高频 tag**,不是固定值 —— 未来会从用户日记里抽统计。
你设计 chip 时要假设它可能变化、可能多到 8-10 个、可能少到 3 个。

### 用户场景

#### 场景 A · 新建

> 点 + → 底部升 sheet → 默认 tag 是 #gateway(已点亮)、时间填了现在的整点或半点、
> title 空、body 空 → 改 tag(点亮/熄灭)、按「现在/整点/半」快速调时间(也可以
> 直接改数字)、写标题、写正文、可选点「+ 贴张图」拼 `![](url)` 进 body → 点
> 「落笔」→ sheet 落下、journal 重 load、新 entry 出现在时间线对应位置

#### 场景 B · 编辑

> 长按 sheet 选「改一块」(或当前实现:tap entry)→ openCard 升起、所有字段预填、
> **HH/MM 是 readonly**(灰色不可改)、时间快捷按钮(现在/整点/半)被隐藏 →
> 改 title/tags/body → 点「改完」→ patch 路径,commits 被客户端拼回保住

### 交互合约 —— 允许什么 / 不允许什么

| 行为 | 状态 |
|------|------|
| 新建时默认时间 = 当前小时 + (现在分钟<30 ? "00" : "30")  | 强制 |
| 新建时默认 tag = `#gateway` 已点亮 | 强制 |
| 时间 input `inputmode="numeric"` + maxlength=2  | 强制 |
| 时间块**步长必须是 30 分钟**(半小时块协议),「:15」「:42」会跟时间线对不齐 | 强制 |
| 编辑时 HH/MM readonly + 时间快捷区隐藏 | 强制 |
| 编辑时**必须**拼回 existing.h.commits 到 new_md 末尾(否则 @user/@ai 批注丢) | 强制 |
| author 字段:编辑 = "user"(用户手动改)、AI 自动写入 = "ai" | 强制(authorship boundary) |
| 自由输入新 tag → 自动补 `#` 前缀(用户漏打那个号不挡路) | 强制 |
| tag chip 列表里点亮过的 + 新输入的,**统统**进 picked 集合 | 强制 |
| 「+ 贴张图」走 `/api/chat/upload-image` → 把 `![](url)` 拼进 body 末尾 | 强制 |
| sheet 关掉方式:点 × / 点空白(scrim)/ 下滑(任一种都行) | 强制 |
| sheet 关掉前**不**确认「真的不保存吗」(信任用户) | 设计哲学 |

### iOS 约束

- iOS 数字 input 必须 `inputmode="numeric"` 才能弹数字键盘(不是 `type=number`,
  那玩意会带 spinner)
- iOS sheet 弹起时,如果 body textarea focus,**键盘会顶高整张 sheet** —— 你的
  sheet 高度需要 dynamic、需要在 textarea focus 时能 scroll 到视图内
- iOS Capacitor Camera plugin 选图后返回 base64 dataUrl,你的「+ 贴张图」点击后
  到拼回 body 之间有个**上传等待期** —— 这段空窗的视觉归你管(loading? 化墨? 涟漪?)
- iOS WKWebView 的 textarea 在 sheet 里 focus 时**整页可能上滑**,需要锁外层 scroll
  (已是 dev 责任,但你画 sheet 时假设它**会**在键盘弹起后变成视口的上半部分)

### cd 视觉自由度

**可以重做的**:+ 按钮的形态、位置微调(右下、底中、悬浮高度);sheet 升起的动画
(滑、卷、翻、拉);time 输入的视觉(数字 input?滚轮?拨盘?但请注意 iOS 拨盘 UX 是
个坑,数字 input 最稳);tag chip 的形态(圆角?印章?标签?);「现在/整点/半」三个
快捷按钮的样式;「落笔」/「改完」按钮文案(可以更有意思但**不能**变 OK/Save);
保存后的反馈(toast?墨晕?纸入信封?);「+ 贴张图」的入口视觉。

**不能改的**:时间步长 30 分钟、编辑时 HH/MM readonly、编辑时必须拼 commits、
作者标签必须分 user/ai 走两套 API、新建时默认时间逻辑(现在小时 + 半小时 round)。

---

## 4 · ③ C lazy 21:30 纸条仪式

### 这是什么

桌面端有个 21:30 cron:每晚 9 点半 AI 在当天日记的 **# 21：30** 块下面留一段
「睡前纸条」。

但**移动端没 cron**(iOS 后台不让跑 Python sidecar,launchd 不存在)。所以
移动端用 **lazy** 模式:**用户每次打开 app 时检查**,如果当天 21:30 H2 块
还是占位 `##`,**就在那个时刻**调 DeepSeek 出一段写进去。

用户视角:「早上打开 app 就看到 AI 昨晚留的纸条」—— 即使**实际**是早上 7 点
打开时才生成的。**这是个善意的错觉,纸条写在 21:30 块下,protocol 保住**。

### 数据流

```
app DOMContentLoaded
  ↓
有 deepseek key?
  ↓ 是
GET /api/note/check-lazy
  ↓
读今天 md → 找 # 21：30 H1 块 → 找下面第一个 H2
  ↓
是占位 ## 且没有 body? → 继续(否则 skip)
  ↓
listJournalDates → 过去 7 天倒序 → 提取每天 # 21：30 H2 body
  ↓
组装 past_boards = "## 6.24\n\n{body}\n\n---\n\n## 6.23\n\n{body}\n\n..."
  ↓
调 DeepSeek (model: deepseek-chat, stream: false, timeout: 90s):
  system = "你是用户的日记 AI 协作者。每晚 21:30 给他留一段纸条 — 这是仪式。
            ① 看见今天他写了什么,具体说几个细节(不空泛、不套话)
            ② 给一两句真实感受 — 鼓励、提醒、或一个轻的回应,不要长篇大论
            ③ 不超过 120 字
            ④ 语气像睡前关灯前那段话,温柔、私人、不像 AI"
            + past_boards + 今天写了什么
  user = "现在写今晚的纸条。"
  ↓
返回 noteText(可能空)
  ↓
PATCH /api/journal/patch {
  date: today, time: "21:30",
  new_md: "## 纸条 @ai\n\n{noteText}",
  author: "ai"
}
  ↓
loadDay 触发 → 时间线 21:30 块从「占位」变成「AI 纸条」
```

### 用户场景

> 早上 7 点,起床打开 app → 顶栏 logo 缓缓亮起 → 时间线 load 出来,看见昨天最后
> 一块的下方多了一片「纸条 @ai · 21:30 写于昨夜」→ 上面是一段温柔的、不到 120 字
> 的话,内容指向昨天他真的做过的事(不是空泛祝福)

「写于昨夜」是**叙事善意**,实际是早上 7 点生成的。MD 时间戳是 21:30 H2 块下,
跟桌面端协议对齐。**这条 brief 不撒谎,但 UI 上你应该让用户感受到「她昨夜在写」
的氛围**(纸的纹理上有夜的痕迹? 字的墨色更深一点?)。

### 交互合约 —— 允许什么 / 不允许什么

| 行为 | 状态 |
|------|------|
| 触发时机:**每次 app 启动一次**(不是定时,不是 21:30 触发) | 强制 |
| 没 deepseek key → skip,不触发(用户连钥匙都没填) | 强制 |
| 当天 21:30 H2 已有 body(非占位 `##`)→ skip(不重写) | 强制 |
| 没找到当天 md 文件 → skip(用户今天还没新建日记) | 强制 |
| 没找到 # 21：30 H1 块 → skip(用户改了模板) | 强制 |
| past_boards 最多取过去 7 天 21:30 H2 body(跨夜连贯) | 强制(对齐桌面 cron) |
| 写入位置:**当天** md 的 # 21：30 H1 下,第一个 H2 替换占位为 `## 纸条 @ai\n\n{noteText}` | 强制 |
| author=ai(走 authorship boundary,不能再被 AI 改) | 强制 |
| AI 输出空字符串 → skip,不写空块 | 强制 |
| 触发时**不**给用户看 loading(后台静默,纸条出现是惊喜不是任务) | 设计哲学 |
| 触发失败(网络断/key 错)→ 静默,**不**给用户看错误(下次再试) | 设计哲学 |
| 写入成功后 → loadDay 重渲染时间线,纸条**自然出现**(不需要特殊弹窗) | 强制 |

### iOS 约束

- DeepSeek API 调用走 Capacitor `CapacitorHttp` plugin(避免 WebView CORS + 走原生
  HTTP 客户端,可设 connectTimeout/readTimeout = 90s 等慢回应)
- iOS app 冷启动时 launch screen 在显示 → DOMContentLoaded → check-lazy 异步触发。
  **launch screen 期间**不应该让用户感觉「卡住等纸条」—— check-lazy 是后台跑、
  load 完日记时纸条**可能还没回来**,过一会儿才自然出现
- iOS 13+ 后端任务限制:如果用户切走 app 再切回,WKWebView 可能 reload 整个页面 →
  check-lazy 会再触发一次,但因为已写过(非占位)→ skip,**幂等**

### cd 视觉自由度

**可以重做的**:纸条出现时是淡入还是墨水晕开;纸条本身的视觉(便签?信纸?
书页边缘?手写感?字体?字号?);「纸条 @ai」标题样式;字体是否衬线/宋体/楷体;
背景是否带夜的纹理(蓝灰?月光?);纸条上方是否有时间戳「写于昨夜 21:30」的
小字;读完后是否有「合上」的视觉。

**不能改的**:必须落在 # 21：30 H1 下、必须 H2 = `## 纸条 @ai`、必须 author=ai、
触发条件(打开 app + 占位 ## + 有 key + 有当天 md)、120 字内、past_boards 7 天、
**不在前台显示生成过程**(纸条出现必须像「她写完离开了,留在桌上」,而不是
「她现在正在键盘上敲」)。

---

## 5 · ⑤ E 信号通道 + ⑥ F 用户意图采集

### 这是什么

产品自带的**轻量遥测**。两条独立信号合用一个云端 sink(`feedback.yanpaidb.cn/signal`):

- **⑤ E 全局错误捕获** — `window.onerror` + `unhandledrejection`,只盖硬错误
  (软错误不上报,避免噪音)
- **⑥ F 用户意图采集** — 三处:① onboarding 风格偏好选项 ② 设置里「我想要新功能」
  按钮 ③ chat 输入扫词 ④ 长按 task sheet「想要新打卡项」

**不是**「想看用户聊啥」—— 严格遵守三条契约:

1. **fire-and-forget** — 失败静默不阻塞 UI,**永远不 throw**
2. **无持久化** — 仅 sessionStorage 临时 anon_sid(避免 iOS ATT 弹窗)
3. **无 PII** — 对话原文不上报,只上报 kind + ≤200 字命中片段

### 数据 schema

```
POST https://feedback.yanpaidb.cn/signal
{
  kind: "want_widget" | "want_paper" | "want_desktop_parity"
      | "onboard_style" | "want_button_click" | "want_new_task"
      | "error.runtime" | "error.promise",
  payload: {
    // 因 kind 而异 —— 举例:
    excerpt: "我想要一个新的打卡项,记录...",   // chat 扫词命中,≤ 200 字
    answer:  "A",                                 // onboarding 风格答 A/B
    from:    "settings" | "task_sheet"            // 触发位置
    msg:     "...",   src: "..."                  // error 时的硬错误信息,≤ 200 字
  },
  platform: "mobile-ios",
  ts: 1719324567890,
  anon_sid: "s-x7k9m2pq"
}
```

### 5.1 · onboarding 风格偏好(双钥匙完成后 +1 题)

#### 用户场景

> 双钥匙(DeepSeek + 阿里云百炼)填完测过 → 翻下一节「想了解你一点 · 可跳过」 →
> 出现一段话:「手机端,你想要的体验是?」+ 两个选项:
>   - **A · 简洁高效**
>   - **B · 像桌面那样精致**
> → 用户点 A 或 B(也可以不点直接「进入」/「跳过」)→ emit 信号 `onboard_style`

#### 合约

| 行为 | 状态 |
|------|------|
| 必须可跳过(显式「先跳过,进去看看」按钮) | 强制 |
| 不点也能进 app(默认行为不被这道题挡住) | 强制 |
| 选过的答案存 localStorage `gateway.mobile.setting/style_preference` | 强制 |
| 「进入」/「跳过」前 emit `onboard_style` 信号(only if 选过) | 强制 |
| 题目文案**不**带「为了给您更好的体验」之类客服味 | 设计哲学 |

### 5.2 · 设置里「我想要新功能 / 新视觉」按钮

#### 用户场景

> 进设置 → 滚到底部一节叫「告诉我们你想要」→ 一行按钮「我想要新功能 / 新视觉」+
> 下面小字「跳进对话告诉 AI,我们一起想。」→ 点 → 关掉设置子页 → 跳到 chat tab →
> 输入框已预填「我想要」,光标在末尾等用户接着写 → emit `want_button_click`,
> from: "settings"

#### 合约

| 行为 | 状态 |
|------|------|
| 点击 → emit 信号 + 关掉当前子页 + 跳 chat tab + textarea 预填「我想要」+ focus | 强制 |
| 不弹任何 confirm | 强制 |
| 用户改主意可直接清空 textarea(没保留义务) | 强制 |

### 5.3 · 长按打卡 sheet「想要新打卡项」入口

#### 用户场景

> 长按某个打卡卡片(daily-task widget)→ sheet 升起,有换图/改 N 粒/历史/删 几项 →
> 底部多一行**轻飘**的「想要新打卡项」→ 点 → emit `want_new_task` 信号 → 关掉 sheet
> + 跳 chat tab + 预填「我想要新打卡项」(逻辑同 5.2,from: "task_sheet")

#### 合约

| 行为 | 状态 |
|------|------|
| 这一行**视觉权重低于**上面的实际功能项(不抢主路) | 强制 |
| 不是「+ 添加新打卡」(那是承诺;这是意图采集 —— **跟 AI 商量**,不是直接加) | 重要 |
| emit 后路径同 5.2 | 强制 |

### 5.4 · chat 扫词隐式信号

#### 用户场景

> 用户在 chat 输入「我想要纸感」+ 发送 → 在 sendChat 之前,客户端**自己**扫这段话,
> 命中正则 → emit `want_paper` 信号(payload.excerpt = 前 200 字) → 然后再走 sendChat
> 流程(emit 是 fire-and-forget,不阻塞)

#### 三个扫词正则(当前实现)

```
want_widget:         /想加|想要 ?widget|搞个面板|加打卡|加 ?widget/
want_paper:          /界面太普通|太简洁|想要纸感|有质感|想要纸/
want_desktop_parity: /像桌面那样|跟桌面一样|桌面有手机没有/
```

#### 合约

| 行为 | 状态 |
|------|------|
| 扫词在 sendChat 入口跑,**fire-and-forget** | 强制 |
| 命中多个 kind → 各 emit 一次(不去重) | 强制 |
| 用户**完全感知不到**这次扫描(无视觉、无 toast) | 强制 |
| excerpt 永远 ≤ 200 字(避免泄漏长文) | 强制 |
| 这一条**不**告诉用户「我们在记录」—— 但隐私政策必须写明 | 重要(合规底线) |

### 5.5 · 错误自动上报

#### 用户场景

> 用户发现某操作崩了 → app 上**不弹错误 modal**(已是设计哲学,见 DESIGN_BRIEF
> 「AI 是隐形协作者」)→ window.onerror / unhandledrejection 捕获 → emit
> `error.runtime` 或 `error.promise` → 用户看到的可能只是某动作没生效,
> 但开发者拿到信号去修

#### 合约

| 行为 | 状态 |
|------|------|
| 只盖硬错误(JS exception / promise reject)| 强制 |
| 软错误(网络失败、API 4xx)走具体 UI 提示(toast),**不**走 error.* 信号 | 强制 |
| 上报 msg ≤ 200 字、src(文件名)≤ 100 字 | 强制 |
| __GW_SIGNAL_BOUND__ 守卫:全局只绑一次(避免重复 emit) | 强制 |
| 用户看不到「正在上报错误」字样 | 强制 |

### iOS 约束

- iOS App Tracking Transparency(ATT)框架:**任何跨 app 跟踪都要弹用户授权**。
  本通道**走 anon sessionStorage**(刷新 app 就换 sid)+ 无 PII + 无设备 ID → 不属于
  ATT 管辖,**但隐私政策仍需写明「匿名遥测」**,否则 App Store 评审会挑
- iOS WKWebView 的 `sessionStorage` 在 app 完全杀掉后清掉(不是 page reload,是
  process kill)。**这正是想要的**:无长期持久化
- 信号 sink endpoint(`feedback.yanpaidb.cn`)走 HTTPS,iOS ATS 不会拒
- emit 走 `realFetch`(不被 shim 拦) —— **不要**经过 `/api/*` 路由,否则会被
  mobile-api.js 自己的 shim 截下来当 404

### cd 视觉自由度

**可以重做的**:onboarding 第三节的措辞「想了解你一点 · 可跳过」、A/B 选项的措辞
和呈现(对比卡? 平铺?);设置里「我想要新功能」按钮的视觉(印章?手写感「想 + 」?);
task sheet 里「想要新打卡项」那一行的样式(便签角?手撕痕迹?);跳 chat 预填后的
visual cue(输入框微微荡一下? 光标墨色加深?)。

**不能改的**:

- **不能可见地报错** —— DESIGN_BRIEF 铁律「AI 是隐形协作者」,信号采集也跟着隐形
- **不能** add 一个「数据上报开关」放在设置里(那等于宣告我们在记录,产品调性会塌)
  —— 取而代之的是**让用户明显感觉「我说了什么,后面真的有变化」**,这是软合同
- **不能** 在隐私政策外加任何「我们在收集您的反馈」措辞
- **不能** 把 onboarding 第三节做成必答题(挡用户路 = 拉新转化崩)
- **不能** 把 chat 扫词信号搞成显式提示(「检测到您想要 widget,要不要…」是 SaaS 噩梦)

---

## 五节通用约束(贯穿全文,不重复)

- **MD 是真相**(DESIGN_BRIEF 铁律):任何 UI 操作最终落 md 文件 + author 字段必带
- **AI 是隐形协作者**(同上):没有 button、没有 modal、没有「AI 正在工作」spinner;
  AI 的存在通过**结果出现**而不是**过程展示**来传达
- **纸的语义**(同上):删除、撤回、撕、揉、墨、晕、折,**不是**垃圾桶/勾选/√/×
- **iOS safe-area-inset-{top,bottom,left,right} 必须留位**(状态栏、Home indicator、
  横屏 notch)
- **reduced-motion 用户**(系统设置开了「减少动效」):所有上述动画必须有降级,
  最低降到「即时切换无动画」,但**不**降到「行为差异」(swipe 删除还是要能 swipe)
- **错误不阻塞**:网络断、API 失败、上传失败,全部走 toast/whisper,**不**弹 modal
- **本文每一句「强制」都是 dev 已经实现或正在实现的契约**。「设计哲学」是
  DESIGN_BRIEF 反复确认过的产品调性,违反它产品会塌

