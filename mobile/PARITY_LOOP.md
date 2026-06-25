# 移动 parity loop — 启动块(复制即跑)

> 在 **gateway repo 根**起一个**新 session**,粘下面一条 `/loop` 就开跑。它冷启动自给自足:
> 读 `PARITY_LEDGER.md`(做到哪)+ `MIGRATION_PARITY_GUIDE.md`(怎么对)+ `parity/`(oracle)。
>
> 先做 Loop A 推平,收敛后常驻 Loop B 守不漂。两个 loop,不是一个(parity 是移动靶,见 guide §6)。

---

## Loop A — 收敛(self-paced,跑到对齐自动停)

> **前置:NEEDS-ORACLE-FIRST 行(N1-N10)桌面没 oracle,对不了。** loop 挑到这种 row 时,
> 第 0 步先按 ledger「怎么补 oracle」列**写桌面 characterization**(GREEN-LOCK 在 monolith 上 + 单独 commit),
> 它从"无法对齐"变成可对的 row 后,再走下面的对齐流程。建议先把 N1-N4 的 oracle 补出来再大批对齐。

```
/loop 移动端 parity 对齐。读 mobile/PARITY_LEDGER.md,挑优先级最高的一个 🔴/❌ row(P0 journal/daily-tasks 先;
NEEDS-ORACLE-FIRST 的 N 行优先补 N1-N4)。**若该 row 在 NEEDS-ORACLE-FIRST 段 → 第0步先写桌面 characterization
(按「怎么补 oracle」列,GREEN-LOCK 在 monolith + commit),再继续。**
按 mobile/MIGRATION_PARITY_GUIDE.md 的 oracle 把 mobile-api.js(必要时含 mobile/m 前端)对齐到该 row 的桌面
characterization 断言。验四件:① mobile/parity 的 oracle(写=golden 字节-diff,读=JSON 形状)红→绿
② 对应桌面 pytest STAY GREEN(.venv-test/bin/python -m pytest tests/<file> -q,绝不改 canonical)
③ bash mobile/parity/check-fe-be.sh 无新死引用 ④ 真机 390px 点一遍该功能。
然后把该 ledger row 改 ✅ + 盖当前桌面 HEAD sha,git commit(一 row 一 commit)。
没 🔴/❌ 了 → 跑全量 oracle + check-fe-be.sh + completeness critic(扫:有桌面端点/断言没进 ledger 吗?);
全绿且无遗漏 → 在 ledger「收敛记录」写 PARITY CONVERGED @<sha> @<date> 并停止(不再 schedule)。
护栏:桌面 characterization 是基准移动活绝不改它;禁碰真 vault(用 fixture/副本);收敛靠机器不靠"看着对了"。
```

---

## Loop B — 维护(收敛后开,每天/桌面有改时)

```
/loop 12h 移动 parity 漂移巡检。git log 看桌面自上轮以来动过哪些 *_routes.py / server.py / tests/test_*_routes.py;
对每个动过的桌面端点,在 mobile/PARITY_LEDGER.md 找对应 row,把 last-checked sha 跟现 HEAD 比,若契约变了(新增端点/
改了 assert)→ 该 row 重置 🔴 并记一行 why。若有 🔴 → 走 Loop A 的对齐流程补平;全 ✅ 且无新变 → 本轮无事,停。
```

---

## 为什么这么设计(别简化掉的三条)

1. **台账 = 跨 session 记忆**。没它每轮重扫、永不收敛。一 row 一 commit 让进度 durable + 单条可 revert。
2. **oracle = 机器可判**。`parity/` 的 golden 字节-diff / JSON 断言让"对齐"有对错判据,不靠 LLM 肉眼(6.16:UI 对 ≠ 行为对)。
3. **收敛信号 = 终止态**。全 row ✅ + check-fe-be 干净 + critic 无遗漏。Loop A 到此自动停;之后是 Loop B 常驻守漂。

## 现成的洞(loop 第一批活,已在 ledger 标 🔴)

- **D2/D8** 补卡窗口 `is_writable`:mobile `date>=today`(L97/293)反了 → 应 `{今天,昨天 if hour<12}`
- **D3** `daily_dose` clamp:check 路径硬编 1(L184/227)→ 读 meta + clamp + sub-box(golden `daily_tasks__check_clamp.md` 已是真值)
- **T5** thread/save 无 CAS:加 base_mtime → 409
- **J-CB1** authorship:改 journal 块别抹 `#commit` 批注(6.16 踩过)

## 关联

- `PARITY_LEDGER.md` · `MIGRATION_PARITY_GUIDE.md` · `parity/README.md`(oracle 三类)· `parity/check-fe-be.sh` · `parity/capture-golden.py` · `parity/harness.mjs`(骨架,需接 mobile-api.js dispatch)
