"""chat_routes — APIRouter for /api/chat + /api/chat/upload-image (LLM 对话引擎).

Extract Module(ctrl-c-v § 9):本 session 最高风险抽取(extract-with-caveats)。chat 编排器 +
流式 chokepoint 从 server.py 搬出 —— DSML 泄漏闸 / SSE 契约 / 可变状态 / claim 审计这些
Cannot-break 代码随之搬来,15 条 characterization(test_chat_routes.py)守红线。

留 server.py(lazy from server import):_dispatch_tool/_active_tools/_initial_groups/TOOL_IMPL 等
tool 引擎(reaches authorship 核心,绝不搬)、build_system_prompt、get_client/profile/model、LLM core、
attachments 索引簇、vision/ocr。re-export:_audit_unauthorized_claim(test_claim_audit 直调)。
DSML 正则字节脆弱(U+FF5C)→ 本文件由 server.py 源码逐字提取,非手抄。lazy import 经 AST 精确探测。
"""
import asyncio
import hashlib
import json
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(tags=["chat"])

# history 里 thread.js 把 ref 拼成 `[image] filename`(或其他 kind),抓 image 那条
_HISTORY_IMG_LABEL_RE = re.compile(r'\[image\]\s+([^\n]+?)(?=\n|$)')

def _trim_history_tool_volume(history: list, max_tool_chars: int) -> list:
    """从最早往后,把超过 max_tool_chars 总量的 tool result 段砍掉。
    被砍的 tool 同步去掉它对应 assistant.tool_calls 里的条目 (避免 schema 孤儿)。
    """
    # 1. 统计所有 tool 段总字符
    total = sum(len(m.get("content") or "") for m in history if m.get("role") == "tool")
    if total <= max_tool_chars:
        return history
    # 2. 从前往后扫,把 tool 段标记为待删,直到剩余总量 <= cap
    overflow = total - max_tool_chars
    dropped_tool_ids: set = set()
    out = []
    for m in history:
        if m.get("role") == "tool" and overflow > 0:
            tcid = m.get("tool_call_id") or ""
            overflow -= len(m.get("content") or "")
            dropped_tool_ids.add(tcid)
            continue   # 丢这条 tool
        out.append(m)
    # 3. 扫所有 assistant.tool_calls,去掉孤儿条目;若整 assistant 的 tool_calls 全孤儿,
    #    保留 content 但删 tool_calls 字段(变成普通文字回复)
    final = []
    for m in out:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            kept = [tc for tc in m["tool_calls"] if (tc.get("id") or "") not in dropped_tool_ids]
            if kept:
                final.append({**m, "tool_calls": kept})
            else:
                # 全部 tool 段被砍了,这条 assistant 也去掉 tool_calls
                stripped = {k: v for k, v in m.items() if k != "tool_calls"}
                # 文本空且无 tool_calls = 没价值,跳过
                if (stripped.get("content") or "").strip():
                    final.append(stripped)
        else:
            final.append(m)
    return final

def _enrich_history_image_labels(history: list) -> list:
    from server import _load_attachments_index
    """history 里 thread.js 把图 ref 拼成 `[image] filename.jpg`,但 AI 视角下
    filename 通常是 hash(如 `54cacfb2c68036b56b26.jpg`)— 看不出内容,
    回头引用之前上传过的图时容易凭空捏造话题(5.20 长鑫存储被答成 HK 虚拟货币 = 这条 bug)。

    本函数在 server 端拼 LLM prompt 前,把每条 history 里的 `[image] X` 替换成:
        [image] X (kind: description) OCR 前 120 字: ...
    数据来自 _attachments_index 的 cache,零额外 LLM 调用。cache miss 时 label 不变。
    """
    if not history:
        return history
    idx = _load_attachments_index()
    by_original = {x.get("original"): x for x in idx if x.get("original")}
    by_filename = {x.get("filename"): x for x in idx if x.get("filename")}

    def _lookup(label: str) -> str:
        entry = by_original.get(label) or by_filename.get(label)
        if not entry:
            return f"[image] {label}"
        vision = entry.get("vision") or {}
        kind = vision.get("kind")
        desc = vision.get("description", "")
        ocr = (entry.get("ocr_text") or "")[:120].replace("\n", " ").strip()
        bits = [f"[image] {label}"]
        if kind and desc:
            bits.append(f"({kind}: {desc})")
        elif desc:
            bits.append(f"({desc})")
        if ocr:
            bits.append(f"OCR前 120 字: {ocr}")
        return "  ".join(bits)

    out = []
    for m in history:
        content = m.get("content")
        if isinstance(content, str) and "[image]" in content:
            new_content = _HISTORY_IMG_LABEL_RE.sub(
                lambda mt: _lookup(mt.group(1).strip()), content
            )
            out.append({**m, "content": new_content})
        else:
            out.append(m)
    return out

def _refs_to_image_blocks(refs):
    from server import ATTACHMENTS_DIR, _ocr_text
    """从 context.refs 抽 image,跑 OCR,返回 [{filename, ocr_text}] 列表。
    上层把这个嵌进 user message 文本里给 LLM。
    走 _ocr_text 统一出口(端侧优先,baidu 兜底)。
    """
    out = []
    for r in refs or []:
        if r.get("kind") != "image":
            continue
        url = (r.get("payload") or {}).get("url") or ""
        m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
        if not m:
            continue
        f = ATTACHMENTS_DIR / m.group(1) / m.group(2)
        if not f.exists():
            continue
        out.append({
            "filename": (r.get("payload") or {}).get("original") or f.name,
            "ocr_text": _ocr_text(f),
        })
    return out

def _refs_to_vision_hints(refs):
    from server import ATTACHMENTS_DIR, _index_upsert, _load_attachments_index, _qwen_classify_image, _report_silent_failure, log
    """upload-side vision router 的第二步:
    chat 收到 image refs 时,从索引拿 cache vision 结果;cache miss / vision 空 → 现场 sync
    call 一次 qwen-vl 补上,并回写索引(下次 hit)。
    返 [{filename, url, vision_dict}],上层拼成 hint 注入 user message。
    """
    out = []
    idx = _load_attachments_index()
    by_url = {x.get("url"): x for x in idx if x.get("url")}
    for r in refs or []:
        if r.get("kind") != "image":
            continue
        url = (r.get("payload") or {}).get("url") or ""
        m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
        if not m:
            continue
        f = ATTACHMENTS_DIR / m.group(1) / m.group(2)
        if not f.exists():
            continue
        entry = by_url.get(url)
        vision = (entry or {}).get("vision") or {}
        # cache miss(没索引 或 vision 字段空)→ 现场补 + upsert 回索引
        # 用 upsert 而非直接 mutate+save,避免和后台 OCR task 互相 read-modify-write
        # 覆盖对方的字段(原来的 bug:OCR 跑得慢,等它写完时把 vision 冲了)
        if not vision:
            try:
                vc = _qwen_classify_image(f)
                if isinstance(vc, dict) and not vc.get("error"):
                    vision = vc
                    _index_upsert(
                        m.group(1), m.group(2),
                        vision=vision,
                        url=url,
                        original=(r.get("payload") or {}).get("original") or m.group(2),
                        size=f.stat().st_size,
                    )
            except Exception as e:
                log.warning(f"sync vision failed for {url}: {e}")
                # vision call 抛 — 不只是返 error,是裸异常逃出。
                # _qwen_classify_image 内部已 hook 各类 return error,这一条
                # 抓的是 import 失败 / SDK 崩 / cache lock 异常这种。
                _report_silent_failure("vision_hint_inline_exception",
                    f"{type(e).__name__}: {str(e)[:120]}",
                    context={"url": url[-40:] if url else ""})
        if vision:
            # 用户 chip 上的"抠/原"开关传过来的偏好(default true)
            cutout_pref = (r.get("payload") or {}).get("cutout")
            if cutout_pref is None:
                cutout_pref = True
            out.append({
                "filename": (r.get("payload") or {}).get("original") or f.name,
                "url": url,
                "vision": vision,
                "user_cutout_pref": bool(cutout_pref),
            })
    return out

# ── chat SSE streaming generator ────────────────────────────────────
# 事件类型:
#   {"type":"action","name":"...","args":{...},"result":{...}}  — 工具执行完
#   {"type":"delta","text":"..."}                                — 文本片段
#   {"type":"done","actions":[...]}                              — 收尾
#   {"type":"error","text":"..."}                                — 异常
def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

# ── synthetic-tool-call fallback ────────────────────────────────────
# 目击于 deepseek-v4-pro:模型把 tool 调用当 content 文本吐,不用 OpenAI 的
# tool_calls 字段。格式 mimic Claude 的 antml,但带 ｜｜DSML｜｜ 命名空间
# (｜ = U+FF5C 全角竖线,见过 1-2 个;偶尔也见纯 ASCII | 或省略 DSML)。
# 不解析的话前端会看见 <｜｜DSML｜｜tool_calls>...</> 这一坨原文,journal 也没落。
_DSML_NS = r'<[｜|]{1,2}(?:DSML[｜|]{1,2})?'
_SYNTH_INVOKE_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}invoke\s+name="([^"]+)"\s*>(.*?)</[｜|]{1,2}DSML[｜|]{1,2}invoke>',
    re.DOTALL,
)
_SYNTH_PARAM_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}parameter\s+name="([^"]+)"[^>]*>(.*?)</[｜|]{1,2}DSML[｜|]{1,2}parameter>',
    re.DOTALL,
)
_SYNTH_WRAPPER_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}tool_calls>.*?</[｜|]{1,2}DSML[｜|]{1,2}tool_calls>',
    re.DOTALL,
)
# orphan 兜底:wrapper 缺失时单独的 <invoke>...</invoke> 整块剥掉
_SYNTH_INVOKE_STRIP_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}invoke[^>]*?>.*?</[｜|]{1,2}DSML[｜|]{1,2}invoke>',
    re.DOTALL,
)
# 最后一道防线:任何残留的 <｜｜DSML｜｜foo> 或 </｜｜DSML｜｜foo> 孤立标签
_DSML_TAG_RE = re.compile(r'</?[｜|]{1,2}DSML[｜|]{1,2}[^>]*?>', re.DOTALL)

def _extract_synthetic_tool_calls(content: str):
    """提 content 里 Claude-antml 风格的伪 tool_calls。
    返回 (stripped_content, [{"id","name","args"}])。无匹配则 (content, [])。

    3 层清理:
      1) 先抠 invoke 块得 calls
      2) wrapper / invoke / 任何 DSML 残留标签全 strip
      3) 即使 calls 为空,只要原文含 DSML 残骸也清掉(防 5.22 msg 9 那种漏)
    """
    if not content or "DSML" not in content:
        return content, []
    calls = []
    for m in _SYNTH_INVOKE_RE.finditer(content):
        name = m.group(1).strip()
        body = m.group(2)
        args = {pm.group(1).strip(): pm.group(2).strip()
                for pm in _SYNTH_PARAM_RE.finditer(body)}
        calls.append({
            "id": f"call_synth_{secrets.token_hex(12)}",
            "name": name,
            "args": args,
        })
    # 即使没抠到 calls 也做清理 — 防 regex 没认出的变体把原文 DSML 漏到 history
    stripped = _SYNTH_WRAPPER_RE.sub("", content)
    stripped = _SYNTH_INVOKE_STRIP_RE.sub("", stripped)
    stripped = _DSML_TAG_RE.sub("", stripped).strip()
    return stripped, calls

def _exec_synth_calls(synth_calls, messages, last_actions, loaded_groups, quota_used):
    from server import _dispatch_tool
    """执行 synth_calls,把 tool result 写进 messages + last_actions。"""
    for c in synth_calls:
        result = _dispatch_tool(c["name"], c["args"], loaded_groups, quota_used)
        last_actions.append({"id": c["id"], "name": c["name"], "args": c["args"], "result": result})
        messages.append({
            "role": "tool",
            "tool_call_id": c["id"],
            "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
        })

# ── claim audit(Path X:防 AI 口头声称已写入但没真 tool call)─────────
# 5.22 msg 5/7 事故:用户"帮我记一下" → AI 回"记进 17:30 了" → last_actions 空,
# journal 文件没动。CC 的解法是 tool_use 结构化 block(说=做绑死);
# 我们用 server 出口审计:claim 措辞 + actions 空 → 自动加 disclaimer,
# 用户看到这条就知道"AI 在撒谎"。
_CLAIM_PHRASE_RE = re.compile(
    r'(记进|写进|搞定|已写[入好]|已加入|已添加|已保存|已记录|已贴|已落|已 ?patch|'
    r'写好了|写完了|加好了|加完了|落进|saved|recorded|wrote|patched|done)',
    re.IGNORECASE,
)
_CLAIM_DISCLAIMER = (
    "\n\n*(server audit:本回合未触发任何 tool 调用,上面的「已写入/记进了」等措辞"
    "未对应真实动作 — 日记 / 聚合页没改。要真落请说『重试』或换一句指令。)*"
)

def _audit_unauthorized_claim(content: str, actions: list) -> str:
    if actions or not content:
        return content
    if not _CLAIM_PHRASE_RE.search(content):
        return content
    return content + _CLAIM_DISCLAIMER

# tool result 上限:multi-round 时同一 result 跨轮重发,大 JSON 会把 token 拉爆。
# 3000 char ≈ 1500 token,普通 read 类够用;真要全文 model 可再调一次同 tool。
_TOOL_RESULT_CAP = 5000

def _truncate_tool_result(content: str) -> str:
    if len(content) <= _TOOL_RESULT_CAP:
        return content
    keep = content[:_TOOL_RESULT_CAP]
    omitted = len(content) - _TOOL_RESULT_CAP
    return f"{keep}\n…(truncated, {omitted} chars omitted; re-call tool with narrower args if needed)"

def _stream_final_reply(client, active_model, messages, loaded_groups, quota_used, last_actions):
    from server import _dispatch_tool, _report_silent_failure
    """单一 chokepoint:流式产出最终回复 + done。**所有**流给前端的模型文本都过这。

    内建 DSML 防漏:任一轮 stream 里冒出 ｜｜DSML 假 tool-call,一律 suppress
    (绝不把 raw DSML yield 给前端)→ extract → execute → 继续下一轮 stream 让模型
    看到 tool result 补回复。循环到拿干净文本 / DSML 抠不出 / 撞迭代上限为止。

    取代旧的两处裸奔 stream 出口(last-round bonus + 模型不要 tool 的重流)——它们
    各自 yield delta.content 无检测,是 DSML 泄漏进聊天的真因(5.27)。
    """
    LOOKAHEAD = 8          # 末尾留 8 char 等 ｜｜DSML 完整出现再判,防 marker 被切两半漏出
    MAX_DSML_ITERS = 4     # DSML→执行→又 DSML 的循环上限,防死循环
    reasoning_buf = ""
    last_buffer = ""
    emitted = False
    hit_cap = True         # for 正常 break 会置 False;跑满循环没 break = 撞上限

    for _it in range(MAX_DSML_ITERS):
        # ping 保活:thinking 模式下首个 delta 可能要等几十秒,客户端 90s 没字节就 abort
        yield _sse({"type": "ping"})
        try:
            stream_resp = client.chat.completions.create(
                model=active_model, messages=messages, stream=True,
            )
        except Exception as e:
            yield _sse({"type": "error", "text": f"{type(e).__name__}: {str(e)[:300]}"})
            # #1 用户功能:聊天 LLM 初始调用失败(网络/quota/auth)— 高频且现在只吐 UI 不上报
            _report_silent_failure("chat_llm_call_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={"model": active_model, "phase": "stream_start"})
            return

        buffer = ""
        yielded_len = 0
        suppress = False
        # workflow B #1 闭合:chunk 迭代裸奔会被 httpx 层的 ReadTimeout / RemoteProtocolError /
        # ChunkedEncodingError 撕断 generator,FastAPI 把 SSE 流关闭但不发 error 事件,前端干等到
        # 90s timer 才 abort。包 try/except → 发 error 事件 + 报 silent-failure 分桶。
        try:
            for chunk in stream_resp:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                if not delta: continue
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf += rc
                if not delta.content: continue
                buffer += delta.content
                if suppress: continue
                if "｜｜DSML" in buffer or "<function_calls" in buffer:
                    suppress = True
                    continue
                safe_end = max(yielded_len, len(buffer) - LOOKAHEAD)
                if safe_end > yielded_len:
                    text = buffer[yielded_len:safe_end]
                    yielded_len = safe_end
                    emitted = True
                    yield _sse({"type": "delta", "text": text})
        except Exception as e:
            err_msg = f"stream torn: {type(e).__name__}: {str(e)[:200]}"
            yield _sse({"type": "error", "text": err_msg})
            _report_silent_failure("chat_stream_torn_down",
                str(e)[:150],
                context={"model": active_model, "emitted_chars": yielded_len,
                         "buffer_chars": len(buffer)})
            return
        last_buffer = buffer

        if not suppress:
            # 无 DSML — flush 末尾 lookahead 留的尾巴,完成
            if yielded_len < len(buffer):
                tail = buffer[yielded_len:]
                if tail:
                    emitted = True
                    yield _sse({"type": "delta", "text": tail})
            hit_cap = False
            break

        # suppress:buffer 含 DSML → 抠 call
        stripped, synth_calls = _extract_synthetic_tool_calls(buffer)
        if not synth_calls:
            # 抠不出(畸形/变体 DSML)→ 至少 yield 清理后的干净文本,**绝不漏 raw DSML**
            if stripped:
                emitted = True
                yield _sse({"type": "delta", "text": stripped})
            hit_cap = False
            break

        # 有 call:登记 asst + 执行(yield action)+ 写 tool result → 下一轮 stream 补回复
        asst_msg = {"role": "assistant", "content": stripped,
                    "tool_calls": [{
                        "id": c["id"], "type": "function",
                        "function": {"name": c["name"],
                                     "arguments": json.dumps(c["args"], ensure_ascii=False)},
                    } for c in synth_calls]}
        if reasoning_buf:
            asst_msg["reasoning_content"] = reasoning_buf
        messages.append(asst_msg)
        for c in synth_calls:
            result = _dispatch_tool(c["name"], c["args"], loaded_groups, quota_used)
            last_actions.append({"id": c["id"], "name": c["name"], "args": c["args"], "result": result})
            yield _sse({"type": "action", "id": c["id"], "name": c["name"], "args": c["args"], "result": result})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False))})
        # 继续循环 → 下一轮 stream

    if hit_cap and last_actions:
        names = ", ".join(a.get("name", "?") for a in last_actions)
        yield _sse({"type": "delta", "text": f"✓ 完成: {names}（工具调用上限,已停止再调）"})
        emitted = True

    # 收尾:fallback + claim audit + done(跟旧两处出口一致)
    if not emitted and last_actions:
        names = ", ".join(a.get("name", "?") for a in last_actions)
        yield _sse({"type": "delta", "text": f"✓ 完成: {names}"})
    if not last_actions and last_buffer and _CLAIM_PHRASE_RE.search(last_buffer):
        yield _sse({"type": "delta", "text": _CLAIM_DISCLAIMER})
    done_payload = {"type": "done", "actions": last_actions, "model_id": active_model}
    if reasoning_buf:
        done_payload["reasoning_content"] = reasoning_buf
    yield _sse(done_payload)

def _chat_stream_generator(client, active_model, messages, loaded_groups, quota_used):
    from server import _active_tools, _dispatch_tool, _log_cache_usage, _report_silent_failure
    """跑跟非 stream 一样的 tool loop,但最后一轮(无 tool_calls 那一次)
    用 stream=True 把 text 一段段 yield 出去。tool 调用之间 yield action 事件。
    active_tools 每轮重算(load_tool_group 可能改 loaded_groups)。
    所有流式文本出口统一走 _stream_final_reply(单一 chokepoint,DSML 防漏)。
    """
    last_actions = []
    MAX_ROUNDS = 10
    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)
        # 非最后轮:先非 stream 让模型决定要不要 tool。
        # 最后一轮:不再给 tool,模型必须出文本收尾 —— 统一走 chokepoint 流(内建 DSML 防漏)。
        if is_last_round:
            yield from _stream_final_reply(client, active_model, messages, loaded_groups, quota_used, last_actions)
            return

        # tool round:非 stream;每轮重算 tools(load_tool_group 可能改 loaded_groups)
        # 先发个 SSE ping —— 客户端 90s 没新字节就 abort(thread.js:591);
        # 一个轮的 model 阻塞调用可能 30-60s,多轮串起来很容易撞 90s。
        # ping 给 client 一个 byte 重置那个 timer。客户端未知 type 静默忽略,安全。
        yield _sse({"type": "ping"})
        try:
            resp = client.chat.completions.create(
                model=active_model, messages=messages,
                tools=_active_tools(loaded_groups), tool_choice="auto",
            )
        except Exception as e:
            yield _sse({"type": "error", "text": f"{type(e).__name__}: {str(e)[:300]}"})
            _report_silent_failure("chat_llm_call_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={"model": active_model, "phase": "tool_loop"})
            return

        msg = resp.choices[0].message
        _log_cache_usage(resp, "chat/stream-tool-round")
        asst_msg = msg.model_dump(exclude_none=True)
        asst_msg["role"] = "assistant"
        if not msg.tool_calls:
            asst_msg.pop("tool_calls", None)
        if asst_msg.get("content") is None:
            asst_msg["content"] = ""

        # ── DSML fallback(同非 stream 路径)──
        synth_calls = []
        if not msg.tool_calls and asst_msg["content"]:
            asst_msg["content"], synth_calls = _extract_synthetic_tool_calls(asst_msg["content"])
            if synth_calls:
                asst_msg["tool_calls"] = [{
                    "id": c["id"], "type": "function",
                    "function": {"name": c["name"],
                                 "arguments": json.dumps(c["args"], ensure_ascii=False)},
                } for c in synth_calls]

        messages.append(asst_msg)

        if synth_calls:
            for c in synth_calls:
                result = _dispatch_tool(c["name"], c["args"], loaded_groups, quota_used)
                last_actions.append({"id": c["id"], "name": c["name"], "args": c["args"], "result": result})
                yield _sse({"type": "action", "id": c["id"], "name": c["name"], "args": c["args"], "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
                })
            continue  # 下一轮让 model 补 reply

        if not msg.tool_calls:
            # 模型不要 tool 了 — pop 出空 asst,改用 chokepoint 真流(内建 DSML 防漏:
            # 模型这轮若反悔又想调工具 → 吐 DSML 也不会裸漏给前端,会被抠出执行)
            messages.pop()
            yield from _stream_final_reply(client, active_model, messages, loaded_groups, quota_used, last_actions)
            return

        # 执行 tools,逐个 yield action 事件
        for tc in msg.tool_calls:
            if getattr(tc, "type", "function") != "function" or not getattr(tc, "function", None):
                continue
            fn = tc.function.name
            args = {}
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                pass
            result = _dispatch_tool(fn, args, loaded_groups, quota_used)
            action_payload = {"id": tc.id, "name": fn, "args": args, "result": result}
            last_actions.append(action_payload)
            yield _sse({"type": "action", **action_payload})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
            })

    # MAX_ROUNDS 用完都没出文本
    yield _sse({"type": "done", "actions": last_actions, "warning": "hit max rounds"})

@router.post("/api/chat/upload-image")
async def chat_upload_image(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    from server import ALLOWED_IMAGE_EXT, ATTACHMENTS_DIR, MAX_IMAGE_BYTES, _find_by_hash, _index_attachment, _index_upsert
    """侧栏拖图上传 — 存到 数据库/valut/attachments/YYYY-MM-DD/。

    返回 {url, filename, size}:
      - url: 用 /attachments/... 通过 GET /attachments/{date}/{name} 取
      - filename: 服务端生成的稳定文件名(原名 + 时间戳 hash 防碰)
    decision: 当前 LLM(deepseek-chat)无视觉,图本身 AI 看不到 — 只保留路径
    + 文件名,留作日记图文档案 + 给 AI 一个"知道你贴了图"的 reference。
    """
    if not file.filename:
        raise HTTPException(400, "no filename")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"unsupported ext '.{ext}'. allowed: {sorted(ALLOWED_IMAGE_EXT)}")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"file too large ({len(data)} bytes > {MAX_IMAGE_BYTES})")
    if len(data) == 0:
        raise HTTPException(400, "empty file")

    # sha256 去重:同字节图(用户重传 / vision-pre-router race / drag 重操作)直接复用既有
    # url + 跳过 OCR/vision call,既省空间也避免 curator 把同图返多次("找狗"返 5 张
    # 一模一样客厅照那条 5.16 bug 的根治)。
    sha = hashlib.sha256(data).hexdigest()
    existing = _find_by_hash(sha)
    if existing and existing.get("url"):
        return {
            "url": existing["url"],
            "filename": existing.get("filename", ""),
            "original": file.filename,
            "size": existing.get("size", len(data)),
            "deduped": True,
            "deduped_to": f"{existing.get('date','')}/{existing.get('filename','')}",
        }

    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = ATTACHMENTS_DIR / today
    day_dir.mkdir(parents=True, exist_ok=True)
    # 文件名:时间戳-rand.ext,保留原名做备注但不进路径(避免奇怪字符)
    stamp = datetime.now().strftime("%H%M%S")
    rand = secrets.token_hex(3)
    saved_name = f"{stamp}-{rand}.{ext}"
    (day_dir / saved_name).write_bytes(data)
    # 同步 upsert 最小 record(hash + url + size):防同字节连续 upload 的 race —
    # 不然 #2 在 #1 的后台 OCR 还没跑完时去 _find_by_hash 找不到东西就误判 新图。
    # OCR 仍走后台不阻塞响应。
    _index_upsert(
        today, saved_name,
        url=f"/attachments/{today}/{saved_name}",
        hash=sha,
        size=len(data),
        original=file.filename,
    )
    if background_tasks is not None:
        background_tasks.add_task(_index_attachment, today, saved_name, file.filename, len(data), sha)
    return {
        "url": f"/attachments/{today}/{saved_name}",
        "filename": saved_name,
        "original": file.filename,
        "size": len(data),
        "deduped": False,
    }

@router.post("/api/chat")
async def chat(req: Request):
    from server import _active_tools, _compute_time_block_hint, _dispatch_tool, _initial_groups, _log_cache_usage, _strip_ocr_from_history, _today_date_str, build_system_prompt, get_client, get_model, get_profile
    body = await req.json()
    context = body.get("context", {})
    user_msg = body.get("message", "")
    history = body.get("history", []) or []
    model_id = body.get("model_id")  # 前端 picker 选的 profile id
    stream_mode = bool(body.get("stream"))

    profile = get_profile(model_id)
    client = get_client(profile)
    if client is None:
        raise HTTPException(503, "API client not configured. See /api/config-status.")

    ctx_str = json.dumps(context, ensure_ascii=False, indent=2)
    time_hint = _compute_time_block_hint()
    # 用户当前浏览的日期(从 thread.js context.view_date 来)。fallback 到 today。
    # AI 落 scrapbook / patch_journal_block 默认必须用这一天 — 不是 today,
    # 不是 hint 里的"now"日期(可能 user 在历史天浏览,now 跟 view_date 不同)。
    view_date = (context or {}).get("view_date") or _today_date_str()
    view_date_hint = f"[view-date] 用户当前浏览: {view_date}(YYYY-MM-DD) — scrapbook / patch_journal_block 的 date 参数默认必传这个,不是 today。"

    # 先做 OCR + vision-pre-router,把结果 hoist 到 user_msg 之前
    # (原本拼在末尾,AI 读到用户那句"贴一下"先回复,常常跳过尾部 hint → 不调工具)
    ocr_results = _refs_to_image_blocks(context.get("refs", []))
    vision_hints = _refs_to_vision_hints(context.get("refs", []))

    pre_sections = []  # 拼在 user_msg 前面的工作流块

    if vision_hints:
        v_lines = ["<vision-pre-router 已分类 — 立即按 WORKFLOW 走,不要先回复用户文字>"]
        for h in vision_hints:
            v = h["vision"]
            kind = v.get("kind", "?")
            desc = v.get("description", "")
            brand = v.get("brand", "")
            suggested = v.get("suggested_action", "")
            ocr_likely = v.get("ocr_likely", False)
            pill_count = v.get("pill_count", 0)
            user_cut = h.get("user_cutout_pref", True)
            v_lines.append(
                f"图片 [{h['filename']}] ({h['url']}):\n"
                f"  · kind={kind} | 描述={desc} | 品牌={brand or '-'}\n"
                f"  · OCR有文字={ocr_likely} | 颗数={pill_count or '-'}\n"
                f"  · 建议下游路径: {suggested or '-'}\n"
                f"  · 用户抠图偏好: {'抠' if user_cut else '原图(用户已点开关 — cutout=false 必传)'}"
            )
        v_lines.append("</vision-pre-router 已分类>")
        v_lines.append(
            f"\nWORKFLOW(image + scrapbook 类 hint — 不再 pin-by-default,先判 user 意图):\n"
            f"\n"
            f"  STEP A · 判 pin 意图(从用户消息文字 + entry ref 两路看):\n"
            f"    explicit-pin   = 消息含 '贴/po/放/记下/留个底/上墙/钉/pin' 或 entry ref [date time] → 走 pin path\n"
            f"    explicit-discuss = 消息含 '看看/识别/这是/好不好/是啥/什么/帮我看/读一下/读下/ocr/认一下' → 走 discuss path\n"
            f"    ambiguous      = 无文字 / 含糊话(如 '哈哈'/'今天的'/'诶') / 讨论意图但没明确触发词 → 走 ask path\n"
            f"\n"
            f"  ── pin path ──\n"
            f"    通用图(scrapbook):\n"
            f"      1. 已有 vision hint — 不要再调 vision_classify\n"
            f"      2. 若消息已含 entry ref [date time] → 直接拿 anchor_time + date,跳到 4\n"
            f"      3. 否则: read_today_schedule(date='{view_date}') → 按 hint 描述匹配 entry → 拿 anchor_time\n"
            f"         匹配不出来才反问 '贴到哪段?'\n"
            f"      4. place_scrapbook_image(attachment_url=..., date='{view_date}',\n"
            f"         anchor_time='HH:MM', cutout=<按用户抠图偏好>)\n"
            f"      5. 一句话告诉用户贴到了哪段(例: '贴到 12:30 那条午饭旁边了')\n"
            f"    特例 · kind=doc + ocr_likely=true:\n"
            f"      用 patch_journal_block 把 OCR 文本写进当前块,**不调** place_scrapbook_image\n"
            f"      (pin 一份文档通常是想留文字版,不是留图)\n"
            f"\n"
            f"  ── discuss path ──\n"
            f"    通用图: 直接根据 hint 描述 + 用户问题回复,**不调** place_scrapbook_image。\n"
            f"            回复末尾可加一句 '想贴到日记上的话告诉我' — 留 escape hatch。\n"
            f"    特例 · kind=doc + ocr_likely=true:\n"
            f"      根据 <图片 OCR 识别结果> 段的文本总结/回答用户的问题,**不写入日记**。\n"
            f"      回复末尾加 '想把这段文字记到日记上的话告诉我' — escape hatch。\n"
            f"\n"
            f"  ── ask path ──\n"
            f"    通用图:\n"
            f"      1. 一句话描述你从 hint 看到的内容(例: '看到一份羊排紫米饭的午餐')\n"
            f"      2. 跟一句 '要贴到日记上吗?要的话我贴在 X 块旁边' — X 是按 hint 匹配的 entry\n"
            f"      3. **什么都不调**,等用户答\n"
            f"    特例 · kind=doc + ocr_likely=true:\n"
            f"      1. 一句话描述看到的文档(例: '看到一份戴尔财报截图')\n"
            f"      2. 跟一句 '要我读出内容跟你聊,还是直接贴到日记上?'\n"
            f"      3. **什么都不调**,等用户答\n"
            f"\n"
            f"  特殊类型分流(覆盖上面三 path):\n"
            f"    用户消息含'水杯/我的杯/喝水图标/这是我的水杯/打卡水杯' → DIY 水杯打卡图,一步:\n"
            f"      set_water_cup_image(attachment_url='...') — 直接调,不要先调 vision_classify。\n"
            f"      调完一句话回:'水杯设上了,8 杯水打卡区会用你这只杯' 之类。\n"
            f"\n"
            f"    kind=supplement → 这是补剂打卡,三步连做(别只设图不勾):\n"
            f"      ① read_today_schedule(date='{view_date}') 拿 daily task 列表,按描述/品牌匹配是哪个;\n"
            f"         匹配不出来才列出来反问用户挑哪个\n"
            f"      ② set_daily_task_image(task_name, attachment_url) — 把照片设成该 task 的打卡图标\n"
            f"      ③ check_daily_task(task_name, checked=true) — 勾上今天的打卡"
        )
        pre_sections.append("\n".join(v_lines))

    if ocr_results:
        ocr_section_lines = ["<图片 OCR 识别结果>"]
        for r in ocr_results:
            text = r["ocr_text"] or "(图中无可识别文字 / OCR 未配置)"
            ocr_section_lines.append(f"\n图片 [{r['filename']}]:\n```\n{text}\n```")
        ocr_section_lines.append("</图片 OCR 识别结果>")
        pre_sections.append("\n".join(ocr_section_lines))

    pre_block = ("\n\n".join(pre_sections) + "\n\n") if pre_sections else ""
    full_user_text = (
        f"{time_hint}\n{view_date_hint}\n\n"
        f"<context>\n{ctx_str}\n</context>\n\n"
        f"{pre_block}"
        f"{user_msg}"
    )

    # ── history processing: strip OCR + sliding-window summarize ──
    # 0.1.4 起 tool 段也保留 (assistant.tool_calls + role:tool 结果) —
    # 之前丢这些导致 AI 每轮 re-call read_today_schedule 等只读工具,cache 频繁 miss。
    # 上限: TOOL_HISTORY_CAP 个 tool result 字符总量,超了从最早的开始扔。
    cleaned_history = []
    for m in history:
        role = m.get("role")
        if role == "user":
            content = m.get("content")
            if not content:
                continue
            content = _strip_ocr_from_history(content)
            cleaned_history.append({"role": "user", "content": content})
        elif role == "assistant":
            content = m.get("content") or ""
            entry = {"role": "assistant", "content": content}
            # 保 tool_calls — 没它,下条 tool 消息会被 DeepSeek 拒(must follow tool_calls)
            tcs = m.get("tool_calls")
            if tcs and isinstance(tcs, list):
                entry["tool_calls"] = tcs
            cleaned_history.append(entry)
        elif role == "tool":
            content = m.get("content") or ""
            tcid = m.get("tool_call_id") or ""
            if not tcid:
                continue   # 没 id 关联不上 assistant.tool_calls,DeepSeek 拒
            # 每条 tool 结果再 truncate 一次 (避免历史里堆几条 5K MD 的)
            content = _truncate_tool_result(content)
            cleaned_history.append({
                "role": "tool", "tool_call_id": tcid, "content": content,
            })

    # 历史 tool 总量限额: 从最早开始扔超额的 tool result 字符。
    # 注意不能扔单独的 assistant.tool_calls (会孤儿)— 跟它配对的 tool 一起扔。
    cleaned_history = _trim_history_tool_volume(cleaned_history, max_tool_chars=24000)

    # 把 history 里裸的 [image] filename 换成带 vision/OCR brief 的形式 —
    # 防止 AI 回头引用过去上传过的图时凭空捏造话题。cache miss 时 label 保持原样。
    cleaned_history = _enrich_history_image_labels(cleaned_history)

    active_model = get_model(profile)
    sys_prompt = build_system_prompt(context, model_id=active_model)

    # decision: chat 路径不再做 sliding-window 摘要(client MAX_HISTORY=100 已截)。
    # DeepSeek prompt cache hit input ~$0.0036/M token,no-compress 全发用稳定 prefix
    # 比 compress 重算 summary 便宜 ~17×。详细论证 see 5.21 21:18 实测命中率。
    # _summarize_history fn 留着给 eval/board 路径用。
    recent = cleaned_history

    messages = [{"role": "system", "content": sys_prompt}]
    for m in recent:
        messages.append(m)
    messages.append({"role": "user", "content": full_user_text})

    # lazy tool loading:bootstrap(read+meta)默认在;write 类按 user msg / refs 自动 load,
    # 或 model 调 load_tool_group 主动 load。loaded_groups 是 mutable set,会被 _dispatch_tool
    # 改写,所以本轮算 active_tools 之后,后面每轮都重新算一遍。
    loaded_groups = _initial_groups(user_msg, context)
    quota_used = {}  # per-chat-turn tool 用量,跟 loaded_groups 一样跨 round 共享

    # ── streaming 模式:SSE 事件流(action / delta / done / error)──
    if stream_mode:
        return StreamingResponse(
            _chat_stream_generator(client, active_model, messages, loaded_groups, quota_used),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # multi-turn tool loop (max 6 rounds);最后一轮 force-no-tool 逼出文本回复,
    # 避免某些模型(如 DeepSeek)search 完仍想继续 search 撞 loop 上限返空 reply。
    last_actions = []
    MAX_ROUNDS = 10
    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)
        try:
            kwargs = {"model": active_model, "messages": messages}
            if not is_last_round:
                # 每轮重算 — load_tool_group 上一轮可能改了 loaded_groups
                kwargs["tools"] = _active_tools(loaded_groups)
                kwargs["tool_choice"] = "auto"
            # 最后一轮:不传 tools / tool_choice → 模型必须给文本
            # sync OpenAI 调用丢 threadpool — 不阻塞 asyncio event loop,
            # eval/board 类同时跑的 endpoint 不再被锁死(详 5.21 21:30 事故)
            resp = await asyncio.to_thread(client.chat.completions.create, **kwargs)
        except Exception as e:
            # 把 OpenAI/Anthropic 等 client 异常转成结构化 JSON,前端能解析
            err_text = str(e)
            status_match = re.search(r"Error code:\s*(\d+)", err_text)
            code = int(status_match.group(1)) if status_match else 500
            short = err_text[:300]
            return JSONResponse(
                status_code=200,  # 200 让前端正常 parse;reply 字段说明错
                content={
                    "reply": f"⚠ AI 调用失败 ({code}): {short}",
                    "actions": [],
                    "error": True,
                    "error_code": code,
                },
            )
        msg = resp.choices[0].message
        _log_cache_usage(resp, "chat/non-stream")
        # 用 model_dump 完整转,保留所有 provider 特有字段(尤其 DeepSeek V4 Pro 的
        # reasoning_content,thinking 模式下下一轮必须回传,否则 400)
        asst_msg = msg.model_dump(exclude_none=True)
        asst_msg["role"] = "assistant"
        # 严格按 OAI spec:tool_calls 空时不带这个 field(部分 provider 收 [] 会卡住)
        if not msg.tool_calls:
            asst_msg.pop("tool_calls", None)
        # content 不能是 None
        if asst_msg.get("content") is None:
            asst_msg["content"] = ""

        # ── DSML fallback:model 把 tool_call 当文本吐时,提取 + 升级成真 tool_calls ──
        synth_calls = []
        if not msg.tool_calls and asst_msg["content"]:
            asst_msg["content"], synth_calls = _extract_synthetic_tool_calls(asst_msg["content"])
            if synth_calls:
                asst_msg["tool_calls"] = [{
                    "id": c["id"], "type": "function",
                    "function": {"name": c["name"],
                                 "arguments": json.dumps(c["args"], ensure_ascii=False)},
                } for c in synth_calls]

        messages.append(asst_msg)

        if synth_calls:
            _exec_synth_calls(synth_calls, messages, last_actions, loaded_groups, quota_used)
            continue

        if not msg.tool_calls:
            # 防 reply 空 + 有 action 时前端啥都不显示
            reply = msg.content or ""
            # MiniMax / 部分 reasoner 模型把 chain-of-thought 当 content 一起返回,strip 掉
            reply = re.sub(r"<think>.*?</think>\s*", "", reply, flags=re.DOTALL).strip()
            if not reply and last_actions:
                names = ", ".join(a.get("name", "?") for a in last_actions)
                reply = f"✓ 完成: {names}"
            reply = _audit_unauthorized_claim(reply, last_actions)
            return {"reply": reply, "actions": last_actions}

        tool_results = []
        for tc in msg.tool_calls:
            # 跳过非 function 类型(如内置 web_search)——上游已自处理,结果直接折进消息流
            if getattr(tc, "type", "function") != "function" or not getattr(tc, "function", None):
                continue
            fn = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            result = _dispatch_tool(fn, args, loaded_groups, quota_used)
            tool_results.append({"id": tc.id, "name": fn, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
            })

        # save side-effect summary for the client
        # NOTE: 0.1.4 起 = 而非 extend,导致只看见最后一轮的工具调用 — known bug,
        # 见 6.2 测试 trace 漏 actions。先不改避免破坏 actions array contract,
        # client 拿 tool 历史的真路径是 stream "action" 事件累积,不是 done.actions。
        if tool_results:
            last_actions = tool_results

    # last round 若 synth 兜底执行了 tool,messages 末尾是 tool result,
    # msg.content 还含原始 DSML 文本 → 多打一次 bonus 拿干净 reply
    if messages and messages[-1].get("role") == "tool":
        try:
            bonus = await asyncio.to_thread(client.chat.completions.create,
                                            model=active_model, messages=messages)
            _log_cache_usage(bonus, "chat/non-stream-bonus")
            final_reply = (bonus.choices[0].message.content or "").strip()
        except Exception as e:
            final_reply = f"(tool loop 用完;synthesis call 失败:{type(e).__name__})"
    else:
        final_reply = msg.content or ""
    final_reply = re.sub(r"<think>.*?</think>\s*", "", final_reply, flags=re.DOTALL).strip()
    final_reply = _audit_unauthorized_claim(final_reply, last_actions)
    return {"reply": final_reply or "(no reply, tool loop hit max iterations)", "actions": last_actions}
