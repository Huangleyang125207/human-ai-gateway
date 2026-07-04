# Scrapbook/Float 贴图 · PC ↔ 移动 对齐侦察报告

> 2026-07-04 探测(Explore agent + CC 抽验)。对齐动手前的事实基线。
> 抽验修正:paper 皮肤贴纸在 day-paper-data.js:699 renderStickers,插 .piece 内、
> 相纸白边(.sticker, shared/components.css:560)、双击取下 — 非字面 float:right,但同属"随文档流"模式。

## A. 桌面端能力清单

### 数据模型(server.py:1698-1708;持久化 data/scrapbook/{date}.json)

```
{ id, src, anchor_time("HH:MM" 语义挂点), x_pct(0-95), y_px, w, h,
  size_pct(占 .sb-layer 宽 %,等比缩放契约 6.15 锁 18.3%), rotation(-4~+4 随机或用户),
  auto_y(y 是否由 anchor 自算;用户拖过即 false), cutout, z(占位未用) }
```
旧字段 align/x/y 由 shared/scrapbook.js normalizeItem() 读端迁移。

### 渲染两模式
- **classic(index/day)**:.sb-layer 绝对定位层叠加全页(pointer-events:none),
  x_pct→left%、y_px→top、size_pct→width%。auto_y=true 时 computeYFromAnchor()
  按 entry offsetTop 算,pretext 绕排异步后 200ms/600ms 两次 repositionPass 校准
  (scrapbook.js:44-126)。
- **paper**:renderStickers 把贴纸插进 anchor 命中的 .piece 内(文档流,相纸白边,
  双击取下;day-paper-data.js:699-719)。

### 文字绕图(classic 独有)
vendor/pretext(@chenglou/pretext@0.0.7 ESM,本地 vendor)+ entry-pretext-wrap.js:
贴纸旋转矩形 → 4 角多边形 → 扫线算每行可用宽 → pretext 自算断行。
**不是 CSS float/shape-outside**。scrapbook reposition 后调 rewrap()。

### 交互全集(scrapbook.js:160-400)
拖动 bindDrag / 旋转 bindRotate(atan2) / 缩放 bindScale(size_pct) /
删除带撤回 / 拖完 inferAnchorByY 自动改挂点 / 600ms debounce upsert。
z 与 cutout 有字段无 UI。

### AI 工具 place_scrapbook_image(server.py:1647-1711)
必填 attachment_url + anchor_time;y_px 缺省 → auto_y=true;rotation 缺省随机;
cutout 默认 true 走 _get_or_create_processed_attachment(端侧/百度抠图)→
写 scrapbook-images/{date}_{id}.png。

## B. 移动端现状
- 数据 13 字段同构(mobile-api.js:1655-1677),存 Preferences/localStorage
  `setting/scrapbook/{date}`。
- 渲染:float:right 进 .gw-entry-body,width = size_pct×1.6%(390 窄屏放大系数),
  rotation 用了,anchor_time 归一容错已加(gw-journal.js:64-81)。
- 编辑:长按 → absolute,拖(写 x_pct/y_px,auto_y=false)/缩(反除 1.6 写回 size_pct)/
  删+3s 撤回(gw-journal.js:296-400)。
- shim /api/scrapbook/{get,upsert,delete} 齐;place_scrapbook_image 转 upsert,
  **无抠图处理**(cutout 字段收下不动作)。

## C. 差距矩阵(桌面→移动)

| 能力 | 状态 | 备注 |
|---|---|---|
| 13 字段数据格式 | ✅ 同构 | 跨端互读安全 |
| upsert/delete API | ✅ | |
| size_pct 等比契约 | ⚠️ | 移动显示 ×1.6、写回 ÷1.6,往返数值不漂(需测钉死) |
| auto_y 语义 | ⚠️ | 移动读了但无 repositionPass(entry 增删后不重算) |
| 拖动/缩放/删除撤回 | ✅ 简化版 | |
| 旋转交互 | ❌ | PC bindRotate 成熟,移动未接 |
| inferAnchorByY | ❌ | 移动拖跨 entry 不会改挂点 |
| pretext 文字绕图 | ❌ | vendor 未入移动 bundle(build-web.sh 0 处 pretext,已核) |
| 抠图(cutout) | ❌ | shim 不处理;端侧 Cutout 插件在但未接此链 |
| z 层级 | — | 两端都只是占位字段 |

## D. 对齐建议分层

**P0(语义安全,先做):**
1. size_pct 往返测试钉死(桌面写 18 → 手机显 28.8% → 手机拖缩写回 → 桌面仍语义一致)
2. auto_y:移动 reloadDay 后按 anchor 重挂(entry 删增后贴纸跟走)
3. 移动编辑写回的 x_pct/y_px 在桌面渲染的还原性验证(y_px 坐标系不同,靠 anchor_time 兜底)

**P1(值得移植):**
4. 旋转交互(约 50 行,照抄 bindRotate 换 touch 语义)
5. inferAnchorByY(约 20 行)
6. place_scrapbook_image 移动侧接端侧抠图(Cutout 插件已在,链路未接)

**P2(明确不照搬):**
- pretext 绕图:390px 窄屏绕多边形后行宽<10 字,可读性反降;+40KB bundle;
  移动 float:right 已达"文字避让"的 80% 效果。除非用户投诉再议(届时先试 shape-outside)。
- y_px 跨端像素换算:两端坐标系宽度不同,换算复杂;auto_y+anchor_time 已是语义兜底,维持。

**风险清单:**
- 移动 bundle 现 ~180KB,监控 <250KB;
- 移动无 _safe_write_text 同级备份(Preferences 靠系统保护,MVP 可接受);
- MOBILE_MVP_PLAN.md:61 曾把 scrapbook 标"砍",现状已部分复活 — 文档需更新。
