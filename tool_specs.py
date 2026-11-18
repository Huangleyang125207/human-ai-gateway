"""tool_specs — LLM 工具的 JSON schema 定义(给模型看的 function specs)。

Extract Module(ctrl-c-v § 9):TOOLS schema 列表(纯数据 leaf,零依赖)从 server.py 抽出。
server `from tool_specs import TOOLS` re-export;消费者 _active_tools(server)+ 名字映射 TOOL_IMPL/
effect 由 action_policy.py 统一定义。characterization:tests/test_tool_specs.py。
"""
_WIDGET_SPEC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "id", "title", "slot", "data", "view"],
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.0"]},
        "id": {
            "type": "string",
            "description": "kebab-case stable widget id, max 64 chars",
        },
        "title": {"type": "string", "description": "user-facing title"},
        "slot": {"type": "string", "enum": ["care"]},
        "data": {
            "type": "object",
            "additionalProperties": False,
            "required": ["capability", "params"],
            "properties": {
                "capability": {
                    "type": "string",
                    "enum": [
                        "daily_tasks.completion_summary",
                        "memo.overview",
                    ],
                },
                "params": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 30,
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8,
                        },
                    },
                },
            },
        },
        "view": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["metric_sparkline", "memo_list"],
                },
                "metric": {
                    "type": "object",
                    "description": (
                        'Use exactly {"path":"summary.rate",'
                        '"format":"percent"}.'
                    ),
                },
                "caption": {
                    "type": "object",
                    "description": 'Use exactly {"path":"summary.caption"}.',
                },
                "series": {
                    "type": "object",
                    "description": (
                        'Use exactly {"path":"days","value":"rate"}.'
                    ),
                },
                "items": {
                    "type": "object",
                    "description": 'For memo_list use exactly {"path":"items"}.',
                },
                "empty_text": {"type": "string"},
                "add_label": {"type": "string"},
            },
        },
    },
}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_widgets",
            "description": "List the merged system and AI-authored widget inventory, including visibility, editability, source, and WidgetSpec revision when available.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_widget_enabled",
            "description": "Show or hide a system or AI-authored widget without changing its implementation.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "enabled"],
                "properties": {
                    "id": {"type": "string", "description": "Widget id returned by list_widgets."},
                    "enabled": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_widget",
            "description": "Remove an AI-authored widget. System widgets cannot be removed; disable them instead.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id"],
                "properties": {"id": {"type": "string", "description": "AI-authored widget id."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_widget_capabilities",
            "description": (
                "List the semantic, least-privilege data capabilities available "
                "to WidgetSpec. Call this before designing a widget."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "optional capability name/description filter",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_widget_spec",
            "description": (
                "Validate a declarative WidgetSpec without installing it. "
                "Generated HTML, JavaScript and unknown fields are rejected."
            ),
            "parameters": {
                "type": "object",
                "required": ["spec"],
                "properties": {"spec": _WIDGET_SPEC_SCHEMA},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_widget_spec",
            "description": (
                "Install a new or replace an existing AI-authored WidgetSpec after "
                "validation. Replacing must keep the existing id and preserves its "
                "enabled state. Only call when the user explicitly asked to add, "
                "install, modify, adjust, or replace the widget. System widgets "
                "cannot be replaced."
            ),
            "parameters": {
                "type": "object",
                "required": ["spec"],
                "properties": {"spec": _WIDGET_SPEC_SCHEMA},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memos",
            "description": (
                "读取 AI 管理的当前备忘录 occurrence。逾期是即时推导状态；"
                "不会创建或修改数据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_memo",
            "description": (
                "根据用户自然语言或已确认的 OCR 文本创建备忘录。due_at 必须是"
                "带时区的 ISO 时间；GUI 与 AI 共用此状态转换。"
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "due_at", "schedule"],
                "properties": {
                    "text": {"type": "string", "maxLength": 200},
                    "due_at": {
                        "type": "string",
                        "description": "ISO 8601 datetime with timezone",
                    },
                    "schedule": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind"],
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "once", "daily", "weekdays",
                                    "weekly", "monthly",
                                ],
                            },
                            "weekdays": {
                                "type": "array",
                                "items": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 7,
                                },
                            },
                        },
                    },
                    "notification_enabled": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memo",
            "description": (
                "修改一条待处理备忘录的内容、到期时间、频率和提醒开关。"
                "GUI 与 AI 共用此状态转换；必须先用 list_memos 取得 IDs。"
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "series_id", "occurrence_id", "text", "due_at", "schedule",
                ],
                "properties": {
                    "series_id": {"type": "string"},
                    "occurrence_id": {"type": "string"},
                    "text": {"type": "string", "maxLength": 200},
                    "due_at": {
                        "type": "string",
                        "description": "ISO 8601 datetime with timezone",
                    },
                    "schedule": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind"],
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "once", "daily", "weekdays",
                                    "weekly", "monthly",
                                ],
                            },
                            "weekdays": {
                                "type": "array",
                                "items": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 7,
                                },
                            },
                        },
                    },
                    "notification_enabled": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "act_on_memo",
            "description": (
                "完成、跳过或推迟一次备忘录 occurrence。完成会先写入日记，"
                "成功后才更新 occurrence；周期任务随后生成下一次。"
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["occurrence_id", "action"],
                "properties": {
                    "occurrence_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["complete", "skip", "snooze"],
                    },
                    "snooze_until": {
                        "type": "string",
                        "description": "snooze 时必填，带时区 ISO 时间",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_memo_series",
            "description": "暂停、恢复或归档一个备忘录系列；不会删除历史。",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["series_id", "action"],
                "properties": {
                    "series_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["pause", "resume", "archive"],
                    },
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
                    "date": {"type": "string", "description": "日期,格式为 YYYY-MM-DD。如果不提供,默认为今天"},
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
            "description": "向时间块添加新条目(正文必填，标题可选)。新条目会追加到现有内容之后(不会覆盖)。AI 调用此工具时会自动添加 @ai 标记。",
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
            "description": "为日常任务设置打卡图标(系统会自动去除背景)。task_name 支持唯一的模糊匹配；有多个候选时先读取任务列表确认。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "attachment_url"],
                "properties": {
                    "task_name": {"type": "string", "description": "任务名称或可唯一定位它的子串。例如:'维生素'"},
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
            "description": "标记任务为完成(打卡)。task_name 支持唯一的模糊匹配；有多个候选时先读取任务列表确认。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "checked"],
                "properties": {
                    "task_name": {"type": "string", "description": "任务名称或可唯一定位它的子串,例如:'维生素'"},
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
            "name": "record_image_observation",
            "description": "当本轮用户消息包含图片且你已经直接看见图片内容时调用。每张新图调用一次，把内容描述写入可检索附件索引；这不是日记写入，也不会修改图片。不得臆测看不见的历史图片。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url", "kind", "description"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "本轮 context 中的图片路径(/attachments/YYYY-MM-DD/xxx)"},
                    "kind": {"type": "string", "description": "简短内容分类，如 photo、exercise、food、supplement、document"},
                    "description": {"type": "string", "description": "适合日后检索的客观中文描述"},
                    "brand": {"type": "string", "description": "明确可见的品牌；不确定则省略"},
                    "pill_count": {"type": "integer", "description": "明确可见的药片/胶囊数量；不适用则省略"},
                    "ocr_likely": {"type": "boolean", "description": "图片是否包含值得读取的文字"},
                    "ocr_text": {"type": "string", "description": "直接看清的关键文字；只记录确定内容"},
                    "suggested_action": {"type": "string", "description": "可选的后续用途短语"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "vision_classify",
            "description": "兼容性视觉重分类工具。主对话模型已可直接看本轮图片，通常应调用 record_image_observation 写入索引；只有需要对历史附件重新识别或回答额外视觉问题时才调用本工具。",
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
            "description": "使用关键词搜索历史上传的图片(搜索范围包括文件名、原文件名、视觉描述和文字识别内容)。适用场景:精确关键词搜索。如需语义搜索或处理不同术语指称同一物体(例如:'狗'、'哈士奇'、用户起的昵称被视为同一概念),请改用 ask_photo_curator 工具。",
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
                "适用: 长期回顾 / 跨称呼(狗=哈士奇=用户起的昵称) / 模糊语义。"
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
            "name": "search_text",
            "description": "像 grep 一样直接搜索当前知识库中的 Markdown 文本；无索引、无缓存。query 按字面量匹配，返回文件、行号和附近上下文。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "要查找的原始文本；按字面量而不是正则表达式匹配"},
                    "case_sensitive": {"type": "boolean", "description": "是否区分大小写，默认 false"},
                    "context_lines": {"type": "integer", "description": "命中行前后各返回几行，默认 2，范围 0-5"},
                    "limit": {"type": "integer", "description": "最多返回多少条结果，默认 20，范围 1-100"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_text",
            "description": "读取 search_text 返回的 Markdown 文件，可按行分页。只能读取知识库内可见的 .md 文件。",
            "parameters": {
                "type": "object",
                "required": ["file"],
                "properties": {
                    "file": {"type": "string", "description": "search_text 返回的相对文件路径"},
                    "start_line": {"type": "integer", "description": "从第几行开始，1 起算，默认 1"},
                    "line_count": {"type": "integer", "description": "最多读取多少行，默认 80，范围 1-200"},
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
            "name": "search_skills",
            "description": "Search available Gateway Skills by workflow, description, or tool name. Returns metadata only; call load_skill for the selected workflow.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"query": {"type": "string", "description": "Optional workflow or tool search text."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load one Gateway Skill's workflow and explicit live references. This guides work but does not grant mutation permission.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {"name": {"type": "string", "description": "Exact Skill name returned by search_skills."}},
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
            "name": "read_skill_resource",
            "description": "Read one declared Skill reference in bounded chunks. Continue with next_cursor until eof=true; loading a resource does not authorize side effects.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "path"],
                "properties": {
                    "name": {"type": "string", "description": "Exact loaded Skill name."},
                    "path": {"type": "string", "description": "Exact reference path returned by load_skill."},
                    "cursor": {"type": "integer", "minimum": 0, "description": "Start offset; use the previous next_cursor."},
                    "limit": {"type": "integer", "minimum": 256, "maximum": 3500, "description": "Maximum characters for this chunk; default 3000."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_tag_aggregate",
            "description": "List registered aggregate tags, register a parent tag and immediately backfill it, or refresh all aggregate rows from journal Markdown.",
            "parameters": {"type": "object", "additionalProperties": False, "required": ["action"], "properties": {
                "action": {"type": "string", "enum": ["list", "register", "refresh"]},
                "tag": {"type": "string"}, "description": {"type": "string"}, "with_sub": {"type": "boolean"},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_care_state",
            "description": "Read one day's care checklist, water progress, inventory metadata, and recent per-task completion history.",
            "parameters": {"type": "object", "additionalProperties": False, "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD; default today."},
                "history_days": {"type": "integer", "minimum": 1, "maximum": 30},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_scrapbook",
            "description": "List, update, or explicitly remove a scrapbook sticker without changing its source attachment.",
            "parameters": {"type": "object", "additionalProperties": False, "required": ["action", "date"], "properties": {
                "action": {"type": "string", "enum": ["list", "update", "remove"]},
                "date": {"type": "string"}, "id": {"type": "string"},
                "patch": {"type": "object", "additionalProperties": False, "properties": {
                    "anchor_time": {"type": "string"}, "x_pct": {"type": "number"}, "y_px": {"type": "number"},
                    "size_pct": {"type": "number"}, "rotation": {"type": "number"}, "z": {"type": "number"},
                }},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_journal_entry",
            "description": "Delete exactly one H2 entry from a time block while preserving sibling entries. Requires explicit user deletion intent.",
            "parameters": {"type": "object", "additionalProperties": False, "required": ["time", "entry_index"], "properties": {
                "date": {"type": "string"}, "time": {"type": "string"},
                "entry_index": {"type": "integer", "minimum": 0},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_mood",
            "description": "Read, set, or clear the dated mood value shared with the mood GUI.",
            "parameters": {"type": "object", "additionalProperties": False, "required": ["action"], "properties": {
                "action": {"type": "string", "enum": ["get", "set", "clear"]},
                "date": {"type": "string"}, "value": {"type": "string", "maxLength": 32},
            }},
        },
    },
]
