"""pulse_io — PULSE 子系统的 leaf:数据/IO/解析/校验,无 LLM 调用。

PULSE LARGE refactor P2。从 server.py 抽出,行为零变化。
依赖 server.py 顶层的 VAULT_DIR / APP_STATE_DIR(在 server.py L83/L111 已定义,
本模块由 server.py 在 L120 之后 import,VAULT_DIR/APP_STATE_DIR 已在 server.namespace)。

包含:
  - 3 个 PULSE 真源路径(env-overrideable):_USER_PULSE_PATH / _PROJECT_PULSE_PATH /
    _AGENT_CONTEXT_PATH
  - PULSE_DIR(app-state mirror)/ PULSE_BUDGET_CHARS / PULSE_STALE_DAYS
  - 4 正则:_TS_RE / _FROZEN_RE / _PLACEHOLDER_RE / _SCHEMA_VERSION_RE
  - 4 小 helper:_extract_frozen / _count_placeholders / _get_schema_version /
    _ensure_schema_version_header
  - _pulse_validate(主校验:budget/ts/strict/frozen/placeholder)
  - _parse_pulse_md(PULSE.md → dashboard dict 解析器)
  - _SELF_EVOLVE_TARGETS 字典(3 target 配置,lambda 闭包内查本模块的 path 常量)

server.py 必须 re-export 全部上述符号(P0+ 测试 fixture 走 server.X 命名空间)。
"""
import os as _os
import re
from datetime import datetime
from pathlib import Path

from server import VAULT_DIR, APP_STATE_DIR


# ── 3 个 PULSE 真源路径(env-overrideable)──────────────────────────────
# 三个 self-evolve target 真源路径 — 默认 vault 旁(陌生用户拿到桌面壳即可用);
# 开发者机器走 env override 指个人扩展位置。
# 默认指向不存在的 vault 文件没事 — _self_evolve_run 检测到 not-exist 走 graceful skip。
_USER_PULSE_PATH = Path(_os.environ.get("GATEWAY_USER_PULSE_PATH", str(VAULT_DIR / "USER_PULSE.md")))
_PROJECT_PULSE_PATH = Path(_os.environ.get("GATEWAY_PROJECT_PULSE_PATH", str(VAULT_DIR / "PROJECT_PULSE.md")))
# workflow #24 闭合:AGENT_CONTEXT 也加 env override(测试隔离需要)
_AGENT_CONTEXT_PATH = Path(_os.environ.get("GATEWAY_AGENT_CONTEXT_PATH", str(VAULT_DIR / "AGENT_CONTEXT.md")))


# ── PULSE app-state mirror(给 dashboard 读)──────────────────────────
PULSE_DIR = APP_STATE_DIR / "pulse-mirror"  # 搬出 vault,app-owned 单向镜像


# ── 校验常量 + 正则 ──────────────────────────────────────────────────
# LLM 重写整份 PULSE,自己决定:
#   - 哪条记录还有效 → ts 改成今天
#   - 哪条过时 → 自己删
#   - 新事实 → 加,ts 今天
# server 只验三条机械规则: ts 格式合规 / 总长度 ≤ 12000 字 / ts 是合法日期。
PULSE_BUDGET_CHARS = 12000
PULSE_STALE_DAYS = 60
_TS_RE = re.compile(r"<!--\s*ts:(\d{4}-\d{2}-\d{2})\s*-->")

_FROZEN_RE = re.compile(r"<!--\s*frozen-start\s*-->(.*?)<!--\s*frozen-end\s*-->", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"<!--\s*placeholder:\s*([^>\-]+?)\s*-->")
_SCHEMA_VERSION_RE = re.compile(r"<!--\s*schema-version:\s*(\d+)\s*-->")


def _extract_frozen(text: str) -> str:
    """抓 frozen-start..frozen-end 段(协议手册区,LLM 不许动)。无 marker 返空。"""
    m = _FROZEN_RE.search(text)
    return m.group(1) if m else ""


def _count_placeholders(text: str) -> int:
    return len(_PLACEHOLDER_RE.findall(text))


def _pulse_validate(text: str, budget: int = PULSE_BUDGET_CHARS,
                    old_text: str = "", strict: bool = False):
    """返 (ok: bool, error: str)。
    根因 A 闭合(workflow #3 #19):
      - 长度 + ts 格式(原有)
      - strict 模式 ts count ratio ≥ 0.5、H2 ratio ≥ 0.7(防 LLM 大量删段绕过 length guard)
      - 有 frozen marker 时,frozen 段 sha256 必须 byte-equal(协议手册不许动)
      - 有 placeholder marker 时,数量必须 ≥ 原 placeholder 数(防 LLM 当用户数据吃掉)
    """
    if len(text) > budget:
        return False, f"超 budget: {len(text)} > {budget}"
    matches = _TS_RE.findall(text)
    if not matches:
        return False, "没找到任何 <!-- ts:YYYY-MM-DD --> 标记"
    for m in matches:
        try:
            datetime.strptime(m, "%Y-%m-%d")
        except Exception:
            return False, f"ts 不是合法日期: {m}"
    if not old_text:
        return True, ""
    # Strict invariant checks 跟 old 对比
    if strict:
        old_ts = len(_TS_RE.findall(old_text))
        new_ts = len(matches)
        if old_ts > 0 and new_ts < int(old_ts * 0.5):
            return False, f"ts 标记腰斩 {old_ts}→{new_ts}(<50%)"
        old_h2 = len(re.findall(r"^##\s", old_text, re.MULTILINE))
        new_h2 = len(re.findall(r"^##\s", text, re.MULTILINE))
        if old_h2 > 4 and new_h2 < int(old_h2 * 0.7):
            return False, f"H2 段数腰斩 {old_h2}→{new_h2}(<70%)"
    # Frozen 段 byte-equal(协议手册区不许动)
    old_frozen = _extract_frozen(old_text)
    if old_frozen:
        new_frozen = _extract_frozen(text)
        import hashlib as _h_fro
        if _h_fro.sha256(old_frozen.encode("utf-8")).hexdigest() != \
           _h_fro.sha256(new_frozen.encode("utf-8")).hexdigest():
            return False, "frozen 段(协议手册)被修改,不允许"
    # Placeholder 完整性
    old_ph = _count_placeholders(old_text)
    new_ph = _count_placeholders(text)
    if old_ph > 0 and new_ph < old_ph:
        return False, f"placeholder 标记被吃掉 {old_ph}→{new_ph}(LLM 误把空槽当用户数据保留)"
    return True, ""


# ── _parse_pulse_md:PULSE.md → dashboard dict ───────────────────────

_STATUS_EMOJI = ["🔴", "🟡", "🟢", "⚪", "🔵"]


def _parse_pulse_md(text: str, name: str) -> dict:
    """从一份 PULSE.md 抽出 dashboard 要的字段。容错:任何 section 缺失都返空串/空列表。"""
    out = {
        "name": name,
        "tagline": "",
        "status_emoji": "",
        "now_line": "",
        "heartbeat": [],
        "last_refreshed": "",
    }
    section = None
    for line in text.splitlines():
        # Last refreshed: 可能在文件任意位置
        if "Last refreshed:" in line and not out["last_refreshed"]:
            m = re.search(r'Last refreshed:\s*(\d{4}-\d{2}-\d{2})', line)
            if m:
                out["last_refreshed"] = m.group(1)
        # section heading
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section == "一句话":
            s = line.strip()
            if s and not s.startswith(">") and not out["tagline"]:
                out["tagline"] = s
        elif section == "现在":
            s = line.strip()
            if s and not s.startswith(">") and not out["now_line"]:
                out["now_line"] = s
                # 提取 status emoji(可能在行首)
                for e in _STATUS_EMOJI:
                    if e in s:
                        out["status_emoji"] = e
                        break
        elif section == "心跳":
            if line.startswith("- ") and len(out["heartbeat"]) < 5:
                out["heartbeat"].append(line[2:].strip())
    return out


# ── schema-version helper ─────────────────────────────────────────────

def _get_schema_version(text: str) -> int:
    """文件头部 `<!-- schema-version: N -->` 标记。无标记 = 0(bootstrap 态)"""
    m = _SCHEMA_VERSION_RE.search(text)
    return int(m.group(1)) if m else 0


def _ensure_schema_version_header(text: str, version: int) -> str:
    """如果文本没 schema-version 标记,在文档前部插入一条;有则更新数字。
    放在第一个 H1 之后(若有),否则放在最前。
    """
    if _SCHEMA_VERSION_RE.search(text):
        return _SCHEMA_VERSION_RE.sub(f"<!-- schema-version: {version} -->", text, count=1)
    marker = f"<!-- schema-version: {version} -->"
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            # H1 后空行后插入
            lines.insert(i + 1, "")
            lines.insert(i + 2, marker)
            return "\n".join(lines)
    return marker + "\n\n" + text


# ── _SELF_EVOLVE_TARGETS:3 target 配置 ─────────────────────────────────
# lambda 闭包查本模块的 _USER_PULSE_PATH 等(本模块就是 pulse_io 自己,字典是引用,
# 跨模块共享 → server 顶部 re-export 后,server._SELF_EVOLVE_TARGETS 跟这里同对象)。
# Self-evolve 三个 target 的 budget 配置;这三个文件机制完全一致:LLM 自由重写,
# server 只验 ts 格式 + 总长。
_SELF_EVOLVE_TARGETS = {
    "user_pulse": {
        "path": lambda: _USER_PULSE_PATH,
        "name": "USER_PULSE",
        "what": "用户当下快照 — 气压 / 想做 / 历史阶段 / 协作偏好 / 不要做",
        "budget": 12000,
        "stale": 60,
        "prompt_template": "default",  # 用 _PULSE_UPDATE_PROMPT
        # per-user 快照,每个用户都该有:不存在时让 LLM 从对话生成首版(走 bootstrap),
        # 不像 project_pulse 那样陌生用户没"项目"就 skip。
        "create_if_absent": True,
    },
    "project_pulse": {
        "path": lambda: _PROJECT_PULSE_PATH,
        "name": "项目 PULSE",
        "what": "项目当下状态 — 一句话 / 当下气压 / Cannot break / Can play / 历史阶段 / 应该知道 / 不要做 / 时间锚点",
        "budget": 24000,
        "stale": 60,
        "prompt_template": "default",
    },
    "agent_context": {
        "path": lambda: _AGENT_CONTEXT_PATH,
        "name": "AGENT_CONTEXT",
        "what": "AI 跟 vault 主人的协作约定 — vault 用法 / tag / #协作 / #commit / 协作偏好",
        "budget": 8000,
        "stale": 90,
        "prompt_template": "agent_context",  # 走 _AGENT_CONTEXT_EVOLVE_PROMPT,frozen 段保护
    },
}
