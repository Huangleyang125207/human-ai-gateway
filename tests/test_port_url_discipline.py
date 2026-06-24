# TEST PATTERN: boundary — port / URL discipline (static + contract)
# USE WHEN: 加新代码可能引入绝对 host:port URL 或硬编 4321 时,这套测试守门
# 背景: Tauri 壳给 sidecar 动态端口(bind :0 内核分配),写到
#       ~/.human-ai/.gateway-port 给 cron 用。任何"前端 fetch http://localhost:NNNN"或
#       "脚本写死 :4321 / 模型生成 http://localhost:18080" 都是回归。
# TESTED IN: gateway (2026-06-03)

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402


# host[:port] 形如 http(s)://(localhost|127.0.0.1)[:NNNN]
ABS_LOCAL_URL = re.compile(r'\bhttps?://(?:localhost|127\.0\.0\.1)(?::\d+)?')

# 远端 prod server(yanpai 自动更新通道),URL 允许出现
ALLOW_PROD_HOST = re.compile(r'101\.42\.108\.30')


def _grep_lines(path: Path, *, skip_comment_prefix=("#", "//", "/*", "*")):
    """yield (line_no, line) 不含注释行。"""
    for i, line in enumerate(path.read_text().splitlines(), 1):
        s = line.lstrip()
        if any(s.startswith(p) for p in skip_comment_prefix):
            continue
        yield i, line


# ─── T0 · 自检正则不误伤 ─────────────────────────────────────

def test_abs_local_url_regex_self_check():
    assert ABS_LOCAL_URL.search("http://localhost:4321/x")
    assert ABS_LOCAL_URL.search("https://127.0.0.1:18080")
    assert ABS_LOCAL_URL.search("http://localhost/api")  # 不带端口也算
    assert not ABS_LOCAL_URL.search("/attachments/2026/x.jpg")
    assert not ABS_LOCAL_URL.search("file:///tmp/x")


# ─── T1 · shared/*.js 全用相对路径,不许 localhost/127 字面 ────────

def test_no_absolute_local_url_in_shared_js():
    bad = []
    for f in sorted((ROOT / "shared").glob("*.js")):
        for i, line in _grep_lines(f):
            if ALLOW_PROD_HOST.search(line):
                continue
            m = ABS_LOCAL_URL.search(line)
            if m:
                bad.append(f"  {f.name}:{i}  {line.strip()[:120]}")
    assert not bad, (
        "shared/*.js 出现 localhost/127.0.0.1 绝对 URL — 应该走相对 /api/... "
        "(Tauri 壳动态端口,写死的会断)\n" + "\n".join(bad)
    )


# ─── T2 · index.html 同上 ──────────────────────────────────

def test_no_absolute_local_url_in_index_html():
    f = ROOT / "index.html"
    bad = []
    for i, line in _grep_lines(f):
        if ALLOW_PROD_HOST.search(line):
            continue
        if ABS_LOCAL_URL.search(line):
            bad.append(f"  index.html:{i}  {line.strip()[:120]}")
    assert not bad, "index.html 写死本地 host:port\n" + "\n".join(bad)


# ─── T3 · launchd / scripts shell 不许裸 :4321 ──────────────

def test_no_hardcoded_4321_in_shell_scripts():
    bad = []
    for d in ("launchd", "scripts"):
        p = ROOT / d
        if not p.exists():
            continue
        for f in sorted(p.glob("*.sh")):
            for i, line in _grep_lines(f):
                # 允许 fallback 兜底但必须在 PORT 读不到时,这种用 ${PORT:-4321} 形式
                if "${PORT:-" in line or "${GATEWAY_PORT:-" in line:
                    continue
                if re.search(r':4321\b', line) or re.search(r'\b4321\b', line):
                    bad.append(f"  {f.relative_to(ROOT)}:{i}  {line.strip()[:120]}")
    assert not bad, (
        "shell 脚本写死 4321 — Tauri 动态端口下会连不上;改读 ~/.human-ai/.gateway-port\n"
        + "\n".join(bad)
    )


# ─── T4 · tauri-stub/index.html 不能误导用户喊 :4321 ───────

def test_tauri_stub_no_hardcoded_port():
    f = ROOT / "tauri-stub" / "index.html"
    if not f.exists():
        pytest.skip("tauri-stub 不在")
    txt = f.read_text()
    assert ":4321" not in txt, (
        "tauri-stub/index.html 提到 :4321 — 误导新用户;改成不带端口的中性提示"
    )


# ─── T5 · upload endpoint 返的 url 必须是相对路径 ──────────

def test_upload_image_returns_relative_url():
    """源码级断言:upload 路由所有 return 分支的 url 字段都必须是相对路径。
    避免任何"为了 dev 方便加了 http://localhost:NNNN"的回归。
    """
    # upload-image 路由 6.24 抽到 chat_routes.py(@router.post);源码级断言跟去那
    src = (ROOT / "chat_routes.py").read_text()
    # 抓 upload-image 路由的整个函数体到下个 @router 装饰器(或文件尾)之前
    m = re.search(
        r'@router\.post\("/api/chat/upload-image"\).*?(?=@router\.|\Z)',
        src, re.DOTALL,
    )
    assert m, "找不到 upload-image 路由"
    body = m.group(0)
    # 函数里至少有 1 个 return 把 url 设成 /attachments/...
    assert re.search(r'"url"\s*:\s*f?"/attachments/', body), (
        f"upload 没有任何 return 用相对 /attachments/ url"
    )
    # 函数里所有 "url": 字面右边不能是 http(s):// 开头
    bad = re.findall(r'"url"\s*:\s*f?"https?://[^"]+', body)
    assert not bad, f"upload return dict 出现绝对 URL:\n{bad}"


# ─── T6 · curator description 必含 URL 原样照抄硬约束 ───────

def test_curator_tool_description_forbids_absolute_url():
    """模型曾把相对 URL 自动补上 http://localhost:18080 — 这是 prompt discipline 的事。
    description 必须明令"原样照抄,不要加 host/port 前缀"。
    """
    src = (ROOT / "server.py").read_text()
    # 抓 ask_photo_curator 那个 tool 的 description 字段(可能跨多行字符串拼接)
    m = re.search(
        r'"name"\s*:\s*"ask_photo_curator"\s*,\s*\n\s*"description"\s*:\s*\((.+?)\)\s*,',
        src, re.DOTALL,
    )
    assert m, "找不到 ask_photo_curator description 块"
    desc = m.group(1)
    assert "原样" in desc, (
        "ask_photo_curator description 必须告诉模型 URL '原样照抄 items[i].url'"
    )
    assert ("不要加" in desc or "禁止加" in desc or "不加" in desc), (
        "ask_photo_curator description 必须明令禁止给 URL 加 host/port 前缀"
    )


# ─── T7 · curator 返的 items url 必须以 /attachments/ 开头 ──

def test_curator_items_url_normalized_relative(monkeypatch, tmp_path):
    """合约:tool_ask_photo_curator 输出的每个 item.url 都是相对路径。
    防止有人在 _load_attachments_index 里偷偷加 host 前缀。
    """
    fake_index = [{
        "date": "2026-05-16",
        "filename": "abc.jpg",
        "url": "/attachments/2026-05-16/abc.jpg",
        "vision": {"description": "哈士奇站客厅"},
    }, {
        "date": "2026-05-18",
        "filename": "def.jpg",
        "url": "/attachments/2026-05-18/def.jpg",
        "vision": {"description": "挠痒"},
    }]
    monkeypatch.setattr(server, "_load_attachments_index", lambda: fake_index)

    # stub 子 agent 调用:让 curator 直接命中两个 stem
    class _FakeMsg:
        content = '{"matches": ["2026-05-16/abc", "2026-05-18/def"], "note": "ok"}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        choices = [_FakeChoice()]
        usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1,
                               "prompt_tokens_details": None})()

    class _FakeCompletions:
        def create(self, **kw):
            return _FakeResp()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(server, "get_client", lambda *a, **kw: _FakeClient())
    # curator 还要 profile 拿 model id;简单 stub
    monkeypatch.setattr(server, "get_profile", lambda *a, **kw: {
        "id": "fake", "model": "fake-model", "max_tokens": 1000,
    })
    monkeypatch.setattr(server, "_rebuild_curator_system_prompt", lambda: None)
    # CURATOR_SYSTEM_PATH 指向一个有内容的临时文件,绕过 fallback
    sys_file = tmp_path / "curator_sys.txt"
    sys_file.write_text("profile placeholder")
    monkeypatch.setattr(server, "CURATOR_SYSTEM_PATH", sys_file)

    out = server.tool_ask_photo_curator({"query": "找我家狗的照片"})
    assert "items" in out, f"curator 返回缺 items 字段: {out}"
    assert out["items"], f"curator items 空: {out}"
    for it in out["items"]:
        assert it["url"].startswith("/attachments/"), (
            f"curator 返绝对 URL: {it['url']} — 必须保持相对路径"
        )
        assert "://" not in it["url"], (
            f"curator URL 含 scheme: {it['url']}"
        )
