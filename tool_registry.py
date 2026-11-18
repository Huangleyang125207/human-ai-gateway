# PATTERN: api — host action policy/quota/dispatch engine extracted from god module (Parallel Change)
# USE WHEN: ActionPolicy / TOOL_QUOTA / _dispatch_tool 相关改动
# COPY THIS: 无 — 本模块是 server.py §9(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§9 深水区第一刀):
# - 原址 server.py L1617–1735;server.py 保留同名 re-export(Parallel Change expand 阶段),
#   caller(chat_routes 的 lazy `from server import _dispatch_tool/_active_tools/...`)一字不改。
# - TOOL_IMPL/失败上报/logger/工具查找由组装根以命名 effect 注入，
#   call-time provider 保留测试 patch 语义。
# - 2026-07-31: 退役模型自授权 load_tool_group；schema 稳定常驻。
# - 2026-08-03: ActionPolicy 收口到 Widget mutation；其他领域走自己的写入守卫。
# - 跨端:RN services/actionPolicy.ts + toolGating.ts 镜像本边界；effect 表由
#   scripts/generate_tool_contracts.py 生成，漂移由契约测试与 --check 抓取。
from action_policy import authorize_tool
from cache_usage import record_cache_usage
from tool_specs import TOOLS

_LIST_WIDGETS = None
_TOOL_IMPL = None
_REPORT_FAILURE = None
_LOGGER = None


def configure_effects(
    *,
    list_widgets,
    tool_impl,
    report_failure,
    logger,
) -> None:
    global _LIST_WIDGETS, _TOOL_IMPL, _REPORT_FAILURE, _LOGGER
    _LIST_WIDGETS = list_widgets
    _TOOL_IMPL = tool_impl
    _REPORT_FAILURE = report_failure
    _LOGGER = logger


def build_tool_impl(implementations: dict) -> dict:
    """从组装根提供的显式实现表构建 TOOL_IMPL。"""
    names = [
        "search_widget_capabilities", "validate_widget_spec",
        "install_widget_spec",
        "set_widget_enabled", "remove_widget",
        "list_memos", "create_memo", "update_memo", "act_on_memo",
        "manage_memo_series",
        "patch_journal_block", "read_today_schedule", "list_recent_days",
        "insert_journal_block", "append_journal_comment",
        "manage_daily_task", "check_daily_task",
        "set_daily_task_image", "set_water_cup_image", "set_daily_task_meta",
        "place_scrapbook_image", "list_my_uploads", "search_my_uploads",
        "ask_photo_curator", "search_text", "read_text", "delete_attachment",
        "vision_classify", "record_image_observation", "web_search", "fetch_url", "load_protocol",
        "search_skills", "load_skill", "read_skill_resource",
        "manage_tag_aggregate", "get_daily_care_state", "manage_scrapbook",
        "delete_journal_entry", "manage_mood",
    ]
    missing = sorted(set(names) - implementations.keys())
    if missing:
        raise ValueError(f"missing tool implementations: {missing}")
    impl = {"list_widgets": (lambda args: implementations["list_widgets"]())}
    for n in names:
        impl[n] = implementations[n]
    return impl


def _active_tools(_action_context=None) -> list:
    """Keep tool schemas stable; host policy, not model-managed groups, gates effects."""
    return list(TOOLS)

# PATTERN: api — per-tool quota with hard cap per chat turn
# USE WHEN: model 容易死循环调同一 tool(web_search loop, list 类反复 read)
# COPY THIS: 改 TOOL_QUOTA 数字 / 加新 tool 进 dict
# 没在 dict 里的 tool = 无限(write/admin 类用户授权过的别卡)
TOOL_QUOTA = {
    "web_search":          3,
    "fetch_url":           5,   # 比 search 多 — 一次 search 可能 fetch 2-3 个有料的
    "append_journal_comment": 5,  # 留评论本来就该克制,5 次/turn 够了
    "read_today_schedule": 5,
    "list_recent_days":    2,
    "list_my_uploads":     2,
    "search_my_uploads":   3,
    "ask_photo_curator":   1,  # 单 call 返完整集,quota 给 1 就够;主 agent 应优先调它做语义检索
    "search_text":         5,
    "read_text":           8,  # 搜索后按行补读，允许少量分页
    "vision_classify":     3,
    "record_image_observation": 8,
    "load_protocol":       3,
    "search_skills":       3,
    "load_skill":          4,
    "read_skill_resource": 5,
}

# PATTERN: util — observability log for LLM cache hit rate
# USE WHEN: 想看 DeepSeek prompt_cache_hit_tokens 实际命中率(stable prefix 假设验证)
# COPY THIS: 改 source 字符串区分调用位置
def _log_cache_usage(resp, source: str):
    """Persist + log cache metrics; never records prompt/response content."""
    try:
        row = record_cache_usage(resp, source=source)
        if not row or not row["cache_fields_present"]:
            return
        hit = row["hit_tokens"]
        miss = row["miss_tokens"]
        total = hit + miss
        if total == 0:
            return
        ratio = hit / total * 100
        _LOGGER().info(f"[cache:{source}] hit={hit} miss={miss} ratio={ratio:.0f}% (total prompt={total})")
    except Exception:
        pass  # observability 不能因为它崩

def _dispatch_tool(fn: str, args: dict, action_context: dict, quota_used: dict):
    """Host integrity check → quota → implementation."""
    policy_error = authorize_tool(fn, args, action_context)
    if policy_error:
        return policy_error
    cap = TOOL_QUOTA.get(fn)
    if cap is not None:
        used = quota_used.get(fn, 0)
        if used >= cap:
            return {"error": f"{fn} 本轮 chat 已用 {used}/{cap} 次,quota 用完。用已有 result 答,别再调。"}
        quota_used[fn] = used + 1
    try:
        return _TOOL_IMPL()[fn](args)
    except KeyError:
        return {"error": f"unknown tool: {fn}"}
    except Exception as e:
        # tool 真崩了 — LLM 会拿 error 串往下走,常常导致幻觉回复("我已经做了 X")。
        # claim audit 会兜底 detect,但根因丢了不利后续修。
        _REPORT_FAILURE("tool_dispatch_exception",
            f"{fn}: {type(e).__name__}: {str(e)[:150]}",
            context={"tool": fn})
        return {"error": str(e)}
