"""tool_specs — LLM 工具的 JSON schema 定义(给模型看的 function specs)。

Extract Module(ctrl-c-v § 9):TOOLS schema 列表(纯数据 leaf,零依赖)从 server.py 抽出。
server `from tool_specs import TOOLS` re-export;消费者 _active_tools(server)+ 名字映射 TOOL_IMPL/
TOOL_GROUPS 留 server。characterization:tests/test_tool_specs.py。
"""
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_widgets",
            "description": "List all widget folders under gateway/widgets/ and which are currently active in .user-widgets.json.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_widget",
            "description": "Create a new widget under widgets/<name>/ + activate it in .user-widgets.json.",
            "parameters": {
                "type": "object",
                "required": ["name", "title", "audience", "slot", "manifest_json", "widget_html", "widget_js"],
                "properties": {
                    "name": {"type": "string", "description": "folder name, kebab-case"},
                    "title": {"type": "string", "description": "user-facing title"},
                    "audience": {"type": "string", "description": "who this widget is for"},
                    "slot": {"type": "string", "enum": ["top-strip", "sidebar"], "description": "which slot it mounts to"},
                    "manifest_json": {"type": "string", "description": "full JSON content for manifest.json"},
                    "widget_html": {"type": "string", "description": "full HTML+inline style for widget.html"},
                    "widget_js": {"type": "string", "description": "full JS for widget.js (use IIFE + window.gatewayToast for feedback)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_widget",
            "description": "Modify an existing widget's manifest/HTML/JS in place.",
            "parameters": {
                "type": "object",
                "required": ["name", "file", "new_content"],
                "properties": {
                    "name": {"type": "string"},
                    "file": {"type": "string", "enum": ["manifest.json", "widget.html", "widget.js"]},
                    "new_content": {"type": "string", "description": "full new file content (replaces existing)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_journal_block",
            "description": "整段替换某时间块内容。改散文/补内容用。要加新 H2 用 insert_journal_block。要给 entry 留评论用 append_journal_comment。用户明示改标题时传 allow_h2_rename=true。",
            "parameters": {
                "type": "object",
                "required": ["time", "new_md"],
                "properties": {
                    "time": {"type": "string", "description": "块时间 HH:MM,从 [time-block] hint 取"},
                    "new_md": {"type": "string", "description": "H1 之下整段:`## #tag 标题` + 散文。§ H5 result + significance,无 procedure dump"},
                    "allow_h2_rename": {"type": "boolean", "description": "用户明示改 H2 标题时传 true,否则默认 false 防误覆盖"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_today_schedule",
            "description": "读今天(或指定日期)的 schedule md,返解析后的时间块 + H2 entries。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "optional YYYY-MM-DD. omit for today."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_days",
            "description": "列最近 N 天的 schedule 文件(只列日期 + 文件名,不读内容)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "how many most-recent days to list. default 7."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_journal_block",
            "description": "加新 H2 条目到时间块(标题 + 正文一次写全)。已有内容会 append 新 H2(不覆盖)。AI 调用自动 @ai stamp。",
            "parameters": {
                "type": "object",
                "required": ["tag", "body"],
                "properties": {
                    "tag": {"type": "string", "description": "条目 tag,不带 #。例 '饮食' '探索'"},
                    "title": {"type": "string", "description": "短标题"},
                    "body": {"type": "string", "description": "正文散文(必填)。写 result + significance:发生了什么 + 为什么重要。禁止只留标题。"},
                    "time": {"type": "string", "description": "HH:MM,omit 默认当前半小时"},
                    "date": {"type": "string", "description": "YYYY-MM-DD,omit 默认今天"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_journal_comment",
            "description": "在时间块 body 末尾追加评论,不动原 H2/body。@user 块 patch 会拒,用这个留'AI 注'。",
            "parameters": {
                "type": "object",
                "required": ["time", "comment_md"],
                "properties": {
                    "time": {"type": "string", "description": "目标块 HH:MM"},
                    "comment_md": {"type": "string", "description": "评论 markdown,带 *AI:* 前缀让人区分"},
                    "date": {"type": "string", "description": "YYYY-MM-DD,omit 默认今天"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_water_cup_image",
            "description": "为 8-cup 喝水打卡设置自定义水杯图标(灰度=未喝,彩色=已喝)。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "/attachments/YYYY-MM-DD/xxx 路径,用户上传后 server 返的"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_daily_task_image",
            "description": "为 daily task 配打卡图标(去背景)。task_name 精确匹配 md 顶部 - [ ] 行。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "attachment_url"],
                "properties": {
                    "task_name": {"type": "string", "description": "task 名,精确匹配 - [ ] 行(含中文括号),例 '鱼油（Swisse）'"},
                    "attachment_url": {"type": "string", "description": "/attachments/YYYY-MM-DD/xxx 路径"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_daily_task",
            "description": "Add/edit/del daily-task 顶部 - [ ] 项。影响模板(后续天)+ 今天文件。",
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["add", "edit", "del"]},
                    "text": {"type": "string", "description": "新内容,不含 '- [ ] '"},
                    "old_text": {"type": "string", "description": "edit/del 用,substring 匹配老 item"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_daily_task",
            "description": "勾打卡。task_name 精确匹配(空格 + 中文括号要对)。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "checked"],
                "properties": {
                    "task_name": {"type": "string", "description": "完整 task 名,例 '鱼油（Swisse）'"},
                    "checked": {"type": "boolean", "description": "true=打卡,false=取消"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_scrapbook_image",
            "description": "把上传的图浮在指定时间块旁边(absolute layer + 文字绕图)。anchor_time 选择规则见 vision protocol。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url", "date", "anchor_time"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "用户拖图后 server 返的 /attachments/YYYY-MM-DD/xxx 路径"},
                    "date": {"type": "string", "description": "目标日 YYYY-MM-DD,通常就是用户当下浏览的那天"},
                    "anchor_time": {"type": "string", "description": "锚点时间块 HH:MM,例 '15:00' — 图属于哪条 entry 的语义(future viewer 用)"},
                    "x_pct": {"type": "number", "description": "横向位置(% of page width,0-95)。AI 自由选,默认 75(右上)。"},
                    "y_px": {"type": "number", "description": "纵向位置(px from page top)。AI 自由选,可不填(默认 0 = 顶部)。"},
                    "cutout": {"type": "boolean", "description": "true=调百度抠图去背景再放,false=保留原图。默认 true"},
                    "rotation": {"type": "number", "description": "旋转角度(度),给一点小角度更像剪贴本,默认 -4 ~ 4 随机"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vision_classify",
            "description": "对图跑结构化视觉分类,返 kind/brand/描述/颗数/OCR 概率。**通常不必调** — server 在 upload 时已经跑过并缓存,user message 里会注入 hint。这条只在 fallback 场景用。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "用户上传后 server 返的 /attachments/YYYY-MM-DD/xxx 路径"},
                    "extra_question": {"type": "string", "description": "追加问 vision LLM 的开放问题(可选)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_uploads",
            "description": "列用户历史上传过的图片,按日期范围 / 数量限制。返 filename / date / 原文件名 / OCR 摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "起始日 YYYY-MM-DD,空则不限"},
                    "date_to": {"type": "string", "description": "终止日 YYYY-MM-DD,空则到今天"},
                    "limit": {"type": "integer", "description": "最多返几条,默认 30"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_my_uploads",
            "description": "关键词搜历史上传图(grep 文件名 + 原文件名 + vision 描述 + OCR 文本)。**精确关键词**走这条;**语义/跨 terminology**(狗=哈士奇=茅茅)走 ask_photo_curator。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索词,支持中英文。会 case-insensitive 匹配。"},
                    "limit": {"type": "integer", "description": "最多返几条,默认 15"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_photo_curator",
            "description": (
                "图书管理员子 agent (deepseek-v4-flash) — 自然语言找照片。"
                "适用: 长期回顾 / 跨 terminology (狗=哈士奇=茅茅) / 模糊语义。"
                "**不适用**: 精确 OCR 关键词(走 search_my_uploads)。"
                "quota=1/轮,失败自动降级 grep。一次返完整匹配集,不像 search 受 quota 限。"
                " **回复硬规则**: 拿到 items 后,每条都必须用 markdown `![描述](url)`"
                " 把照片 inline 贴出来 — 不要光写文字 narrative。"
                " 描述串叙事时引用,但每张图自己显示一次。"
                " **URL 必须原样照抄 items[i].url(形如 `/attachments/2026-05-16/xxx.jpg`)— "
                "不要加任何 host/port/http 前缀,浏览器自己会解析相对路径。**"
                " 例: '5.16 在客厅地板上 ![哈士奇站客厅](/attachments/2026-05-16/abc.jpg) — 那天...'"
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "自然语言问题,如 '找我家狗的所有照片'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_journal",
            "description": "全文搜 vault 里所有 md(半小时复盘 / 标签聚合 / PULSE / 知识库 / 散落 md),case-insensitive,多关键词空格分(AND)。返命中文件 + 行号 + ±2 行上下文,按文件 mtime 倒序。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索词,中英文都行。多关键词用空格分(全部要命中)。"},
                    "limit": {"type": "integer", "description": "最多返几条,默认 20"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_attachment",
            "description": "删一张已上传的图(硬盘 + 索引)。仅在用户明确要求时用,不主动建议。",
            "parameters": {
                "type": "object",
                "required": ["date", "filename"],
                "properties": {
                    "date": {"type": "string", "description": "图的日期 YYYY-MM-DD,从 list/search 结果里拿"},
                    "filename": {"type": "string", "description": "图的文件名,从 list/search 结果里拿"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_daily_task_meta",
            "description": "改 daily task 的剂量/瓶装总颗数。total_pills=整瓶颗数,daily_dose=每天吃几颗(默认 1)。",
            "parameters": {
                "type": "object",
                "required": ["task_name"],
                "properties": {
                    "task_name": {"type": "string", "description": "完整 task 名,例 '鱼油（Swisse）'"},
                    "total_pills": {"type": "integer", "description": "瓶装总颗数(可选,只填这次要改的)"},
                    "daily_dose": {"type": "integer", "description": "每日剂量(可选,默认 1)"},
                },
            },
        },
    },
    # 自定义 web_search function tool — 跨 provider 统一(DeepSeek/MiMo/MiniMax 都通过同一个 function tool 调,
    # 后端用 ddgs)。复用 investment-dashboard 的同款 pattern。
    # decision: 放弃 MiniMax 原生 {"type":"web_search"} server-side tool —— 单 provider 优化换不来跨 provider 一致性。
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索(大陆直连)。category 选源:general=通用网页;wechat=微信公众号文章。"
                           "**看完标题/摘要决定要不要 fetch_url 看正文,别只凭摘要答**。"
                           "找公众号文章时务必用 category=wechat,通用搜搜不到公众号。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词,中英文均可"},
                    "category": {"type": "string", "enum": ["general", "wechat"],
                                 "description": "搜索源:general 通用(默认) / wechat 微信公众号文章"},
                    "max_results": {"type": "integer", "description": "返回多少条(默认 5,上限 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "渐进披露第二步:拉某 URL 正文(HTML stripped → text,最多 3000 char)。先 web_search 看标题再 fetch,别盲 fetch。同一 URL 不要 fetch 多次。",
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "完整 URL,带 http(s)://"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_protocol",
            "description": "拉某个协议的详细规则(目前只有 'schedule')。要写 / 改日记 entry 之前调一次,普通聊天不调。",
            "parameters": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "protocol 名,目前可选 'schedule'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_tool_group",
            "description": "按需加载一组工具。bootstrap 只装 read + meta;要写 / 贴图 / 改 widget 之前先 load 对应组。一次 chat 只需 load 一次。",
            "parameters": {
                "type": "object",
                "required": ["group_name"],
                "properties": {
                    "group_name": {
                        "type": "string",
                        "enum": ["write_journal", "images", "widgets_and_tasks"],
                        "description": "write_journal=写日记块/切勾daily task; images=贴图/删图/改task配图; widgets_and_tasks=widget增删改/task配置改名",
                    },
                },
            },
        },
    },
]
