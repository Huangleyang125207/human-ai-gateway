# Gateway 移动端 · 后续工作计划

> 起点:2026-06-26 10:00 CST(PARITY CONVERGED + chat tool-loop 补 + OCR Phase A 完)
> 终点:iOS App Store + Android Google Play 双平台正式上线
> 估期:1 个月内 Public Beta,2 个月内正式上线

---

## 0 · 一句话

**今晚 30 分钟真机验完 → iOS 内测 1 周拿 20-30 装机 → Android 完善 2-3 周 → Public Beta 1 月 → 正式上线 2 月。**

---

## 1 · 今晚真机验证 Checklist(30-45 分钟)

> 目的:把 PARITY CONVERGED 的"代码就绪"变成"用户真能用"。
> 设备:iPhone(iOS 16+)+ 一瓶补剂(鱼油 / 维生素 D / 任意带"60 粒/180 capsules"字样)
> 前置:Phase 2 真机调试 runbook 走完(npm i + cap sync ios + Xcode signing)

| 验 | 测什么 | 预期 | 失败应急 |
|---|---|---|---|
| **① 装机 + 启动** | App 打开不闪退 + 看到日记单日页 | 1-2s 启动 → cd v0 视觉(顶栏 ☰ + 今日补剂 + 时间线) | 看 Xcode console log → 多半是 capacitor.config.json plugins 段错 |
| **② OCR 拍补剂瓶**(N2 验 ✅)| 加新打卡项 → 拍照 → 自动填 total_pills | label "60 粒" → catalog 拿到 total_pills=60 | 看 NativeOcr.available() / 退到云端百炼 / 检 dashscope key |
| **③ chat tool-loop**(X1 验 ✅)| 输入"帮我加一条 14:00 的 #工作 entry,内容写'做了真机验'" → AI 调 insert_journal_block → 真写入 | 收到流式回 + tool chip 三态 + 翻日记真有那条 | claim audit 若触发 → AI 确实没调,改 prompt 重试 |
| **④ 端侧抠图**(iOS 17+)| chatbar 贴一张图 → 自动抠主体 | 透明背景 PNG 贴日记 | iOS 17 以下 fall back 原图 |
| **⑤ 滑水 / 打卡** | 滑 4 杯水 + tap 鱼油 | localStorage 写入 + UI 立刻更新 + 重启后状态留存 | bridge.syncPulseState 防抖看 console |
| **⑥ 加 / 改 / 删日记** | openCard 新建 + 长按改 + 横滑删 + 5s 撤回 | md 字节级写 vault(对照桌面同 vault 字节一致)| reloadDay diff 看 mobile-api L1402 校验 |
| **⑦ 离线 fallback** | 飞行模式 → 用 app | 读写本地 OK,chat 报"无网"错误 | _ocrViaCloud / chat 兜底 |
| **⑧ 视觉验**(cd v0 5 件套)| iOS 真机 390px viewport | tokens 双模式(日/夜)+ 18 tool 自然句 + .gw-chip-tool 三态正确 | refresh cap copy ios + 验 cf=03 |

### 验证完成后

- 全过 → ledger N2 + X1 改 ✅(✅ 数 34 → 36,🟡 数 1 → 0)+ commit + Phase 3 TestFlight 准备
- 部分失败 → 写 issue + 当晚 fix(简单)或排进下周(复杂)

---

## 2 · Android 端完善工作清单

> 优先级排序:用户高频 × 工程量小先做
> 估期:Phase B(MLKit 完整工作)1-2 天 + Phase C(国行无 GMS 兜底)按真用户反馈

### 2.1 必做(发 Android 前)

| 项 | 工程量 | 说明 |
|---|---|---|
| **OCR Android 真机验**(`@capacitor-mlkit/text-recognition` Phase B)| 0.5 天 | 拿一台有 GMS 的 Android 设备(国行小米/华为可能没,海外版 Pixel/三星都有) |
| **抠主体 Android 实装**(MLKit Subject Segmentation 或 ML Kit Selfie Segmentation)| 1-2 天 | Android 12+ 自带,加 plugin/cutout/ 的 Android 实装(类似 ios/Sources/CutoutPlugin.swift)|
| **Android 真机 build runbook**(类似 iOS PHASE_2_RUNBOOK.md)| 0.5 天 | 走 `npx cap add android` + Android Studio 开 → run + signing key 配 |
| **AndroidManifest 权限文案**(camera / storage / internet)| 0.5 天 | Play Store 审核必要;中英文双语 |
| **Cleartext traffic policy**(对齐 iOS ATS)| 0.5 天 | Android 9+ 默认 block http;白名单 deepseek + 阿里云 + 内 cdn |

### 2.2 看真用户反馈再决定

| 项 | 触发条件 | 工程量 |
|---|---|---|
| **国行无 GMS PaddleOCR 兜底** | 真有华为 / 鸿蒙用户 + 不接受云端 OCR latency | 3-4 天 |
| **国内应用市场**(华为 / 小米 / OPPO / vivo 应用商店)| 国行用户量级足够 | 1-2 周(各家审核流程)|
| **国行 Android cutout 替代**(无 ML Kit Segmentation)| Android 11 及以下用户量足 | 2-3 天 |

---

## 3 · 上线三阶段规划

### 3.1 Beta 内测(iOS 优先,1-2 周)

**目标**:20-30 装机,silent failure 反馈通道沉淀真问题。

| 任务 | 估期 |
|---|---|
| Apple Developer 注册 + Mac codesign + Notarize | 已有(参考 RELEASE_TEMPLATE.md) |
| iOS App Store Connect 配置 + Beta provisioning profile | 0.5 天 |
| TestFlight 上传 v0.2.0 | 0.5 天 |
| 小红书内测群 + 同事亲友群拉新 | 持续 |
| Silent-failure feedback-sink server 部署到云(已 backlog P4)| 0.5 天 |
| 反馈日志监控 + 当周回滚机制 | 持续 |

**出口标准**:
- ≥ 20 装机
- 0 严重数据丢失 bug(authorship boundary / vault md 字节 / CAS)
- < 5 个高频 issue
- 用户写日记真 retention 5+ 天

### 3.2 Android Beta(iOS Beta 后第 2-3 周)

**目标**:跨平台双 Beta;海外 GMS 用户 + 部分国行用户。

| 任务 | 估期 |
|---|---|
| Android 完善工作清单 §2.1(OCR + cutout + build)| 3-4 天 |
| Google Play Console 注册($25 一次性)+ 内测 track | 0.5 天 |
| Beta APK 上传 + 评审(快 24h)| 1 天 |
| 国行渠道分发(直接 APK 下载,无 Play Services)| 0.5 天 |
| Android 真机反馈通道(同 iOS silent-failure)| 0 天(已有) |

**出口标准**:
- iOS + Android 共 ≥ 50 装机
- iOS / Android 体验一致(误差在文案 / 圆角 / 触感反馈级别)
- 跨平台数据同步(双端同 vault git 双向 push/pull)— **本期不做,留 Public Beta**

### 3.3 Public Beta(Beta 后第 4-6 周)

**目标**:小红书发文公测 + 邀请码扩散到 100-200 装机。

| 任务 | 估期 |
|---|---|
| 小红书运营手册执行(已沉淀 spread/小红书运营手册.md)| 持续 |
| TestFlight Beta link(iOS)+ Google Play 公测 track(Android)| 0.5 天 |
| 价格策略调研(免费 / 订阅 / 一次性 / freemium)| 1 周 + PM 拍板 |
| In-app feedback 入口(silent failure 已有,加 explicit "反馈" 按钮)| 1 天 |
| Onboarding 流程优化(双钥匙 / 一把钥匙 / 0 钥匙 freemium)| 看用户反馈,1-3 天 |

**出口标准**:
- ≥ 150 装机
- DAU/MAU 比 > 30%(真在用,不是装了就丢)
- 30 天 retention > 20%
- 用户主动分享(小红书 / 朋友圈截图)出现自然增长

### 3.4 正式上线(1 个月后)

**目标**:App Store + Google Play 正式发布。

| 任务 | 估期 |
|---|---|
| App Store 上架(Apple Review 1-7 天)| 1 周 |
| Google Play 正式上架(自动审,< 1 天)| 1 天 |
| 自动更新链路(Tauri updater on iOS 桌面已做;mobile 在 App Store 自带)| 0 天(自带) |
| 隐私政策 + 用户协议(中英文)| 0.5 天 |
| 客服 / 反馈对接(at-mention / 邮件)| 持续 |

---

## 4 · 关键 Milestone(时间表)

```
2026-06-26  10:00  ◄── Now: PARITY CONVERGED + chat tool-loop + OCR Phase A 完
2026-06-26  20:00  ◄── 今晚:真机验完 30-45 min(N2 + X1 ✅ → ledger 36 ✅)
2026-06-27       ◄── iOS Beta v0.2.0 准备(TestFlight 上传)
2026-06-28       ◄── 启动 iOS Beta · 邀 20-30 装机
2026-07-05       ◄── Android 完善启动(MLKit OCR + cutout + AndroidManifest)
2026-07-08       ◄── Android Beta v0.2.0(Google Play 内测)
2026-07-15       ◄── 跨平台 Public Beta(小红书发文)
2026-07-30       ◄── 正式上线(iOS App Store + Google Play)
```

---

## 5 · 风险 + 退路

| 风险 | 严重度 | 退路 |
|---|---|---|
| iOS Apple Developer 没买 / notarize 没做 | 🔴 高(装机 Gatekeeper 警告) | $99/年立刻买(参考 RELEASE_TEMPLATE.md §1)|
| Android 国行无 GMS 占比 > 30% | 🟡 中(端侧 OCR 走云端兜底慢 1-3s)| Phase C PaddleOCR 集成 |
| DeepSeek API 限流 / 价格调整 | 🟡 中(用户付不起 token)| 备用阿里云通道已 vision 端走通,加 chat 通道 |
| Apple Review 拒(隐私 / 内容)| 🟡 中 | 准备隐私清单 + Privacy Manifest(已做 PrivacyInfo.xcprivacy)+ 改文案 |
| 用户反馈"chat 不流式逐字"体验差 | 🟢 低 | 0.5 天加 stream:true(决策 1B,已 plan)|
| 真机端到端 ❌(今晚验出大 bug) | 🟢 低(代码就绪 + 桌面 oracle 守底) | 当晚 fix 或排下周 |
| Cannot-break 数据丢失 | ⚪ 极低(7 类全清 + 40+ test 守)| 仍备 vault git 回滚 |

---

## 6 · 不在本期做的(显式 SKIP)

| 项 | 为什么不做 | 何时做 |
|---|---|---|
| Chat stream:true 流式逐字 | 用户没强烈反馈,体验级优化 | Public Beta 后看真用户呼声 |
| PULSE / 留言板 / vault 健康 移动版 | 桌面专属,移动用户不需 | 不做(产品决策)|
| 多语言 i18n | 当前只中文用户 | 真海外用户出现后 |
| 跨平台数据同步(iOS ↔ Android ↔ 桌面)| LAN 直连 / git 真实现复杂 | Public Beta 反馈后(1-2 月)|
| In-app 应用更新(非 App Store 渠道)| App Store 自带 | 国行 APK 渠道用户多了再做 |
| PaddleOCR Android(无 GMS 兜底)| 当前云端兜底够用 | 真有华为 / 鸿蒙用户反馈 |

---

## 7 · 工作量汇总

| 阶段 | 工程天 | 持续期 |
|---|---|---|
| 今晚真机验 | 0.5 天 | 1 晚 |
| iOS Beta 发版 | 2-3 天 | 1-2 周 |
| Android 完善 + Beta 发 | 4-6 天 | 2-3 周 |
| Public Beta | 1-2 天(配置)| 2 周 |
| 正式上线(Apple/Google review)| 1-2 天 | 1 周 |
| **合计** | **~10-15 工程天** | **1-2 月** |

---

## 附录 · 关联文档

- [`PARITY_LEDGER.md`](PARITY_LEDGER.md) — 行为契约对齐台账
- [`MIGRATION_AUDIT_REPORT.md`](MIGRATION_AUDIT_REPORT.md) — 端点级技术审计
- [`PM_REPORT.md`](PM_REPORT.md) — PM 视角功能簇报告
- [`OCR_NATIVE_PLAN.md`](OCR_NATIVE_PLAN.md) — 端侧 OCR iOS+Android 路径
- [`PHASE_2_RUNBOOK.md`](PHASE_2_RUNBOOK.md) — iOS 真机调试 runbook
- [`../agents/human-ai-schedule/RELEASE_TEMPLATE.md`](../agents/human-ai-schedule/RELEASE_TEMPLATE.md) — 桌面发版模板(Apple Developer / DigiCert / 跨平台 CI)
- [`spread/小红书运营手册.md`](spread/小红书运营手册.md) — 传播 / 拉新作战手册
- [`RUNBOOK.md`](RUNBOOK.md) — 日常 build/跑 runbook

## 附录 · 关键 commit

```
f98a4c9 feat(mobile-chat): tool-loop 加 claim audit + DSML 闸 — X1 OUT → 🟡 ✅
1ab6aa0 docs(audit): PM 视角迁移报告 — 功能簇为入口 + 决策点
c3cfce7 docs(audit): 修 audit 数字一致性 — OUT 14 → 19
9616e36 audit: PC↔Mobile 功能迁移审核报告 · 6 子代理并行扫 + 综合
5b7c0a9 feat(mobile-ocr): native OCR plugin + cutout endpoint
962fa8d parity: PARITY CONVERGED @ 2026-06-26
```
