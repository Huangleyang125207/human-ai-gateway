"""web_tools — AI 工具层的 web_search / fetch_url 一对。
从 server.py 抽出(2499-2746),行为零变化。

外部依赖(注入式·函数体内 lazy import 避循环):
  - server.load_config           — _resolve_dashscope_creds 找百炼 key
  - server._report_silent_failure — _do_web_search 降级时上报
  - server.log                   — _do_web_search 降级日志

其余依赖:requests/re/html/random/string/lxml/openai/ddgs — 全标准/三方库。
"""
import re
import html as _html_mod
import requests


# ── web_search 后端:百炼 enable_search 为主,ddgs 兜底 ──────────────────
# 为什么:ddgs 走 DuckDuckGo/Google,大陆被墙、无代理用不了(5.27 调研实测)。
# 百炼 enable_search 在大陆直连、复用用户已配的 dashscope key、对 deepseek/qwen 都支持,
# 是大陆 + 单 API 的正解。OpenAI 兼容接口拿不到结构化来源,但模型文字答里常带链接,够用。
_BAILIAN_SEARCH_MODEL = "qwen-flash"   # 便宜+快;搜索-总结任务足够;百炼托管,带 enable_search


def _resolve_dashscope_creds():
    """找百炼(dashscope)的 (api_key, base_url)。优先 models[] 里 base 含 dashscope 的 profile
    (这用户 key 在那,非顶层),再退顶层 dashscope_api_key。找不到返 (None, None)。"""
    from server import load_config
    cfg = load_config() or {}
    for p in (cfg.get("models") or []):
        if "dashscope" in (p.get("base_url") or "") and p.get("api_key"):
            return p["api_key"], p["base_url"]
    dk = cfg.get("dashscope_api_key", "")
    if dk:
        return dk, cfg.get("dashscope_base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    return None, None


def _bailian_web_search(query: str) -> str:
    """百炼 enable_search:模型联网搜 + 总结。大陆直连。没 key / 失败 → 抛异常给调用方降级。"""
    key, base = _resolve_dashscope_creds()
    if not key:
        raise RuntimeError("no dashscope key")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=base)
    r = client.chat.completions.create(
        model=_BAILIAN_SEARCH_MODEL,
        messages=[{"role": "user", "content":
                   "联网搜索并回答下面的查询。列关键事实要点,能附来源链接就附。简洁,别废话。\n\n" + query}],
        extra_body={"enable_search": True,
                    "search_options": {"search_strategy": "turbo", "enable_source": True}},
        timeout=40,
    )
    ans = (r.choices[0].message.content or "").strip()
    if not ans:
        raise RuntimeError("百炼 search 返空")
    return ans


_WEB_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _sogou_wechat_search(query: str, max_results: int = 8) -> str:
    """搜微信公众号文章(经搜狗微信,大陆直连)。选择器移植自 SearXNG sogou_wechat 引擎。
    返标题/链接/摘要;链接是搜狗跳转页,要看正文让 AI 再 fetch_url 它。"""
    from lxml import html as _lx
    try:
        r = requests.get("https://weixin.sogou.com/weixin",
                         params={"query": query, "type": 2, "page": 1},
                         headers={"User-Agent": _WEB_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                         timeout=12)
    except Exception as e:
        return f"[公众号搜索失败:{type(e).__name__}: {str(e)[:120]}]"
    if "antispider" in r.url or "验证码" in r.text[:3000]:
        return "[公众号搜索被搜狗反爬拦截 — 稍后再试或换关键词]"
    parts = []
    for item in _lx.fromstring(r.text).xpath('//li[contains(@id, "sogou_vr_")]')[:max_results]:
        a = item.xpath('.//h3/a')
        if not a:
            continue
        title = a[0].text_content().strip()
        href = a[0].get("href", "")
        if href.startswith("/link?url="):
            href = "https://weixin.sogou.com" + href
        snip = item.xpath('.//p[contains(@class, "txt-info")]')
        content = (snip[0].text_content().strip()[:120]) if snip else ""
        if title and href:
            parts.append(f"- {title}\n  {href}\n  {content}")
    return "\n".join(parts) if parts else "[公众号搜索无结果]"


def _bilibili_search(query: str, max_results: int = 10) -> str:
    """搜 B站视频(官方 JSON API,大陆直连)。移植自 SearXNG bilibili 引擎(假 buvid3 + Referer)。"""
    import random, string
    buvid = "".join(random.choice(string.hexdigits) for _ in range(16)) + "infoc"
    try:
        r = requests.get("https://api.bilibili.com/x/web-interface/search/type",
                         params={"search_type": "video", "keyword": query, "page": 1,
                                 "page_size": 20, "single_column": "0", "__refresh__": "true"},
                         headers={"User-Agent": _WEB_UA, "Referer": "https://www.bilibili.com"},
                         cookies={"buvid3": buvid, "i-wanna-go-back": "-1", "b_ut": "7"}, timeout=12)
        data = (r.json().get("data") or {}).get("result") or []
    except Exception as e:
        return f"[B站搜索失败:{type(e).__name__}: {str(e)[:120]}]"
    parts = []
    for it in data[:max_results]:
        title = re.sub(r"<[^>]+>", "", it.get("title", "") or "")
        desc = (it.get("description") or "")[:100]
        parts.append(f"- {title}(UP:{it.get('author','')})\n  {it.get('arcurl','')}\n  {desc}")
    return "\n".join(parts) if parts else "[B站搜索无结果]"


def _360_search(query: str, max_results: int = 8) -> str:
    """360 通用搜索(so.com,大陆直连)。选择器移植自 SearXNG 360search 引擎。
    先 GET 一次拿 cookie(防空结果),再带 cookie 请求。返 标题/链接/摘要。"""
    from lxml import html as _lx
    sess = requests.Session()
    sess.headers.update({"User-Agent": _WEB_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        url = "https://www.so.com/s"
        params = {"q": query, "pn": 1}
        # cookie 预热(360 对无 cookie 请求常返空)
        try:
            warm = sess.get(url, params=params, timeout=10, allow_redirects=False)
            ck = warm.headers.get("set-cookie", "")
            if ck:
                sess.headers["Cookie"] = ck.split(";")[0]
        except Exception:
            pass
        r = sess.get(url, params=params, timeout=12)
    except Exception as e:
        return f"[360 搜索失败:{type(e).__name__}: {str(e)[:120]}]"
    if not r.text.strip():
        return "[360 搜索返空(可能被风控)]"
    parts = []
    for item in _lx.fromstring(r.text).xpath('//li[contains(@class, "res-list")]')[:max_results]:
        a = item.xpath('.//h3[contains(@class, "res-title")]/a')
        if not a:
            continue
        title = a[0].text_content().strip()
        href = a[0].get("data-mdurl") or a[0].get("href", "")
        desc = item.xpath('.//p[@class="res-desc"]') or item.xpath('.//span[@class="res-list-summary"]')
        content = (desc[0].text_content().strip()[:120]) if desc else ""
        if title and href:
            parts.append(f"- {title}\n  {href}\n  {content}")
    return "\n".join(parts) if parts else "[360 搜索无结果]"


def _do_web_search(query: str, max_results: int = 5, category: str = "general") -> str:
    """web_search 后端,按 category 分流(都大陆直连):
      wechat   → 搜狗微信(公众号文章)
      bilibili → B站视频(JSON API,dormant)
      general  → 360(主力,免费+真来源 URL) → 百炼兜底(360 挂时) → ddgs(海外兜底)
    """
    from server import _report_silent_failure, log
    if category == "wechat":
        # 包 try:lxml 缺失 / parser 崩 不能逃出去变成 tool hard-error(无 fallback,至少干净返回)
        try:
            return _sogou_wechat_search(query, max_results)
        except Exception as e:
            _report_silent_failure("web_search_wechat_exception",
                f"{type(e).__name__}: {str(e)[:80]}")
            return f"[公众号搜索暂不可用:{type(e).__name__} — 稍后再试]"
    if category == "bilibili":
        return _bilibili_search(query, max_results)
    # 通用:360 主力。失败/无结果 → 百炼兜底(大陆可靠) → ddgs(需代理)
    # 包 try:防 lxml 缺失/parser 崩 等异常逃出 → 跳过整条 fallback 链 + 隐身(web_search 硬挂真因)
    try:
        r360 = _360_search(query, max_results)
    except Exception as e:
        log.info(f"[web_search] 360 抛异常,降级百炼: {type(e).__name__}: {str(e)[:120]}")
        _report_silent_failure("web_search_360_exception",
            f"360 抛异常,降级百炼: {type(e).__name__}: {str(e)[:80]}")
        # sentinel 字符串(非 None)—— 后续 .startswith/[:40] 不炸,且触发降级
        r360 = f"[360 异常:{type(e).__name__}]"
    if r360 and not r360.startswith("[360"):   # 有真结果
        return r360
    log.info(f"[web_search] 360 无结果({r360[:40]}),试百炼兜底")
    _report_silent_failure("web_search_360_degraded",
        f"360 无结果,降级到百炼: {r360[:80]}")
    try:
        r = _bailian_web_search(query)
        return r
    except Exception as e:
        log.info(f"[web_search] 百炼也降级 ddgs: {type(e).__name__}: {str(e)[:120]}")
        _report_silent_failure("web_search_bailian_degraded",
            f"360 + 百炼都没出货,降级到 ddgs: {type(e).__name__}")
        return _ddgs_search(query, max_results)


def _ddgs_search(query: str, max_results: int = 5) -> str:
    """[兜底] ddgs 后端(DuckDuckGo/Google 聚合,大陆需代理)。三段式 fall through。
    auto 失败常见 TLS handshake 崩('Unsupported protocol version 0x304')。失败/空都返字符串。"""
    max_results = max(1, min(int(max_results or 5), 10))
    try:
        from ddgs import DDGS
    except Exception as e:
        return f"[ddgs 没装好:{e}]"

    # ddg+google 组合实测中文 query 出真结果(单 ddg 偶尔"No results",
    # 单 google 给随机数学题,bing 把中文 tokenize 飞);auto 兜底
    backends_to_try = ["duckduckgo,google", "duckduckgo,google,bing,wikipedia", "auto", "wikipedia"]
    last_err = None
    for backend in backends_to_try:
        try:
            results = list(DDGS().text(query, max_results=max_results, backend=backend))
        except Exception as e:
            last_err = e
            continue
        if not results:
            continue
        parts = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            # 短摘要(~80 char)— 只够判断要不要 fetch_url 进一步看
            body = (r.get("body") or "")[:80]
            parts.append(f"- {title}\n  {href}\n  {body}")
        return "\n".join(parts)
    if last_err:
        return f"[搜索后端全崩(3 个 backend 配置都试过):{type(last_err).__name__}: {last_err}]"
    return "[无结果]"


def tool_web_search(args):
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "need query"}
    n = args.get("max_results", 5)
    cat = (args.get("category") or "general").strip().lower()
    if cat not in ("general", "wechat"):   # bilibili 撤下(B站 search 需 WBI 签名,先不开;函数 dormant)
        cat = "general"
    return {"ok": True, "query": q, "category": cat, "results": _do_web_search(q, n, cat)}


# PATTERN: util — minimal HTML → text(no deps)
# USE WHEN: 给 LLM 看网页正文,但不想拉 BeautifulSoup
# COPY THIS: 调 strip 顺序 / 截断长度
_HTML_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_HTML_STYLE_RE  = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE    = re.compile(r"<[^>]+>")
_HTML_WS_RE     = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    s = _HTML_SCRIPT_RE.sub("", html)
    s = _HTML_STYLE_RE.sub("", s)
    s = _HTML_TAG_RE.sub(" ", s)
    s = _html_mod.unescape(s)
    s = _HTML_WS_RE.sub(" ", s).strip()
    return s


_FETCH_CAP = 3000  # 单次 fetch 最多塞 3000 char 进 messages


def tool_fetch_url(args):
    """拉某 URL 正文(HTML strip → text,truncate 到 _FETCH_CAP)。
    渐进披露第二步:web_search 拿标题决定 fetch 哪条,再用这个工具看正文。
    """
    url = (args.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "need valid http(s):// URL"}
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (gateway-fetch)"})
        r.raise_for_status()
    except Exception as e:
        return {"error": f"fetch failed: {type(e).__name__}: {str(e)[:200]}"}
    text = _html_to_text(r.text)
    truncated = False
    if len(text) > _FETCH_CAP:
        text = text[:_FETCH_CAP] + f"…(+{len(text)-_FETCH_CAP} chars omitted)"
        truncated = True
    return {"ok": True, "url": url, "text": text, "truncated": truncated}
