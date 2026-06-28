# E2E:标签聚合(tag-aggregation)— 设计 + 迁移蓝图

> 工作流:**先设计 E2E 测试 → 对照 PC 实现逻辑迁移**(同 scrapbook)。
> 用户原话:① 从本地 gateway md 拉**一整条聚合标签**进模拟环境 ② tap+对话框测**聚合标签更新能力**
> ③ 对话框验收 **AI 通过标签读取历史记录**的能力。

---

## PC 真相(canonical,对照源)

| 端点 | 文件:行 | 契约 |
|---|---|---|
| `GET /api/tag-aggregate` | journal_routes.py:266 | 读 `标签聚合.md` → `_parse_tag_aggregate` → `{sections:[{tag,description,columns,rows[]}]}` |
| `POST /api/tag-aggregate/register` | journal_routes.py:193 | `{tag,description?,with_sub?}` → 追加 `## #tag` + 空表头 → `{ok,tag,with_sub}` / `{ok:false,error}` |
| `POST /api/tag-aggregate/refresh` | journal_routes.py:252 | 扫 journal md → diff 现有 → append 缺失行 → `{ok,added,per_tag,scanned}` |
| `GET /api/journal/tag-stats` | journal_routes.py:60 | top-N tag 计数(mobile **已有** mobile-api.js:1402)|
| LLM `search_journal` | tool_specs.py:281 | 全文搜 vault md(含标签聚合)→ 文件+行号+±2 行上下文 |

**parse 契约**(server.py:4284):`## #tag` 起 section;表行 `\| 日期 \| 时间 \| 链接 \| 内容 \| [Sub] \|`;
链接 `[26.5.7#9：30](半小时复盘/26.5.7(第五天).md#9：30)` → 正则抽 `iso_date=2026-05-07`(前端点 row → goto)。
表头行(cells[0]∈{日期,Date})跳过;分隔行(全 `-:`)跳过;`>` 开头是 description。

**seed 源**(真 #yanpai section,~30 行真数据):真 vault `~/.human-ai/vault/标签聚合.md`(**只读,禁写**)。

---

## E2E 判据(两 sub-test)

### Sub-test 1 — tap + 对话框「聚合标签更新能力」
1. seed 真 `## #yanpai` section(30 行)进 sim(Documents/gw/标签聚合.md)。
2. ☰ → 聚合页 → 见 `#yanpai` tab + 行列表(日期/时间/内容,倒序),tap 一行 → 跳对应历史日。
3. 对话框让 AI 注册新 tag(或 refresh):`register #配置系统` → 聚合页多一个 tab。
4. **判据**:`GET /api/tag-aggregate` 返 #yanpai section + rows;register 后新 section 出现;panel 重渲含新 tab。

### Sub-test 2 — 对话框「AI 通过标签读取历史记录」
1. 对话框问 AI:「我之前 yanpai 都干了啥」/「summarize my yanpai history」。
2. AI emit `search_journal("yanpai")` → 扫 journal md + 标签聚合.md → 返命中行。
3. AI 用命中内容总结历史(引用真事件:ICP 备案 / HTTPS / 域名迁移 …)。
4. **判据**:search_journal tool chip 真 emit + 返真行 + AI 回复引用真历史(非杜撰)。

---

## 迁移清单(对照 PC,逐块)

- [ ] **P1 Store**:`readTagAggregate/writeTagAggregate`(Documents/gw/标签聚合.md,Filesystem 文件,同 journal)
- [ ] **P1 shim GET /api/tag-aggregate**:port `_parse_tag_aggregate`(JS 版,parse table rows + iso_date)
- [ ] **P2 shim POST register**:追加 `## #tag` + 表头 + dedup + 校验(无 `/`)
- [ ] **P2 shim POST refresh**:扫 journal md 的 H2 `#tag` → diff → append 缺失行(只 append)
- [ ] **P3 shim LLM search_journal**:TOOL_SPECS + dispatch(扫 journal md + 标签聚合.md keyword,返 file+line+±2)
- [ ] **P4 frontend 聚合页 panel**:替换 gw-app.js:240 placeholder → port aggregate.js(tabs/rows/tap-jump/register/refresh)
- [ ] **P5 真机 E2E**:seed → 两 sub-test 逐项过 + 截图

**红线**:MD 真源不动(register/refresh 只 append 标签聚合.md,不删不改 description);
seed 从真 vault **只读**拷;聚合页不 card 化(DESIGN_BRIEF 铁律)。

---

## 进度

(本 session 自动建,逐 commit 局部,HOLD push)
