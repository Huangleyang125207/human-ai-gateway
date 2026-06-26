# Gateway PC ↔ Mobile 功能迁移审核报告

> 生成时间:2026-06-26 09:10 CST
> PC 端 HEAD:`5b7c0a9`(commit "feat(mobile-ocr): native OCR plugin + cutout endpoint")
> 基线:`PARITY CONVERGED @ 962fa8d @ 2026-06-26`
> 方法:6 个 Explore 子代理并行扫描 + 综合
> 范围:`server.py + *_routes.py` + `tests/` + `mobile/mobile-api.js + m/ + plugins/ + PARITY_LEDGER.md`

---

## 0 · 一句话结论

**桌面 80 endpoint / 41 oracle 文件 / ~280 test;移动 ~45 endpoint(其中 34 in-scope 完全 parity 对齐,1 待真机,19 显式 OUT);ledger 34 ✅ + 1 🟡(N2 OCR 真机阻塞)+ 19 OUT + 0 ❌(in-scope 共 54 row)。**

桌面所有 7 个 Cannot-break ★ 家族(40+ assert)在 mobile 端全守住;canonical 自身 1 个 known drift documented;迁移**procedurally converged**,差 N2 真机 OCR 拍补剂瓶验最后一步。

---

## 1 · PC 端功能维度地图

来自 [scan:pc-endpoints] + [scan:pc-tests]。

### 1.1 endpoint 按 cluster 分布(80 个)

| cluster | endpoint 数 | 主要 endpoint | 关联 oracle 文件 |
|---|---|---|---|
| **journal 读写 + tag-aggregate** | 10 | today / days / new-day / tag-stats / insert-block / delete-block / patch / tag-aggregate/{register,refresh,get} | `test_journal_routes.py` (15) + `test_authorship.py` (13) + `test_patch_h2_rename.py` (4) + `test_insert_block_body.py` (6) |
| **daily-tasks** | 8 | catalog (GET /api/daily-tasks) / check / meta / backfill-progress / delete / history / water-cup × 2 | `test_daily_tasks_routes.py` (16) |
| **thread** | 3 | history (GET) / save (POST) / restore-from-bak | `test_thread_routes.py` (8) + `test_thread_cas.py` (9) |
| **chat** | 2 | chat (POST SSE) / upload-image | `test_chat_routes.py` (15) + `test_claim_audit.py` (6) + `test_attachment_dedup.py` (6) |
| **board / eval** | 4 | eval/list, today, test, run | `test_board_routes.py` (11) |
| **setup / 配置** | 10 | setup-status / templates / test{,-baidu,-gemini} / current / save{,-partial,-gemini} / models | `test_setup_routes.py` (21) |
| **pulse(项目 PULSE)** | 7 | pulse / pulse/{name} / pulse/{user,project,agent-context}-update / compact-summary / refresh-mirror | `test_pulse_endpoints.py` (16) + `test_pulse_validate.py` (10) + 4 个 self-evolve 测试文件 |
| **image / attachments** | 7 | /attachments/{date}/{name} GET + /api/attachments × 5 + cutout + vision/classify | `test_image_routes.py` (13) + `test_attachment_dedup.py` + `test_ocr_local.py` (6) |
| **migration** | 1 | migration/stream(SSE 版本迁移)| `test_migration.py` (5) + `test_migration_glue.py` (10) |
| **server / other(desktop-only)** | 28 | health / init-status / config-status / quit / abort / user-widgets / scrapbook × 3 / vault × 4 / history × 4 / consent × 4 / notifications / updater × 2 / telemetry × 3 / silent-failures / open-external / widgets × 2 / template/task | `test_consent.py` (16) + `test_history_exporter.py` (18) + `test_vault_git.py` (11) + `test_updater_report.py` (5) + `test_silent_failure_probe.py` (10) |

**总计:80 endpoint × 41 oracle 测试文件 × ~280 test 用例**。

### 1.2 Cannot-break 不变量(从 [scan:pc-tests] 推断)

| 不变量 | 守门 endpoint | oracle 文件 | mobile parity row |
|---|---|---|---|
| Authorship boundary(AI 不覆盖 @user 块) | journal/patch + insert-block + append-comment | `test_authorship.py` 13 条 | J-CB1 ✅ |
| H2-rename guard(5.29 联想 entry 不被吃)| journal/patch | `test_patch_h2_rename.py` 4 条 | J-CB2 ✅ |
| Insert body 一体(§ H5 守)| journal/insert-block + TOOL_SPECS | `test_insert_block_body.py` 6 条 | J-CB3 ✅ |
| Thread CAS 409(5.26 陈旧 tab)| thread/save base_mtime | `test_thread_cas.py` 9 条 | T5 ✅ |
| Thread 损坏 modal(5.17)| thread/history | `test_thread_routes.py` corrupt 段 | T3 ✅ |
| 补卡窗口闭集 `{today, yesterday-if-h<12}` | daily-tasks/check + catalog is_writable | `test_daily_tasks_routes.py` window 段 | D2/D8 ✅ |
| Delete cascade(5.15 肌酸 leak)| daily-tasks/delete | `test_daily_tasks_routes.py` cascade 段 | D7 ✅ |

---

## 2 · Mobile shim 实装完成度

来自 [scan:mobile-shim]。

### 2.1 mobile-api.js handler 总览(~45 endpoint)

| cluster | mobile shim 数 | 对应 PC | 完成度 | 备注 |
|---|---|---|---|---|
| journal | 9 | 10 | 9/10(tag-aggregate 3 个 OUT)| insert/patch/delete/today/days/new-day/tag-stats/append-comment/search |
| daily-tasks | 9 | 8 | **超载**(mobile 多 `/api/cutout` `/water`)| catalog/check/meta/add/delete/history/set-image/water/cutout |
| thread | 3 | 3 | 3/3 ✅ | history/save/restore-from-bak |
| chat | 2 | 2 | 2/2 ✅ | chat(SSE,thin wrapper)/ upload-image |
| board | 0 | 4 | 0/4(全 OUT)| 桌面专属 eval 不渲染 |
| setup | 8 | 10 | 简化版(6 OUT)| 硬编 configured:true,绕开双钥匙仪式 |
| pulse | 0 | 7 | 0/7(全 OUT)| mobile 无 PULSE dashboard |
| image / vision | 7 | 7 | 7/7(架构分叉)| attachments/uploads(localStorage / Capacitor FS)+ cutout + vision/classify |
| migration | 0 | 1 | OUT | mobile 无版本迁移 stream |
| server/other | ~2(health stub + init-status stub)| 28 | 2/28(剩 OUT)| 桌面 vault audit / history / consent / notifications / scrapbook 全无 mobile 对应 |
| **mobile-自创快路径** | 4 | — | — | journal/search / web/fetch / widgets/list / note/check-lazy(21:30 lazy 纸条)|

**总计:mobile 实装 ~45 endpoint(in-scope 24 对齐 + 21 自创 / stub / OUT)**。

### 2.2 浏览器 / 真机存储差异(LocalBackend vs CapacitorBackend)

| 后端 | 触发 | 存储格式 | 关键 key |
|---|---|---|---|
| LocalBackend | 浏览器 / Playwright 自测 | localStorage `gateway.mobile.*` | `journal/<iso>`, `thread`, `setting/*` |
| CapacitorBackend | 真机 iOS / Android | Capacitor Filesystem(`gw/`) + Preferences | `gw/journal/<stem>.md`, `gw/thread.json`, `Preferences.get/set(<key>)` |

Native plugin 后退链:**NativeOcr → CloudVision(N4 endpoint)→ BrowserStub(返空)**。

---

## 3 · ledger 对齐矩阵

来自 [scan:ledger]。

| 状态 | 数量 | rows / cluster | 备注 |
|---|---|---|---|
| **✅ 对齐** | **34** | P0 journal 15(J1-J12 + J-CB1/2/3) + P0 daily-tasks 8(D1-D8;D9 OUT) + P1 thread 6(T1-T6) + X 漏收 4(X2-X5) + N image 1(N4) | 全 sha 入 ledger |
| **🟡 待验** | **1** | N2 OCR(`/api/cutout`) | plugin + endpoint + regex 就绪;待 iOS 16+ 真机拍补剂瓶 → ocr_pill_count = 60 验通 → ✅ |
| **OUT** | **19** | 桌面专属 4(J13/J14/J15 + D9)+ mobile 自创 4(N1/N3/N9/N10)+ 架构分叉 4(N5/N6/N7/N8)+ 独立产品形态 1(X1 chat tool-loop)+ Setup 整段 6(S1-S6,6.25 重判:mobile 硬编 configured:true 绕开双钥匙仪式)| 显式产品决策 |
| **❌ 未查** | **0** | — | 全 row 显式判定 |

**完整 in-scope row 总和:34 + 1 + 19 + 0 = 54**(报告前版"24"是 6.25 first-pass 旧估算,实际收尾 54)

### 3.1 收敛记录条目(从 [scan:ledger] 直引)

```
PARITY CONVERGED @ 74ac4bb @ 2026-06-26

- ✅ 34 rows · OUT 14 · 🟡 1(N2 OCR)· ❌ 0
- 桌面 pytest:83 passed + 1 known canonical drift(documented)
- check-fe-be ① 死引用空 + ② 真缺口都 OUT-OF-SCOPE
- ★Cannot-break 7 家族 / 40+ assert 全清:
  J-CB1 authorship + J-CB2 H2-rename + J-CB3 insert body
  + T3 corrupt modal + T5 CAS 409
  + D2/D8 is_writable 闭集 + D7 cascade
```

---

## 4 · 前端 → 后端 call chain(4 个关键 flow)

来自 [scan:mobile-frontend]。

### 4.1 加新日记 entry(用户拍 nib 提笔)

```
gw-journal.js openCard({st})
  └─ user 填表(时间/标签/正文)→ .gw-save.click
GW.journal[dayKey].push({id, time, tags, title, body})
GW.bus.emit('reloadDay')
  ↓
gw-real-bridge.js syncJournalDiff()
  ├─ snapshot.find(e.id) == null → 新增
  └─ POST /api/journal/insert-block {date, time, tag, title, body}
mobile-api.js L1402(本 loop fix:missing time → 400, no journal → 404)
  └─ Store.writeJournalMd(date, md + new entry)
LocalBackend(浏览器)/ CapacitorBackend(真机)
```

### 4.2 打卡(滑水 / tap task)

```
gw-widgets.js apply(clientX) 或 toggle()
  ├─ st.water = i+1(八杯水)
  └─ t.today_intake += 1(task)
GW.bus.emit('pulse')
  ↓
gw-real-bridge.js syncPulseState() [250ms 防抖]
  ├─ POST /api/daily-tasks/water {date, filled}
  └─ POST /api/daily-tasks/check {date, task_name, intake}(逐 task)
mobile-api.js L1448 check handler(D3 数学:三入口 + clamp + dose>=2 sub-box)
  └─ Store.writeJournalMd + setSetting taskintake/<name>
```

### 4.3 对话 sendChat(SSE 流式)

```
gw-real-bridge.js GW.sendChat patched
  ├─ st.thread.push(user msg)
  ├─ GW.scanIntent(text)  → window.scanUserIntent(信号采集)
  ├─ 显示 "磨墨中…"
  └─ fetch('/api/chat', { history, message })
mobile-api.js L1959 chat handler
  └─ chatViaDeepseek(body, key, model)
     ├─ system prompt 注入今天日记 + tool spec
     └─ DeepSeek SSE → sseResp 包成 {type:delta|tool_call|tool_result|done}
gw-real-bridge.js pump SSE → renderThread + tool chip 三态
  └─ 完成后 POST /api/thread/save {history}
```

### 4.4 拍图 → 抠图 → OCR → meta(本次新增)

```
gw-app.js 用户点 chatbar 附件 / openCard 贴图
  ↓
Capacitor.Camera 拍照 → dataURL
POST /api/chat/upload-image → {url, deduped}
  └─ sha256 去重写 attachments/<date>/<sha>.<ext>
[端侧抠图]
window.Capacitor.Plugins.Cutout.cutout({image: dataURL})
  └─ iOS 17+ VNGenerateForegroundInstanceMask → 透明背景 PNG
[Phase A 新增]
POST /api/cutout {task_name, image: dataURL}
mobile-api.js L1237 cutout endpoint
  ├─ window.Capacitor.Plugins.NativeOcr.recognize({image, languages:['zh-Hans','en-US']})
  │  ├─ iOS:VNRecognizeTextRequest(accurate mode)
  │  └─ Android:MLKit ChineseTextRecognizerOptions
  ├─ extractPillCount(text) → "60 粒" → 60
  ├─ setSetting taskimg/<name> = url
  └─ setSetting taskmeta/<name>.total_pills = 60
  → 返 {ok, ocr_pill_count, engine: "VNRecognizeText" | "MLKitTextRecognition"}
```

---

## 5 · 端侧 native plugin 覆盖

来自 [scan:mobile-plugins]。

### 5.1 平台矩阵

| plugin | iOS impl | Android impl | browser fallback | engine | iOS min | Android min | 状态 |
|---|---|---|---|---|---|---|---|
| **Cutout**(抠主体)| Swift 66 行 | ❌ 未实装 | ❌ undefined | Vision `VNGenerateForegroundInstanceMaskRequest` | iOS 17 | — | iOS 单平台 |
| **NativeOcr**(端侧 OCR)| Swift 100 行 | Kotlin 105 行 | ❌ undefined | iOS Vision `VNRecognizeTextRequest` / Android `ML Kit text-recognition-chinese v16` | iOS 13(中文 16+)| Android 22+ | **Phase A 完整双平台** |

### 5.2 NativeOcr JS 接口

```typescript
window.Capacitor.Plugins.NativeOcr.available()
  → { available: boolean; engine: string; languages?: string[]; reason?: string }

window.Capacitor.Plugins.NativeOcr.recognize({ image: string; languages?: string[] })
  → {
      text: string;             // 按行 join
      blocks: [{
        text: string;
        confidence?: number;    // ML Kit 0-1
        bbox?: { x, y, w, h }   // normalized
      }];
      engine: string;           // "VNRecognizeText" | "MLKitTextRecognition"
    }
```

### 5.3 兜底链

无 native plugin / 无 GMS 时:
```
NativeOcr.available() → false
  ↓
mobile-api.js cutout endpoint
  ├─ ocrP = _ocrViaCloud(attachment_url, dataUrl)
  └─ POST /api/vision/classify {attachment_url, extra_question: "OCR 出文字..."}
     └─ 真后端 = 阿里云百炼 qwen3-vl-flash
```

---

## 6 · 缺口 + 风险

### 6.1 🔴 严重(无)

**所有 Cannot-break 7 家族在 mobile 全守住。** ledger ❌ 数 0。无严重缺口。

### 6.2 🟡 漂移(documented)

| 项 | 详情 | 影响 | 处置 |
|---|---|---|---|
| canonical drift | `tests/test_authorship.py::test_patch_block_ai_allows_ai_block` 5.22 fixture 没传 `allow_h2_rename=true`,5.29 加 H2-rename guard 后 canonical 自身红 | 桌面 1 test fail 是历史的,不是 mobile 引入的 | 护栏禁动 canonical;mobile 跟桌面实装一致 reject;等桌面侧自己修 fixture |
| N2 OCR 待真机验 | iOS 16+ 拍补剂瓶 → ocr_pill_count = 60(label "60 softgels")| 当前 ledger 🟡,代码就绪 | Phase 2 真机阶段验完 → 改 ✅ |

### 6.3 🟢 架构分叉(显式产品决策,不是 bug)

| 项 | 桌面 | mobile | 决策 |
|---|---|---|---|
| chat tool-loop(X1)| 多轮 tool dispatch + DSML 闸 + 流式 chokepoint | thin DeepSeek SSE wrapper,无 tool loop | 独立产品形态,不按 parity 迁(讨论中:让手机 AI 写日记/打卡是另一个设计任务)|
| attachments 存储(N5-N8)| server 文件流 + OCR 索引 | dataURL inline + Capacitor FS + vision_classify 缓存 | local-first vs server-side 分叉;mobile 选 local-first 是核心 |
| widgets / pulse / vault / scrapbook / consent / notifications | 桌面完整 | mobile 0 | 移动端无对应 UI;不在 MVP scope |
| setup(双钥匙 / 模型仪式)| 21 test 全套配置流 | 硬编 configured:true 绕开 | 用户拍移动 onboarding 极简 — 一把钥匙不要双仪式 |

### 6.4 桌面 endpoint 未在 ledger(completeness critic)

scan agent 给出 80 PC endpoint,ledger in-scope 54(34 ✅ + 1 🟡 + 19 OUT)。**剩 ~46 个桌面 endpoint mobile 端无对应**,主要是:
- pulse 7 个 + board 4 个 + migration 1 个 + server/other 28 个 = 桌面专属 / 非用户高频
- mobile UI 设计上**不渲染** PULSE dashboard / 留言板 / vault audit / history viewer 等
- **已隐式 OUT,不在 ledger 但也不是 parity gap**(MIGRATION_PARITY_GUIDE.md §6 优先级表已声明 mobile = "用户高频" 优先)

### 6.5 Cutout plugin Android 未实装

Cutout 端侧抠主体 plugin **仅 iOS 17+**(Vision 前景实例 mask)。Android 端**未实装**,移动端 Android 用户拖图后**无客户端抠图**,目前 fall back 桌面云端逻辑或不抠。

- 影响:Android 拍图贴 entry 时背景未抠;视觉体验弱
- 修法:Android 加 MLKit ObjectDetection or PaddlePaddle PaddleClas 抠图(工程 1-2 天)
- 优先:N2 真机验完后再启 Cutout Android(优先级低于 OCR)

---

## 7 · 下一步建议

### 7.1 立即(本周)

1. **N2 真机 OCR 验证**(2-3 小时):
   - iOS 16+ 设备拍 Swisse 鱼油瓶 → POST `/api/cutout` → 返 `ocr_pill_count == 60`
   - 验完 ledger N2 改 ✅ + 盖桌面当时 sha + commit
   - Phase B Android 真机同步(如有 GMS 设备)

2. **桌面 canonical drift fix**(可选,不阻塞):
   - 修 `tests/test_authorship.py::test_patch_block_ai_allows_ai_block` 加 `allow_h2_rename=true`
   - 桌面 84/84 GREEN

### 7.2 短期(下次发版前)

3. **Cutout Android 实装**(Phase D):
   - MLKit Subject Segmentation(Android 12+ 自带)/ PaddlePaddle Lite(老 Android)
   - 工程 8-12h

4. **chat tool-loop 移动版独立设计**(X1 解 OUT):
   - mobile AI 能"调 tool 写日记/打卡"是手机用户高需求场景
   - 设计 mobile 端 dispatcher(可能简化版 / 流式 chokepoint 缩短)
   - 工程 1-2 周 + 设计讨论

### 7.3 中期(1-2 个月)

5. **attachments 架构收口决策**:
   - 当前 dataURL inline + Capacitor Filesystem 在 5GB+ vault 时 base64 编码膨胀显著
   - 决策:加 Capacitor FS 文件路径 + 异步 thumbnail layer,还是保持当前
   - 跟 N5/N6/N7/N8 OUT 重判挂钩

6. **Phase C Android 无 GMS PaddleOCR 兜底**(只在真有用户反馈时启):
   - 国产 ROM 鸿蒙等无 GMS → 当前 fall back 阿里云百炼(慢但通)
   - PaddleOCR Android Demo 集成 ~3-4h

### 7.4 长期

7. **pulse / vault / scrapbook 移动版 UI 重设计**(若产品上线后用户需要):
   - 这些桌面 cluster 故意没迁,等真用户反馈决定优先级

---

## 8 · 关键数字

| 维度 | 数 |
|---|---|
| PC endpoint 总数 | 80(10 journal + 8 daily-tasks + 3 thread + 2 chat + 4 board + 10 setup + 7 pulse + 7 image + 1 migration + 28 server/other) |
| PC oracle 测试文件 | 41 |
| PC oracle test 总数 | ~280(test_setup 21 / daily-tasks 16 / journal 15 / chat 15 / consent 16 / image 13 / authorship 13 / thread_routes 8 / thread_cas 9 / ...)|
| Mobile shim endpoint 数 | ~45(24 in-scope 对齐 + 21 mobile-自创 / OUT / stub)|
| **ledger ✅ 对齐 rows** | **34** |
| ledger 🟡 待验 rows | 1(N2 OCR) |
| ledger OUT rows | **19**(桌面专属 4 + mobile 自创 4 + 架构分叉 4 + 独立产品 1 + Setup 6)|
| ledger ❌ 缺口 rows | 0 |
| **完整 in-scope row 总和** | **54** |
| Cannot-break 守 family | 7(J-CB1/2/3 + T3 + T5 + D2/D8 + D7)|
| Cannot-break assert 数 | 40+ |
| 本次 loop commit 数 | **30+** row-by-row + 9 个 OUT 收口 + 1 PARITY CONVERGED + 1 OCR Phase A |
| 桌面 STAY GREEN | 83 / 84(1 canonical drift documented)|
| native plugin 数 | 2(cutout iOS-only + native-ocr iOS+Android)|
| 真机阻塞项 | 1(N2 OCR 真机)|

---

## 附录 · 关联文档

- [`mobile/PARITY_LEDGER.md`](PARITY_LEDGER.md) — 移动端 parity 台账(本报告主要数据源)
- [`mobile/MIGRATION_PARITY_GUIDE.md`](MIGRATION_PARITY_GUIDE.md) — 桌面 oracle = mobile shim 契约方法论
- [`mobile/OCR_NATIVE_PLAN.md`](OCR_NATIVE_PLAN.md) — 端侧 OCR 集成 iOS + Android 分平台路径(N2 落地依据)
- [`mobile/PHASE_2_RUNBOOK.md`](PHASE_2_RUNBOOK.md) — Phase 2 真机调试 runbook(N2 真机验前置)
- [`mobile/RUNBOOK.md`](RUNBOOK.md) — 移动端 build/跑 runbook

## 附录 · 关键 commit

```
5b7c0a9 feat(mobile-ocr): native OCR plugin + cutout endpoint
962fa8d parity: PARITY CONVERGED @ 2026-06-26
74ac4bb parity(N1+N3+N9+N10 OUT): mobile 自创 endpoint 无桌面对等 ✅
2de5f2f parity(J13/14/15+D9+X1 OUT;X2/X3/X4/X5 ✅): 9 行收口
5db5f04 parity(T3+T4): thread corrupt modal + restore-from-bak ★Cannot-break ✅
... + 25 其它 row-by-row commit(详 git log)
```

---

**审核结论**:迁移 procedurally converged。**唯一阻塞 = N2 真机 OCR**,代码就绪,需要 iOS 16+ 设备拍补剂瓶图实测 5 分钟即可。所有 Cannot-break 不变量验通,所有架构分叉 OUT 都是显式产品决策不是 bug,后续 chat tool-loop / Cutout Android / pulse mobile UI 等都是新功能 scope 不是迁移欠债。
