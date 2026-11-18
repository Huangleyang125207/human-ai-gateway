# PATTERN: util — protocol loading + system prompt assembly extracted from god module
# USE WHEN: build_system_prompt / load_protocol / time-block hint 改动
# COPY THIS: 无 — 本模块是 server.py §5(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§5, Parallel Change expand):
# - 原址 server.py(拆前行号 L1068–1300 一带,已漂移到 L483–709):PROTOCOLS_DIR/PROTOCOLS/
#   _wants_widget_skill/load_protocol/_load_user_context/build_system_prompt/
#   _TIMEBLOCK_HOOK_PATH/_compute_time_block_hint/_compute_time_block_hint_inline。
# - 红线:baseline prompt 字节不变。稳定路径直接来自依赖叶子；time-block 的
#   vault/logger 由 server 窄适配器注入。
# - 被 chat_routes.py:590 与 pulse_eval.py:282 函数体内 lazy `from server import
#   build_system_prompt, _compute_time_block_hint` 回拉 — server 顶层必须继续 re-export 这两个名字。
import os as _os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from pulse_io import (
    _AGENT_CONTEXT_PATH,
    _PROJECT_PULSE_PATH,
    _USER_PULSE_PATH,
)
from runtime_paths import GATEWAY_DIR
from skill_runtime import render_skill_index


PROTOCOLS_DIR = GATEWAY_DIR / "protocols"
PROMPTS_DIR = GATEWAY_DIR / "prompts"


def _read_prompt(name: str) -> str:
    """读 prompts/{name} 原样返回(不 strip — 文件内容就是 f-string 的原字面量)。"""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")

# protocol 文件名 → 索引描述,baseline preamble 给 AI 看的目录
PROTOCOLS = {
    "schedule": "编辑日记格式 / 时间块 / 标签 / commit 双签 / 1-year test 等规则",
    # 未来再加:"vision", "widgets", "forensics" — 当前 vision 是 per-msg 注入,widgets 走 _wants_widget_skill
}


def _wants_widget_skill(context: dict) -> bool:
    """是否需要装载 widget skill。default 不装(省 ~6.7K tokens)。
    触发条件:context 明示 widget-edit 类型 OR 引用了 widget DOM 元素。
    """
    if not context:
        return False
    if context.get("type") in ("widget-edit", "widget"):
        return True
    for r in context.get("refs") or []:
        if r.get("kind") in ("widget", "widget-element"):
            return True
    return False


def load_protocol(name: str, model_id: str = None) -> str:
    """读 protocols/{name}.md 并返内容。{model_id} 占位符会被替换为传入的 model_id。
    AI 通过 load_protocol tool 触发;build_system_prompt 也可以预 load 某 protocol。
    """
    if name not in PROTOCOLS:
        return f"(unknown protocol: {name}. available: {', '.join(PROTOCOLS.keys())})"
    f = PROTOCOLS_DIR / f"{name}.md"
    if not f.exists():
        return f"(protocol file missing: {f})"
    text = f.read_text(encoding="utf-8")
    if model_id:
        text = text.replace("{model_id}", model_id)
    return text


# ── system prompt builder ────────────────────────────────────────────
# 三份自演化 md 注入 system prompt:USER_PULSE / 项目 PULSE / AGENT_CONTEXT
# compact 完成后 LLM 重写文件,mtime 变 → cache 失效 → 下次 chat 自动读最新
# memory dir + USER_PULSE 路径走 env(陌生用户没 → 默认 None,不 inject)
# _USER_PULSE_PATH / _PROJECT_PULSE_PATH / _AGENT_CONTEXT_PATH 已搬到 pulse_io.py
# (P2,顶部 re-export 进 server 命名空间)
# workflow #8 PII 防护:_MEMORY_DIR 默认 None,绝不再硬编开发者绝对路径。
# 我自己机器走 env GATEWAY_MEMORY_DIR 指向私人 memory dir;陌生用户 / VM 镜像 / username
# 撞名一律读不到 — 防 PII 灌进陌生用户 system prompt。
_GATEWAY_MEMORY_DIR_ENV = _os.environ.get("GATEWAY_MEMORY_DIR", "").strip()
_MEMORY_DIR = Path(_GATEWAY_MEMORY_DIR_ENV) if _GATEWAY_MEMORY_DIR_ENV else None
_USER_CTX_CACHE: dict = {"sig": None, "content": ""}

def _load_user_context() -> str:
    """合并 vault/AGENT_CONTEXT + 项目 PULSE + USER_PULSE + memory/*.md(排除索引)。
    任何文件改了 mtime 变 → cache 失效 → 下次 chat 自动重读。
    陌生用户场景:USER_PULSE/memory env 没设默认 None,只读 vault 旁 AGENT_CONTEXT + 项目 PULSE(若有)。
    """
    files = []
    if _AGENT_CONTEXT_PATH.exists():
        files.append(_AGENT_CONTEXT_PATH)
    if _PROJECT_PULSE_PATH.exists():
        files.append(_PROJECT_PULSE_PATH)
    if _USER_PULSE_PATH.exists():
        files.append(_USER_PULSE_PATH)
    if _MEMORY_DIR is not None and _MEMORY_DIR.exists():
        files.extend(sorted(p for p in _MEMORY_DIR.glob("*.md") if p.name != "MEMORY.md"))
    sig = tuple((str(p), p.stat().st_mtime) for p in files)
    if _USER_CTX_CACHE["sig"] == sig:
        return _USER_CTX_CACHE["content"]
    parts = []
    if _AGENT_CONTEXT_PATH.exists():
        try:
            ac_text = _AGENT_CONTEXT_PATH.read_text(encoding='utf-8')
            # workflow #4 闭合:placeholder 字段是空槽,严禁 LLM 从对话反推填进
            # 提示词层加硬约束。frozen 段是协议手册,user-region 是用户区。
            parts.append(
                "\n\n=== AGENT_CONTEXT(vault 协作约定 + 用户角色)===\n"
                "**注意**:文件里 `<!-- placeholder: XXX -->` 注释下方的空字段(冒号后空白)"
                "是用户**未填**的槽。严禁从对话反推内容填进去,也不要假设这条已知。"
                "用户主动告诉你他的角色 / 关心点 时才用,否则一律视为未知。\n\n"
                + ac_text
            )
        except Exception:
            pass
    if _PROJECT_PULSE_PATH.exists():
        try:
            parts.append(f"\n\n=== 项目 PULSE(项目当下状态)===\n{_PROJECT_PULSE_PATH.read_text(encoding='utf-8')}")
        except Exception:
            pass
    if _USER_PULSE_PATH.exists():
        try:
            parts.append(f"\n\n=== USER_PULSE(用户当下快照)===\n{_USER_PULSE_PATH.read_text(encoding='utf-8')}")
        except Exception:
            pass
    mem_parts = []
    for p in files:
        if p in (_AGENT_CONTEXT_PATH, _PROJECT_PULSE_PATH, _USER_PULSE_PATH):
            continue
        try:
            mem_parts.append(f"--- {p.stem} ---\n{p.read_text(encoding='utf-8')}")
        except Exception:
            pass
    if mem_parts:
        parts.append("\n\n=== 协作 memory(具体规则 / 用户事实 / 项目决策)===\n" + "\n\n".join(mem_parts))
    content = "".join(parts)
    _USER_CTX_CACHE["sig"] = sig
    _USER_CTX_CACHE["content"] = content
    return content


def build_system_prompt(
    context: dict = None,
    model_id: str = None,
) -> str:
    """构造 system prompt。Lean baseline + protocol 索引;具体协议 AI 用
    load_protocol tool 按需拉。model_id 用于替换 prompt 模板里的 {model_id}。
    """
    parts = [_read_prompt("baseline.md")]

    # user 视图 inject(USER_PULSE + 全部 memory)— 放在身份段后、protocol 目录前
    user_ctx = _load_user_context()
    if user_ctx:
        parts.append(user_ctx)

    # protocol 目录 — AI 知道有这些协议可 load
    protocol_index = _read_prompt("protocol_index_header.md")
    for name, desc in PROTOCOLS.items():
        protocol_index += f"· {name}: {desc}\n"
    protocol_index += _read_prompt("protocol_index_footer.md")
    parts.append(protocol_index)

    # 工具目录 + 宿主行为边界；schema 常驻，是否可执行由 ActionPolicy 决定。
    tool_catalog = _read_prompt("tool_catalog.md")
    parts.append(tool_catalog)

    # 日记写入决策与质量规则是跨端常驻合同；详细 schedule 协议仍按需加载。
    parts.append(_read_prompt("journal_writing.md"))

    # 只常驻轻量 Skill 索引；完整工作流由 search_skills → load_skill 按需披露。
    parts.append(render_skill_index())

    return "\n".join(parts)


_TIMEBLOCK_HOOK_PATH = Path.home() / ".claude" / "scripts" / "timeblock-stamp.sh"


def _week_calendar_hint(now: datetime) -> str:
    """Resolve the current Monday-Sunday dates before the model sees relative weekdays."""
    monday = now - timedelta(days=now.weekday())
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    mapping = "; ".join(
        f"{label}={(monday + timedelta(days=index)).strftime('%Y-%m-%d')}"
        for index, label in enumerate(labels)
    )
    return (
        f"[week-calendar] 本周: {mapping}; 今天={labels[now.weekday()]}. "
        "周一/周二等按此表解析; 上周/下周=本表日期-7/+7天。"
    )


def _compute_time_block_hint(*, vault_dir, logger) -> str:
    """source CC 那边的 ~/.claude/scripts/timeblock-stamp.sh — single source of truth。
    先读取 CC 的 [time-block] / [schedule-voice] baseline,再为 DeepSeek 追加
    确定性的 [week-calendar],避免让模型临场做星期日期算术。
    未来在 bash 里改 hook,两边自动同步,不必两份维护。

    cwd 设到 JOURNAL_DIR 父级,让 hook 里的 has_schedule_dir gate 通过(否则空输出)。
    `[skill-required]` 行对 deepseek 没意义(它不能 invoke Skill),过滤掉。

    fallback:bash 没装 / 文件缺 / 超时 → 内联 Python 算最小版,保证 chat 不挂。
    """
    if _TIMEBLOCK_HOOK_PATH.exists():
        try:
            result = subprocess.run(
                ["bash", str(_TIMEBLOCK_HOOK_PATH)],
                cwd=str(vault_dir if vault_dir.exists() else Path.home()),
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = [l for l in result.stdout.splitlines()
                         if not l.startswith("[skill-required]")]
                return "\n".join(lines).rstrip() + "\n" + _week_calendar_hint(datetime.now())
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning(f"timeblock-stamp.sh failed ({e}), inline fallback")
    return _compute_time_block_hint_inline()


def _compute_time_block_hint_inline() -> str:
    """fallback:hook 不可用时的最小内联实现。"""
    now = datetime.now()
    block_minute = 30 if now.minute >= 30 else 0
    block_label = f"{now.hour}：{block_minute:02d}"
    end_minute = 59 if block_minute == 30 else 29
    weekday_cn = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][now.weekday()]
    return (
        f"[time-block] now={now.strftime('%H:%M')} CST {now.strftime('%Y-%m-%d')}({weekday_cn}) "
        f"→ current block: {block_label} (covers {now.hour:02d}:{block_minute:02d}-{now.hour:02d}:{end_minute:02d})\n"
        f"[time-block] H1 use: `# {block_label}` (full-width colon). For PAST events, ASK user.\n"
        f"{_week_calendar_hint(now)}"
    )
