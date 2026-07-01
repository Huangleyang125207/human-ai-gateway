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
            "description": "替换时间块的标题和正文。当用户明确要求修改标题时,需要将 allow_h2_rename 参数设为 true,否则系统会拒绝修改以防止误覆盖。如果要添加新的条目请用 insert_journal_block;如果要追加注释请用 append_journal_comment。",
            "parameters": {
                "type": "object",
                "required": ["time", "new_md"],
                "properties": {
                    "time": {"type": "string", "description": "块时间,格式为 HH:MM(例如 14:30)。从提示信息中获取"},
                    "new_md": {"type": "string", "description": "时间块中 H1 之下的完整内容(包含标题和正文)。内容应包含结果和意义(发生了什么、为什么重要),不应包含冗长的过程描述。格式例:`## #标签 标题` 加上正文段落。"},
                    "allow_h2_rename": {"type": "boolean", "description": "当用户明确要求修改标题时设为 true,默认为 false 以防止意外覆盖"},
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
            "description": "向时间块添加新条目(需同时提供标题和正文)。新条目会追加到现有内容之后(不会覆盖)。AI 调用此工具时会自动添加 @ai 标记。",
            "parameters": {
                "type": "object",
                "required": ["tag", "body"],
                "properties": {
                    "tag": {"type": "string", "description": "条目标签,不包含 # 符号。例如:'饮食'、'探索'"},
                    "title": {"type": "string", "description": "短标题"},
                    "body": {"type": "string", "description": "正文内容(必填字段)。应包含发生了什么以及为什么重要的说明。注意:不能只提供标题而空着正文。"},
                    "time": {"type": "string", "description": "时间,格式为 HH:MM(例如 14:30)。如果不提供,默认为当前半小时块"},
                    "date": {"type": "string", "description": "日期,格式为 YYYY-MM-DD。如果不提供,默认为今天"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_journal_comment",
            "description": "在时间块末尾追加评论,不修改原有的标题或正文。当用户创建的条目内容被锁定时,可以用此工具追加 AI 注释,而不是直接修改。",
            "parameters": {
                "type": "object",
                "required": ["time", "comment_md"],
                "properties": {
                    "time": {"type": "string", "description": "目标时间块,格式为 HH:MM(例如 14:30)"},
                    "comment_md": {"type": "string", "description": "评论 markdown,带 *AI:* 前缀让人区分"},
                    "date": {"type": "string", "description": "日期,格式为 YYYY-MM-DD。如果不提供,默认为今天"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_water_cup_image",
            "description": "为喝水打卡设置自定义水杯图标。图标状态区分:灰度表示未喝,彩色表示已喝。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "图片的存储路径,格式为 /attachments/YYYY-MM-DD/xxx。这是用户上传图片后服务器返回的路径。"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_daily_task_image",
            "description": "为日常任务设置打卡图标(系统会自动去除背景)。注意:task_name 必须精确匹配 markdown 文件顶部的任务列表项。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "attachment_url"],
                "properties": {
                    "task_name": {"type": "string", "description": "任务名称,必须精确匹配 markdown 文件中的任务项(包括中文括号等)。例如:'维生素'"},
                    "attachment_url": {"type": "string", "description": "图片的存储路径,格式为 /attachments/YYYY-MM-DD/xxx"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_daily_task",
            "description": "添加、编辑或删除日常任务列表中的项目。修改会影响任务模板(影响后续几天)和今天的文件。",
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["add", "edit", "del"]},
                    "text": {"type": "string", "description": "新的任务名称(不包括 '- [ ] ' 前缀)。建议使用最短的可识别名称,避免在名字中包含品牌、规格或剂量等详细信息。注意:任务名称在打卡卡片上显示时最多两行,超长内容会被截断。"},
                    "old_text": {"type": "string", "description": "用于编辑或删除操作,支持子串匹配来查找要修改的任务项(不需要完全精确匹配)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_daily_task",
            "description": "标记任务为完成(打卡)。注意:task_name 必须精确匹配,包括空格和中文括号等。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "checked"],
                "properties": {
                    "task_name": {"type": "string", "description": "完整的任务名称,例如:'维生素'"},
                    "checked": {"type": "boolean", "description": "true 表示标记为已完成,false 表示标记为未完成"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_scrapbook_image",
            "description": "将上传的图片浮动显示在指定时间块旁边,实现文字围绕图片的排版效果。关于 anchor_time 的选择规则,请参考视觉协议的说明。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url", "date", "anchor_time"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "图片路径(/attachments/YYYY-MM-DD/xxx),由服务器在用户上传后返回"},
                    "date": {"type": "string", "description": "目标日期,格式为 YYYY-MM-DD。通常应该是用户当前正在浏览的那一天。"},
                    "anchor_time": {"type": "string", "description": "锚点时间块,格式为 HH:MM(例如 '15:00')。这表示图片在语义上属于哪个时间块的条目,便于后续查看时理解上下文。"},
                    "x_pct": {"type": "number", "description": "图片的横向位置,以页面宽度的百分比表示(0-95)。AI 可自由选择,默认值为 75(靠右上方)。"},
                    "y_px": {"type": "number", "description": "图片的纵向位置,以像素计算(从页面顶部起)。AI 可自由选择,可选字段(默认值为 0 表示顶部)。"},
                    "cutout": {"type": "boolean", "description": "true 表示使用百度抠图服务去除背景后再放置,false 表示保留原图。默认值为 true(自动去背景)。"},
                    "rotation": {"type": "number", "description": "图片的旋转角度(单位:度)。建议设置较小的角度(如 -4 到 4 度)使其看起来更像剪贴本风格。默认为随机的 -4 到 4 度。"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vision_classify",
            "description": "对图片运行结构化视觉分类,返回分类结果(类型、品牌、描述、颗粒数、文字识别概率等)。注意:通常无需主动调用本工具 — 服务器在用户上传时已自动分类并缓存,分类提示会在对话中注入。仅在需要重新分类或回退处理的特殊情况下使用。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "图片路径(/attachments/YYYY-MM-DD/xxx),由服务器在用户上传后返回"},
                    "extra_question": {"type": "string", "description": "追加问题,让视觉分类模型进一步回答(可选字段)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_uploads",
            "description": "列出用户历史上传的图片,支持按日期范围和数量进行筛选。返回结果包括文件名、日期、原始文件名和文字识别摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "开始日期,格式为 YYYY-MM-DD。留空则无日期下限。"},
                    "date_to": {"type": "string", "description": "结束日期,格式为 YYYY-MM-DD。留空则默认到今天。"},
                    "limit": {"type": "integer", "description": "最多返回多少条结果,默认值为 30"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_my_uploads",
            "description": "使用关键词搜索历史上传的图片(搜索范围包括文件名、原文件名、视觉描述和文字识别内容)。适用场景:精确关键词搜索。如需语义搜索或处理不同术语指称同一物体(例如:'狗'、'哈士奇'、'茅茅'被视为同一概念),请改用 ask_photo_curator 工具。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词,支持中英文。匹配时不区分大小写。"},
                    "limit": {"type": "integer", "description": "最多返回多少条结果,默认值为 15"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_photo_curator",
            "description": (
                "图片检索助手 — 用自然语言找照片。"
                "适用: 长期回顾 / 跨称呼(狗=哈士奇=茅茅) / 模糊语义。"
                "**不适用**: 精确 OCR 关键词(走 search_my_uploads)。"
                "每轮限用 1 次,失败会自动降级为关键词搜索。一次返回完整匹配集,不受条数限制。"
                " **回复硬规则**: 拿到结果后,每条都必须用 markdown `![描述](url)`"
                " 把照片内嵌显示出来 — 不要只写文字描述。"
                " 描述串叙事时引用,但每张图自己显示一次。"
                " **URL 必须原样照抄返回的 url(形如 `/attachments/2026-05-16/xxx.jpg`)— "
                "不要加任何 host/port/http 前缀,浏览器会自动解析相对路径。**"
                " 例: '5.16 在客厅地板上 ![哈士奇站客厅](/attachments/2026-05-16/abc.jpg) — 那天...'"
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "自然语言查询,例如:'找我家狗的所有照片'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_journal",
            "description": "全文搜索用户的日记库中所有 markdown 文件(包括日间日记、标签聚合、PULSE 进度、知识库和其他文档),不区分大小写。多个关键词用空格分隔表示逻辑与(全部要命中)。返回搜索结果包括文件名、所在行号、前后各 2 行的上下文,按文件修改时间倒序排列。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词,支持中英文。多个关键词用空格分隔,表示全部关键词都要在搜索结果中出现(逻辑与)。"},
                    "limit": {"type": "integer", "description": "最多返回多少条结果,默认值为 20"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_attachment",
            "description": "删除已上传的图片(包括从硬盘和索引中清除)。仅在用户明确要求删除时使用,不要主动建议删除操作。",
            "parameters": {
                "type": "object",
                "required": ["date", "filename"],
                "properties": {
                    "date": {"type": "string", "description": "图片的日期,格式为 YYYY-MM-DD。可从列表或搜索结果中获取。"},
                    "filename": {"type": "string", "description": "图片的文件名。可从列表或搜索结果中获取。"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_daily_task_meta",
            "description": "修改日常任务的元数据(如每日剂量或总颗数)。参数说明:total_pills 表示瓶装的总颗数,daily_dose 表示每日剂量(默认为 1)。",
            "parameters": {
                "type": "object",
                "required": ["task_name"],
                "properties": {
                    "task_name": {"type": "string", "description": "完整的任务名称,例如:'维生素'"},
                    "total_pills": {"type": "integer", "description": "瓶装的总颗数(可选字段,只需填入本次要修改的值)"},
                    "daily_dose": {"type": "integer", "description": "每日剂量(可选字段,默认值为 1)"},
                },
            },
        },
    },
    # 自定义 web_search function tool — 跨 provider 统一(DeepSeek/MiMo/MiniMax 都通过同一个 function tool 调,
    # 后端用 ddgs)。复用同款 pattern。
    # decision: 放弃 MiniMax 原生 {"type":"web_search"} server-side tool —— 单 provider 优化换不来跨 provider 一致性。
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索(面向中文互联网)。category 选源:general=通用网页;wechat=微信公众号文章。"
                           "**看完标题/摘要决定要不要 fetch_url 看正文,别只凭摘要答**。"
                           "找公众号文章时务必用 category=wechat,通用搜搜不到公众号。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词,支持中文和英文"},
                    "category": {"type": "string", "enum": ["general", "wechat"],
                                 "description": "搜索源:general 表示通用网页搜索(默认),wechat 表示微信公众号文章搜索"},
                    "max_results": {"type": "integer", "description": "返回多少条搜索结果(默认值为 5,最多 10 条)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "获取指定 URL 的正文内容(提取纯文本,最多 3000 字符)。使用建议:先通过 web_search 查看搜索结果的标题和摘要,确认需要查看正文后再调用本工具,避免盲目获取。同一 URL 不应重复调用此工具。",
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "完整的网址,需要包含 http:// 或 https:// 前缀"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_protocol",
            "description": "加载特定协议的详细规则文档(目前支持 'schedule' 协议)。建议在编辑日记条目前调用一次以了解规则,普通对话中通常不需要调用。",
            "parameters": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "协议的名称,目前支持的选项:'schedule'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_tool_group",
            "description": "按需加载一组相关工具。初始启动时仅加载读取和元数据工具。在执行以下操作前需加载对应的工具组:编辑日记时加载 write_journal,处理图片时加载 images,修改 widget 或任务配置时加载 widgets_and_tasks。单次会话中只需加载一次。",
            "parameters": {
                "type": "object",
                "required": ["group_name"],
                "properties": {
                    "group_name": {
                        "type": "string",
                        "enum": ["write_journal", "images", "widgets_and_tasks"],
                        "description": "工具组选项:\n- write_journal:用于编辑日记块和管理日常任务的勾选\n- images:用于上传图片、删除图片和为任务设置配图\n- widgets_and_tasks:用于创建、删除、修改 widget 以及更改任务配置和名称",
                    },
                },
            },
        },
    },
]
