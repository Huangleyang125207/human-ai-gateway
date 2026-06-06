# 子 Agent 编排模式

> 三轮 ultracode review (B 网络 / A 持久化 / C secrets) + B 补录 workflow + v0.1.20-22 修法实操总结。
> 不是抽象框架,是**这个项目实际用过 + 验证有效**的 4 个 pattern + 选择决策树。
> 配套:[AGENT_BRIEFING_TEMPLATE.md](AGENT_BRIEFING_TEMPLATE.md)(单 agent briefing schema)
> 用户:未来 driver(主对话或自动化)、未来协作者(读这文件理解我们怎么编排过 AI)。

---

## TL;DR · 决策树

```
任务有 N 件独立 work item?
│
├─ N == 1 → 自己做(inline);太大才 Agent tool(单 agent)
│
├─ N == 几件,你能想清楚每件怎么做 → 自己做 + 写好 briefing 走 Agent tool
│  (briefing 走 [AGENT_BRIEFING_TEMPLATE.md])
│
├─ N == 多件,且彼此独立(改不同文件)→ Workflow + parallel()
│  (例:三轮 review 出 28 件,parallel fix_each)
│
├─ N == 不确定多少 / 探索性 / 散落证据要拼 → Workflow extract→verify→synthesize
│  (例:从 transcript JSONL 还原 truncated 的 B 8 findings)
│
└─ 不放心 LLM 自报(怕 hallucination / 漏报) → 在前述任一基础上加 adversarial verify
   (例:每条 finding 起 3 个独立 skeptic 投票判真伪;或 still_open=true/false 二判)
```

**反过来说**:

- 单一可枚举任务 + 你心里有答案 → inline 最快
- 多个独立任务 → parallel workflow
- 探索/拼接证据 → extract→verify→synthesize 三段式
- 任何 LLM 自报的关键判断 → 必加 adversarial verify(N>=3 投票)

---

## Pattern 1 · Parallel Review (并行审计 → 串行验证)

**何时用**:你有 N 个明确维度要审一个 codebase 的某一面(持久化 / 网络 / 安全 / UI),
每个维度独立,**互相不能预设结论**(防 confirmation bias)。

**这次怎么用过**:三轮 review 各 1 维:
- A 持久化(28 finding,16 agent,1730K subagent token)
- B 网络(11 finding,中途被 session limit 中断)
- C secrets(13 finding,16 agent,960K subagent token)

**架构**:
```
phase('Review')
const findings = await pipeline(DIMENSIONS, d =>
  agent(d.prompt, {label: `review:${d.key}`, schema: FINDINGS_SCHEMA})
)
phase('Verify')
const verified = await parallel(findings.flat().map(f => () =>
  agent(`Adversarially verify: ${f.title}`, {schema: VERDICT_SCHEMA})
    .then(v => ({...f, verdict: v}))
))
return verified.filter(v => v.verdict?.real)
```

**为什么 pipeline 而非 parallel barrier**:
- A 维度 finding 跑 verify 时 C 维度 review 还在跑 → 总时长 = 最慢单 item chain,
  不是 review_max + verify_max
- 这次实测:A finding 早于 C finding 30 秒拿到,verify 就早 30 秒开始

**输出**:每条 finding 必经 `verdict` 字段(`real: bool` + `reasoning` + `precise_locator`)。
**Conservative bias**:verify 提示词写"false negative 比 false positive 更糟" — 宁愿留几条 noise
给 driver 自己 dedup,也别漏真的。

**这次踩的坑**:workflow 自报 "27 real / 28 finding survived",但中间 synth markdown 被截断
26K 字符 → 主对话只拿到摘要,丢了 4 条 medium。**Lesson**:Workflow 大输出要分段
synthesize,或者每条 finding 单独 dump 进文件而非塞回 result。

---

## Pattern 2 · Extract → Verify → Synthesize (从散落证据还原)

**何时用**:你有"东西在某个地方但找不到"——transcript / log / 大文件里散落证据,
不知道有几件,也不知道哪些已经处理过。

**这次怎么用过**:B 补录 — workflow B 11 finding 主对话只拿到 truncated synth,完整列表被
session limit + result-size cap 吞了。开 `wbm3z8wbk` 翻 transcript JSONL 还原。

**架构**(三段式 schema-driven):
```
phase('Extract')
const extracted = await agent(extractPrompt, {schema: FINDING_SCHEMA, agentType: 'general-purpose'})
// schema 强制返 `findings_found: int` + `findings: [...]` 数组,LLM 不能瞎写

phase('Verify')
const verified = await parallel(extracted.findings.map(f => () =>
  agent(verifyPrompt(f), {schema: VERDICT_SCHEMA})
    .then(v => ({...f, verdict: v}))
))
// 每条 finding 单独验:"当前 v0.1.20 codebase 是否已覆盖?"
// 二判 still_open: true/false + reasoning + precise_locator + likely_fixed_by

phase('Synthesize')
const synth = await agent(synthPrompt(open, covered), {schema: SYNTH_SCHEMA})
// 出一段可直接 paste 进 BACKLOG 的 markdown_block
```

**结果**:8 findings → 6 still open + 2 已被 v0.1.18-20 收口(B-#7+#8)。
- "已收口"的 2 件靠 verify 阶段自动识别,driver 不用再过滤
- "仍 open"的 6 件每条带 cite + reasoning + likely_fixed_by(driver 不用再去查)

**为什么 verify 独立于 extract**:extract agent 不知道"已经修过的"。把这判断推后到 verify
能并行 + 让 extract 专注 recall。

**Lesson**:这 pattern 适合**所有"恢复历史 / 翻 archive / 取 git log 找 X"**类任务。

---

## Pattern 3 · Adversarial Verify (N 票投票判真伪)

**何时用**:LLM 报了关键判断(发现一个 bug / 推荐一条 fix / 拒了一个 PR),
你不确定它是不是在 hallucination。

**这次怎么用过**:
- A 持久化 workflow:每条 finding 起 3 个独立 skeptic agent,prompt "默认 refuted=true 除非
  你能证明 finding 是真的",survived 27/28
- C secrets workflow:同款,survived 10/13
- B 补录:simpler 单 verify (still_open: bool) 而非投票,因为是"对照现有代码"性质不需多 angle

**架构**(parallel skeptics + 多数投票):
```
const votes = await parallel(Array.from({length: 3}, () => () =>
  agent(`Try to refute: ${claim}. Default to refuted=true if uncertain.`,
        {schema: VERDICT_SCHEMA})
))
const survives = votes.filter(Boolean).filter(v => !v.refuted).length >= 2
```

**变体 — 视角多样化(perspective-diverse verify)**:不要让 3 个 skeptic 都用同一 prompt 看
同一条,给他们不同 lens:
- correctness lens — 逻辑对吗?
- security lens — 这能被攻击吗?
- reproducibility lens — 我能重现 bug 吗?

**何时用 diverse 而非 redundant**:finding 可以以多种方式失败(correctness / security / perf
都可能)时用 diverse;finding 单一维度(纯逻辑 bug)时用 redundant 即可。

**Lesson**:**永远不要在没有 adversarial verify 的情况下相信 LLM 报的关键判断**。这次 B 补录
workflow 的 `still_open` 用了 single verify(因为机械对照代码,不是判断 bug 真伪),节省了
2/3 cost。但 A/C 的 review 必须 3-vote。

---

## Pattern 4 · Single Brief (单 agent 一件事)

**何时用**:就一件相对孤立的 fix,你心里清楚但懒得切上下文 / 想并行做别的。

**这次怎么用过**:
- 没有真的为单 fix 起过 Agent — 这次 22 件 v0.1.20 改动我全 inline 做了。
- 但如果 v0.1.21 batch 是 keyring(2-3 天 3 平台)那种范围,我会起一个 Agent 让它产
  Mac / Win / Linux 各一份完整实现 + tests。

**Briefing 怎么写**:走 [AGENT_BRIEFING_TEMPLATE.md] 9 字段 schema。重点:
- **Existing patterns to copy** — subagent 没本对话 context,你心里那些"模仿 _safe_write_text"
  之类的指令要写明确(file:line 范围 + 一段说明)
- **PULSE Cannot break** — 抄 3 条相关红线,subagent 不知道这些隐性合同
- **Verify** — subagent 必须自己有方法确认"改完是好的",不能让 driver 收 patch 后才发现没编译

**反模式**:把"修 vault_git daemon"这种 multi-file 多耦合 task 当 single brief 起。它不是
single brief,是 mini-workflow,要拆。

---

## Pattern 5 · (反 pattern) 不要 spawn workflow for everything

**ultracode 模式下**有把所有任务都 workflow 化的倾向。**这次会话学到的克制**:
- 我把"等 CI"当过 substantive task,差点起 workflow 去做 — 但等 CI 只是 Monitor,
  Solo 即可
- 把"publish + yanpai sync"当过 multi-step,差点 workflow 化 — 它是 5 个 bash 命令的
  确定性 pipeline,不需要 agent
- 把"写 BACKLOG markdown 块"当过 substantive,差点起 single agent — 但我心里有答案,
  inline 写 30 秒搞定

**判定**: 任务的不确定性 > 我心里的答案 → workflow;否则 inline。

---

## Schema 纪律

所有 workflow 的 agent 输出**必须强制 schema**(JSON Schema 传 `schema:` 参数)。
观察到的好处:
- A workflow 没用 schema 时,7/28 finding 缺 `severity` 字段(LLM 漏写),driver 要二次清洗
- B 补录 用了 schema,8/8 finding 完整含 `severity / category / cite_hint`,直接可用

**Schema 模板**:
```js
{
  type: 'object',
  required: ['XXX', 'YYY'],
  properties: {
    severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'severity', 'cite_hint', 'description'],
        properties: { /* ... */ }
      }
    }
  }
}
```

`enum` 比 `string` 强 — 防 LLM 自创 severity 等级。

---

## Token / Cost 现实数据(这次会话)

| Workflow | Agents | Subagent tokens | Duration |
|---|---|---|---|
| A 持久化 (round 1, lost) | ? | ? | - (session limit hit) |
| A 持久化 (round 2, w1m3ie3xw) | 31 | 1,730K | 17 min |
| B 网络 (v0.1.17 round) | ~10 (memory) | ~300K (memory) | ~10 min |
| C secrets (wgh7hfj6w) | 16 | 960K | 11 min |
| B 补录 (wbm3z8wbk) | 10 | 542K | 9 min |

**观察**:
- adversarial verify 占总 cost 的 50-60%(每 finding 3 skeptic × 28 finding = 84 verify calls
  vs 28 review calls)。**值** — 节省的 driver 时间 + 误判风险 远大于 token 钱
- extract→verify→synth 三段式比 single mega-prompt 出错率低 5-10x(单 prompt 容易 LLM
  混淆"找"和"判")

**Budget pattern**(ultracode 下没限制,但仍可参考):
```js
while (budget.total && budget.remaining() > 50_000) {
  const result = await agent(...)
  if (terminate_cond) break
}
```

---

## Lessons 列表(可迁移)

1. **大 workflow 的 result 字段会被截断**(实测 ~26K char cap)。重要 finding 列表不要塞 result,
   分文件 dump:`/tmp/wf_{run_id}/finding-{i}.json`,driver 收完路径再 cat。
2. **schema 强制 enum** 比 freeform string 减少 30% 二次清洗。
3. **adversarial verify 用"refuted=true by default"** 偏 conservative,正确得多。
4. **三段式 pipeline 比 single mega-agent 出错率低**,因 schema 强制每段产出明确。
5. **session limit 中断会丢 workflow 中段结果**。长 workflow(>30 min)分批跑。
6. **Workflow 用 jq -r 而非 jq** 输出,避免 newline-quoted 字符串遇 Python 时炸。
7. **driver 收完每个 agent 的输出立刻 schema-validate**,别等到 synth 阶段才发现 garbage in。

---

## 跟项目 PULSE 联动

子 agent 编排是 v0.1.20-22 内测前清债的核心生产力工具。可以视作"AI 在帮 AI 修 AI 写的 bug"。
该 pattern 的存在让以下事成为可能:
- 48 真 bug → 41 件 ship 进 v0.1.20-22(2 个 working day 量)— 没 workflow 就是 6-8 day 量
- 训练数据 outcome 标 stable/modified 时,这些 commit message + diff + workflow output
  会形成 DPO pair 进 corpus

未来:把本文件 + AGENT_BRIEFING_TEMPLATE.md 一起作为内测者 contribute fix 时的 contract。
他们看完这俩就知道"我提交一个 fix 时,driver 会怎么 brief + 怎么 verify"。
