# 葱鸭 · USER PULSE

> Length budget: 12000 字 · Stale threshold: 60 天未刷新 → LLM 应评估删除
> Last refreshed: 2026-06-05 · 演化方式:LLM 自由重写,server 只验时间戳格式 + 总长

<!-- ts:2026-06-05 -->
## 一句话
券商业余时间用 AI (Claude Code) 搭了一套日记+投资工具+硬件玩具的本地优先产品矩阵,human-ai-schedule 桌面壳 + 自动更新 + 跨境下载链路全通,已从"准备分发"切到"出门见人启动期"。

<!-- ts:2026-06-05 -->
## 当下气压
🟡 **出门见人启动期 — 工程节奏明显从"堆功能"切到"打磨 + 修 dogfood 反馈"**。Tauri 桌面壳 Mac 端落地,自动更新链路接通 yanpai feedback-sink,跨境下载页 gateway.yanpaidb.cn 上线;Win 端从 PyInstaller standalone 迁到 Tauri shell 撞了 6 轮 smoke 失败才发现真因是 PyInstaller 默认 --onedir 跟 Tauri externalBin 不兼容 — 一条典型的"Mac dogfood 永远验不出的 Win-only 雷"。dogfood 自家 Win 设备时一次性反馈 5 条产品级 bug(默认补剂带 user 私人药名 / 隐私 modal 太复杂 / "第N天"基准 hardcoded / DeepSeek 调不动水杯工具 / patch H2 锁太死),已批量修完。**主线**:让 Win 真机跑通(--onefile fix CI 验证中)+ Apple 认证 + 把内测发出去看真用户反应;身体状态在过去 10 天 schedule 里几乎没出现,可能继续在清账,也可能项目兴奋盖过了感觉。

## 心跳（本周 / 本月 实际动作）

<!-- ts:2026-06-05 -->
- **Tauri 桌面壳 Mac 端落地 + 自动更新链路接通**:Gateway 从浏览器 launcher 升成独立窗口应用,启动后台 check yanpai feedback-sink `/updates/latest.json` minisign 验签下载;走自家服务器 host 避免 GitHub 跨境慢(见 [5.27] [6.1])

<!-- ts:2026-06-05 -->
- **silent-failure 反馈通道全栈上线**:客户端 ~30 类 error_type 接 37 处 hook,持久化 UUID + 后台 sender thread,服务端 FastAPI + SQLite 部署到 yanpai;内测期"AI 反应怪怪的"那类静默失败终于能远端看到(见 [5.29#21:00–22:00])

<!-- ts:2026-06-05 -->
- **跨境下载页 gateway.yanpaidb.cn 上线**:本机当中转(Clash 翻墙拉 GitHub Release + rsync 推 yanpai),陌生人扫码秒装;Caddy edge + LE 自动签证 + ICP 公安备案脚标(见 [6.4#10:30])

<!-- ts:2026-06-05 -->
- **Win 端从 PyInstaller 迁到 Tauri shell**:6 轮 smoke 失败,最后查 Tauri 官方 doc 发现 externalBin 要求 PyInstaller `--onefile`,Win YAML 默认 onedir 没带 `_internal/` 散文件;Mac 一直对的因为 build-sidecar.sh 一开始就照 doc 写 --onefile(见 6.5 v0.1.10 fix)

<!-- ts:2026-06-05 -->
- **dogfood 自家 Win 设备扫出一批产品级 bug**:默认补剂模板带 user 私人药名 / 隐私 modal 太复杂 / "第N天"hardcoded 基准对新机器永远显示"第33天" / DeepSeek 调不动 set_water_cup_image / patch_journal_block H2 锁太死(AI 帮 user 改 17:00 标题被拒);批量修完进 v0.1.8+(见 6.4 用户反馈批)

<!-- ts:2026-06-05 -->
- **把 gateway 从「工单味工具」改到「搭子感」**:精简了 prompt、去掉了工具人话术,token 砍 41%

<!-- ts:2026-06-05 -->
- **启动 Apple Developer 公司注册**:D-U-N-S 直接命中已有记录省了一个月,现在卡在借 iPhone 完成 enrollment

<!-- ts:2026-06-05 -->
- **给 vault 装上自动 git + training corpus 全栈**:任何日记写入自动 commit,历史可导出为 JSONL 训练数据,consent dashboard 上线

<!-- ts:2026-06-05 -->
- **投资上持续跟踪联想(AI 叙事兑现 +20%)、BEST 聚变、FSD 入华**,把"框架优于订单"这个 pattern 串了三条线

## 节律（日常 pattern）

<!-- ts:2026-06-05 -->
- **起床**:闹钟 7:40,实际 8-9 点起,质量波动大
- **上午**:工作晨会处理客户(调佣、开户、认证),中间穿插和 AI 协作开发
- **午饭**:大米先生、肠粉、麦当劳,比较随意
- **下午**:工作下午场穿插项目开发,15-17 点经常安排运动(健身房力量/拳击/普拉提/筋膜刀)
- **晚饭**:麦当劳出现频率极高,偶尔点外卖炒菜
- **晚上**:18-23 点是项目开发黄金时段,经常到 23 点以后
- **补剂**:每天打卡鱼油/镁/醉茄/D3,但经常漏
- **周末**:社交(约会 blue、朋友聚会)、娱乐(CSGO 决赛、LOL),项目节奏放慢

## 协作偏好（怎么跟他说话 + 怎么不踩雷）

<!-- ts:2026-06-05 -->
- **先出完整草稿让他审,不要逐项问**:他说"你的判断是对的,所以你以后只需要写完给我审核就行"。AI 推断的部分标清楚 `[CC 推断 — 你审核]`,他事后调。

<!-- ts:2026-06-05 -->
- **做事 vs 想事要分清**:`#协作` 标签只打「一起完成具体工作」不包「帮忙想/综述」。别把帮他理思路也标成协作。

<!-- ts:2026-06-05 -->
- **UI 改动验收必须给截图**:别拿"数据字段对了"就当过,他亲口打回并强调"你怎么评估落对了的?"

<!-- ts:2026-06-05 -->
- **不要在他没说"记一下"时往日记里写东西**:这条红线清晰。

<!-- ts:2026-06-05 -->
- **commit 双签仅写风险/不确定性,不写表态**:他定下的规矩——"绝不写:表态、鼓励、复述结果。这些是噪音。"

<!-- ts:2026-06-05 -->
- **不要在远端 agent 上丢"你闭环修"这种指令**:Windows CC 选了最暴力路径把他的用户账户和 VSCode 配置全删了。任何 OS 级操作必须逐条问他。

<!-- ts:2026-06-05 -->
- **他不喜欢工具人味**:AI 别用"为您处理""已完成,请刷新"这类客服话术,要像搭子聊天。偶尔可以抬杠但不能杠精。

<!-- ts:2026-06-05 -->
- **数据所有权是他比较深层的价值观**:vault→LLM training corpus 这件事他兴奋的点是"用户=资本,不是平台=资本"。别随便把他的数据往外送。

<!-- ts:2026-06-05 -->
- **"别急着推"是节奏指令,不是否决**:CI 没绿 / multi-round 反复修没收敛时,他会说"别急着推"让 AI 停一手再看;意思是先 commit 锁住改动 + 想清楚再发版,不是放弃这条路。后面收敛了他会主动说"OK 开做"。

<!-- ts:2026-06-05 -->
- **multi-round 失败 ≥3 轮 → 必须先查 doc/web,别再凭猜继续**:Win Tauri smoke 连失败 5 轮我都在凭假设修(stdout 重定向 / Rust rx drain),第 6 轮被他点醒"上网查查"才查到 PyInstaller --onefile 才是真因。可迁移规则:连失败 3 轮以上,停止试错,去看官方 doc / GitHub issues。

<!-- ts:2026-06-05 -->
- **dogfood bug 报告是一批整理后才发,别每条单独动**:他攒着一批问题一起说,意思是希望我也一次看完一起 plan + 一起修,不要 fire-and-forget 单条单修。

## 历史阶段（人生 chapter）

<!-- ts:2026-06-05 -->
- **5.3 – 5.9** :搭建"半小时复盘"日记体系 + skill 化。花了 7 天把纯日记变成协议 + 标签 + 聚合页 + commit 双签的一套 harness。

<!-- ts:2026-06-05 -->
- **5.10 – 5.13** :协议和元工具闭环(PULSE、sync 脚本、viewer 起跑)。human-ai-schedule 项目成立。5.13 大跃迁日:一天 8 个 #配置系统/schedule 事件,viewer 从 v0.2 跨到 v0.3("是平台"→ 插件市场 + PULSE dashboard + MD 双向同步),同一天 yanpai 合规闭环。

<!-- ts:2026-06-05 -->
- **5.16 – 5.19** :高强度把 gateway 从 MVP 堆到"能出门":单 API 收敛、端侧抠图、vision-router、装机包打通。叙事从"扫尾"变成"准备分发"。

<!-- ts:2026-06-05 -->
- **5.20 – 5.26** :收敛期。发版模板沉淀、training corpus 论证、Apple Developer 注册启动。项目功能基本完整,人开始感觉到项目收尾后的身体疲劳。

<!-- ts:2026-06-05 -->
- **5.27 – 6.5** :出门见人启动期。Tauri 桌面壳 Mac 端落地 → silent-failure 反馈通道全栈 → 自动更新链路接通 yanpai → 跨境下载页 gateway.yanpaidb.cn 上线 → Win 端 Tauri 化撞 6 轮 smoke 真因是 PyInstaller --onefile。dogfood 自家 Win 设备扫出一批产品级 bug 整批修完。叙事从"准备出门"切到"已经出门,正在接住第一波 friction"。

<!-- ts:2026-06-05 -->
现在大概在 **第五章开端**:陌生人能扫码下、能装、能跑;接下来看真用户的 silent-failure 反馈通道里冒什么出来。

## 想做的（短期 + 长期）

**短期（2 周内）** :

<!-- ts:2026-06-05 -->
- Win Tauri 真机跑通(v0.1.10 --onefile fix 验证中) — 6 轮 smoke 之后的最终关
- Apple Developer 认证 + notarize DMG — 桌面壳已 Mac 端落地,下一步消 Gatekeeper 警告
- 内测发出去,看真用户在 silent-failure 反馈通道里冒什么(已部署到 yanpai,等流量)
- 让 cron 在 app 没启动时也能跑 — 当前 launchd 跑空气是 Tauri 化后的新常态,5.31 应用层兜底是临时方案
- 可能开始写 landing page / demo video

**中期（几个月）** :

<!-- ts:2026-06-05 -->
- 接 Apple Health 把步数/心率/睡眠流进 journal(从 5.14 就挂着)
- 小范围内测,改 bug
- 投资上密切跟踪联想、BEST 聚变、舜宇光学等标的

**长期（方向性）** :

<!-- ts:2026-06-05 -->
- 把 human-ai-schedule 变成"用户拥有的 AI 训练数据平台"
- 做出海(和陈楚棋讨论中美商业差异后坚定)
- ESP32 schedule 物理终端(先验需求再开模)
- 用韩国的全民红包模式论证"AI rent 再分配"

## 不要做的事（他坚决拒绝的）

**硬合同（踩了就炸）** :

<!-- ts:2026-06-05 -->
- **不要让 AI 字节级覆盖他的 `@user` 块**:他花了 8 层防御 + 13 个 pytest 把这搞定,这是"比任何性能优化都重要的事"。
- **不要在 OS 级别系统修复时给远端 agent "你自己闭环"的权限**
- **不要在测试中 rm/clobber 他的生产 state 文件** — 发生过一次全覆盖 38 条真实聊天历史的惨案。
- **不要在他没说"记一下"时往日记里写东西**
- **不要在 gateway 加"需要用户再配一个 key"的功能**,除非强论证
- **不要把远期 deepseek 独立通道做成简单的"切 provider"按钮** — 要仪式感角色分工
- **Win PyInstaller sidecar 必须 --onefile,不要 onedir** :Tauri externalBin 只识别单 .exe,onedir 的 `_internal/` 散文件复制不齐 sidecar 会静默崩 — Mac dogfood 永远验不出这条 Win-only 雷。
- **不要让 patch_journal_block 在 H2 不匹配时绕过 guard** :5.29 16:00 联想 entry 被舜宇覆盖那条恶性 bug 的防御层,user 想改标题时必须明示 `allow_h2_rename=true`,默认 false 不能动。
- **CI dispatch 用 --ref TAG 走的是 TAG 上的 YAML 不是 main 的** :想测最新 main 的 workflow 必须 bump 新 tag 重发,不能在老 tag 上 retry。

**价值观冲突（让他不爽的）** :

<!-- ts:2026-06-05 -->
- **不要用客服话术**("为您处理""已完成"),要像搭子聊天
- **不要把 AI 推断的 PULSE 状态当定论** — 他说"还是紧"后我改过来,强调"不要替用户感觉好坏"
- **不要假定他的数据可以随意上传** — 他对数据所有权敏感,training corpus 方案明确要 consent dashboard + PII redaction

**性能/流程问题** :

<!-- ts:2026-06-05 -->
- **不要在 schedule entries 里写 procedure dump(工具名/路径/版本号)** ,要 result + significance
- **JSONL 时间戳是 UTC,必须 +8 → CST 再写时间块**
- **UI 改动验收必看 viewport 截图**,数据字段对不算过
- **multi-file 实验性 feature 之前必须 commit**

## 时间锚点入口

<!-- ts:2026-06-05 -->
- **日记体系起步** → [5.3#16:00](数据库/valut/半小时复盘/26.5.3(第一天)-修正版.md#16:00)(第一次半小时复盘,"掌控自己的感觉挺不错")
- **协议 skill 化 + 推上 GitHub** → [5.9#16:30](数据库/valut/半小时复盘/26.5.9(第七天).md#16:30)
- **viewer 大跃迁日(v0.3)** → [5.13](数据库/valut/半小时复盘/26.5.13(第十一天).md)(一天 8 个 event,从工具跨到"是平台")
- **项目收敛日(单 API + 端侧抠图 + 装机包)** → [5.19](数据库/valut/半小时复盘/26.5.19(第十七天).md)
- **training corpus 上线日** → [5.24#14:30–16:00](数据库/valut/半小时复盘/26.5.24(第二十二天).md#14:30)(vault → LLM training data pipeline 全线贯通)
- **Tauri 桌面壳 Mac 端落地** → [5.27](数据库/valut/半小时复盘/26.5.27(第二十五天).md)(单窗口 .app + 单实例 + .dmg 一条龙)
- **silent-failure 反馈通道全栈上线日** → [5.29#21:00–22:00](数据库/valut/半小时复盘/26.5.29(第二十七天).md#21:00)(客户端 P1+P2+P3 + 服务端部署 + E2E 联调通)
- **自动更新链路接通日** → 6.1(Tauri updater + yanpai feedback-sink + minisign 验签 + deploy key sandbox)
- **跨境下载页 + Win Tauri saga** → [6.4](数据库/valut/半小时复盘/26.6.4(第33天).md)(gateway.yanpaidb.cn 上线 + Win Tauri 撞 6 轮 smoke + --onefile 真因)