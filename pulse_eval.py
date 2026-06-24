"""pulse_eval — 21:30 daily eval 子系统(复盘评估)。

PULSE LARGE refactor P3。从 server.py 抽出 11 个 `_eval_*` + `_classify_eval_err`
+ 3 个 prompt 常量 + EVAL_LOG_DIR。endpoint(/api/eval/test, /api/eval/run,
/api/eval/list, /api/eval/today)留 server.py(P5 收尾时一起考虑要不要也走 router)。

红线(PULSE.md Cannot break):
- `_eval_build_messages` 注入 past_boards(跨夜连贯,T4 守)
- 段次序 = today_md → recent_md → past_boards → pulse → claude_md(T4 顺序契约守)

依赖(函数体内 lazy import 避循环):
- server.find_today_journal / build_system_prompt / _compute_time_block_hint
- server.load_config / _safe_write_text / _report_silent_failure / log
- server._summarize_history / RECENT_KEEP
- server._load_task_image_map / _load_attachments_index / WATER_CUP_KEY
- server.DATA_HOME / WIDGETS_DIR / VAULT_DIR
- pulse_io.PULSE_DIR(已 P2 抽出,这里 lazy 走 server re-export)
"""
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


# ── EVAL_LOG_DIR(在 server.py L111 APP_STATE_DIR 之后才能解;走 lazy)──
# 因为 APP_STATE_DIR 在 server.py 才定义,我们 import 后用。pulse_io 同款做法。
from server import APP_STATE_DIR

EVAL_LOG_DIR = APP_STATE_DIR / "eval-log"  # 在 vault 之外 + app-protected → 协作 AI 永不读,用户也别误删


def _eval_load_recent_md(target: datetime, days: int = 7) -> str:
    """读最近 N 天 md(不含今天),拼成一大段。"""
    from server import find_today_journal
    chunks = []
    for i in range(1, days + 1):
        d = target - timedelta(days=i)
        f = find_today_journal(d)
        if f and f.exists():
            chunks.append(f"--- {d.strftime('%Y-%m-%d')} ({f.name}) ---\n"
                          f"{f.read_text(encoding='utf-8')}\n")
    return "\n".join(chunks) if chunks else "(过去 7 天无 md)"


def _eval_load_project_claude_md() -> str:
    """读项目 CLAUDE.md(待办 / Do not / Progress 段)。容错:文件不存在就空。"""
    candidates = [
        Path("/Users/claudecodedezhuanshumac/agents创作平台/CLAUDE.md"),
        Path("/Users/claudecodedezhuanshumac/agents创作平台/agents/human-ai-schedule/CLAUDE.md"),
    ]
    out = []
    for f in candidates:
        if f.exists():
            out.append(f"=== {f.name} @ {f.parent.name} ===\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(out) if out else "(no project CLAUDE.md found)"


def _eval_load_pulse_all() -> str:
    """读所有 PULSE.md 拼一起。"""
    from server import PULSE_DIR
    if not PULSE_DIR.exists():
        return "(no PULSE dir)"
    out = []
    for f in sorted(PULSE_DIR.glob("*.md")):
        out.append(f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(out) if out else "(no PULSE files)"


def _eval_scan_feature_signals(target: datetime) -> dict:
    """扫 gateway 全状态,产 raw signals。LLM 据此判断哪个 feature 该 intro(或不 intro)。
    都是廉价的 文件/计数 读,不调任何 API。
    """
    from server import (
        load_config, _load_task_image_map, WATER_CUP_KEY, find_today_journal,
        DATA_HOME, WIDGETS_DIR, VAULT_DIR, PULSE_DIR,
    )
    cfg = load_config() or {}
    sig = {}

    # 水杯 / daily-task 图配置
    image_map = _load_task_image_map()
    sig["water_cup_image_set"] = bool(image_map.get(WATER_CUP_KEY))
    sig["daily_task_images_set_count"] = sum(1 for k in image_map if k != WATER_CUP_KEY)

    # daily tasks (从模板 + 今日 md 推算大致数量)
    today_f = find_today_journal(target)
    if today_f and today_f.exists():
        text = today_f.read_text(encoding="utf-8")
        sig["daily_task_count_today"] = len(re.findall(r"^\s*-\s*\[[ x]\]\s+", text, re.MULTILINE))
    else:
        sig["daily_task_count_today"] = 0

    # attachments
    try:
        from server import _load_attachments_index
        arr = _load_attachments_index()
    except Exception:
        arr = []
    sig["attachments_total"] = len(arr)

    # widgets:可用 vs 已启
    widgets_user_cfg = DATA_HOME / ".user-widgets.json"
    if widgets_user_cfg.exists():
        try:
            cfg_w = json.loads(widgets_user_cfg.read_text(encoding="utf-8"))
            sig["user_widgets_enabled"] = cfg_w.get("enabled", []) if isinstance(cfg_w, dict) else []
        except Exception:
            sig["user_widgets_enabled"] = []
    else:
        sig["user_widgets_enabled"] = []
    if WIDGETS_DIR.exists():
        sig["widgets_available"] = sorted([
            d.name for d in WIDGETS_DIR.iterdir()
            if d.is_dir() and (d / "manifest.json").exists()
        ])
    else:
        sig["widgets_available"] = []

    # vault path 是否非默认
    sig["vault_path"] = str(VAULT_DIR)

    # PULSE
    pulse_count = len(list(PULSE_DIR.glob("*.md"))) if PULSE_DIR.exists() else 0
    sig["pulse_files_count"] = pulse_count

    # scrapbook
    sb_dir = DATA_HOME / "scrapbook-images"
    sig["scrapbook_images_total"] = len(list(sb_dir.glob("*"))) if sb_dir.exists() else 0

    # AI 能力是否配通
    sig["gemini_configured"] = bool(cfg.get("gemini_api_key"))
    sig["baidu_configured"] = bool(
        cfg.get("baidu_ocr_api_key") or cfg.get("baidu_cutout_api_key")
    )

    # eval 自己跑过几次
    eval_log_dir = EVAL_LOG_DIR
    sig["eval_runs_count"] = len(list(eval_log_dir.glob("*.md"))) if eval_log_dir.exists() else 0

    # 近 7 天 tag 分布 (从 md grep 来,廉价)
    tag_counts = {}
    for i in range(7):
        d = target - timedelta(days=i)
        f = find_today_journal(d)
        if not (f and f.exists()):
            continue
        text = f.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("## "):
                for tag in re.findall(r"#[\w一-鿿/]+", line):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
    sig["tag_entries_last_7d"] = tag_counts

    return sig


_FEATURE_INTRO_OPTIONS = """
可 intro 的 feature 候选(每天只挑一个;判断不出强信号该 intro 就 **跳过整个 feature_intro 字段**):

- **拖图设水杯**: 拖你水杯照片到右下角,AI 抠图后变成 daily-task 区水杯图标。signal:水杯图未设 = water_cup_image_set false
- **启 widget(mood / steps / supplements / ctrl-c-v-bridge)**: 设置面板 "插件市场" tab 勾。signal: user_widgets_enabled 为空 + widgets_available 不空
- **AI 搜历史 attachment**: 跟 sidebar 说"我之前传的 X 那张",自动翻 OCR 索引找。signal: attachments_total > 15 且 user 从没问过"之前的"
- **AI 看图返结构化**: 拖任意图 + 跟 AI 说"这是啥",Gemini 返 brand/颗数/建议动作。signal: gemini_configured true 但 sidebar 没主动调过
- **daily eval 自己**: 每晚 21:30 evaluator 给硬评 + 引导未试功能 = 你现在看到的这条。signal: eval_runs_count 第一次时必出(self-introduce)
- **tag-stats 注意力分布**: 每 tag 累计 entry 数。signal: tag_entries_last_7d 某 tag 已 ≥ 3 次该入聚合,但用户未感知
- **PULSE in vault**: 4 项目 PULSE 已镜像 vault,Obsidian 翻。signal: pulse_files_count > 1
- **scrapbook 多日浏览**: scrapbook viewer 按日期翻。signal: scrapbook_images_total > 5 + 多在最近几天
- **vault selector**: 让 AI 改 vault 路径同源 Obsidian。signal: vault_path 仍是默认 ~/.human-ai/vault

判断规则:
1. signals 看一遍,找 **真有强 trigger** 的 feature(数字明显 + 未用)。
2. 强 trigger 选最高 priority 一个。无强 trigger → feature_intro = null,不要硬塞。
3. why_now 必须 cite 具体 signal 数字,不能空话。
"""


# workflow B #2 闭合 helper:把 eval LLM 调用异常按子类型分桶,silent-failure 仪表盘可聚类。
# 不再把 "401 鉴权 / 429 quota / 网络 timeout / response_format 不支持" 一锅煮成
# `eval_response_format_unsupported` 让运维误以为是模型不支持 JSON mode。
def _classify_eval_err(e: Exception) -> str:
    s = str(e).lower()
    cls = type(e).__name__.lower()
    if "401" in s or "403" in s or "auth" in s or "unauthor" in cls:
        return "eval_call_auth"
    if "429" in s or "quota" in s or "rate" in s or "limit" in s:
        return "eval_call_quota"
    if "timeout" in s or "timeout" in cls or "timed out" in s:
        return "eval_call_timeout"
    if "response_format" in s or "json_object" in s or "json mode" in s:
        return "eval_response_format_unsupported"
    return "eval_call_failed"


_EVAL_INJECTION = """

═══════════════════════════════════════════════════════════════════════════
[21:30 复盘时刻 — 你是 user 的人生决策伙伴]
═══════════════════════════════════════════════════════════════════════════

你是 user 的人生决策伙伴 — 同时扮演三种角色的综合体:

· 一位见过很多人走弯路的资深导师 — 你知道哪条岔路通向倦怠、哪条通向稳态;
  早就见过同样的形状在别人身上演出过结局。
· 一位关心他整体状态的好友 — 你在意他工作以外的部分(睡眠、心情、关系、
  身体)。不是温情,是因为这些东西最先反映他在不在轨。
· 一位用数据 + 长期视角说话的战略顾问 — 你看的不是今天一天,是周 / 月 /
  季度的形状。今天的选择会通向哪儿。

身份连贯:之前是你建议并协助 user 做每天的日程表 — 把他从纷繁流动的外部
锚定下来。现在是晚上 21:30,复盘时刻 — 你回来读他这一天写了什么,根据
内容给鼓励、给建议、指出你认为日程表上还缺什么。

行为规则:

1. 必读 today_entries + 7day_md + past_boards + project_pulse — 一项不漏。
2. 每个判断必须 cite 具体证据 — time block / entry 标题 / 数字。无 cite =
   invalid。
3. **encouragement** 不要泛泛肯定。挑一件具体的事,说为什么这件事在长线上
   是好信号。空话比沉默更糟。
4. **suggestion** 是战略顾问视角的话 — "这一周这个 pattern 如果继续会..."、
   "你过去 3 次都是 X 之后会 Y,所以..."。不是当天的碎念。
5. **what_missing** 是这次最重要的一项 — 你读完一天的 schedule,觉得这个
   人今天**缺记了什么**?
   - 优先关注:**身体感受**(疲倦 / 精神状态 / 肩颈 / 胃口 / 情绪)。
     如果 schedule 里只有"做了什么",没有"身体怎么了",直接点出来。
   - 也可能是:反思 / 决策思路 / 关系(家人 / 朋友) / 长期目标对齐。
   - 只挑最显眼的一类缺失,说"我注意到今天/最近 schedule 里几乎没有 X,
     这个对你来说重要"。
6. **tomorrow_question** 必须具体可答(不是开放式哲学题)。
   **当身体维度信号稀薄时,优先问身体感受** — 目的是鼓励 user 把"身体
   感受"也作为一类合法 entry 写进 schedule。例:
   "今天下午 3 点写 pretext 时,肩膀的状态怎样? 明天起记一下。"
7. 写散文,不写条目列表。每段 2-4 句。

注意同样事情的提醒频率 — 一个主题如果你已反复点过 3 次(看 past_boards),
user 在 schedule 里仍没回应,继续点就是噪音,主动换维度问别的。

输入维度:
- today_entries / 7day_md / past_boards / project_pulse / project_todos

输出严格 JSON,无前后解释,无 markdown code fence,无 <think>:

{
  "encouragement":     "今天值得肯定的一件,带 cite + 为什么这是好信号。",
  "suggestion":        "战略顾问视角的建议,长期视角,1-2 句。",
  "what_missing":      "你读完一天,觉得这个 schedule 缺记了什么 — 优先身体维度。",
  "tomorrow_question": "一个具体可答的问题给明天的 user(身体维度稀薄时偏问身体)。",
  "_roles_used":       ["实际用到的角色:'mentor'/'friend'/'strategist' 任选 1-3 个"]
}

═══════════════════════════════════════════════════════════════════════════
"""


def _eval_load_past_boards(target: datetime, n: int = 7) -> str:
    """读过去 N 天的 eval-log markdown(不含 target 当天本身),拼成一段。
    用于注入 _eval_build_messages 的 payload — 让今晚的 eval AI 看到自己
    过去几晚说过什么,保持留言板的连贯性(不重复鼓励、跟进之前的 tomorrow_question)。
    """
    if not EVAL_LOG_DIR.exists():
        return "(没有历史 eval — 这是第一次)"
    target_str = target.strftime("%Y-%m-%d")
    files = sorted(EVAL_LOG_DIR.glob("????-??-??.md"))
    files = [f for f in files if f.stem < target_str][-n:]  # 严格小于 target,按日期升序取最近 N
    if not files:
        return "(target 之前没有历史 eval)"
    parts = []
    for f in files:
        try:
            parts.append(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return "\n\n---\n\n".join(parts) if parts else "(eval-log 读取失败)"


def _eval_build_messages(target: datetime, model_id: str = None) -> list:
    """构造给 LLM 的 messages。系统提示 = base co-writer + evaluator inject。
    user payload = 维度料。model_id 用于 prompt 里 {model_id} signature 占位符
    替换 — 让 AI 用自己的真实模型 id 署名。
    """
    from server import build_system_prompt, _compute_time_block_hint, find_today_journal
    base_sys = build_system_prompt({}, model_id=model_id)  # 保留原本身份
    # 5.31:eval 也注入 [time-block] + [schedule-voice],让 deepseek 写复盘 entry
    # 时遵守 § H5 voice baseline(否则就写函数名 / endpoint 那种 6 个月后看不懂的)
    time_hint = _compute_time_block_hint()
    sys_prompt = base_sys + "\n\n" + time_hint + "\n" + _EVAL_INJECTION

    today_f = find_today_journal(target)
    today_md = today_f.read_text(encoding="utf-8") if (today_f and today_f.exists()) else "(今天 md 不存在)"

    payload = (
        f"# 今天 ({target.strftime('%Y-%m-%d %A')}) 的 schedule md\n\n"
        f"{today_md}\n\n"
        f"# 近 7 天 schedule\n\n{_eval_load_recent_md(target, 7)}\n\n"
        f"# 过去 7 晚你(AI)给 user 的留言板原文 — 看完决定今晚说什么,"
        f"不要重复鼓励、可以跟进之前的 tomorrow_question 看 user 有没有回应\n\n"
        f"{_eval_load_past_boards(target, 7)}\n\n"
        f"# 项目 PULSE\n\n{_eval_load_pulse_all()}\n\n"
        f"# 项目 CLAUDE.md (待办 / Do not / Progress)\n\n{_eval_load_project_claude_md()}\n"
    )
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": payload},
    ]


_FEATURE_INTRO_PROMPT = """
你是 user 协作多日的 Gateway AI。每晚 21:30 eval 之后单独一次 call,**只看下面 signals + 候选清单**,挑一个 user 没用过但该试的 feature。

严格规则:
1. **优先 intro,不优先 null/图鉴满**。看 signals 找 unused-feature 强信号(数字明确 + 该用没用)就挑出最强一个。
2. **第一次跑(eval_runs_count == 0)** → 强制 intro daily eval 自介。
3. **图鉴满分支** — 如果 signals 显示所有候选 feature 都已经用过 / 配过(没一个 unused 强信号),**不要返 null**,而是返一条温柔鼓励 + 等下个版本的提示。一句话,诚恳,不要过度热情。例:
   ```
   {"name":"✨ 全图鉴解锁","one_liner":"你已经用过所有上线功能","why_now":"signals 里每条候选都有使用痕迹了,这是个里程碑 — 接下来等开发者更新。"}
   ```
4. **null 几乎用不到** — 只在 signals 完全读不到 / 系统状态扫描失败时返。
5. why_now **必须 cite signal 里的具体数字或事实**(e.g. "你 attachments 总数 32,从没用过 search_my_uploads")。**图鉴满分支例外**,可以说"所有候选都已用过"这种总结性描述。
6. 只挑一个,绝不挑多个。

严格 JSON,不要前后解释,不要 markdown fence,不要 <think>:

{
  "feature_intro": null 或 {
    "name": "...",
    "one_liner": "...",
    "why_now": "..."
  }
}
"""


def _eval_build_feature_intro_messages(target: datetime) -> list:
    """单独一次 call,只为 feature_intro。payload 极简:只 signals + 候选清单。"""
    signals = _eval_scan_feature_signals(target)
    payload = (
        f"# feature_signals(系统扫描,廉价文件/计数)\n\n"
        f"```json\n{json.dumps(signals, ensure_ascii=False, indent=2)}\n```\n\n"
        f"# feature_options(可 intro 的候选 + trigger 规则)\n"
        f"{_FEATURE_INTRO_OPTIONS}\n"
    )
    return [
        {"role": "system", "content": _FEATURE_INTRO_PROMPT},
        {"role": "user",   "content": payload},
    ]


# ─── eval 持久化 + 通知 ────────────────────────────────────────────

def _eval_persist(target: datetime, parsed: dict) -> Path:
    """落到 ~/.human-ai/data/eval-log/YYYY-MM-DD.md (rendered md,人可读)。
    NOT 进 vault — vault-reading AI 永远看不到。
    """
    from server import _safe_write_text
    EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = EVAL_LOG_DIR / f"{target.strftime('%Y-%m-%d')}.md"

    enc  = (parsed.get("encouragement")     or "").strip()
    sug  = (parsed.get("suggestion")        or "").strip()
    miss = (parsed.get("what_missing")      or "").strip()
    q    = (parsed.get("tomorrow_question") or "").strip()
    fi   = parsed.get("feature_intro")

    lines = [
        f"# Daily Eval — {target.strftime('%Y-%m-%d %A')}",
        f"_generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "## 🌱 今天值得肯定",
        enc or "_(empty)_",
        "",
        "## 🧭 战略建议",
        sug or "_(empty)_",
        "",
        "## 🪟 schedule 还缺什么",
        miss or "_(empty)_",
        "",
        "## ❓ 明天的问题",
        q or "_(empty)_",
    ]
    if fi:
        lines += [
            "",
            f"## ✨ {fi.get('name','')}",
            f"**{fi.get('one_liner','')}**",
            "",
            fi.get('why_now', ''),
        ]
    _safe_write_text(f, "\n".join(lines), rotate=True)
    return f


def _eval_notify(target: datetime, parsed: dict):
    """macOS 通知。osascript 内置,无需 install。失败静默。"""
    from server import log, _report_silent_failure
    if not parsed:
        return
    enc = (parsed.get("encouragement") or "").strip()
    # 截短到通知 banner 合理长度
    body = (enc[:120] + "…") if len(enc) > 120 else enc
    title = f"今晚复盘 · {target.strftime('%m-%d')}"
    body_e = body.replace('"', '\\"').replace("\n", " ").replace("\\", "\\\\")
    title_e = title.replace('"', '\\"')
    script = f'display notification "{body_e}" with title "{title_e}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, check=False)
    except Exception as e:
        log.warning(f"eval notify failed: {e}")
        # 用户没听见 banner 会以为 21:30 eval 没跑 — UX silent miss
        _report_silent_failure("eval_notify_failed",
            f"{type(e).__name__}: {str(e)[:120]}")


# 复用 compression hook —— 暂时 stub,evaluator memory-isolated 时用不到。
# 未来"周复盘 / 月趋势"模式想读过去 N 天 eval 摘要时,call 这个函数:
#   recent_summary = _eval_compress_past_logs(days=30, client, model)
# 内部跑 _summarize_history,沿用 chat 的同款 sliding-window pattern。
def _eval_compress_past_logs(days: int, client, model: str) -> str:
    """读 past N 天 eval-log,超 RECENT_KEEP 的旧条目用 _summarize_history 压。
    现在不调用,留接口给未来 trend-detection 用。
    """
    from server import RECENT_KEEP, _summarize_history
    if not EVAL_LOG_DIR.exists():
        return ""
    files = sorted(EVAL_LOG_DIR.glob("*.md"))[-days:]
    if not files:
        return ""
    msgs = []
    for f in files:
        try:
            msgs.append({"role": "assistant", "content": f.read_text(encoding="utf-8")})
        except Exception:
            continue
    if len(msgs) <= RECENT_KEEP:
        return "\n\n---\n\n".join(m["content"] for m in msgs)
    old = msgs[:-RECENT_KEEP]
    recent = msgs[-RECENT_KEEP:]
    summary = _summarize_history(old, client, model)
    parts = []
    if summary:
        parts.append(f"=== past {len(old)} evals compressed ===\n{summary}")
    parts.append("=== recent evals raw ===")
    parts.extend(m["content"] for m in recent)
    return "\n\n---\n\n".join(parts)
