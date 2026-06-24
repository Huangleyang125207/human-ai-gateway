"""pulse_evolve — LLM-driven self-evolve(_self_evolve_run + 2 prompt + EVOLVE_LOCKS)。

PULSE LARGE refactor P4(最敏感,silent corruption 红线集中地)。从 server.py 抽出
_self_evolve_run(194 行) + _PULSE_UPDATE_PROMPT + _AGENT_CONTEXT_EVOLVE_PROMPT +
_EVOLVE_LOCKS + _EVOLVE_LOCKS_GUARD + _get_evolve_lock。

PULSE.md Cannot break 红线(P0+ 40 测试守):
- _EVOLVE_LOCKS 锁身份不漂(并发同 target → 同 lock 实例)
- sha256 external-edit + file-deleted 双分支 race guard
- retry loop + 4 类 error 分桶 + HTTPException(500) 上报
- vault_git.commit_after_write 真调(author='ai' for evolve,msg 'self-evolve {name} ...')
- USER_PULSE create_if_absent=True 走 bootstrap(6.17 那个 bug)
- agent_context 走 _AGENT_CONTEXT_EVOLVE_PROMPT(frozen 段保护)

依赖:
- 顶层 import vault_git(test 用 monkeypatch.setattr(server.vault_git, ...) 入口,
  pulse_evolve 通过模块属性查找仍命中)
- 顶层 from pulse_io import _SELF_EVOLVE_TARGETS / _TS_RE / _pulse_validate /
  _get_schema_version / _ensure_schema_version_header(P2 已抽)
- 函数体内 lazy:server.get_profile / get_client / VAULT_DIR / _safe_write_text /
  _push_notification / _report_silent_failure / log
"""
import re
import threading
from datetime import date

from fastapi import HTTPException

import vault_git
from pulse_io import (
    _SELF_EVOLVE_TARGETS, _TS_RE, _pulse_validate,
    _get_schema_version, _ensure_schema_version_header,
)


_PULSE_UPDATE_PROMPT = """这是当前 {name} 全文({what}):
═══════════════════════════════════════════
{pulse}
═══════════════════════════════════════════

这是刚才那段对话(用户和 AI 协作记录):
═══════════════════════════════════════════
{conversation}
═══════════════════════════════════════════

今天: {today}

请重写整份 {name}。{bootstrap_note}

机械要求(server 会校验,违反就被拒):
- 每条记录前必须有 `<!-- ts:YYYY-MM-DD -->` 标记(HTML 注释格式)
- 整份不超过 {budget} 字
- ts 必须是合法 YYYY-MM-DD 日期

内容自由(没人限制你):
- 这条记录还有效?→ 把 ts 改成今天 {today}
- 这条记录过时了 / 不再适用 / 已完成?→ 自己删掉,别留
- 对话里冒出新事实 / 新决定?→ 加进去,ts 今天
- 结构、段落、语气怎么排你定 — 旧的分段不是合同,想重新分段就重新分
- ts 超过 {stale} 天没刷新的强烈嫌疑要删,自己评估
- 你认为这条记录是「硬合同」(踩了就炸的那种),保留并刷新 ts;只有真过时才删

返回纯 markdown,不要解释、不要 ``` 包裹。"""


# AGENT_CONTEXT 独立 evolve prompt(workflow #1 critical 修):
# 跟 USER_PULSE / PROJECT_PULSE 不同 — 这是「协议手册 + 用户区」混合体,frozen 段绝对不能动
_AGENT_CONTEXT_EVOLVE_PROMPT = """这是当前 AGENT_CONTEXT.md 全文(vault 协议手册 + 用户区):
═══════════════════════════════════════════
{pulse}
═══════════════════════════════════════════

这是刚才那段对话(用户和 AI 协作记录):
═══════════════════════════════════════════
{conversation}
═══════════════════════════════════════════

今天: {today}

**重要**:这文件分两段,处理方式不一样:

### frozen 段(`<!-- frozen-start -->` 到 `<!-- frozen-end -->` 之间)

vault 协议手册 — vault 怎么用 / tag 怎么打 / #协作 #commit 是什么 / 聚合页规则。
**这段一字节都不能改**。server 会 byte-equal 比对,改了就被拒。
你只能给段头 `<!-- ts:YYYY-MM-DD -->` 标记不变继续传递(标记本身在 frozen 段内,
你连这都不要动,原样输出)。

### user-region 段(`<!-- user-region-start -->` 到 `<!-- user-region-end -->` 之间)

用户的协作 context 在这写。这段你可以根据对话长内容,但:
- 看到 `<!-- placeholder: XXX -->` 注释,**保留这条注释**(server 会校验,丢了就拒)。
  注释下面是这个 placeholder 对应的字段:用户填了就用用户填的,**用户没填(空冒号 / 留空)
  你绝对不要替他脑补内容** — 留空原样,等用户自己填。
- 用户在对话里**主动提到**自己的角色 / 关心点 / 协作偏好,可以填进对应字段。
- 用户**没主动提**的字段保留空 + 保留 placeholder 注释。

### 机械要求(server 会校验,违反就被拒)

- frozen 段 byte-equal,不准改
- 每个 `<!-- placeholder: ... -->` 注释必须保留(数量不能少)
- 每条 ts 标记保留并按需刷新到今天 {today}
- ts 总数不能比原文少一半(防你大量删段)
- 整份不超过 {budget} 字

{bootstrap_note}

返回纯 markdown,不要解释、不要 ``` 包裹。"""


# 每个 self-evolve target 一把锁 — read→LLM→write 整段串行,防 startup migration
# 跟用户点圆环并发同一 file 把数据搞坏(review #5 #21)。GIL 在 LLM call(120s timeout)
# 不能 cover 长 IO,必须显式锁。
_EVOLVE_LOCKS: dict = {}  # str → threading.Lock
_EVOLVE_LOCKS_GUARD = threading.Lock()  # 保护 _EVOLVE_LOCKS 字典本身


def _get_evolve_lock(target: str) -> threading.Lock:
    with _EVOLVE_LOCKS_GUARD:
        lk = _EVOLVE_LOCKS.get(target)
        if lk is None:
            lk = threading.Lock()
            _EVOLVE_LOCKS[target] = lk
        return lk


def _self_evolve_run(target: str, conversation: str) -> dict:
    """通用 self-evolve:LLM 重写真源 md。USER_PULSE / 项目 PULSE / AGENT_CONTEXT 都走这一条路。
    锁保护 read→LLM→write 整段(防 #5 race);atomic write + rotate backup(#11 #13);
    mtime guard 防用户外部编辑被覆盖(#21);schema-version 保留(#8);
    len/H1/H2 sanity 防 LLM 大量删内容(#6);写入 VAULT_DIR 走 vault_git(#14 #17)。
    """
    # lazy import:test 的 monkeypatch.setattr(server, X) 仍生效(每次 call 重读)
    from server import (
        get_profile, get_client, VAULT_DIR, _safe_write_text,
        _push_notification, _report_silent_failure, log,
    )

    cfg = _SELF_EVOLVE_TARGETS.get(target)
    if not cfg:
        raise HTTPException(400, f"未知 target: {target}")
    path = cfg["path"]()
    # creating:文件不存在 + 该 target 允许创建(user_pulse)→ 当空 pulse 让 LLM 生成首版(走 bootstrap)。
    # 不允许创建的(project_pulse:陌生用户没"项目")→ 维持 graceful skip。
    creating = (not path.exists()) and cfg.get("create_if_absent", False)
    if not path.exists() and not creating:
        # graceful skip,不算失败;让 frontend ok_count 算上,防 #20 永远 2/3 + #22 死循环
        return {
            "ok": True,
            "skipped": True,
            "reason": f"{cfg['name']} 文件不存在,跳过(路径 {path})",
            "target": target,
            "name": cfg["name"],
        }

    with _get_evolve_lock(target):
        # 读快照,记 sha256 内容指纹(R10):比 mtime 精确,跨 fs 一致,
        # iCloud / Obsidian Sync / NAS 同秒外部编辑也能检测到。
        import hashlib as _hashlib_se
        if creating:
            old = ""  # 首次创建:空 pulse,LLM 从对话生成首版
            old_sha = _hashlib_se.sha256(b"").hexdigest()
        else:
            try:
                old = path.read_text(encoding="utf-8")
                old_sha = _hashlib_se.sha256(old.encode("utf-8")).hexdigest()
            except Exception as e:
                raise HTTPException(500, f"读 {cfg['name']} 失败: {e}")

        today = date.today().isoformat()
        bootstrap = not _TS_RE.search(old)  # 全文无 ts = bootstrap 态
        old_schema_version = _get_schema_version(old)
        bootstrap_note = (
            f"\n**bootstrap 注意**:当前文件还没有任何 `<!-- ts:YYYY-MM-DD -->` 标记 — "
            f"这是首次自演化。你重写时**必须**给每段都加上 ts(初始全用今天 {today}),"
            f"后续 cycle 才能正常演化。漏一条就被拒。\n"
            if bootstrap else ""
        )

        # Per-target prompt template(workflow #5 root cause B 闭合):
        # AGENT_CONTEXT 走独立 _AGENT_CONTEXT_EVOLVE_PROMPT 保护协议手册 frozen 段;
        # USER_PULSE / PROJECT_PULSE 走 default(快照型记录,允许压精简)
        tmpl_key = cfg.get("prompt_template", "default")
        if tmpl_key == "agent_context":
            prompt = _AGENT_CONTEXT_EVOLVE_PROMPT.format(
                pulse=old, conversation=conversation, today=today,
                budget=cfg["budget"], bootstrap_note=bootstrap_note,
            )
        else:
            prompt = _PULSE_UPDATE_PROMPT.format(
                name=cfg["name"], what=cfg["what"],
                pulse=old, conversation=conversation, today=today,
                budget=cfg["budget"], stale=cfg["stale"],
                bootstrap_note=bootstrap_note,
            )

        profile = get_profile("deepseek-v4-pro") or get_profile()
        if not profile:
            raise HTTPException(503, "deepseek 主模型未配置")
        client = get_client(profile)
        if client is None:
            raise HTTPException(503, "deepseek client 起不来")

        last_err = ""
        new_text = ""
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=profile.get("model", "deepseek-v4-pro"),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=8000,
                    temperature=0.3,
                    timeout=120,
                )
            except Exception as e:
                last_err = f"LLM call 失败: {type(e).__name__}: {e}"
                continue
            text = (resp.choices[0].message.content or "").strip()
            text = re.sub(r"^```(markdown|md)?\s*", "", text).strip()
            text = re.sub(r"\s*```\s*$", "", text).strip()
            # 升级 validator:non-bootstrap 时 strict + 传 old_text(workflow #3 #19 闭合)
            # strict 同时查 ts ratio ≥ 0.5、H2 ratio ≥ 0.7、frozen 段 byte-equal、placeholder 完整
            ok, err = _pulse_validate(
                text, budget=cfg["budget"],
                old_text=("" if bootstrap else old),
                strict=not bootstrap,
            )
            if not ok:
                last_err = err
                prompt = prompt + f"\n\n上次返回被校验拒了: {err}。修这条再返。"
                continue
            # 内容长度兜底(non-strict 模式即 bootstrap 也不能写空)
            if not bootstrap and len(text) < int(len(old) * 0.4):
                last_err = f"重写后内容只剩 {len(text)}/{len(old)} 字符(<40%),拒"
                prompt = prompt + f"\n\n上次返回内容腰斩了({last_err})。请重新写,保留所有有效记录,只删 stale 那些。"
                continue
            # schema-version 保留(workflow #8):旧有新没有 → 后处理注入(避免 retry 浪费 token)
            new_schema_version = _get_schema_version(text)
            if old_schema_version > 0 and new_schema_version < old_schema_version:
                text = _ensure_schema_version_header(text, old_schema_version)
            new_text = text
            break

        if not new_text:
            # workflow B #3 闭合:self-evolve LLM 失败接 silent-failure 通道。
            # 按 401/403/quota/timeout 子类型分桶,跟 vision_classify / curator 同款规则
            errlow = last_err.lower()
            if "401" in last_err or "403" in last_err or "auth" in errlow:
                err_type = "self_evolve_call_auth"
            elif "429" in last_err or "quota" in errlow or "rate" in errlow:
                err_type = "self_evolve_call_quota"
            elif "timeout" in errlow:
                err_type = "self_evolve_call_timeout"
            else:
                err_type = "self_evolve_llm_call_failed"
            _report_silent_failure(err_type, last_err[:150],
                context={"target": target, "model": profile.get("model"), "attempts": 2})
            raise HTTPException(500, f"{cfg['name']} 更新失败: {last_err}")

        # 内容指纹 guard(R10 + R11):read 后用户/外部进程改了 → 跳过写,但返
        # graceful skip(HTTP 200 + skipped:true)而不是 409,跟 file-not-exist 路径
        # 对齐,前端 compact-ring 当作 ok 不计 fail count,不会撞 1h cooldown。
        try:
            current = path.read_text(encoding="utf-8")
            current_sha = _hashlib_se.sha256(current.encode("utf-8")).hexdigest()
            if current_sha != old_sha:
                _push_notification(
                    "pulse-skip-external-edit",
                    f"{cfg['name']} 在 LLM 重写期间被外部编辑,跳过写入保留你手编内容(LLM 结果丢弃)",
                    {"target": target},
                )
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "external-edit",
                    "target": target,
                    "name": cfg["name"],
                }
        except FileNotFoundError:
            # creating 模式:文件本就不存在,这是预期 — 继续写首版,不当"被删"。
            if not creating:
                _push_notification(
                    "pulse-skip-external-edit",
                    f"{cfg['name']} 在 LLM 重写期间被删除,跳过写入",
                    {"target": target},
                )
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "file-deleted",
                    "target": target,
                    "name": cfg["name"],
                }

        # atomic write + 5 份 rotate backup(#11 #13)
        try:
            _safe_write_text(path, new_text, rotate=True)
        except Exception as e:
            raise HTTPException(500, f"{cfg['name']} 写盘失败: {e}")

        # vault_git audit(#14 #17):路径在 VAULT_DIR 内才走 hook
        # 用 vault_git.commit_after_write(顶层 import vault_git),test 走
        # monkeypatch.setattr(server.vault_git, "commit_after_write", spy) 仍命中
        # (server.vault_git 跟我们 import vault_git 是同一个 module 对象)
        try:
            if path.resolve().is_relative_to(VAULT_DIR.resolve()):
                vault_git.commit_after_write(
                    VAULT_DIR,
                    f"self-evolve {cfg['name']} ({len(old)}→{len(new_text)} chars)",
                    author="ai",
                    paths=[path],
                )
        except Exception as e:
            log.warning(f"vault_git commit_after_write {cfg['name']} 失败: {e}")

        return {
            "ok": True,
            "target": target,
            "name": cfg["name"],
            "old_chars": len(old),
            "new_chars": len(new_text),
            "old_records": len(_TS_RE.findall(old)),
            "new_records": len(_TS_RE.findall(new_text)),
            "backup": str(path) + ".bak.1",  # _safe_write_text rotate=True 写进 bak.1
            "bootstrap": bootstrap,
            "schema_version": _get_schema_version(new_text),
        }
