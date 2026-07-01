# Session 测试钥匙 + 模拟器接续手册

> migration session 真机自验的接续文档。**保留主因两条**:① session 自验用的真 DeepSeek key
> ② 可复用的 simulator / plist 验收基础设施。
> 当前**进度真相以 [`PARITY_LEDGER.md`](PARITY_LEDGER.md) 为准**;真 tap 协议见
> [`parity/interaction/run-cases.md`](parity/interaction/run-cases.md);全局导航见 [`MIGRATION.md`](MIGRATION.md)。

---

## DeepSeek key(已撤销 + 换占位 · 运行期注入)

```
[REDACTED — 原真 key 已按"干净初始态"撤销并从本文件清除]
```

- 用途:simulator 自验 chat / tool loop 时注入,**不是给最终用户的**。
- 已注入 simulator 的 Capacitor Preferences(plist 内,uninstall 才清),新 session 不需重注入。
- ❌ 不入 shipped source;原刻意保留的真 key 已撤销 + 换占位(若已进 git 历史需 BFG/filter-repo 清史)。
- 运行期注入靠 `window.__GW_REAL_KEY__`;无注入则 self-test 的 T7-T16 跳过。

---

## 模拟器

```bash
# iPhone 17 Pro(常驻 boot)
xcrun simctl boot   F362B9E3-58F3-4E07-A698-B91EFCBF7CA6
xcrun simctl launch F362B9E3-58F3-4E07-A698-B91EFCBF7CA6 com.humanai.gateway

# plist 真副作用查验(验收的金标准证据)
plutil -p <DataContainer>/Library/Preferences/com.humanai.gateway.plist
```

---

## 验收现状(2026-06-28)

- **chat 22 tool 验收 = 全通**:STRICT first-PASS 22/22(attempts=22 双重稳定,两次独立 run 0 retry)
  + 簇式 dispatcher 22/22 actions + plist 真副作用落盘 + iOS Vision 真抠图/OCR。
  早期"14/22 in-progress、待切 MCP 法"的叙述**已被这轮超越**,不再是现状。
- **交互层真 tap**:现行执行器是 **fb-idb 真 OS-level tap**(`parity/interaction/idb_runner.sh`),
  取代早期 opensafari MCP / webview SyntheticTap 法。
  ⚠ 注意:`idb_runner.sh all` 当前只 loop 01-20、过半 case 仅 screenshot 单断言——
  "逐条四断言全绿"仍是持续活,不是收官(详 [`MIGRATION.md`](MIGRATION.md) §1 诚实定义)。

## 可复用验收基础设施(保留作回归参考)

- **self-test**:`mobile-api.js` IIFE 末尾(L2213+),plist 法冗余;靠 `__GW_REAL_KEY__` 注入。
- **plist-as-evidence 测试法**:方法论见 [`TEST_WORKFLOW.md`](TEST_WORKFLOW.md)。
- **tool 触发 prompt 速查**(回归时按场景手触发):

| tool | chat prompt |
|---|---|
| insert_journal_block | "在今天 17:00 插入新条目,标题 'self-test 插入'" |
| set_water_cup_image | "把水杯图标换成蓝色 emoji 🚰" |
| vision_classify | (先上传 dummy attachment)"看一下我刚拖进来的那张图" |
| ocr_image | "OCR 这张图" |
| delete_attachment | "删 X 张图" |
| list_widgets | "list_widgets 列我所有 widget" |
| remove_widget | "remove_widget 删 self-test-coffee widget" |
| set_widget_enabled | "set_widget_enabled 关掉 self-test-coffee widget" |

---

## 历史(留作上下文,非现状)

- 本 session 起点:跑了 14/22 chat tool(plist 法),曾计划切 opensafari/XcodeBuildMCP MCP 法继续
  —— 后续实际走了 fb-idb 真 tap,MCP 法不再是主线。
- Storage 5 Critical bug + 1 field mismatch 全 fix(commit `9d618e3`/`ae3569a`/`1fb5415`/`8c5afbe`/`8fe465d`):
  IIFE-cached Backend 永久锁、`.catch(()=>{})` 静默吞写失败、`_fs` 无 null check 真机崩、
  CapacitorHttp timeout 单位错(秒→毫秒)、`/api/setup/current` 顶级 key 字段缺。
