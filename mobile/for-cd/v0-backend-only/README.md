# Mobile v0 · 反向 brief — 给 cd 看的入口

> 这一份不发指令、不下设计稿。这是一份**反向 brief**:把后端、数据和真机约束讲清楚,让 cd 在已有约束之内**自由重做视觉**。
> 路径:`agents/human-ai-schedule/mobile/for-cd/v0-backend-only/`
> 写给:claudedesign(下称 cd) · 创建:2026-06-25 · 葱鸭 × claude-opus-4.7 共写

---

## 1 · 这是什么 · 为什么提供

human-ai-schedule 的桌面端(gateway)已经定型并发了内测,paper 皮肤验收通过。
**移动端**(`mobile/m/`, Capacitor + WKWebView 装进 iOS)是 6.13 那天大转向之后的事 —— 把桌面 monolith 包进 webview 在触屏上是死路,改走原生手机交互(顶栏 + 渐变日期带 + 横滑打卡 + 时间线 + 悬浮 +)。

**为什么现在重新给 cd 出 brief?**

- **6.14 出过一版稿**,但项目随后再次转向(双端同步格式地基 + 移动 CRUD 闭环 + compact 真激活...),那版稿对应的产品形态已经偏了。
- 中间的设计 cache 已经删掉,**这次不是迭代,是重做一版**。
- 后端的硬合同(数据 schema / AI tool 集 / 真机约束)在过去 10 天里反复打磨,已经稳定 —— **现在是给 cd 一份不会再大改的输入的最佳时机**。

这份 brief 不是"按图施工"。后端、数据流、真机约束是契约,**视觉如何承载这些契约,由 cd 决定**。

---

## 2 · cd 的自由度 · 三条硬约束

### 自由(随便重做)

- 色板(沿用 paper token 也行、整套新做也行,但要双模式 day/night)
- 排版(单栏/不规则/纵向报头 都行,扛住卡片化的肌肉记忆即可)
- 入场动效(墨晕/纸页翻动/呼吸,但要**安静** —— 不要 dashboard 弹跳)
- 图标 / 装饰 / ornament / drop cap / 朱印 / sparkline 风格
- 信息密度(每平方厘米塞多少,cd 的呼吸)
- 各 widget 的视觉骨架(不必齐高、不必同款边框)

### 硬约束(违反 = 稿没法用,不是品味问题是架构红线)

1. **MD 是真相 · 浏览器/WKWebView 打开即用**
   写日记的真源始终是 markdown。HTML/移动端是热镜像,两边都能改,**md 始终是 canonical**。任何"必须 build / 必须 npm / 必须 server 才能渲染"的方案都死路。组件交付物必须是 vanilla HTML/CSS/JS,vendor 进 repo 锁版本。

2. **不卡片化 · 不 dashboard 感 · AI 是空气不是按钮**
   DESIGN_BRIEF 铁律。这一条在桌面端已经踩过 v1-v4 三轮反馈的坑 —— v1 死于"工具感"、右键浮窗方案被推翻、AI 做成按钮就是错。**AI 应是隐形协作者,通过 chip(03 描述)和留言板(02 描述)出现**,不是右上角永远在的按钮。

3. **气味:安静 / 慢 / 像纸 / 私人 / 深夜 11 点低光下舒服**
   `DESIGN_BRIEF.md` 第一稿就立的调子。不像 dashboard,不像 SaaS,像他自己的一本杂志。**双模式必交**:夜间偏深(深夜 11 点开台灯舒服),日间是米黄纸系(`#fefaf2 / #fffaf0 / #fbf6ec`)、棕墨 `#a86e46 / #7a6e5e`、朱砂 `#b14a2b / #b85a3b`。两模式共用同一份 token 变量,组件层零裸色值。

### 隐性约束(不写明但 cd 要扛住的)

- **CJK 排版优先**(中文衬线扛得住,深夜低光下舒服)
- **字体只 vendor 不走 CDN**(弱网/离线下 CDN 阻塞首屏 —— 桌面端踩过)
- **reduced-motion gate**(prefers-reduced-motion: reduce 时所有动画退化)
- **3 类作者并存**:用户(宋体)、AI(文楷)、commits 注解(小字) —— 笔迹即身份,零成本世界观
- **写操作禁 UI 惯性**:删除禁垃圾桶 icon(用纸的做法 —— 划掉收纸)、新增禁 FAB+、等待禁 spinner、对话禁纯气泡

---

## 3 · 推荐 cd 工作流

```
00 · 看完本 README(20 min)
       ↓
01 · vault-data-model.md   学底层 md 长啥样、taskmeta / taskintake_log
                           / widget manifest 怎么挂 —— 知道"AI 在写什么"
       ↓
02 · widgets.md            4 个核心 widget(八杯水 / 今日打卡 / 今日 PULSE
                           / 今天心情)+ 关怀区竖排骨架 —— 出视觉容器规范
       ↓
03 · ai-tools.md           18 个 AI tool 的 chip 三态(doing/ok/fail)+ 自然
                           句翻译 —— 出 chip 视觉规范
       ↓
04 · interactions.md       chatbar / 时间线 / 悬浮 + / 行内编辑 / 长按菜单
                           —— 出 5 套交互习语
       ↓
05 · ios-constraints.md    真机约束:390 基线 / safe-area / 键盘 / 字号
                           —— 验稿前 checklist
       ↓
06 · user-stories.md       3-5 个完整一天的用户故事 —— 走流不走单页
       ↓
出稿:① 单日页(关怀区 + 时间线 + chatbar)
       ② 关怀区 widget 容器 reference + 4 个 widget 视觉
       ③ chip 视觉(三态 + 自然句容器)
       ④ 5 套交互习语(行内编辑 / 长按 / 悬浮+ / 横滑 / 撤回)
       ⑤ token + components.css(双模式,接 components 同规矩)
```

**先交一屏竖切定气味,验收过再铺全套** —— 跟桌面 paper 皮肤的工作流一致。

**截图验收红线**(桌面踩过):
- 数据字段对 ≠ 用户看到的对 —— **每稿自己在浏览器开一遍再交**
- cd 的页面动画常驻,Playwright 截图会超时 —— **用 headless Chrome `--virtual-time-budget` 截**,或临时 URL 参数控状态
- **390 × 844 是基线**(iPhone 12-16 标准款),320 也不能崩(SE / 8),414+ 只留白别塞内容

---

## 4 · 设计 brief 历史脉络(必读不再讲第二遍)

桌面端 paper 皮肤定调时的核心几条,**移动端继承**:

- **5.12 DESIGN_BRIEF 初稿**:`安静 / 慢 / 像纸 / 私人 / 深夜 11 点低光下舒服`,Edward Tufte / Maggie Appleton / Stripe Press / 日本文学杂志 / NYT longform 是灵感坐标。
- **5.13 viewer 长成平台**:不是一页 viewer,是一本杂志的全部版面;widget 是用户跟 AI 对话长出来的,不是预设。
- **6.11 双模式定调**:夜间 + 日间共用 token,组件层零裸色值。
- **6.12 分工收窄**:cd = 素材(排版稿 + 图标效果 + 组件 css reference),CC = 组装(接真数据 / 写操作 / 红线守门)。**本 brief 沿用此分工**。
- **6.13 移动转向**:桌面 monolith 在触屏上是死路 —— 移动端必须按传统手机交互习语重做,但**视觉调性仍守 DESIGN_BRIEF**。
- **6.16 移动 CRUD 闭环 lesson**:产品状态以 grep 为准 —— 死按钮(plan 砍了但 UI 留入口)= 说谎。**cd 出的每个按钮 / 入口都要在 03/04 找得到对应 tool 或 endpoint**,找不到 = 删掉别画。

桌面端 paper 皮肤交付的成绩单:components.css 1900 行全家桶(写操作五件套 + 信笺消息流 + 折页 + 磨墨 + 设置家族 10 节 + 钥匙双角色 + 同意书朱印 + 诊断行)。**移动端不要求做到 1900 行体量**(原生交互习语跟桌面纸感拉锯),但**世界观要连续**:同一个 AI 在桌面写信笺、在移动写 chip,不能切出客服感。

---

## 5 · 关于"卡住的时候问谁"

后端的硬合同(数据 / AI tool / 约束)由本 brief 5 份 md 承担。设计层面遇到含糊地带,默认按 DESIGN_BRIEF 调性自决,**不要等回复** —— 拿稿来对就比拿问题等更快。

唯一例外:**红线**(MD 真源 / 无 build / 不卡片化 / AI 不当按钮 / 双模式)碰到了再问,问之前先 grep 本 README 看是不是已经写明。

---

---
