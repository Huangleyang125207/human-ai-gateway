# 架构清册 · 总索引（ARCHITECTURE LEDGER）

> **2026-11-18 · API 发行版**　桌面端由本地 sidecar、移动端由设备使用用户自己的凭据请求 DeepSeek 官方 API。应用在本地组装对话与留言上下文。下文 9 月的设备令牌、快照同步和定时领取属于暂停的 staging 方案。

> **时效**：这是截至 **2026-07-22** 的架构快照，不是实时状态页。先看 [`CURRENT_STATUS.md`](CURRENT_STATUS.md) 确认当前事实；需要理解当时的系统结构、风险和决策才进入本清册。阅读路径：先看本页的“鸟瞰一段话”和 TOP10；只在处理某个子系统时进入 `ledger/00-08` 对应分册。项目总导航见 [`../../DOCUMENTATION.md`](../../DOCUMENTATION.md)。

> 两仓全量建卡：`gateway/`（PC 桌面端,python + vanilla JS,~55k 行）+ `gateway-rn/`（RN 移动端 Expo,~14k 行）。
> 方法：第 0 遍全文件过手（头注+结构+行数,server.py 189 函数全量 outline 分段）→ 分 8 册逐卡（职责/真源锚点/依赖/疤/跨端/健康度）→ **每章经对抗审核修订**。
> 疤（事故注释）一律原样摘录；未实读处标"存疑"。初版写于 2026-07-20。
>
> **2026-07-22 终态刷新**：server.py 拆分战役完成（5259→1408 行,-73%,20 段迁出 19 个模块）、contract 第一批 39 符号退役、基线 384 过 0 红、prompt 契约数据化（prompts/*.md → promptContract.json）、mobile/ 归档完毕、thread.js 首张 characterization 网、新增 updater 契约测试。健康度统计/TOP10/可勾选清单已按此重算,详细执行记录见 [01-server-core.md](ledger/01-server-core.md)；02-08 各章开头补终态注,不逐卡重写。
> **2026-07-31 增量注**：RN 备忘录确立 GUI + AI 双入口边界，两者共用 `memoStore` 唯一真源；后台 AI 唤醒仍未接入。
> **2026-07-31 Harness 增量注**：DeepSeek 的 34 个注册工具被 `skills/registry.json` 唯一归属到 8 个领域 Skill；system prompt 只常驻索引，`search_skills` / `load_skill` 披露方法，大型参考文档通过 `read_skill_resource` 分页读取。Skill 不授权；`gateway-architecture` 直接引用本清册，不维护影子副本；PC 是运行真源，RN 由工具/effect/prompt 生成链携带同一快照。

> **2026-08-02 RN 留言读侧增量注**：21:30 纸条仍以日记 Markdown 为唯一真源；`findNightNote` 负责领域识别，`CareZone` 只暴露入口，`NightNoteSheet` 经日记渲染门面展示正文。普通 21:30 日记不再误报“留言已写”，UI 不复制持久化状态。
> **2026-08-01 指令范围修正（历史）**：实机证明“只看最新一句”会误拦截紧邻纠正/确认，因而引入上一条用户操作的有界继承。2026-08-03 起这套意图继承只用于 Widget 变更审核，不再闸日记等领域工具。PC/RN 仍在送模型前过滤历史 `load_tool_group` 调用，避免旧协议回流。
> **2026-08-02 RN 日记展示边界**：RN 新增 `services/journalMarkdown.ts` 作为存储 Markdown→UI 投影的唯一适配层，`components/JournalMarkdown.tsx` 隔离第三方渲染器。磁盘 Markdown、解析和写入契约保持原样；独占行 HTML 元数据只在展示投影中隐藏，围栏代码与行内代码示例保留，并由独立合同测试守门。
> **2026-08-05 对话信封 / KV Cache 合同**：8 月 3 日只保存 `ts`、再把历史投影成 `[sent-at]` 的修复被证实只解决语义可见性，会把首次发送的 `[time-block] + [view-date] + context + vision/OCR + 原文` 改写成另一串字节。PC/RN 现分离 UI `content` 与不可变 `model_content` / `modelContent`，并保存助手工具轮的真实 `model_messages` / `modelMessages`；新消息在后续请求中逐字重放，旧消息继续走兼容投影。PC/RN 主流式路径均请求 DeepSeek usage；PC 写 cache 日志，RN 只在本地保留最近 20 条 hit/miss 指标，不记录正文。Compact、PULSE/system prompt 更新仍是有意的缓存新周期。
>
> **2026-08-13 RN History / Compact 边界纠正**：完整对话 History 是用户可回看的原始真源，不能等同于模型上下文。RN thread v3 取消 200 条持久化截断，Compact 不再用“摘要 + 最近 5 轮”覆盖 `messages`；它只持久化 `summary/through/at` checkpoint，模型请求与顶栏计量才从完整 History 派生压缩上下文，UI 的 16 条分页继续读取完整原文。Compact 排障日志写入沙盒 `debug/compact.jsonl`，只记录模式、状态、条数、字符数、摘要长度和截止下标，不记录对话或摘要正文。当时仍以单个 MMKV JSON 保存完整 History；该存储事实已由 2026-08-19 增量替代。
> **2026-08-19 PC History / Compact 边界对齐**：桌面端 `thread-history.json` 升级为兼容旧 list 的 v2 envelope，完整 History 与 `summary/through/at` checkpoint 分开持久化；普通保存、本地缓存和模型请求不再使用 100/200 条固定窗口。Compact 只推进 checkpoint，UI 原文不变；同一标签页的保存经单写队列推进 CAS 基线，checkpoint 保存失败会回滚，409 合并 server 与本地未同步消息而不再整段覆盖。损坏文件必须经显式 start-fresh 归档后才能新开。PC/RN 共同遵守“History 是用户真源，Compact 只改变模型派生上下文”。
> **2026-08-19 PC 附件路径安全边界**：`attachment_service.resolve_attachment_path/url` 是附件语义 URL 到本地文件的唯一 owner；HTTP、Chat OCR/vision、抠图、AI 图片/贴纸与删除路径均复用它。解析同时约束日期、正反斜杠、`..`、文件存在性及 canonical path 必须位于附件根内，符号链接也不能把文件送出 root。新附件消费者不得自行用正则拆 URL 后拼路径。
> **2026-09-07 写入授权取消**：`ActionPolicy` 的关键词、日期、删除意图和确认审核均已按产品决定退役；AI 对已注册工具的写入、Widget 变更与删除直接派发，不再从当前用户文本推断授权。它仅保留未知工具的失败关闭，以及“图片观察必须引用本轮可见原图”的完整性检查；`@user` / `@ai` authorship、领域 schema、原子持久化和日更 Widget 写窗仍各自生效，它们不是对话授权闸。
> **2026-08-05 标签记忆边界纠正**：日记 Markdown 是项目情景记忆的唯一真源，`标签聚合.md` 只保存注册标签、说明和可重建表格投影。PC/RN 应用内新增、改名、删除和撤回会按日期局部同步；聚合页刷新会全量重建，以吸收 Obsidian 等外部编辑。旧“只追加、按日期+时间+子标签判重”已退役；跨年文件名不再写死 2026，同时间多条记录均保留。reconcile 只拥有注册段表头后紧邻的主表，后续人工表格不属于派生数据。源日记读取失败时必须中止重建并保留旧索引；派生同步失败不得回滚已成功的日记真源写入，PC 在写入结果披露 warning，RN 留 `tagagg_dirty` 诊断标记供后续全量修复。
> **2026-08-17 RN 标签聚合生命周期闭合**：标签注册由 `store` owner 自动触发历史回填；启动、回前台和进入聚合页会安全执行全量维护，以吸收外部 Markdown 修改和消费 `tagagg_dirty`。维护失败只保留旧派生索引并留下重试信号，不回滚日记真源。日记日期月历只投影并修改 `journalStore.date`，没有第二份选中日期状态。
> **2026-08-18 标签自动注册边界纠正**：PC/RN 不再把“已注册标签自动回填”误称为完整自动化。有效时间块 H2 中出现的新顶层标签会由标签聚合 owner 在同一锁内追加注册段并重建派生行；`#parent/child` 自动注册 parent，新自动段一律使用可容纳 `Sub` 的表头。注册只增不自动删：日记删除或改名会清理派生行，但不会注销既有标签、说明或人工附录。首次没有聚合文件时也从日记真源建索引；读取失败仍保持旧索引，禁止半写。
> **2026-08-18 标签词表 / Harness 边界**：`标签聚合.md` 在派生行之外新增人可读的 `说明 / 适用范围 / 避免用于` 元数据，成为 DeepSeek 的受控标签词表；日记仍是标签实际使用的唯一事实真源。PC/RN 的基线 system prompt 不注入词表，只常驻未知标签的处理方法；当 AI 的 insert/patch 首次提出未注册顶层标签时，宿主在落盘前返回按标签名稳定排序、只含语义元数据的有界 `tag_vocabulary`，要求复用已有标签，或显式调用 `manage_tag_aggregate(register)` 后重试。GUI、人手编辑、系统备忘写入和已注册标签路径不经过该闸门。计数、日期和使用行不得进入披露块。标签注册落盘后由后台注释器在写锁外调用 DeepSeek、回锁后仅补仍缺失的字段，人的并发编辑优先，失败不得回滚日记或注册。PC 的 `scripts/enrich_tag_metadata.py` 可重试旧缺失项。普通对话和词表变化均不再改写稳定 system 前缀。
> **2026-08-17 通用文本检索边界**：领域专用 `search_journal` 已由只读 `search_text` + `read_text` 取代。两端每次直接读取当前可见 Markdown：PC 扫 vault，RN 扫本机 journal 与标签聚合；无索引、Embedding、检索缓存或影子真源。搜索只做字面量行匹配并返回文件/行号/上下文，补读只能访问搜索边界内的 `.md` 且有行数上限。PC `tool_specs.py` 继续拥有公共 schema，RN 由生成链携带当前 41 工具合同。
> **已知边界**：ActionPolicy 当前是保守关键词意图判定，Widget 变更尚未约束到具体 id/spec 修订；单条日记与贴纸删除已收窄到参数级目标，但仍依赖当前用户文本表达明确删除意图。Skill 注册表仍假定仓库内文件可信，没有第三方 Skill 所需的逐项错误隔离与 mtime 缓存。
> **2026-08-05 Harness 领域能力补齐**：注册工具由 34 增至 39；新增 `manage_tag_aggregate`、`get_daily_care_state`、`manage_scrapbook`、`delete_journal_entry`、`manage_mood`，PC/RN 继续由同一 schema/effect 生成链约束。工具是领域语义门面，不是原始 HTTP API 镜像；`create journal day` 仍是宿主生命周期能力。普通日记写入不进通用关键词审核，只有单条日记/贴纸删除与 Widget mutation 需要匹配当前用户的明确意图。心情是按日期的应用状态：各端 GUI 与 AI 共用同一端内真源，不写入 Markdown。
> **2026-08-05 星期解析边界**：实机证明仅注入 `date(Wednesday)` 仍会让模型把周一误算成周二。PC/RN 的每轮动态用户信封现注入本周周一至周日的确定日期表和上/下周 ±7 天规则；日期算术由宿主承担。该信息留在动态尾部，不挪入 system prompt，避免扩大 KV cache 的稳定前缀失效面。
> **2026-08-05 DeepSeek 思考协议边界**：PC/RN 主对话显式固定 V4 `thinking=enabled` 与 `reasoning_effort=high`，不依赖 provider 默认值；参数在每一工具轮和收尾轮保持一致，消息字节与稳定 system 前缀不变。工具调用的原始 `reasoning_content` 属 provider 协议帧，必须随本地 canonical 历史完整保存、回放，并在 AI 消息中默认折叠、按需展开；升级前动作没有该字段，因而只能降级为不可执行摘要，禁止伪造 CoT。遥测和运行日志只记录 requested/effort/received/chars，不复制思维链正文；PC 的 DeepSeek 私有参数不下发给其他兼容 provider。
> **2026-08-11 RN 日记交互与留言边界**：手写正文不再继承日更 Widget 写窗，用户可整理所选日期；喝水、打卡、心情等按日 Widget 只允许改当天，过日后冻结。留言 Markdown 仍是唯一真源；`CareZone` 常驻暴露入口，`NightNoteSheet` 承担空态/重试，App 冷启按“建日→载入→检查”串行并在前台跨 21:30 触发。后台唤醒仍未实现，App 被终止时不得宣称会准点生成。
> **2026-08-11 留言板 / Cache 观测增量**：RN 将日记内“今晚纸条”和跨日“留言板”拆成两个 UI 语义；两者仍读取同一份 21:30 日记 Markdown，`NightBoardView` 只做最近 14 封的预加载投影，不另建持久化真源。新留言按桌面复盘的四段业务契约生成，稳定规则留在 system 前缀，今天/近 7 天/过去 7 晚按固定次序放入动态 user payload。桌面新增 `cache_usage.py` 隐私安全 JSONL 观测边界与 `scripts/inspect_cache_usage.py` 复用检查器；chat/eval 只写调用位置、模型、指纹和 hit/miss token，不写 Prompt/回复。动态时间已移到桌面 eval 稳定规则之后；命中提升须由后续真实请求基线验证，不能由结构推断冒充实测。
> **2026-08-11 PC 1.0 对齐增量**：桌面产品版本与 RN 对齐到 `1.0.0`；`server.py`、Tauri 配置和旧 Mac 打包器由合同测试守住同一版本，改号不代表已经 tag、发布或推送 updater。桌面备忘 Widget 补齐 GUI + AI 双入口：浏览器只经 `memo_routes.py` 的窄 HTTP 适配调用 `memo_store.py`，AI 工具仍调用同一 owner；Renderer 不持久化第二份备忘状态，完成操作继续遵守“日记写成功后再推进 occurrence”。
> **2026-08-19 备忘事务边界**：PC `memo_store.py` 与 RN `memoStore.ts` 对存在但无法解析/校验的 `memos.v1.json` 一律失败关闭，任何列表或写操作都不得把损坏状态解释为空集合并覆盖。完成动作跨越“日记 Markdown + 备忘状态”两个真源，不能假装成单文件原子事务；两端改以 `<!-- memo:occurrence-id -->` 作为日记副作用幂等键，重试先复用已有标记，再推进 occurrence 与下次频率实例。
> **2026-08-19 RN 日记崩溃恢复边界**：RN 仍以可读 Markdown 文件为日记唯一真源，但不再“备份后直接覆盖”。`backend.ts` 在覆盖前写入含长度和内容哈希的 `.pending` envelope 并读回校验；覆盖真身后再次逐字校验才删除 pending。若进程在真身写入中止，下一次读取优先从有效 pending 恢复；无效 pending 不得覆盖健康真身，真身缺失时仍保留 `.bak` 最后防线。该协议由纯 `journalWriteAhead.ts` 承担并可在 Node 中模拟截断恢复。
> **2026-08-19 RN 根渲染边界**：`App` 暂时仍拥有导航与 overlay 编排状态，但常驻 `JournalDay` / `ConversationView` 是显式 memoized 边界；日记 header、日期窗口、贴纸投影和事件 callback 只在对应领域输入变化时换引用。Drawer、MemoSheet、Lightbox 等局部 UI 状态不得仅因父组件重渲而重新解析整页 Markdown 或全部已加载对话。后续若继续拆 overlay controller，必须保持这一渲染合同。
> **2026-08-19 RN 对话展示窗口**：完整 History 仍是持久化真源，UI 披露继续按 16 条向前扩展，但 Renderer 改由 `FlatList` 虚拟化并以全局历史下标作为稳定 key；prepend 依赖 `maintainVisibleContentPosition` 保持阅读锚点。不得为前端性能重新裁剪 History 或改变 Compact checkpoint。
> **2026-08-19 RN History 分段持久化**：RN 新写入使用 v4 manifest + 64 条 source-message 分段，稳定前缀直接复用旧 chunk，通常只投影并改写尾段；Compact checkpoint 留在小 manifest。旧 v3 单 JSON 继续只读兼容，首次成功分段保存后才删除旧键。manifest 缺段或损坏必须走 corrupt 归档/显式重开，不得回退旧单文件掩盖损坏；manifest 提交前的新 chunk 对旧快照不可见，提交后才清理失效引用。
> **2026-08-19 RN 标签维护成本边界**：应用内日记写路径继续按日期局部同步，并以 `tagagg_dirty` 驱动失败自愈；该全局 dirty 只有成功的全量 reconcile 可以清除，任意单日成功不能替其他日期作证。启动、回前台和进入聚合页不再每次无条件全量读取日记：自动全量 reconcile 最多每 6 小时一次，dirty、未来异常时间戳与聚合页显式 force 均绕过新鲜期，并发触发共用同一次扫描；因而 Obsidian 等同文件外部修改仍会最终吸收。标签 AI 注释失败按标签持久化指数退避（5 分钟起、24 小时封顶），异常未来 deadline 不会永久饿死，新注册标签只强制一次即时尝试；成功后清除重试状态。派生索引与注释失败均不得影响日记真源。
> **2026-08-24 单一模型 / 直接多模态 / 图片索引边界**：PC 与 RN 的运行态、模型入口和 picker 统一为 `deepseek-v4-flash-vision-exp`；key 是 provider-scoped credential，只有 DeepSeek 官方端点的旧 key 可以迁移，任意兼容端点 key 必须 fail-closed。附件以逻辑 URL 持久化，首次发送与后续历史重放都在请求边界确定性压缩、物化成同形 `image_url`；Base64 禁止进入 History、Compact 与日志。主模型直接看图并调用 `record_image_observation`；宿主只允许它写本轮实际物化成功的图片，且合并 `vision` 子对象，不覆盖 hash、原文件名或确定性 OCR。发送前先把索引义务持久标记为 pending；主工具成功会清除，遗漏或失败则由响应后、PC 启动、RN 启动/回前台的 worker 重试，因此进程退出不会丢失索引义务。`search_my_uploads` 同时检索确定性 OCR 与 `vision.ocr_text`。`vision_classify` 暂留作历史图片重分类兼容面，不再是新图主路径。实验模型不可用时显式失败，禁止静默回退第二家 key。
> **2026-08-24 存量照片升级边界**：迁移 owner 只枚举应用私有 `attachments/YYYY-MM-DD/`，不读取系统相册。物理文件缺索引时补基础记录；旧 `vision_result` 可无损归一到当前视觉子对象，已有可检索描述、分类、品牌或视觉 OCR 时不得重复排队，确定性 OCR 与其他元数据不得覆盖。无语义索引的旧图只持久标记 `vision_pending`，迁移过程本身禁止请求模型；PC/RN worker 在启动、回前台或对话完成后每批最多 3 张，本轮附件优先。该节流既是费用边界也是故障边界，后续不得用“升级便利”恢复全图库同步上传。
> **2026-08-27 原图优先边界**：附件目录可保留抠图等派生渲染缓存，供贴纸、图标和既有 UI 正常使用；但 AI 照片 History、附件索引、语义检索、curator、待索引队列和多模态历史重放只接受原图。新抠图以 `.cutout.png` 持久标记角色，升级 reconcile 会移除已误入索引的该类记录而不删除物理文件。不得为了保留 UI 效果把派生图重新暴露给模型，也不得为了清理 AI 历史删除用户正在使用的渲染缓存。
> **2026-09-10 云端共享上下文 / 夜间 Skill 边界**：产品已改变“最小快照、正文默认不留存”的目标：每个设备令牌对应一份持续的云端文本工作副本，供正常对话与 `nightly-letter` 共用；本地 vault Markdown 与完整 History 仍是可恢复真源，不由云端覆盖。夜间留言不是另一条 Prompt/对话链，而是调度器或显式重试在相同副本上运行 Skill；Skill 按需读取日记、可见对话与 Compact checkpoint、PULSE、当天打卡、标签、备忘和历史留言，结果经队列领取后才写回本地 `21:30` 块。原图、抠图、provider reasoning 和密钥不进长期工作副本。云端正文的保留期、删除入口、静态加密、备份恢复与跨设备身份仍未完成，部署前不得把这条目标写成既有生产保障。
> **2026-09-11 云端共享上下文 staging 落地**：广州 Provider Gateway 已承接 `context_store`、`night_notes` 与 `nightly_letter_skill`，Caddy/HTTPS 和既有 `/v1/chat/completions` 透明转发边界保持不变。端侧只异步上传文本/JSON 工作副本，日记和 History 的本地真源地位不变；夜间结果必须由设备领取并以既有日记写入协议落盘后才确认。当前 SQLite 队列的失败会在下一次 30 秒 tick 立即重试，且 running job 没有租约恢复；因此 staging 可验证闭环，但在增加退避、最大尝试、死信与 crash lease 前不得作为生产级调度保证。
> **2026-09-10 Gateway-only 凭据边界；2026-09-13 认证与计量分离**：`cloud_gateway/` 是独立于本地 `server.py` 的 Provider Gateway ingress owner，禁止反向导入桌面组合根。它提供 `/healthz`、`/v1/edge/status`、`POST /v1/auth/token` 与模型/上下文/留言业务接口。长期设备凭据经注册表验证后可换取默认 15 分钟 access token；服务端只持久化两类 token 的 hash，Bearer 轮换期间始终映射回同一设备 hash，设备吊销会级联撤销短令牌。PC/RN 的所有 AI 与云上下文出口已在源码层改为先换取、短令牌仅驻内存并提前续期；连接探针也验证 exchange + Bearer 两段链。所有模型调用经 SQLite 原子账本执行分钟频率、并发和 provider usage 结算，但日请求数与日费用默认只计量，只有运维显式进入 emergency 模式才作为硬闸；缓存未命中和最大输出的最坏估算不得冒充盗刷证据阻断已授权设备。云端严格模式开关已实现但在新客户端发布覆盖前保持关闭，因此长期凭据当前仍可直接进入业务接口；即使关闭兼容入口，凭据被完整复制后仍不能区分克隆设备，硬件密钥绑定或平台证明仍是商业发布前目标。
> **2026-09-13 多模态阈值疤**：PC/RN 的历史原图会作为真正的 `image_url` 重放，因此网关看到的图片数是整段历史累计，不是本轮新增。不得用低于 provider 合同的任意“小批量上传”阈值拦截这个公共边界；图片上限跟随 provider 的 600 张，入口仍受 24 MiB 请求体、唯一模型、单输出和瞬时并发边界保护。费用预占按每图最高 384 token 计算，base64 只属于传输表示，禁止估成模型文本 token；该预占只服务并发账本，默认不能触发日费用拒绝。
> **2026-09-13 对话复制跨端合同**：PC 与 RN 的每条用户正文、AI 正文、Compact 摘要和展开的 reasoning 都必须可选择且有显式“复制”入口；复制源是用户可见的该块文本，不能混入工具 chip、附件二进制、隐藏协议帧或 `model_content`。桌面正文选择依赖 CSS，RN Markdown 的叶文本须显式声明 `selectable`；两端的 clipboard 写入失败只提示，不改变对话真源。
> **2026-09-07 日期授权退役**：`patch_journal_block`、`insert_journal_block`、`append_journal_comment` 与 `delete_journal_entry` 不再由宿主 ActionPolicy 基于日期、浏览日或用户措辞拦截。底层写入仍负责参数格式、`@user` authorship、文件真源和原子性；日更 Widget 的写窗仍由领域服务拥有。
> **2026-08-19 发布质量闸**：Mac/Windows 发版工作流在安装 Rust、冻结 sidecar 或构建 Tauri 之前必须运行完整 Python 与桌面 Node 合同测试；测试依赖由 `requirements-test.txt` 单一锁定（含 async runner），不得在两个 YAML 中手写漂移。Prompt/工具生成链在 gateway 单仓 CI 以提交的 SHA-256 输出指纹检查源 freshness，本地双仓存在时再额外逐字核对 RN JSON 与 golden；指纹不是运行时影子文档。测试或生成物任一不新鲜均不得进入签名/发布。

## 鸟瞰一段话

系统是"一个人 + AI 的日记操作系统"：桌面端 Tauri 壳 spawn PyInstaller sidecar（server.py 从 5259 行拆到 1408 行,19 个新模块 + 9 个既有薄路由,全仓 142 处 `from server import` 回环——**拆分降低了单文件复杂度,没有降低系统性回环耦合**）,前端 26 个 window 全局 vanilla JS 模块拼装双皮肤（classic / paper tokens 化;day.html 僵尸 monolith 已归档）；移动端已从 Capacitor WebView 整体迁到 gateway-rn（mobile/ 归档至 archive/webview-mobile/,分层干净、226+ 测全绿）,两端靠 docs/contracts/mobile-api.reference.js 字节对齐契约 + tests/parity 109 golden + toolSpecs/promptContract 生成链维持 parity。数据真源是 vault 里的 markdown,一切写路径围绕"不丢字节"设防（原子写/CAS/authorship/5.17 铁律）。最脆的三处：发布 updater 链（SSL 死锁未解,契约测试已补）、contract 收口只走 18%（AST 级分析待做）、RN 8 文件待复测提交。

## 章节

| 册 | 文件 | 范围 |
|---|---|---|
| 00 | [ledger/00-map.md](ledger/00-map.md) | 全仓地图/依赖拓扑/分 part 方案/初版 TOP10 |
| 01 | [ledger/01-server-core.md](ledger/01-server-core.md) | server.py 22 逻辑段 |
| 02 | [ledger/02-routes-and-py.md](ledger/02-routes-and-py.md) | 其余 24 个 .py（路由层+leaf） |
| 03 | [ledger/03-frontend-engine.md](ledger/03-frontend-engine.md) | shared/*.js 26 件 + 5 页 + 主 css + window 契约总表 |
| 04 | [ledger/04-skins-pretext-widgets.md](ledger/04-skins-pretext-widgets.md) | paper 皮肤族 + vendor/pretext + widgets/扩展协议 |
| 05 | [ledger/05-webview-legacy.md](ledger/05-webview-legacy.md) | mobile/ 1GB 处置裁决书 |
| 06 | [ledger/06-rn-data-engine.md](ledger/06-rn-data-engine.md) | RN services/store + 契约链 + 测试概览 |
| 07 | [ledger/07-rn-ui-e2e.md](ledger/07-rn-ui-e2e.md) | RN UI 20 组件 + theme + e2e 真机网 |
| 08 | [ledger/08-shell-release.md](ledger/08-shell-release.md) | Tauri/打包/CI/tests 总账/updater·SSL 实况/relDebug |

（各章均含对抗审核修订；08 头部有审计行记录修正项。）

## 健康度统计（2026-07-22 重算；按各章卡片主评级汇总，子系统合并计，约数）

| 册 | 健康 | 臃肿 | 危险 | 僵尸/死 | 备注 |
|---|---|---|---|---|---|
| 01 server.py：19 模块 + 1408 行核心 | 14（新抽模块多数评健康/健康偏臃肿） | 5 | 3（不变：回环+承重墙/TOOL_IMPL 引力中心/authorship 危险写路径） | — | 危险性质未变但**面**已收窄：非危险代码搬空,危险 helper 集中留守 server.py 本体 |
| 02 py 25 卡 | 19 | 1 | 5 | 0 | 未动，同初版（危险=chat_routes/migration_routes/pulse_eval/parse 段/顺序契约 leaf） |
| 03 前端引擎 33→32（day.html 移出） | 25 | 4 | 3 | 0（day.html 已归档，不再计入本册僵尸格） | 新增：thread.js 首张 characterization 网（14 断言），危险评级未降（测试才刚开始） |
| 04 皮肤+pretext+widgets 33 | 26 | 2 | 2 | 1+2 存疑 | 未动，pretext 存废仍待拍板 |
| 05 mobile/ → **已处置**（archive/webview-mobile/） | — | — | — | 0 活（原 2 活已随归档降级为存档） | **处置完毕**，不再是活口径的风险面 |
| 06 RN 数据引擎 34+（新增 promptContract 消费） | 32 | 1 | 1 | — | 危险=chatEngine（热，真机未验，未变） |
| 07 RN UI+e2e 39 | 35 | 1 | 1 | — | 未动；新增"8 文件待复测提交"待办 |
| 08 壳与发布 ~22 | 18 | — | 2 | — | updater 链新增契约测试，SSL/明文现状未变 |
| **合计（约）** | **~169** | **~14** | **~15** | **~1** | 总卡片 ~209（mobile/ 处置册 5 死格已随归档清零，僵尸格大减） |

## 危险 TOP10（2026-07-22 终态重排，详细论证见 [00-map.md §4](ledger/00-map.md)）

**已解除 / 大幅收口**：旧#7 mobile/ 1GB 遗产误伤面（**解除**，归档完毕）；旧#6 day.html monolith（**解除**，已归档零引用）；旧#3 updater 零契约测试（**半收口**，py 侧 Rust↔JS 测试已补，SSL/明文现状未变，见新#4）。

1. **server.py 仍是危险 helper 守夜人 + frozen guard 承重墙**：19 个模块搬走非危险代码后，authorship 三原语/TOOL_IMPL 权威绑定/遥测可变状态/thread CAS 锁**有意**留守 server.py；142 处 `from server import` 回环未减少（新模块内部 `S = _srv()` 代理还多了一层隐式通路）；frozen guard（server.py:44）删一行仍是 build 秒崩。拆分降低了单文件复杂度，没有降低系统性回环耦合。
2. **contract 收口只走了 18%**（215 个 re-export 符号，第一批仅 39 个安全删除）：剩 109 个字面"Class A"符号命中 tool_* 动态 getattr / `S.`/`_srv()` 代理引用，需 AST 级分析才能继续（人工 grep 已两次误删导致红测，靠 git checkout 撤回）；29 个 Class C（pulse 相关）测试迁移未开始。
3. **chat_routes.py:860 known bug** 依旧：actions 用 `=` 覆盖丢多轮工具调用，有意不修，未受拆分影响。
4. **updater 链实况仍双险**：HTTP 明文兜底 + `dangerousInsecureTransportProtocol:true` 未改；Rust↔JS 契约测试已补（6+2 枚举快照），但只冻结现状不修复 SSL CDN CNAME 死锁根因；灰度两步（真解 SSL + silent-download UX）仍待产品决策排期。
5. **桌面前端测试真空仍是主体**：thread.js 拿到第一张网（14 断言），其余 25 个 shared/*.js 与 window 全局隐式契约仍零测试；前端拆分本体（8,900+ 行零模块化）尚未启动。
6. **pretext 子系统存废未拍板**：4,300 行无脐带排版引擎，消费者归档后仅剩桌面 2 处，本轮无进展。
7. **RN 8 个文件待复测提交**：本轮 promptContract.json 接入尚在本地未真机复测/提交固化——若与 chatPretext.ts 手动同步存在残留差异，会重新打开"PC↔RN 契约人肉段"旧危险点。
8. **RN 最热代码仍在验证网最薄处**：runChatStream/ChatView 真机未验现状未变；层 B 无 CI 三前置全手动。
9. **遥测 sink 明文 IP 硬编码**（现活在 telemetry.py，`http://101.42.108.30:18080`）+ 历史客户端 :18080 永久兼容义务未变。
10. **回归防线仍薄**：基线从"379 过 2 红"实打实修到"384 过 0 红"，但前端/RN 真机验证覆盖仍是短板，全绿不等于覆盖面够。

## 对齐/处置清单（可勾选，2026-07-22 刷新）

**结构性前置（已完成项打勾）**
- [x] server.py 巨石拆分：5259→1408 行，20 段迁出 19 个模块，384 过 0 红（server 拆分战役核心目标）
- [x] mobile-api.js 三步安全归档：摘惰性加载行 → 平移 docs/contracts/mobile-api.reference.js → 归档原件
- [x] parity/golden + capture-golden.py + harness 平移 gateway/tests/parity/
- [x] 归档 mobile/ 整体（app/m/plugins/for-cd/ 全部，含 DerivedData 855M + node_modules 24M 立删）
- [x] 归档 day.html（03 册僵尸判定，全仓零引用核实过）
- [x] prompt 与 Skill 契约数据化：prompts/*.md + skills/* + generate_prompt_contract.py → promptContract.json
- [x] thread.js 第一张 characterization 网落地（tests/frontend/，14 断言）
- [x] updater Rust↔JS `updater://progress` 步骤契约测试（test_updater_step_contract.py）
- [x] 两个长期红测修复（基线 384 过 0 红）
- [x] contract 第一批：39 个 re-export 符号安全退役（01 章 §10 三列账）

- [ ] conftest raising=False → 显式 assert（守 server re-export,08 册；本轮未动）
- [ ] 补记版本变更底账,更新 CLAUDE.md Local progress（08 册；未核实是否仍 stale）
- [ ] dist-pyinstaller/ 移出源码仓/加 ignore

**剩余待办（2026-07-22 新增小节）**
- [ ] **contract AST 批**：对 109 个留守"Class A"符号做 AST/字节码级引用分析（覆盖 `_srv()`/`S.`/tool_* getattr 动态引用），逐符号配测试验证，比人工 grep 更可靠
- [ ] **C 类 29 符号测试迁移**：pulse 相关 re-export（`_USER_PULSE_PATH`/`PULSE_DIR`/`EVAL_LOG_DIR` 等）目前一律不碰，需规划专门批次
- [ ] **前端拆分本体**：thread.js 等 25 个 shared/*.js 的模块化 + 测试覆盖（characterization 网只覆盖 1/26）
- [ ] **updater 灰度两步**：① SSL CDN CNAME 死锁真解（换直连域名或其他方案）② silent-download UX 决策排期
- [ ] **pretext 存废待拍板**：消费者归档后仅剩桌面 2 处，需产品/技术共同决策去留
- [ ] **RN 8 文件待复测提交**：promptContract.json 接入侧改动需真机复测后提交固化

**PARITY 同步义务（PC 改动必须跟,06 册/PARITY_HARNESS，未变）**
- [ ] tool_specs.py / protocols/*.md 变更 → 重跑生成（toolSpecs.json ×2 + protocols.ts + promptContract.json）
- [ ] PROTOCOLS dict 新协议 → protocols.ts + PC_PROTOCOL_INDEX
- [ ] chat_routes WORKFLOW（vision 注入）变更 → buildVisionHint
- [ ] claim 词表超集回灌 PC（RN 强于 PC,PARITY_HARNESS 建议项）

**RN 未收口项（06/07 册，未变）**
- [ ] runChatStream 真机跑一轮完整对话（含工具循环+流式）
- [ ] modules/expo-cutout 原生侧真机验证（iOS Vision / Android MediaPipe）
- [ ] Android 打包 LXGW/思源字体（笔迹身份缺失,fonts.ts）
- [ ] 层 B 真机 journey 补 ChatView/流式 journey 一条

**桌面侧债（03/04 册，未变）**
- [ ] gatewayToast 双定义收敛（thread.js:954 vs widget-loader.js:34）
- [ ] compact-ring 偷读 thread 私有 localStorage key → 走公开面
- [ ] ctrl-c-v-bridge widget 250 行样式从 style.css 回迁 widget.html
- [ ] paper 皮肤 dialog-paper（confirm 静默失效护栏）
- [ ] marketplace/setup 重复文案段收敛
