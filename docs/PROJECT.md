# 项目: human-ai-schedule

> agents 创作平台中的"日记 + 协议 + 可视化"项目。
> Skill 源：`~/cltrc+v code/skills/human-ai-schedule/`（ctrl-c-v-code-skills repo）
> Runtime：`~/.claude/skills/human-ai-schedule/`（sync-runtime.sh 部署）

---

## 一句话

半小时块日记的协议 + 数据 + viewer 三件套——人写、AI 写、人 + AI 共写的日记体系。

## 项目组成（散落在 platform 各处，本文件作总入口）

| 组件 | 路径 | 角色 |
|------|------|------|
| **数据** | `~/.human-ai/vault/半小时复盘/*.md` | 每天一个 md，★源头真相(真源;`数据库/valut/` 是 5 月冻结镜像勿用) |
| **标签聚合** | `~/.human-ai/vault/标签聚合.md` | 项目维度的横切索引 |
| **PULSE 镜像** | `~/.human-ai/vault/PULSE/` | 4 个项目 PULSE 进 Obsidian 浏览口 |
| **gateway 总览** | `gateway/index.html` | 主入口（widget loader + 私印小报基调） |
| **gateway 单日** | `gateway/day.html` | v0.2 私印小报 monolith（v0.4 待 widget 化） |
| **widget 引擎** | `gateway/shared/widget-loader.js` | 读 `.user-widgets.json` 动态拼装 |
| **reference widgets** | `gateway/widgets/{supplements,steps,mood}/` | 3 类型示例供未来 AI copy |
| **gateway 扩展协议** | [`gateway-extension/`](gateway-extension/) | 给未来 AI 看：怎么加 widget |
| **设计 brief** | [`DESIGN_BRIEF.md`](DESIGN_BRIEF.md) | viewer 大改版的氛围 brief |
| **传播手册** | [`spread/小红书运营手册.md`](spread/小红书运营手册.md) | 传播线作战文件：四层漏斗 + 三栏目 + 风控红线 + 数据周报 |
| **Skill 源** | `~/cltrc+v code/skills/human-ai-schedule/` | description + § H0-H9 + playbooks |
| **同步脚本** | `scripts/sync-pulse-to-vault.sh` | PULSE 单向镜像进 vault |
| **时间戳 hook** | `~/.claude/scripts/timeblock-stamp.sh` | UserPromptSubmit 注入 `[time-block]` 信号 |
| **Drift hook** | `~/.claude/scripts/schedule-drift-check.sh` | 周一+周五 Stop hook 检测 drift |

## 此 vault 注册的项目标签（§ H3 vocabulary）

进聚合页的 project tag：
- `#yanpai` — 演牌 / investment-dashboard 合规面 + 技术面（子标签 `/传播` — 自媒体 / 内测拉新 / 出门见人，6.11 拎出）
- `#ESP32` — claudebuddy 桌宠项目
- `#配置系统` — Claude Code 自身 skill / hook 迭代（子标签 `/ctrl-c-v` `/tdd` `/schedule`）

观望中（出现 3 次以上再入聚合页）：
- `#晨会 #探索 #思考` — 5.12 起出现的新 tag

不进聚合（generic）：
- `#运动 #饮食 #娱乐 #午休 #晚饭 #on-the-road #社交 #摸鱼 #看盘 #工作`

## 该 vault 的日常工作流

```
新一天 → bash scripts/new-day.sh → 自动按"5.3=第一天"算第 N 天 + 拷模板
进 session → UserPromptSubmit hook 注入 [time-block] + [skill-required]
AI 写入 → 读 [time-block] block 标签 → 落到对应 H1 下 H2
项目标签段 → 同轮镜像进标签聚合.md
周一周五 → drift-check Stop hook 自动扫漏 + 提示
周日 → § H9 PULSE refresh 仪式（手动触发）
每轮结束 → sync-pulse-to-vault.sh 静默把 PULSE 镜像进 vault
```

## DIY 模板

`SCHEDULE_TEMPLATE.md` 顶部是用户自定 section（补剂打卡 / morning standup / etc.）。
本 vault 当前定制：每日补剂 4 项打卡。
改法：编辑 `~/.claude/skills/human-ai-schedule/templates/SCHEDULE_TEMPLATE.md` 顶部 → 下一次新建日记自动用新模板。

## 待办

- [ ] **内测前清债执行** — v0.1.20 已收 22 件 P1+P2;v0.1.21+22 B 补录 6 件 high;v0.1.23 接入腾讯云 CDN HTTP(cdn.yanpaidb.cn);v0.1.24 trivial bump 测自更新触发(yanpai sync 卡在 VPN 抽风,truncate);**SSL 死锁** — CDN CNAME 接入下 DV 探针永远 NXDOMAIN;**自更新 UX 不对** — silent download_and_install 违反"用户授权拉流量"基本契约。**v0.1.25 双修**:① 换 update.yanpaidb.cn 直 A + Caddy + LE 绕开 SSL 死锁、② 加询问 modal + 进度条;详 [`human-ai-dev/gateway/INTERNAL_TEST_BACKLOG.md`](../../../human-ai-dev/gateway/INTERNAL_TEST_BACKLOG.md)。**P4 服务端 deploy** 命令在 backlog P4 段。
- [ ] **设计 logo(收集候选 + 最后竞标)** — 桌面图标 / favicon / 启动器共用。氛围参 [DESIGN_BRIEF.md](DESIGN_BRIEF.md):安静 / 慢 / 像纸 / 私人 / 深夜 11 点低光下舒服。**先 logo,再做套壳**(没图标的 .app 在 Dock 里是默认灰方块,不能给用户)。
  - 候选 v1 · **Si+C 共价键**:碳硅都 4 价电子→ SiC 共价键 = 人–AI 共享外层电子。文件 [brand/logo.svg](brand/logo.svg) / [brand/logo-animated.svg](brand/logo-animated.svg) / [brand/preview.html](brand/preview.html)
  - 候选 v2..vN · _待加_
  - 决策方式:**所有候选放 preview 页并排,看大小 / 暗底 / 远看 / 缩到 favicon 哪个还认得出 → 竞标定 v1.0**
- [ ] **桌面一键启动套壳** — Mac `.app`(Platypus 或自写 shell wrapper)+ Win `.bat`,内跑 `python3 -m uvicorn server:app --host 127.0.0.1 --port 4321` + 自动开浏览器到 `http://127.0.0.1:4321/`。论证见 26.5.16 17:00 那块讨论(不用 Docker,Docker 跟"打开即用"DNA 冲突)。
- [ ] **PyInstaller 单二进制**(P1) — 解决"用户没装 Python"。跨平台需 Mac/Win/Linux 三台机分别打。
- [ ] **迁移测试** — 把当前 .dmg 拿到一台干净 Mac 装,从零跑通 fresh install:阿里云 key 填进去 → 拖图 → AI 抠图 + 贴 entry → 21:30 留言板出来。验"单 API 解锁全部能力"这条 UX 假设在新机器上真的成立。
- [ ] **苹果开发者认证 + notarization** — Apple Developer 账号($99/年)+ 应用签名 + notarize,让 .dmg 拖装时不再触发 Gatekeeper "无法验证开发者"那个弹窗。配套 universal2 binary(Intel mac 也能跑)。完整发版矩阵 + GitHub Actions secrets / Win DigiCert / Linux AppImage / mobile 不做 等清单见 [RELEASE_TEMPLATE.md](RELEASE_TEMPLATE.md)。
- [ ] **远期:独立 deepseek API 通道** — 跟阿里云通道并存。仪式感设计:阿里云负责装"眼睛"(vision/OCR),deepseek 才是"说话"的那个。详见 memory [bailian-deepseek-ritual]。
- [ ] **远期:i18n sweep(多语言 + TZ 修活)** — 真有海外用户报"AI thinks I'm in China"之前不动。届时一起做:`_compute_time_block_hint()` 的 hardcoded "CST" 改成 `astimezone().tzname()`;UI 文案表(`shared/*.js` 大量中文);日期格式(`26.5.20(第十八天).md` 这种命名约定要不要改);全角冒号 `：` 海外 Obsidian 兼容。**架构上 gateway 因为 single-user + local-first 比微信简单一个数量级**,真正成本就这些。
- [ ] **侧边栏后台看板 + 搜索健康信号(5.28 之后做)** — 量"运行时实际行为",不靠 cron/源码漂移哨兵(github via Clash 不稳 + 间接信号)。最小版:`_360_search` 失败/降级百炼时记可见计数 → 留言板每晚顺手提一句"国内搜后端最近降级 N 次,该重 port 了"。看板版:独立小页展示后端命中率/降级率/最近失败样本。优先看板,但先建信号管道(没信号看板也空)。讨论见 5.27 23:30 之后。
- [x] **内测期 silent-failure 反馈通道** — 5.29 全栈搭好,v0.1.19+v0.1.20 收口:① `_sanitize_sf_context` 白名单(C-#9);② consent gate 撤回期不写本地(C-#4);③ /forget GDPR/PIPL 撤回真删(C-#10);④ X-Admin-Token 第二闸守 /stats /recent (C-#5);⑤ append+trim+cursor 三写者 lock + fsync(A-H6+H11);⑥ vault_git daemon 失败接通道,连续 5 次 → 用户通知(A-H13)。剩 P1-#3+ keyring(留 v0.1.21)+ updater HTTPS 客户端切换(等 server Caddy deploy 后 v0.1.21)。
- [ ] **viewer canvas + sticker(远期)** — 半小时块时序保留,在 entry 上加贴纸 layer(JSON 旁路存 sticker URL+x/y+缩放/旋转,MD 真源不动)。MVP 3-5 天:Fluent Emoji(MIT)+ Excalidraw libraries(草图风,贴 Maggie Appleton 数字花园美学)+ 拖拽 UI。**前提**:迁移测试拿到反馈说"日记太单调"才上,免造无人用功能。最贴 brief 的 source 是 vintage scrap collage SVG(Figma community 免费 pack),自己手挑几十个真贴"私印小报"那条 brief 铁律。

## 不要做的事

- 不要把 schedule 时间块凭"感觉"放——读 `[time-block]` 系统提醒，floor，不四舍五入
- 不要写技术细节散文（procedure dump）——只写 result + significance
- 不要直接编辑 `数据库/valut/PULSE/` 里的镜像——它会被下轮 Stop hook 覆盖；改源 PULSE.md
- 不要在通用 generic tag 段（#运动 #饮食 等）写项目工作——会漏入聚合页
- 不要绕过 [skill-required] 直接动 schedule 文件（globaly CLAUDE.md 硬合同）

## 时间锚点入口

- viewer Day 1 落地 → [26.5.12#17：00](../../数据库/valut/半小时复盘/26.5.12(第十天).md#17：00)
- skills 通用化 sweep → [26.5.10#21：30](../../数据库/valut/半小时复盘/26.5.10(第八天).md#21：30)
- vault 同步链 v1 → [26.5.10#22：30](../../数据库/valut/半小时复盘/26.5.10(第八天).md#22：30)
- 时间戳系统上线 → [26.5.10](../../数据库/valut/半小时复盘/26.5.10(第八天).md)（同日 timestamp-system commit）
- skill 自身化 → [26.5.9#16：30](../../数据库/valut/半小时复盘/26.5.9(第七天).md#16：30)
