# mobile/parity — parity oracle harness

> "对齐"必须**机器可判**,不能靠 LLM 肉眼(那是漂移)。这套是给 parity loop 用的 oracle:
> 同一输入,mobile shim 产出 == 桌面 canonical 行为 → 绿。配套 `../PARITY_LEDGER.md` + `../MIGRATION_PARITY_GUIDE.md`。

## 三类 oracle(按强度)

### A. 写操作 → golden 字节-diff(最强,6.15 已验过的手法)
桌面是 canonical。流程:
1. **capture**:跑桌面 characterization 场景,把 canonical 输出(md / json)dump 进 `golden/`。
   见 `capture-golden.py`(一个 feature 的样板)。golden 文件名 = `<feature>__<case>.md`。
2. **assert**:`harness.mjs` 驱动 `mobile-api.js` 跑同一输入,产出 mobile md,跟 golden **字节比较**。
   空 diff = 对齐。这是 journal 写 / daily-task check 这类的金标准 —— md 是真相,字节级才算迁对。

### B. 读操作 → JSON 形状/字段/状态码断言
catalog / history / today 这类:断言 mobile shim 返的 JSON 跟桌面测试 assert 的形状一致
(字段名、类型、状态码 200/400/404/409、边界值)。直接把桌面 `assert` 翻成 JS。

### C. 覆盖/前后端 → grep(无运行时,`check-fe-be.sh`)
- 前端引用的 /api ↔ shim handle 的(死按钮)
- PC 有 ↔ shim 缺(未迁缺口,完整性 critic 用)
loop 每轮收敛检跑一次。

## loop 怎么用这套(每轮)

```
挑 ledger 一个 🔴/❌ row
  → A/B 找/写它的 oracle(golden 或 JS assert)
  → 跑:红?改 mobile-api.js(+前端)→ 绿
  → 同时 `pytest tests/<对应桌面测试>` 必须 STAY GREEN(没动 canonical)
  → ledger 该行 ✅ + 盖桌面 HEAD sha → commit
收敛检:node harness 全绿 + check-fe-be.sh 干净 + critic 无遗漏 → PARITY CONVERGED
```

## 跑

```bash
# 覆盖/前后端(随时):
bash mobile/parity/check-fe-be.sh

# 抓 golden(改桌面后重抓):
.venv-test/bin/python mobile/parity/capture-golden.py

# JS oracle(mobile session 把 harness 接上 mobile-api.js 后):
node mobile/parity/run.mjs        # 或 vitest,看 mobile 工具链
```

## ⚠ harness.mjs / run.mjs 是骨架,需 mobile session 接活

`mobile-api.js` 是浏览器/Capacitor 里跑的(用 fetch 拦截 + Capacitor Preferences/FS 做 Store)。
在 node 里跑它要 mock 掉 Backend(已给内存版)+ **接上 mobile-api.js 真正的 dispatch 入口**
(它怎么暴露 handler / 拦 fetch —— 这块 mobile session 最清楚自己的架构,按 TODO 补)。
桌面 oracle 侧(golden、断言来源)是确定的;不确定的只有"怎么在 node 里喂 mobile-api.js"。

## Cannot-break(oracle 必覆盖)

- authorship:AI 不能覆盖 @user 块、`#commit` 批注不被抹 → 写操作 golden 必含一个"AI patch @user 块被拒"案例
- thread 损坏不空覆盖(5.17)· thread save CAS 409(5.26)
- md 全角冒号 `# HH：MM` + @author marker 字节兼容
