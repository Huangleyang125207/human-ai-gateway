# 交互用例 Runner 协议(fb-idb 真 OS-level tap)

> **重大修订(2026-06-28 00:45)** — webview 内 SyntheticTap 跑 64/64 PASS 是 fake-green。
> 没经过 Capacitor Preferences 真实部署链(node Map mock),错过两个真核心 bug:
>   1. self-test 每次启动擦 user 真 deepseek_key(commit f44ca3c)
>   2. Capacitor Preferences group="NSUserDefaults" 配错被当字面 prefix(commit d98bd74)
>
> **现协议** — 用 **fb-idb**(Facebook,Appium 同款 SimulatorBridge IPC,GitHub 4k+ stars)
> Simulator 上真注入 OS-level touch event,绕开 Mac mouse event 链。
>
> 装:`brew tap facebook/fb && brew trust facebook/fb && brew install idb-companion`
>     `pip3 install fb-idb` → client 在 `~/Library/Python/3.9/bin/idb`
> 验:`idb ui tap 122 75 --udid <SIMID>` → "对话" tab 真切换(屏幕 obvious 反馈)
>
> **真 tap 链**(本协议 mandate):
>   1. seed app state via simctl(plist + Documents/gw/journal md)
>   2. launch app
>   3. webview 内 `__GW_TEST_API__.dumpRects()` 把 selector→viewport rect 写进 plist
>   4. Bash 读 plist 拿 rect
>   5. `idb ui tap <rect.center.x> <rect.center.y>` 真注入 touch
>   6. screenshot + 读 plist + 比 md = 三道断言
>
> 真 tap 走 SimulatorBridge IPC → WKWebView 收到 touch → JS pointer event → handler →
> fetch → endpoint → plist 改 / md 改。这是 user 用手指点屏幕的完整链。

人读规格见 [`../../INTERACTION_TEST_CASES.md`](../../INTERACTION_TEST_CASES.md);
两层模型见 [`../../TEST_FIRST_MIGRATION.md`](../../TEST_FIRST_MIGRATION.md) §0。

---

## (旧文档保留)XcodeBuildMCP a11y tree 协议

---

## 前置(第 0 号:这两件不齐,64 条都跑不了)

### P1 · 设备 + app 就位
- `session_show_defaults` 确认 project/scheme/simulator;没配 → `discover_projs` + `list_sims`。
- `build_run_sim`(空参或带 scheme)把 app 装进 booted sim 并启动。

### P2 · tap 目标可定位(webview 的硬约束)
`snapshot_ui`/`tap` 看到的是**原生 accessibility 树**。mobile/m 是 webview,DOM 元素只有带
**可见文案 / `aria-label` / `role`** 才会暴露成可点 accessibility element。
`cases.mjs` 里的 tap 目标现在多用 CSS class(`.gw-task`/`.gw-nib`/`.gw-day`)——**class 对 snapshot_ui 不可见**。
所以落地前要给关键 tap 目标补 accessibility:
- 悬浮提笔 `.gw-nib` → 已有 `aria-label="提笔写一段"` ✅(可按 label 定位)
- 打卡卡片 `.gw-task` → 需补 `aria-label`(如 `打卡:鱼油`)或靠卡片内可见文案"鱼油"定位
- 日期 pill `.gw-day` → 靠可见日号/星期文案定位
- 保存 `.gw-save`("落笔"/"改完")、tab("日记"/"对话")→ 靠可见文案
**补 accessibility 的清单 = 真正的"第 0 号 UI 活"**;补完一类,该簇 case 才可 tap。

### P3 · 设备 seed(摆前置状态)
case 的 `precondition` 要把 plist/md 摆成已知初态。两条路(选一):
1. **simctl 写 Preferences**:`xcrun simctl get_app_container booted <bundle-id> data` → 进 `Library/Preferences/<bundle-id>.plist`,用 `plutil`/`PlistBuddy` 写 Capacitor Preferences key(journal md、daily-task-meta 等)。
2. **app 内 test seed 钩子**(推荐,更稳):复用 node harness 已有的 `globalThis.__GW_TEST_API__.setBackend`(见 PARITY_LEDGER「harness 接通」)——给 app 加一个 debug-only deep-link 或启动参数,把 seed JSON 灌进 Backend,避开 plist 二进制坑。

---

## 逐条 case 跑法(6 步)

对 `cases.mjs` 里每条 `c`:

```
1. SEED      按 c.precondition 用 P3 摆初态;launch_app_sim(冷启,让 prefetch 读到 seed)
2. TAP       按 c.tap 执行:
               snapshot_ui → 在树里定位目标(按 P2 的 label/文案)→ tap(坐标/elementRef)
               多步序列逐个做(swipe/longpress 用 swipe/long_press;拖图用 drag)
3. 断言①屏幕  snapshot_ui → 比 c.expect.ui:目标元素的态(出现/消失/.done/.readonly/文案)
4. 断言②存储  读 plist(simctl get_app_container + plutil -convert json)→ 比 c.expect.persist
5. 断言③截图  screenshot → 比 c.expect.screenshot(回归基线 diff 或人看)
6. 比底座     该交互最终落的 md/plist 字节 == c.golden(mobile/parity/golden/<x>)→ 不等即 FAIL
            记 PASS/FAIL + 截图引用,回写 PARITY_LEDGER 对应 row
```

判据(同 TEST_FIRST_MIGRATION §5):**① snapshot_ui 对 + ② plist 对 + ③ 截图对 + 底座字节对 = 该 case PASS**;
缺一不是"差一点",是这条交互不成立。★Cannot-break 的 case 必须先全绿。

---

## worked example:`daily_tasks__check_backfill_yesterday_closed`(★补卡窗口)

验"过了次日中午,补昨天的卡必须被 UI 锁死 + 端点拒"。

```
1. SEED   设备时钟 = 今天 13:00(simctl 不便改钟 → 用 app 的注入 now,或 seed 一个"昨天"日;
          关键是 catalog?date=yesterday 返 is_writable=false 的分支)。seed 昨天 md 有"鱼油"未打卡。
2. TAP    launch → 日记/今日页 → snapshot_ui 定位日期带"昨天"那颗(可见日号)→ tap
          → snapshot_ui 重取
3. 断言①  昨天 care 区元素带只读态(.gw-care-block.readonly 对应的 accessibility:杯子/打卡不可点;
          whisper 文案"历史日只读")。再 tap"鱼油"卡 → snapshot_ui 状态**不变**(无勾选切换)
4. 断言②  读 plist:daily-task-meta 无昨天的 intake 写入(字节不变)
5. 断言③  screenshot:昨天区灰只读、杯子不可点
6. 底座   golden/daily_tasks__check_backfill_yesterday_closed.response.json(status 400)
          —— 机器层 callApi POST check{date:yesterday} 必 400,与 UI 只读一致
PASS 条件:UI 锁 + 不落账 + 端点 400 三者齐。
负例核心:旧 mobile L454 `date>=today` 会放过未来/拒昨天 = 正好反向,这条就是抓它的。
```

---

## 现状 + 下一步

- `cases.mjs`:**64 条 · 20 ★Cannot-break · 35 UI已建 / 29 待建**(`STATS`)。
- **先做 P2**(给已建簇的 tap 目标补 accessibility)→ 该簇 case 立即可跑。
- **29 条 UI待建**:先当"UI 该长啥"的规格,UI 建好再跑(见各 case `[UI待建]` 标注)。
- 全 64 条真跑是持续活(每条 ~分钟级 + seed/截图);**契约层(`node ../run.mjs`,78/78)已自动兜底回归**,
  交互层按"★Cannot-break 优先 → 已建簇 → 待建簇"推进。
