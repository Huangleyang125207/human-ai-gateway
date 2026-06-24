"""board_routes — APIRouter for /api/eval/* (留言板 / daily eval).

Extract Module(ctrl-c-v § 9):eval/留言板 4 endpoint 从 server.py 抽出。
核心簇拆分 target 3(desktop-only,不在移动 shim)。纯 handler 搬迁 —— 所有 _eval_*
helper + EVAL_LOG_DIR 早已在 pulse_eval.py(server 顶部 re-export),本模块全走
function-body lazy `from server import` 拉回(含 re-export 的 pulse_eval 符号)。

留 server/pulse_eval(lazy import):
- _eval_build_messages(★past_boards 跨夜注入在这里)/ _eval_build_feature_intro_messages
  / _eval_persist / _eval_notify / _classify_eval_err / EVAL_LOG_DIR(pulse_eval)
- get_profile / get_client / get_model(LLM core)/ _report_silent_failure / find_today_journal

HTTP-only,零直接调用方 → 不 re-export。
characterization:tests/test_board_routes.py(11)。
"""
import asyncio
import json
import re

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["board"])


# ── GET /api/eval/list ───────────────────────────────────────────────
@router.get("/api/eval/list")
def eval_list(n: int = 14, include_missing: bool = False):
    """返最近 N 天的 eval 复盘原文(按日期降序),给留言板做垂直 stack 渲染。
    item: {date, is_today, markdown}。没记录返 {items: []}。

    include_missing=True 时,若**昨天**没 eval md 但有 schedule md,追一条
    {date, is_today: false, missing: true, markdown: null} 让 UI 渲染"补跑"卡片。
    窗口故意窄:只昨天 — cron 偶尔挂(app 没启动)是常见原因,补当天意义清晰;
    再往前拉数据陈旧、AI 生成质量也差。
    """
    from server import EVAL_LOG_DIR, datetime, timedelta, find_today_journal
    if not EVAL_LOG_DIR.exists() and not include_missing:
        return {"items": []}
    n = max(1, min(60, int(n)))  # clamp 防滥用
    today_str = datetime.now().strftime("%Y-%m-%d")
    files = (sorted(EVAL_LOG_DIR.glob("????-??-??.md"), key=lambda p: p.name, reverse=True)[:n]
             if EVAL_LOG_DIR.exists() else [])
    items = []
    for f in files:
        try:
            items.append({
                "date": f.stem,
                "is_today": f.stem == today_str,
                "markdown": f.read_text(encoding="utf-8"),
            })
        except Exception:
            continue
    if include_missing:
        # 只查昨天是否缺。日期降序,所以塞到合适位置。
        y_dt = datetime.now() - timedelta(days=1)
        y_str = y_dt.strftime("%Y-%m-%d")
        existing = {it["date"] for it in items}
        if y_str not in existing and find_today_journal(y_dt) is not None:
            items.append({
                "date": y_str,
                "is_today": False,
                "missing": True,
                "markdown": None,
            })
            items.sort(key=lambda x: x["date"], reverse=True)
    return {"items": items}


# ── GET /api/eval/today ──────────────────────────────────────────────
@router.get("/api/eval/today")
def eval_today():
    """返今天(或最近一次)的 eval 复盘原文。
    用于侧边「留言板」tab 渲染:AI 给用户的今晚复盘卡片。
    """
    from server import EVAL_LOG_DIR, datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_f = EVAL_LOG_DIR / f"{today_str}.md"
    if today_f.exists():
        return {
            "date": today_str,
            "is_today": True,
            "markdown": today_f.read_text(encoding="utf-8"),
        }
    # 没今天 → 找最近一份
    if EVAL_LOG_DIR.exists():
        candidates = sorted(
            EVAL_LOG_DIR.glob("????-??-??.md"),
            key=lambda p: p.name, reverse=True,
        )
        if candidates:
            f = candidates[0]
            return {
                "date": f.stem,
                "is_today": False,
                "markdown": f.read_text(encoding="utf-8"),
            }
    return {"date": None, "is_today": False, "markdown": None}


# ── POST /api/eval/test — 测试端点(不持久化)────────────────────────
@router.post("/api/eval/test")
async def eval_test(req: Request):
    """daily eval 测试端点。
    body: {date?: "YYYY-MM-DD" (默认今天), model_id?: int}
    NOT persisted — 只返回给 caller 看效果。生产版另起 endpoint 负责 push + log。
    """
    from server import (datetime, get_profile, get_client, get_model, _classify_eval_err,
                        _report_silent_failure, _eval_build_messages,
                        _eval_build_feature_intro_messages, log)
    body = await req.json()
    date_str = (body.get("date") or "").strip()
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_str}")
    else:
        target = datetime.now()

    model_id = body.get("model_id")
    profile = get_profile(model_id)
    client = get_client(profile)
    if client is None:
        raise HTTPException(503, "API client not configured")
    active_model = get_model(profile)

    async def _call_json(messages):
        """同款 try/fallback 包装。返 (raw_text, parsed_or_none)。
        sync OpenAI 调用丢 threadpool 防阻塞 event loop(详 /api/eval/run 处注释)。
        workflow B #2 闭合:第一次异常按子类型分桶(auth/quota/timeout/format),
        不再无差别打成 `eval_response_format_unsupported` 让运维误判。第二次 fallback
        也包 try/except,失败时返 (None, None) 让上层 graceful。"""
        def _blocking():
            try:
                return client.chat.completions.create(
                    model=active_model, messages=messages,
                    response_format={"type": "json_object"},
                    timeout=90,
                )
            except Exception as e:
                err_type = _classify_eval_err(e)
                log.info(f"eval call_1 失败 ({err_type}: {e}), 重试 fallback")
                _report_silent_failure(err_type,
                    f"{type(e).__name__}: {str(e)[:120]}",
                    context={"model": active_model, "phase": "test_call_1"})
                try:
                    return client.chat.completions.create(
                        model=active_model, messages=messages, timeout=90)
                except Exception as e2:
                    _report_silent_failure("eval_fallback_call_failed",
                        f"{type(e2).__name__}: {str(e2)[:120]}",
                        context={"model": active_model, "phase": "test_call_2"})
                    raise
        r = await asyncio.to_thread(_blocking)
        text = (r.choices[0].message.content or "").strip()
        # 容忍 <think>...</think> 和 ```json fence
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        cleaned = re.sub(r"^```(json)?\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
        try:
            return text, json.loads(cleaned)
        except Exception as e:
            # 留言板会落 _(empty)_ 卡 — 用户次晨看 AI"啥都没说"。最高 UX 影响。
            # 不送 text 原文 — 它是 LLM 对 user 日记的评议,属 consent.js 承诺
            # "不收集对话记录"范围。只送长度元数据够定位"空/短/长非 JSON"。
            _report_silent_failure("eval_json_parse_failed",
                f"{type(e).__name__}: {str(e)[:80]}",
                context={"model": active_model,
                         "text_len": len(text or ""),
                         "cleaned_len": len(cleaned or "")})
            return text, None

    # call 1: 主 eval
    eval_raw, eval_parsed = await _call_json(_eval_build_messages(target, model_id=active_model))

    # call 2: feature_intro 单独
    fi_raw, fi_parsed = await _call_json(_eval_build_feature_intro_messages(target))

    # merge: eval_parsed 加 feature_intro 字段
    merged = dict(eval_parsed) if eval_parsed else {}
    if fi_parsed and "feature_intro" in fi_parsed:
        merged["feature_intro"] = fi_parsed["feature_intro"]
    else:
        merged["feature_intro"] = None  # call 2 解析失败也填 null

    return {
        "ok": True,
        "model": active_model,
        "target_date": target.strftime("%Y-%m-%d"),
        "parsed": merged,
        "raw_eval": eval_raw,
        "raw_feature_intro": fi_raw,
    }


# ── POST /api/eval/run — 生产端(持久化 + 通知)──────────────────────
@router.post("/api/eval/run")
async def eval_run(req: Request):
    """生产端 — 同 /api/eval/test 跑 2-call,但持久化 + 触发 macOS 通知。
    body: {date?, model_id?}
    """
    from server import (datetime, get_profile, get_client, get_model, _classify_eval_err,
                        _report_silent_failure, _eval_build_messages,
                        _eval_build_feature_intro_messages, _eval_persist, _eval_notify, log)
    body = await req.json() if (await req.body()) else {}
    date_str = (body.get("date") or "").strip()
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_str}")
    else:
        target = datetime.now()

    model_id = body.get("model_id")
    profile = get_profile(model_id)
    client = get_client(profile)
    if client is None:
        raise HTTPException(503, "API client not configured")
    active_model = get_model(profile)

    async def _call_json(messages):
        # OpenAI SDK 是 sync 的,直接调会阻塞 event loop —— 21:30 eval 跑的时候
        # 整个 server 60-120s 失联(包括 chat endpoint),就是这个锅。丢 threadpool。
        # workflow B #2 闭合:同上 — 异常分桶 + fallback 也包 try。
        def _blocking():
            try:
                return client.chat.completions.create(
                    model=active_model, messages=messages,
                    response_format={"type": "json_object"},
                    timeout=90)
            except Exception as e:
                err_type = _classify_eval_err(e)
                log.info(f"eval call_1 失败 ({err_type}: {e}), 重试 fallback")
                _report_silent_failure(err_type,
                    f"{type(e).__name__}: {str(e)[:120]}",
                    context={"model": active_model, "phase": "run_call_1"})
                try:
                    return client.chat.completions.create(
                        model=active_model, messages=messages, timeout=90)
                except Exception as e2:
                    _report_silent_failure("eval_fallback_call_failed",
                        f"{type(e2).__name__}: {str(e2)[:120]}",
                        context={"model": active_model, "phase": "run_call_2"})
                    raise
        r = await asyncio.to_thread(_blocking)
        text = (r.choices[0].message.content or "").strip()
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        cleaned = re.sub(r"^```(json)?\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
        try:
            return text, json.loads(cleaned)
        except Exception as e:
            # 不送 text 原文 — 它是 LLM 对 user 日记的评议,属 consent.js 承诺
            # "不收集对话记录"范围。只送长度元数据够定位"空/短/长非 JSON"。
            _report_silent_failure("eval_json_parse_failed",
                f"{type(e).__name__}: {str(e)[:80]}",
                context={"model": active_model,
                         "text_len": len(text or ""),
                         "cleaned_len": len(cleaned or "")})
            return text, None

    eval_raw, eval_parsed = await _call_json(_eval_build_messages(target, model_id=active_model))
    fi_raw, fi_parsed = await _call_json(_eval_build_feature_intro_messages(target))

    merged = dict(eval_parsed) if eval_parsed else {}
    if fi_parsed and "feature_intro" in fi_parsed:
        merged["feature_intro"] = fi_parsed["feature_intro"]
    else:
        merged["feature_intro"] = None

    persisted = _eval_persist(target, merged)
    _eval_notify(target, merged)

    return {
        "ok": True,
        "model": active_model,
        "target_date": target.strftime("%Y-%m-%d"),
        "persisted_to": str(persisted),
        "parsed": merged,
        # 诊断用:eval_parse_ok = False 说明主调用返了 LLM 的话但 JSON parse 失败 / 没匹配 schema
        "eval_parse_ok": bool(eval_parsed),
        "raw_eval_preview": (eval_raw or "")[:600],
    }
