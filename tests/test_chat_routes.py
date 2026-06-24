# TEST PATTERN: characterization — chat 引擎(/api/chat 流式 + tool loop + DSML 闸)
# USE WHEN: 锁 chat/stream 现行行为,守 chat_routes 抽出(§ 9)。**本 session 最高风险抽取**:
#           Cannot-break 代码(DSML 泄漏闸/SSE 契约/可变状态/claim 审计)是要*搬走*的那块。
# TESTED IN: gateway chat_routes extraction (2026-06-24), § T7 characterization
#
# § T7 GREEN-LOCK:monolith 上先全绿,chat_routes.py 抽出后 STAY GREEN。
# 关键手法:_stream_final_reply / _chat_stream_generator 收 client/messages/loaded_groups/quota
# 当参数 → 可*直接*喂 fake streaming client 驱动,不需起 app。SSE = "data: {json}\n\n"。
# ★ = cannot-break(非协商)。配合现有 test_claim_audit.py + test_attachment_dedup.py(re-export tripwire)。

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

# U+FF5C 全角竖线 —— DSML 命名空间的字节,正则脆弱点,测试必须用真字节
BAR = "｜"
DSML_INVOKE = (f'<{BAR}{BAR}DSML{BAR}{BAR}invoke name="check_daily_task">'
               f'<{BAR}{BAR}DSML{BAR}{BAR}parameter name="task_name">鱼油'
               f'</{BAR}{BAR}DSML{BAR}{BAR}parameter></{BAR}{BAR}DSML{BAR}{BAR}invoke>')


# ── fake streaming client ────────────────────────────────────────────
def _chunk(content=None, rc=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=content, reasoning_content=rc))])


class _StreamClient:
    """create(stream=True) 按顺序吐每轮 chunk;每轮 = list[str|(str,rc)]。"""
    def __init__(self, rounds, raise_on=None):
        self.rounds = list(rounds)
        self.raise_on = raise_on  # 第 N 次 create 抛异常
        self._i = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kw):
        i = self._i
        self._i += 1
        if self.raise_on is not None and i == self.raise_on:
            raise RuntimeError("Error code: 503 boom")
        chunks = self.rounds[min(i, len(self.rounds) - 1)]
        out = []
        for c in chunks:
            if isinstance(c, tuple):
                out.append(_chunk(content=c[0], rc=c[1]))
            else:
                out.append(_chunk(content=c))
        return iter(out)


def _events(gen):
    """SSE 文本流 → [dict]。"""
    out = []
    for raw in gen:
        assert raw.startswith("data: ") and raw.endswith("\n\n")
        out.append(json.loads(raw[6:-2]))
    return out


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    # _stream_final_reply 不直接调 _log_cache_usage,但保险:dispatch 默认记录器
    monkeypatch.setattr(server, "_report_silent_failure", lambda *a, **k: None)


# ══ ★ DSML 泄漏闸(5.27 事故)══════════════════════════════════════════

def test_stream_no_raw_dsml_in_any_delta_split_chunks(monkeypatch):
    """DSML invoke 跨多个 chunk 吐 → 任何 delta 都不含 raw DSML/全角竖线;action 触发;后续干净文本流。"""
    disp = []
    monkeypatch.setattr(server, "_dispatch_tool",
                        lambda fn, args, lg, qu: disp.append((fn, args)) or {"ok": True})
    # 把 DSML 切成 3 段(marker 被切两半),再来一轮干净收尾
    mid = len(DSML_INVOKE) // 2
    rounds = [["好的我记一下。", DSML_INVOKE[:mid], DSML_INVOKE[mid:]], ["记好了"]]
    ev = _events(server._stream_final_reply(_StreamClient(rounds), "m", [], set(), {}, []))
    deltas = [e["text"] for e in ev if e["type"] == "delta"]
    for t in deltas:
        assert "DSML" not in t and BAR not in t and "<function_calls" not in t
    assert any(e["type"] == "action" and e["name"] == "check_daily_task" for e in ev)
    assert disp == [("check_daily_task", {"task_name": "鱼油"})]   # 真派发了
    assert ev[-1]["type"] == "done"
    assert "记好了" in "".join(deltas)                              # pre/post 正常文本仍流


def test_stream_malformed_dsml_still_no_leak(monkeypatch):
    """畸形 DSML(抠不出 call)→ 仍绝不漏 raw,至少吐清理后的文本。"""
    monkeypatch.setattr(server, "_dispatch_tool", lambda *a: {"ok": True})
    broken = f"前文 <{BAR}{BAR}DSML{BAR}{BAR}tool_calls> 坏的没闭合"
    ev = _events(server._stream_final_reply(_StreamClient([[broken]]), "m", [], set(), {}, []))
    for e in ev:
        if e["type"] == "delta":
            assert "DSML" not in e["text"] and BAR not in e["text"]


# ══ ★ SSE 事件序列契约 ════════════════════════════════════════════════

def test_stream_clean_text_sequence_ping_delta_done():
    ev = _events(server._stream_final_reply(_StreamClient([["你好", "世界"]]), "gpt-x", [], set(), {}, []))
    types = [e["type"] for e in ev]
    assert types[0] == "ping"
    assert "delta" in types
    assert types[-1] == "done"
    done = ev[-1]
    assert done["model_id"] == "gpt-x" and done["actions"] == []
    assert "".join(e["text"] for e in ev if e["type"] == "delta") == "你好世界"


def test_stream_reasoning_content_threaded_to_done():
    ev = _events(server._stream_final_reply(_StreamClient([[("回复", "思考中")]]), "m", [], set(), {}, []))
    assert ev[-1].get("reasoning_content") == "思考中"


def test_stream_llm_error_emits_error_event_no_done(monkeypatch):
    rung = []
    monkeypatch.setattr(server, "_report_silent_failure",
                        lambda et, *a, **k: rung.append(et))
    ev = _events(server._stream_final_reply(_StreamClient([["x"]], raise_on=0), "m", [], set(), {}, []))
    assert ev[-1]["type"] == "error"
    assert not any(e["type"] == "done" for e in ev)
    assert "chat_llm_call_failed" in rung           # 分桶上报


# ══ ★ claim 审计(流式副本与 helper 一致)═════════════════════════════

def test_stream_claim_disclaimer_when_claim_and_no_actions():
    """流式收尾:claim 措辞 + actions 空 → 吐 _CLAIM_DISCLAIMER(跟非流 helper 同一对象)。"""
    ev = _events(server._stream_final_reply(_StreamClient([["已经记进 17:30 了"]]), "m", [], set(), {}, []))
    joined = "".join(e["text"] for e in ev if e["type"] == "delta")
    assert server._CLAIM_DISCLAIMER.strip() in joined


def test_claim_audit_helper_and_stream_share_disclaimer():
    # helper 版:claim + 空 actions → 加;有 action → 不加
    assert server._audit_unauthorized_claim("已写入了", []).endswith(server._CLAIM_DISCLAIMER)
    assert server._audit_unauthorized_claim("已写入了", [{"name": "x"}]) == "已写入了"
    assert server._audit_unauthorized_claim("普通回复", []) == "普通回复"


# ══ ★ 可变状态 identity:loaded_groups 跨 round 同一对象 ═══════════════

def test_mutable_state_loaded_groups_threads_by_identity(monkeypatch):
    """_chat_stream_generator 用传入的 SAME loaded_groups;load_tool_group 真改它,
    下一轮 _active_tools 看得见。复制 = load 静默 no-op(AI 写不了日记)。"""
    monkeypatch.setattr(server, "_log_cache_usage", lambda *a, **k: None)
    seen_ids = []
    real_dispatch = server._dispatch_tool

    def spy_dispatch(fn, args, lg, qu):
        seen_ids.append(id(lg))
        if fn == "load_tool_group":
            lg.add(args.get("name"))      # 模拟 load_tool_group in-place mutate
            return {"ok": True, "loaded": args.get("name")}
        return {"ok": True}
    monkeypatch.setattr(server, "_dispatch_tool", spy_dispatch)

    # round0: 非流,model 调 load_tool_group;round1: 非流,无 tool → 进 _stream_final_reply;stream: 文本
    def _tc(name, args):
        return SimpleNamespace(id="c1", type="function",
                               function=SimpleNamespace(name=name, arguments=json.dumps(args)))

    class _NS:  # 非流 message 假货
        def __init__(self, content="", tcs=None):
            self.content = content; self.tool_calls = tcs; self.reasoning_content = None
        def model_dump(self, exclude_none=True):
            d = {"content": self.content, "role": "assistant"}
            return d

    class _Mixed:
        def __init__(self): self._i = 0; self.chat = SimpleNamespace(completions=self)
        def create(self, **kw):
            i = self._i; self._i += 1
            if kw.get("stream"):
                return iter([_chunk(content="完成")])
            if i == 0:
                return SimpleNamespace(choices=[SimpleNamespace(message=_NS("", [_tc("load_tool_group", {"name": "write_journal"})]))])
            return SimpleNamespace(choices=[SimpleNamespace(message=_NS("", None))])

    my_groups = set()
    ev = _events(server._chat_stream_generator(_Mixed(), "m", [{"role": "user", "content": "记一下"}], my_groups, {}))
    assert "write_journal" in my_groups                 # 传入的同一 set 被真改了
    assert len(set(seen_ids)) == 1                       # 每轮 dispatch 拿的都是同一个 id
    assert ev[-1]["type"] == "done"


# ══ ★ 派发 reaches 真 tool 注册表(wiring + cold-boot)═════════════════

def test_dispatch_wiring_present():
    """chat 经 _dispatch_tool → TOOL_IMPL 到 authorship 核心。抽出后这条 lazy seam 必须仍通。"""
    assert callable(server._dispatch_tool)
    assert "patch_journal_block" in server.TOOL_IMPL
    assert callable(server.TOOL_IMPL["patch_journal_block"])


# ══ DSML 提取(字节级 + 3 层 strip)═══════════════════════════════════

def test_extract_synthetic_tool_calls_byte_level():
    content = f"前 {DSML_INVOKE} 后"
    stripped, calls = server._extract_synthetic_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["name"] == "check_daily_task"
    assert calls[0]["args"] == {"task_name": "鱼油"}
    assert "DSML" not in stripped and BAR not in stripped     # 残骸清光
    assert "前" in stripped and "后" in stripped


def test_extract_no_dsml_passthrough():
    assert server._extract_synthetic_tool_calls("普通文本") == ("普通文本", [])


# ══ 纯 helper ═════════════════════════════════════════════════════════

def test_truncate_tool_result():
    short = "x" * 100
    assert server._truncate_tool_result(short) == short
    big = "y" * 6000
    out = server._truncate_tool_result(big)
    assert len(out) < 6000 and "truncated" in out


def test_trim_history_drops_orphan_tool_calls():
    """超量 tool result 丢最早的,孤儿 assistant.tool_calls 一并清(防 DeepSeek 400)。"""
    hist = [
        {"role": "assistant", "tool_calls": [{"id": "a"}], "content": ""},
        {"role": "tool", "tool_call_id": "a", "content": "z" * 30000},
        {"role": "assistant", "tool_calls": [{"id": "b"}], "content": ""},
        {"role": "tool", "tool_call_id": "b", "content": "short"},
    ]
    out = server._trim_history_tool_volume(hist, max_tool_chars=100)
    # 大 tool 'a' 被丢;留下的任何 assistant 不能带孤儿 tool_call_id 'a'
    ids_in_tool = {m["tool_call_id"] for m in out if m.get("role") == "tool"}
    for m in out:
        if m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                assert tc["id"] in ids_in_tool          # 无孤儿


# ══ 非流契约(TestClient)═════════════════════════════════════════════

@pytest.fixture
def chat_client(monkeypatch):
    monkeypatch.setattr(server, "get_profile", lambda *a, **k: {"model": "m"})
    monkeypatch.setattr(server, "get_model", lambda *a, **k: "m")
    monkeypatch.setattr(server, "build_system_prompt", lambda *a, **k: "SYS")
    monkeypatch.setattr(server, "_initial_groups", lambda *a, **k: set())
    monkeypatch.setattr(server, "_active_tools", lambda lg: [])
    monkeypatch.setattr(server, "_log_cache_usage", lambda *a, **k: None)
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def test_chat_nonstream_llm_error_returns_200_structured(chat_client, monkeypatch):
    """client.create 抛 → 200 + 结构化 error(前端按 reply 字段解析,绝不 5xx)。"""
    class _Boom:
        chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **k: (_ for _ in ()).throw(RuntimeError("Error code: 429 rate"))))
    monkeypatch.setattr(server, "get_client", lambda *a, **k: _Boom())
    r = chat_client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "stream": False})
    assert r.status_code == 200
    d = r.json()
    assert d["error"] is True and d["error_code"] == 429 and d["actions"] == []


def test_chat_nonstream_plain_text_reply(chat_client, monkeypatch):
    msg = SimpleNamespace(content="<think>嗯</think>你好", tool_calls=None, reasoning_content=None)
    msg.model_dump = lambda exclude_none=True: {"content": msg.content, "role": "assistant"}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **k: SimpleNamespace(choices=[SimpleNamespace(message=msg)]))))
    monkeypatch.setattr(server, "get_client", lambda *a, **k: client)
    d = chat_client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "stream": False}).json()
    assert d["reply"] == "你好"          # <think> 剥掉
    assert d["actions"] == []
