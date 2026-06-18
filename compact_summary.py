"""compact_summary — thread 压缩后给 AI 写 200 字摘要(防失忆冷启)。

从 server.py 抽出。endpoint(`/api/pulse/compact-summary`)留在 server.py,
本模块只持有 prompt + 同步 LLM call 的 worker。

依赖(函数体内 lazy import 避循环):
  - server.get_profile          — 选 deepseek-v4-flash/pro
  - server.get_client           — 拿 OpenAI 兼容 client
  - server._report_silent_failure — 失败上报(workflow #23 闭合,不再裸 except)
  - server.log                  — logger
"""


# Compact 摘要 — 防 thread 清空后 AI 失忆冷启
_COMPACT_SUMMARY_PROMPT = """这是一段刚被压进 md 的对话。
请用 200 字以内中文写一个摘要,给后续对话延续上下文,**只写关键决策 / 待办 / 当下话题**,
不写流程细节、不复述每句话、不带工具名。读者是这个对话的下一回合,不是外人。

对话原文:
═══════════════════════════════════════════
{conversation}
═══════════════════════════════════════════

返一段散文,不带标题,不带 ``` 包裹。"""


def compact_summary_run(conversation: str) -> str:
    """同步 LLM call,给 to_thread 包。返摘要文本。
    workflow #23 闭合:失败接 silent-failure 通道,不再裸 except 让前端误以为 ok。
    """
    from server import get_profile, get_client, _report_silent_failure, log
    profile = get_profile("deepseek-v4-flash") or get_profile("deepseek-v4-pro") or get_profile()
    if not profile:
        _report_silent_failure("compact_summary_no_profile",
                               "deepseek 模型未配置,summary 跳过")
        return ""
    client = get_client(profile)
    if client is None:
        _report_silent_failure("compact_summary_no_client",
                               "deepseek client 起不来,summary 跳过")
        return ""
    prompt = _COMPACT_SUMMARY_PROMPT.format(conversation=conversation)
    try:
        resp = client.chat.completions.create(
            model=profile.get("model", "deepseek-v4-flash"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
            timeout=60,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.warning(f"compact summary 失败: {e}")
        _report_silent_failure("compact_summary_llm_call_failed",
                               f"{type(e).__name__}: {e}",
                               {"conversation_chars": len(conversation)})
        return ""
