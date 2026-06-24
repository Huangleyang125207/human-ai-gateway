# 移动端迁移指南 — 用桌面 characterization 网当 parity oracle

> 写给做移动端迁移的 session。
> 背景:2026-06-24 桌面 `server.py`(9499→6271 行)被拆成 per-feature route 模块,
> **每个模块配了一组 characterization 测试**。这份指南告诉你:那些测试**就是**移动 shim
> 必须满足的契约 oracle —— 迁移一个功能 = 让 `mobile-api.js` 通过同一组断言。
>
> 创建:2026-06-24 · 配套 commit `e965677`(server.py 解构收官)

---

## 0. 一句话

> 桌面模块是 canonical 契约;它的 characterization 测试是对错判据。
> 迁移 = 拿桌面测试当 spec,逐条验 `mobile-api.js` 是否产出同样行为,不一致就改 shim。

---

## 1. 心智模型(先记这 4 条,跟 DESIGN_BRIEF 的 DNA 一致)

1. **MD 是真相**。两端共写,**桌面是 canonical 那一份**;移动端最终也要把改动落回同样字节的 md。
2. **移动端不复用桌面 Python** —— `mobile/mobile-api.js`(691 行)是个 JS shim,在客户端**重新实现** server 端点(local-first,无后端)。所以"迁移一个功能" = 在 shim 里把它的端点行为复刻对。
3. **桌面 route 模块 = 该功能的完整契约面**;它顶部的端点 + 它的 characterization 测试 = 这个功能"该怎么表现"的黄金标准。
4. **比对以 grep / 断言为准,不看 UI 长相**(6.16 血的教训:UI 对了 ≠ 行为对了,产品状态以 handler diff 为准)。

---

## 2. 地图:feature → 桌面模块 → oracle 测试 → mobile shim

| 功能 | 桌面模块(端点数) | oracle 测试(条数) | mobile 是否在迁 | 移动 parity 价值 |
|---|---|---|---|---|
| **journal 读写 + tag-aggregate** | `journal_routes.py` (10) | `tests/test_journal_routes.py` (15) + helper 层 `test_authorship` / `test_patch_h2_rename` / `test_insert_block_body` | ✅ 在迁(最高频) | ★★★ 最高 |
| **daily-tasks 打卡 + 八杯水** | `daily_tasks_routes.py` (8) | `tests/test_daily_tasks_routes.py` (16) | ✅ 在迁 | ★★★ |
| **thread 聊天历史持久化** | `thread_routes.py` (3) | `tests/test_thread_routes.py` (8) + `test_thread_cas` (8) | ✅ 在迁 | ★★ |
| **setup / 钥匙 / 模型** | `setup_routes.py` (10) | `tests/test_setup_routes.py` (21) | ✅ 在迁 | ★★ |
| **chat 对话引擎** | `chat_routes.py` (2) | `tests/test_chat_routes.py` (15) + `test_claim_audit` / `test_attachment_dedup` | ⚠️ mobile 是 thin SSE wrapper,**无 tool loop** | ✩ 低(见 §6) |
| **board / 留言板 eval** | `board_routes.py` (4) | `tests/test_board_routes.py` (11) | ✗ desktop-only | — |

> **危险代码(authorship 边界 + sha-lock + H2-guard + CAS)留在 `server.py` 没搬**,
> 由 helper 层测试(`test_authorship` 等)锁。移动端复刻 journal 写时,这些不变量**一样要守**(§5)。

---

## 3. 每功能迁移工作流(照这 6 步走)

```
1. 选一个功能 → 打开它的桌面模块(server 那侧)+ 它的 characterization 测试文件。
2. 读测试的每个 assert —— 这就是该功能的完整契约:
     · HTTP 输入(body/query 形状)
     · 输出(字段名、状态码 200/400/404/409)
     · 副作用(md 字节怎么变、哪个 json map 改了)
3. grep mobile-api.js 找对应实现段(按端点路径 / 函数名)。
4. 逐条 diff:同样输入,mobile-api.js 产出的是不是桌面断言要的那个?
5. 不一致 → 改 shim 对齐(优先级:① md 字节 ② 状态码 ③ 字段名 ④ 边界/时区)。
6. 验:
     · 理想 —— 把桌面 assert port 成 JS 测试(node/vitest)跑 shim,红→绿。
     · 最小 —— 桌面 `pytest -v` 把测试名当 checklist 人工对照 + 真机点一遍。
```

**看某功能的契约清单(测试名即清单):**

```bash
cd ~/human-ai-dev/gateway
.venv-test/bin/python -m pytest tests/test_daily_tasks_routes.py -v   # 列出 16 条契约
# 再直接读断言:每条 assert 就是 mobile 要复刻的那个行为
```

---

## 4. 已知 parity 洞(立即工作清单 —— 重构时实测出来的,不是猜)

这些是 6.24 抽模块时,拿桌面 oracle 对照 `mobile-api.js` 当场抓到的真背离。**这就是你的第一批活。**

### ① daily-tasks 补卡窗口 `is_writable`  ★Cannot-break
- **桌面真相**:`tests/test_daily_tasks_routes.py::test_check_backfill_window_yesterday_before_noon_else_403`
  + `test_check_rejects_future_and_catalog_is_writable_window`。窗口是**闭集** `{今天, 昨天(仅当 now.hour<12)}`,
  服务端按时区算;未来日期 + 前天都 **403**。
- **mobile 背离**:`mobile-api.js` 用 `todayIso()`(L97)、`is_writable = date >= today`(L293 一带)——
  正好**反**:放未来、拒昨天。
- **改法**:shim 的 `is_writable` 复刻 `{today, yesterday-if-hour<12}` 闭集;`/check` 对窗口外日期返错。

### ② daily-tasks `daily_dose` / intake clamp 数学
- **桌面真相**:`test_check_intake_increment_clamp_and_md_box` —— intake/increment clamp 到 `daily_dose`,
  `intake>=daily_dose` 才 md `[x]`,intake=0 从 log pop。
- **mobile 背离**:catalog 路径(L439-449)已会读 `meta.daily_dose`,但 **check/写勾路径(L184/227)还硬编 `daily_dose:1`**,
  没 intake/clamp/子 box。dose>1 的补剂(如维生素 D 一天 2 粒)在手机上勾一下就满,跟桌面不一致。
- **改法**:check 路径也读 meta 的 daily_dose,复刻 `_bump_intake` 的 clamp + sub-box 逻辑。

### ③ thread/save 无 CAS(陈旧覆盖)  ★Cannot-break
- **桌面真相**:`tests/test_thread_cas.py`(8 条)—— `/api/thread/save` 带 `base_mtime`,跟当前 mtime 不符 → **409 + 文件原样**;
  防 5.17/5.26"陈旧标签页盖掉新历史"。
- **mobile 背离**:`mobile-api.js` 的 thread/save **没有 base_mtime / 409**(grep 空)—— 裸覆盖。
- **改法**:shim save 加 mtime CAS(local-first 下多设备同步时尤其重要);损坏读 → 返 `status:'corrupt'` 不空 [] 覆盖。

### ④ chat 无 tool loop(不是 bug,是产品决策点)
- **桌面真相**:`chat_routes.py` 是多轮 tool loop + DSML 闸 + 流式 chokepoint(`test_chat_routes.py` 15 条锁)。
- **mobile 现状**:thin DeepSeek SSE wrapper,无 tool loop —— **没对等契约可比**。
- **建议**:chat 不按"逐条对齐桌面"迁(那是另一个产品形态)。要让手机 AI 能写日记/打卡,
  需要单独设计移动端的 tool 执行路径,**不在本指南的 parity 范围**。先把 §4①②③ 三个数据洞补了。

---

## 5. Cannot-break(移动端复刻时绝不能丢的不变量)

桌面把这些危险代码**留在 server**,移动端 local-first 自己实现时**一样要守**,否则就是数据事故:

- **authorship 边界** —— 改 journal 块时,AI 字节不能覆盖 `@user` 块;`#commit` 批注/签字不能被抹
  (6.16 实测:mobile 的 patch 替整块到下个 `---` 时差点抹掉协作签字,靠拼回原始批注救回)。桌面 `test_authorship` 是 oracle。
- **patch H2 不匹配 guard** —— patch 不能当 insert 用吃掉别的 entry(`test_patch_h2_rename`)。
- **thread 损坏 → modal,不空覆盖** —— 读失败返 `status:'corrupt'` + baks,**绝不**拿空 [] 当真覆盖(5.17)。
- **MD 字节兼容** —— 时间块 `# HH：MM` 用**全角冒号**;`@author` marker;顶部 `- [ ]` 打卡段。
  6.15 已验两端半点块**字节级兼容**(shim parser 复刻了 server),改 shim 别破坏这个。
- **补卡窗口服务端语义** —— `is_writable` 是行为契约不是 UI 提示,复刻 server 的时区窗口逻辑(§4①)。

---

## 6. 优先级(按 mobile 已 shim × 用户高频 × parity 价值)

```
P0  journal 写路径(patch/insert/delete) —— 最高频 + 危险不变量最多,先把 authorship/字节 对齐
P0  daily-tasks 三个数据洞(§4①②③ 里的 ①②)
P1  thread/save CAS(§4③)
P1  setup / 钥匙(低风险,纯契约对齐)
P2  daily-tasks 其余(history / backfill / water-cup)
不做 chat tool loop(独立产品决策)· board/eval(desktop-only,移动不渲染)
```

---

## 7. 怎么把桌面测试真的当 oracle 用(具体)

**A. 看契约**(测试名 = checklist):
```bash
.venv-test/bin/python -m pytest tests/test_journal_routes.py tests/test_authorship.py -v
```

**B. 读真值**:打开测试文件,每个 `assert` 就是 mobile 要复刻的精确行为(状态码、字段、md 字节)。
测试里的 fixture(怎么造 today 日记 / meta map)也告诉你输入长什么样。

**C. 对照 shim**:`grep -n "<端点路径>" mobile/mobile-api.js`,把那段行为跟 B 的断言逐条比。

**D. 落差变测试**(理想):把桌面 assert 翻成 JS 跑 shim;最小版人工对照 + 390px 真机点一遍(MD 字节级查,
不只看 UI —— 用 `git diff` 看手机生成的 md 跟桌面真文件差,目标是空 diff,6.15 已达成过)。

---

## 关联文档

- `mobile/MOBILE_DESIGN_BRIEF.md` —— 移动端视觉/交互 brief
- `mobile/RUNBOOK.md` —— 移动端 build/跑的 runbook
- `agents/human-ai-schedule/SKIN_WORKFLOW.md` —— 桌面"对等 diff"方法论(阶段 4:两边 `label:` 全量 diff)
- 桌面各模块 docstring —— 每个 `*_routes.py` 顶部写了"留 server / 搬走 / 不变量"
- 6.15/6.16 半小时复盘 —— 双端同步格式地基 + 移动 CRUD 闭环的实测教训
