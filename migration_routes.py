"""migration_routes — MD/schema 迁移编排 glue(横幅状态机 + SSE + 启动 hook + legacy rewriter)。

Extract Module(ctrl-c-v § 9):server.py 的迁移*编排*层抽出(engine 早已外置 migration_plan.py)。
含:v0.1.25 横幅状态机(_migration_log/consumers/done + push_migration_event + /api/migration/stream)、
_MigrationLLM 工厂、启动 hook _startup_v0125_md_migration、参考文件引导 _ensure_vault_reference_files、
legacy schema rewriter _run_schema_migration_if_needed + attempts 防狂拺。
★Cannot-break:横幅 replay→live→done(断了用户看到卡死横幅)+ schema 数据安全门(不动 vault 真源)。
server helper(get_client/_safe_write_text/vault_git/_get_schema_version/_self_evolve_run/路径常量/
_VAULT_REFERENCE_TARGETS<-lambda 闭包绑 server 全局故留 server)全留 server,本模块走 function-body
lazy from server import。startup 三函数 re-export 回 server 供 startup hook 调。
characterization:tests/test_migration_glue.py(10)。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["migration"])

_migration_log: list[dict] = []

_migration_consumers: list[asyncio.Queue] = []

_migration_done: bool = False

_migration_lock: asyncio.Lock | None = None

def _migration_lock_get() -> asyncio.Lock:
    global _migration_lock
    if _migration_lock is None:
        _migration_lock = asyncio.Lock()
    return _migration_lock

async def push_migration_event(ev: dict) -> None:
    """T-D run_migration 的 progress_callback 入口。

    把事件落 log + fanout 给所有 SSE 客户端。
    `kind in ("migration_done", "migration_skipped")` 标记终态,SSE 自动收尾。
    """
    global _migration_done
    async with _migration_lock_get():
        _migration_log.append(ev)
        consumers = list(_migration_consumers)
        if ev.get("kind") in ("migration_done", "migration_skipped"):
            _migration_done = True
    for q in consumers:
        try:
            await q.put(ev)
        except Exception:
            pass  # 客户端断了不影响其他


@router.get("/api/migration/stream")
async def migration_stream():
    """SSE: v0.1.25 起的 MD 迁移进度推送。

    新 client 连接 → 先 replay 已有 log → 然后实时 stream → 见 migration_done/skipped 关闭。
    多 client 共存(用户刷新页面也能继续看)。
    """
    q: asyncio.Queue = asyncio.Queue()
    async with _migration_lock_get():
        snapshot = list(_migration_log)
        already_done = _migration_done
        if not already_done:
            _migration_consumers.append(q)

    async def event_gen():
        try:
            for ev in snapshot:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("kind") in ("migration_done", "migration_skipped"):
                    return
            if already_done:
                return
            while True:
                ev = await q.get()
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("kind") in ("migration_done", "migration_skipped"):
                    return
        finally:
            async with _migration_lock_get():
                if q in _migration_consumers:
                    _migration_consumers.remove(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 防代理 buffer 卡死 SSE
        },
    )

class _MigrationLLM:
    """migration_plan.run_migration 用的 LLM 客户端。

    协议:
      async call_plan(templates, vault) → [{user_file, target_template, action, reason}, ...]
      async call_rewrite(plan_item) → 新 user_file 内容(完整 MD text)
    """

    _PLAN_SYS = (
        "你是 MD 文件迁移 planner。给你新版 binary 自带的 canonical templates 列表"
        "+ 用户 vault 里现有的 MD 文件列表(及内容片段)。"
        "为每个 user MD 决定:它对应哪个 template(没有则 \"\"),action 是 migrate 还是 skip,reason 一句话。"
        "严格返 JSON 数组,无前后说明:[{\"user_file\":\"...\",\"target_template\":\"...\",\"action\":\"migrate|skip\",\"reason\":\"...\"}]"
    )

    _REWRITE_SYS = (
        "你是 MD 重写助手。把用户现有 MD 按新版 template 的结构重新组织。"
        "铁律:user 原内容(措辞、数据、tag、个人信息)100% 保留;template 的新区段在合理位置加上"
        "(可空可默认填);返**完整新 MD 文件内容**,无 code fence 无前后说明。"
    )

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    async def call_plan(self, templates: list, vault: list) -> list:
        tmpl_summary = "\n".join(
            f"- {t.name}" for t in templates
        ) or "(无)"
        # vault 只送文件名 + 前 600 字节,降 token
        vault_summary_lines = []
        for v in vault:
            try:
                head = v.read_text(encoding="utf-8")[:600].replace("\n", " ⏎ ")
            except Exception:
                head = "(读失败)"
            vault_summary_lines.append(f"- {v}: {head}")
        vault_summary = "\n".join(vault_summary_lines) or "(无)"

        user_msg = (
            f"## 新版 templates\n{tmpl_summary}\n\n"
            f"## 用户 vault(每文件前 600 字)\n{vault_summary}\n\n"
            "请输出 JSON 数组。"
        )

        def _do_call():
            r = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._PLAN_SYS},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                timeout=120.0,
            )
            return r.choices[0].message.content or ""

        text = await asyncio.to_thread(_do_call)
        text = text.strip()
        # response_format json_object 会返 `{"...":[...]}` 单 key 包对象;容忍。
        if text.startswith("{"):
            obj = json.loads(text)
            for v in obj.values():
                if isinstance(v, list):
                    return v
            return []
        return json.loads(text)

    async def call_rewrite(self, plan_item: dict) -> str:
        from server import GATEWAY_DIR
        user_file = Path(plan_item["user_file"])
        template_name = plan_item.get("target_template", "")
        try:
            user_text = user_file.read_text(encoding="utf-8")
        except Exception as e:
            raise RuntimeError(f"read user_file fail: {e}")
        # 找对应 template — 假设 bundle_dir/templates/<name>
        template_path = GATEWAY_DIR / "templates" / template_name if template_name else None
        if template_path and template_path.exists():
            try:
                template_text = template_path.read_text(encoding="utf-8")
            except Exception:
                template_text = "(无)"
        else:
            template_text = "(无)"

        user_msg = (
            f"## 用户现有 MD ({user_file.name})\n{user_text}\n\n"
            f"## 新版 template ({template_name})\n{template_text}\n\n"
            "请输出新 MD 文件完整内容。"
        )

        def _do_call():
            r = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._REWRITE_SYS},
                    {"role": "user", "content": user_msg},
                ],
                timeout=120.0,
            )
            return r.choices[0].message.content or ""

        text = await asyncio.to_thread(_do_call)
        return text.strip()

def _create_migration_llm():
    from server import get_client, get_model
    """工厂:有 key 时返 _MigrationLLM 实例,没有返 None。
    None 时 startup hook 跳过迁移,记一次 log 不告警。
    """
    client = get_client()
    if client is None:
        return None
    model = get_model()
    return _MigrationLLM(client, model)

async def _startup_v0125_md_migration():
    from server import APP_VERSION, GATEWAY_DIR, VAULT_DIR, log
    """v0.1.25 起的 MD 迁移 startup hook。

    spawn 一个后台 task 跑 migration_plan.run_migration。
    progress_callback = push_migration_event(SSE 出口)。
    bundle_dir = GATEWAY_DIR(PyInstaller frozen 时是 _MEIPASS / Resources;dev 时是 repo root)。
    vault_dir = VAULT_DIR。state_dir = ~/.human-ai/(跟 .updater-pending.json 同层)。
    """
    try:
        import migration_plan  # 延迟 import 避免 server.py 模块加载顺序问题
    except Exception as e:
        log.warning(f"migration_plan import fail: {e}")
        return

    llm = _create_migration_llm()
    if llm is None:
        log.info("[v0.1.25 migration] LLM 没配置,跳过迁移")
        return

    state_dir = Path.home() / ".human-ai"
    try:
        await migration_plan.run_migration(
            app_version=APP_VERSION,
            bundle_dir=GATEWAY_DIR,
            vault_dir=VAULT_DIR,
            state_dir=state_dir,
            llm_client=llm,
            progress_callback=push_migration_event,
        )
    except Exception as e:
        log.warning(f"[v0.1.25 migration] 顶层异常: {e}")
        # 兜底:推 migration_done(had_errors=True)让 SSE 客户端能收尾
        try:
            await push_migration_event({
                "kind": "migration_done",
                "success": False,
                "had_errors": True,
                "files_done": 0,
                "files_error": 0,
                "error": f"{type(e).__name__}: {e}",
            })
        except Exception:
            pass

def _bundled_reference_dir() -> Path:
    from server import GATEWAY_DIR
    """bundle 内 reference 目录;PyInstaller --add-data 进 GATEWAY_DIR/reference。"""
    return GATEWAY_DIR / "reference"

def _ensure_vault_reference_files() -> dict:
    from server import VAULT_DIR, _VAULT_REFERENCE_TARGETS, _push_notification, _safe_write_text, log, vault_git
    """startup 拷贝 reference 进 vault — 缺才补,已存在一字节不动(用户数据安全)。
    新拷的文件走 vault_git.commit_after_write(#17)留 audit chain。
    """
    bundle_dir = _bundled_reference_dir()
    if not bundle_dir.is_dir():
        return {"skipped": "bundle reference dir 不在"}
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    newly_copied: list[Path] = []
    for key, cfg in _VAULT_REFERENCE_TARGETS.items():
        dst = cfg["vault_path"]()
        if dst.exists():
            result[key] = "exists"
            continue
        src = bundle_dir / cfg["bundled_name"]
        if not src.exists():
            result[key] = "no bundled src"
            continue
        try:
            # atomic write,防 startup 中途崩留半文件
            _safe_write_text(dst, src.read_text(encoding="utf-8"), rotate=False)
            result[key] = f"copied to {dst}"
            newly_copied.append(dst)
        except Exception as e:
            result[key] = f"copy fail: {e}"
    # 批量 vault_git commit
    if newly_copied:
        try:
            vault_git.commit_after_write(
                VAULT_DIR,
                f"reference bootstrap: {', '.join(p.name for p in newly_copied)}",
                author="system",
                paths=newly_copied,
            )
        except Exception as e:
            log.warning(f"vault_git commit reference 失败: {e}")
        _push_notification(
            "vault-reference-bootstrapped",
            f"vault 已落地 {len(newly_copied)} 份起点 reference",
            {"files": [p.name for p in newly_copied]},
        )
    return result

_MIGRATION_ATTEMPTS_CACHE: dict = {}

def _migration_attempts_path() -> Path:
    from server import APP_STATE_DIR
    return APP_STATE_DIR / "data" / ".schema-migration-attempts.json"

def _read_migration_attempts() -> dict:
    from server import log
    """优先读文件,失败退 module cache(防 disk 读错重置计数)。"""
    p = _migration_attempts_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            # 文件读成功 → 合并 module cache(以文件为权威,cache 兜底未持久化的)
            for k, v in _MIGRATION_ATTEMPTS_CACHE.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception as e:
            log.warning(f"read migration attempts 失败,退 cache: {e}")
    return dict(_MIGRATION_ATTEMPTS_CACHE)

def _write_migration_attempts(data: dict) -> bool:
    from server import _safe_write_text, log
    """返 bool:文件写成功 True,失败时把数据存进 module cache 仍返 False。
    下次 startup 重启会丢 cache,但同 process 内连续 startup hook 仍能 gate 住。
    """
    global _MIGRATION_ATTEMPTS_CACHE
    _MIGRATION_ATTEMPTS_CACHE = dict(data)  # 总是更新 cache
    p = _migration_attempts_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        _safe_write_text(p, json.dumps(data, indent=2, ensure_ascii=False))
        return True
    except Exception as e:
        log.warning(f"write migration attempts 持久化失败,只在 module cache 中: {e}")
        return False

async def _run_schema_migration_if_needed():
    from server import VAULT_DIR, _SCHEMA_MIGRATION_PROMPT, _VAULT_REFERENCE_TARGETS, _classify_eval_err, _ensure_schema_version_header, _get_evolve_lock, _get_schema_version, _migration_llm_call, _push_notification, _report_silent_failure, _safe_write_text, _validate_migration_output, date, get_client, get_profile, log, vault_git
    """async 后台跑:bundle schema-version > vault 时,**安全**升级 vault 文件。

    重设默认行为(#2 #6 数据安全铁律):
      ① sha256 比 bundle vs vault — 完全一致 → 只注入 schema-version marker(不调 LLM)
      ② 不一致 → 写 LLM 迁移产物到 `vault/<name>.proposed.md` + push notification
         **不动 vault 真源**,等用户 review 后手动 mv
      ③ attempts 文件防狂拺 — 失败 ≥3 次 + 24h 内不再 try

    daily-tasks / 标签聚合 evolve_target=None → 不走 LLM,只看 schema bump 情况手动决定
      (写到 .proposed.md 也行,但优先级低,这里直接跳过)。
    """
    bundle_dir = _bundled_reference_dir()
    if not bundle_dir.is_dir():
        return
    attempts = _read_migration_attempts()
    now_ts = datetime.now().timestamp()
    attempts_changed = False

    import hashlib

    for key, cfg in _VAULT_REFERENCE_TARGETS.items():
        if cfg["evolve_target"] is None:
            continue
        bundle_path = bundle_dir / cfg["bundled_name"]
        vault_path = cfg["vault_path"]()
        if not bundle_path.exists() or not vault_path.exists():
            continue
        try:
            bundle_text = bundle_path.read_text(encoding="utf-8")
            vault_text = vault_path.read_text(encoding="utf-8")
        except Exception:
            continue
        bundle_v = _get_schema_version(bundle_text)
        vault_v = _get_schema_version(vault_text)
        if bundle_v <= vault_v:
            continue

        evolve_target = cfg["evolve_target"]

        # 路径 A(数据安全 #2 + R1 lock 闭合):bundle == vault 内容 → 只注入 marker,不调 LLM
        # 整段拿 self-evolve 同把锁,锁内重新 read+sha256 比对再写,防 startup migration
        # 跟用户点圆环 race(R1)。
        bundle_hash = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()
        vault_hash = hashlib.sha256(vault_text.encode("utf-8")).hexdigest()
        marker_key = f"{key}::marker"
        llm_key = f"{key}::llm"

        if bundle_hash == vault_hash:
            # attempts gate 单独看 marker 子 key(R7):marker IO 失败不污染 LLM path 计数
            a_marker = attempts.get(marker_key, {})
            if a_marker.get("count", 0) >= 3 and (now_ts - a_marker.get("last_ts", 0) < 86400):
                log.info(f"schema marker-only {key}: 24h 内已失败 3 次,跳过")
                continue
            try:
                with _get_evolve_lock(evolve_target):
                    # 锁内重新 read,sha256 再比一次(R1)
                    vault_text_recheck = vault_path.read_text(encoding="utf-8")
                    if hashlib.sha256(vault_text_recheck.encode("utf-8")).hexdigest() != vault_hash:
                        log.info(f"schema marker-only {key}: 锁内 vault 已变,改走 LLM path")
                        # 让下面的 LLM path 接手(继续走下去)
                    else:
                        new_text = _ensure_schema_version_header(vault_text_recheck, bundle_v)
                        _safe_write_text(vault_path, new_text, rotate=True)
                        try:
                            if vault_path.resolve().is_relative_to(VAULT_DIR.resolve()):
                                vault_git.commit_after_write(
                                    VAULT_DIR,
                                    f"schema bump {cfg['bundled_name']} v{vault_v}→v{bundle_v} (marker only)",
                                    author="system",
                                    paths=[vault_path],
                                )
                        except Exception:
                            pass
                        _push_notification(
                            "vault-schema-bumped",
                            f"vault {cfg['bundled_name']} 内容跟新版完全一致,直接升级到 schema v{bundle_v}",
                            {"target": key, "old_version": vault_v, "new_version": bundle_v, "kind": "marker-only"},
                        )
                        # 成功 — 清 attempts marker 子 key
                        attempts.pop(marker_key, None)
                        attempts_changed = True
                        continue
            except Exception as e:
                log.warning(f"schema marker-only bump {key} 失败: {e}")
                a_marker["count"] = a_marker.get("count", 0) + 1
                a_marker["last_ts"] = now_ts
                a_marker["last_err"] = f"marker-only: {type(e).__name__}: {e}"
                attempts[marker_key] = a_marker
                attempts_changed = True
                continue

        # 路径 B(auto-merge):不一致 → LLM 重写直接覆盖 vault 真源
        # user 6.5 23:00 拍 auto-merge:相信 LLM + 5 份 rotate backup + vault_git
        # audit 可回滚。validator 长度 ≥ 70% / 必含 ts / 必含 schema-version 三条
        # 拦住明显的 LLM 翻车。
        # 沿用 v0.1.13 设计初心:user 0 操作,schema 升级自动跟上。

        # attempts gate 单独看 llm 子 key(R7)
        a_llm = attempts.get(llm_key, {})
        if a_llm.get("count", 0) >= 3 and (now_ts - a_llm.get("last_ts", 0) < 86400):
            log.info(f"schema llm {key}: 24h 内已失败 3 次,跳过")
            continue

        migration_prompt = _SCHEMA_MIGRATION_PROMPT.format(
            name=cfg["bundled_name"],
            old_version=vault_v,
            new_version=bundle_v,
            bundle_reference=bundle_text,
            vault_current=vault_text,
            today=date.today().isoformat(),
        )
        try:
            profile = get_profile("deepseek-v4-pro") or get_profile()
            if not profile:
                raise Exception("deepseek 主模型未配置")
            client = get_client(profile)
            if client is None:
                raise Exception("deepseek client 起不来")
            new_text = await asyncio.to_thread(_migration_llm_call, client, profile, migration_prompt)
            ok_msg = _validate_migration_output(new_text, vault_text, bundle_v)
            if ok_msg:
                raise Exception(ok_msg)
            # 直接覆盖 vault 真源 — rotate=True 保 5 份 .bak.{1..5} 兜底
            with _get_evolve_lock(cfg["evolve_target"]):
                # 锁内重读 sha256,user 在 LLM 跑期间手编了就跳过(防覆盖手编)
                current = vault_path.read_text(encoding="utf-8")
                import hashlib as _h_in
                if _h_in.sha256(current.encode("utf-8")).hexdigest() != vault_hash:
                    log.warning(f"schema migration {key}: 锁内 vault 已改,跳过本次 merge")
                    _push_notification(
                        "vault-schema-migration-skip-external-edit",
                        f"vault {cfg['bundled_name']} 升级期间被外部编辑,跳过 merge 保留你的手编(下次启动再试)",
                        {"target": key, "old_version": vault_v, "new_version": bundle_v},
                    )
                    continue
                _safe_write_text(vault_path, new_text, rotate=True)
                try:
                    if vault_path.resolve().is_relative_to(VAULT_DIR.resolve()):
                        vault_git.commit_after_write(
                            VAULT_DIR,
                            f"schema migrate {cfg['bundled_name']} v{vault_v}→v{bundle_v} (LLM auto-merge)",
                            author="ai",
                            paths=[vault_path],
                        )
                except Exception:
                    pass
            _push_notification(
                "vault-schema-migrated",
                f"vault {cfg['bundled_name']} 已自动升级到 schema v{bundle_v}(LLM 按新结构重组,5 份 bak 兜底)",
                {"target": key, "old_version": vault_v, "new_version": bundle_v,
                 "old_chars": len(vault_text), "new_chars": len(new_text)},
            )
            attempts.pop(llm_key, None)
            attempts_changed = True
        except Exception as e:
            log.warning(f"schema migration {key} failed: {e}")
            a_llm["count"] = a_llm.get("count", 0) + 1
            a_llm["last_ts"] = now_ts
            a_llm["last_err"] = f"{type(e).__name__}: {e}"
            attempts[llm_key] = a_llm
            attempts_changed = True
            _push_notification(
                "vault-schema-migration-failed",
                f"vault {cfg['bundled_name']} 自动升级失败(已重试 {a_llm['count']} 次,真源未动)",
                {"target": key, "error": str(e), "attempts": a_llm["count"]},
            )
            # B-#1: schema migration 是 startup hook,用户不可见;3 次失败 + 24h cooldown
            # 后 LLM migration channel 彻底停摆。失败必须进 silent-failure 通道,否则
            # 内测期 deepseek quota / 401 / timeout 这种根因丢失。
            err_class = _classify_eval_err(e) if "_classify_eval_err" in globals() else "eval_call_failed"
            err_type = err_class.replace("eval_call_", "schema_migration_").replace(
                "eval_response_format_unsupported", "schema_migration_format_invalid"
            )
            try:
                _report_silent_failure(
                    err_type,
                    f"{type(e).__name__}: {str(e)[:120]}",
                    context={"attempt": a_llm["count"], "err_class": err_class,
                             "model_id": (profile or {}).get("model", "unknown")
                             if isinstance(profile, dict) else "unknown"},
                )
            except Exception:
                pass

    if attempts_changed:
        _write_migration_attempts(attempts)
