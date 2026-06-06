# 内测前清债清单

> 三轮 ultracode workflow review (B 网络 / A 持久化 / C secrets) 出 48 真问题。
> v0.1.18 收口 B 3 high,v0.1.19 收口 A+C 9 critical,v0.1.20 收口剩余 P1+P2 ~~36~~ 5。
> 内测期间一件一件改。每条修完打勾 + 写哪个版本。

---

## P1 · 出门见人前必修(影响信任 / 隐私 / 用户体验)

### Updater 通道安全

- [~] **C-#2 + #8** updater HTTPS 接 TLS — 当前 `dangerousInsecureTransportProtocol: true` 是 Tauri 显式 opt-in 的"我知道这不安全"开关 — **服务端就绪**(v0.1.20: caddy-snippet.txt 加 /updates/ HTTPS 路由 + /forget DELETE 口);**客户端切换留 v0.1.21**(需 server 先 deploy + 验证 `https://feedback.{domain}/updates/latest.json` 200,再改 tauri.conf.json 关 dangerous flag)
  - 风险:MITM 降级(manifest.version 与 tarball 内部版本无交叉校验);版本+IP 明文嗅探可与 heartbeat client_id 时序关联反匿名
  - 修法:Caddy snippet 加 @updates handle 反代 feedback-sink:8000 的 StaticFiles `/updates`;tauri.conf.json updater endpoint 切 `https://feedback.{domain}/updates/latest.json`
  - 注意:PULSE 自承"接 TLS 后关掉"
  - 顺便:把 v0.1.19 强制改的 IP+port URL 改回域名(参 26.6.7 02:00 那段 yanpai sync 操作)

### Privacy / Consent 合规

- [x] **C-#10** 撤回 consent 不通知 yanpai 删除已上传数据 — 违 GDPR Art.17 / PIPL 第 47 条 — **v0.1.20**
  - 修:feedback-sink 加 `DELETE /forget?client_id=...`(无 admin 鉴权,client_id 即 capability token,幂等);client `_telemetry_consent_set` 检测"之前同意过 + 现在两项都关"→ fire-and-forget 一发(独立 thread daemon)

- [x] **C-#4** consent 关闭期间 silent-failure 仍写本地,再开同意时一次性回灌 — **v0.1.20**
  - 修:`_report_silent_failure` 入口加 consent gate(撤回期连本地都不写);带 try/except 兜 `_telemetry_consent → load_config` 损坏路径理论回拨递归

### Secrets / 应用层鉴权

- [ ] **C-#3 跟进** API key 走 keyring(Mac Keychain / Win Credential Manager / Linux Secret Service) — **留 v0.1.21**
  - 现状:v0.1.19 已 chmod 0o600 兜住"拷 .app 漏 key"
  - 升级:keyring 后即使 .app 拷给同事 troubleshoot,key 留在原机 Keychain
  - 估时:2-3 天 — Python `keyring` 库,3 平台分支

- [x] **C-#5** feedback-sink `/stats` `/recent` 仅靠 Caddy basic_auth,无应用层第二道闸 — **v0.1.20**
  - 修:`_require_admin(req)` 检查 `X-Admin-Token` 头(env `FEEDBACK_ADMIN_TOKEN` 设了才生效;unset → 信任反代层兜底,向后兼容);加在 /stats /stats/dau /recent 三处

### 安全卫生(顺手做)

- [x] **C-#6** `.gitignore` 缺 `silent-failures.jsonl` / `client-id.txt` / `data/` — **v0.1.20**
  - 触发链:user error(手动 HUMAN_AI_STATE 指向 repo + git add .),代码本身无 fallback 甩到 repo 根
  - 修法:5 行 .gitignore 改动
  - 估时:5 分钟

---

## P2 · 内测稳定后 / 扩用户群前(影响可恢复性 / 静默故障)

### 写盘工具自身的洞

- [x] **A-H2 + H12** `_rotate_backup` 自身非原子 — `bak.1` 直接 `write_bytes`,链式 rename 无原子整体性,catch-all `pass` 吞异常 — **v0.1.20**
  - 修:bak.1 走 `tmp+replace`;except 改 `_report_silent_failure('rotate_backup_failed')`;同时 `_safe_write_text` 整段加 path-keyed lock + uuid tmp + fd/parent fsync(参 A-H3/M5)

- [x] **A-H3** `_safe_write_text` tmp 文件名固定 `.tmp` → 并发写者 race — **v0.1.20**
  - 修:tmp 名 `f"{path}.{os.getpid()}.{uuid4().hex[:8]}.tmp"` + 模块级 path-keyed lock (`_WRITE_GUARD_LOCKS`);finally 清残留 tmp

- [x] **A-M5** `_safe_write_text` 无 `fsync(tmp fd)` + 无 `fsync(parent dir)` — 断电场景 atomic rename 不保内容到盘 — **v0.1.20**
  - 修:tmp `flush() + os.fsync(fh.fileno())` → replace → `_fsync_parent` `os.open(parent, O_DIRECTORY)` + fsync + close

### 二级关键路径非原子

- [x] **A-H1** scrapbook-config / attachments_index / curator-system-prompt 3 处直写 — **v0.1.20**
  - 修:三处全走 `_safe_write_text`;curator prompt rotate=False(可重建);attachments_index + scrapbook rotate=True

- [x] **A-H4** Rust `.updater-pending.json` 非原子 + server 端 `unlink-on-error` 缺失 — **v0.1.20**
  - 修:Rust tmp + rename(POSIX/Win 都 atomic);Python `_consume_updater_pending` 把 unlink 挪出 try + 损坏文件也上报 silent-failure + 必删兜底解卡 banner

- [x] **A-H5** `_persist_pending_notification` append 非原子 + consume unlink 整文件 — **v0.1.20**
  - 修:`_PENDING_NOTIF_FILE_LOCK` 全局锁;persist append + fsync;consume 改 read → push → atomic write 空(write-back-good-lines)避免 read 期间新 append 被吞

- [x] **A-H6 + H11** silent-failures.jsonl trim/append/cursor 三写者无 lock + 并发吞行 — **v0.1.20**
  - 修:`_SF_FILE_LOCK` 包 append + trim;trim 走 `_safe_write_text`;trim 后同步调整 cursor (`drop_count` = `len(lines) - RING_MAX`) 避免漏发;append 加 fsync(反馈通道自己挂最不该悄无声息)

- [x] **A-H7** history_exporter 4 处 export jsonl 非原子 — **v0.1.20**
  - 修:模块内 `_atomic_write_text`(独立于 server,不拉 FastAPI 栈);tmp 名带 pid + uuid 防并发

- [x] **A-H8** outcome_tracker `save_outcomes` 非原子 + load 静默吞 — **v0.1.20**
  - 修:save 加 5-rotate bak + tmp+rename;load 损坏 → stderr WARN + 尝试 bak.1 fallback;history_exporter 端的 `except: outcomes_map = {}` 改 stderr WARN

- [x] **A-H9** `USER_WIDGETS_PATH` 非原子 + AI `tool_add_widget` 的 `json.loads` 无 try/except — **v0.1.20**
  - 修:read 端加 try → silent-failure 上报 + fallback `{"active": []}`;两处 write 走 `_safe_write_text(rotate=True)`;legacy migration 模块加载期内联 tmp+replace

### 长期记忆 / audit chain 静默退化

- [x] **A-H13** vault_git daemon 异常吞 + `.git/index.lock` 卡住 → audit chain 永久空但用户不知 — **v0.1.20**
  - 修:(a) `_CONSECUTIVE_FAILURES` 计数 + 阈值 5 → `_push_broken_notification('vault-git-broken')`;(b) `_clear_stale_index_lock` 探测 `.git/index.lock` 老于 600s → 清 + 重试一次;(c) 成功 commit 重置计数。(d) audit_chain_ok 接口 + 周日 ritual 留 v0.1.21+

- [x] **A-H14** thread-history.json 读端损坏返 `[]` + 前端 fallback 用本地覆盖 — 5.17 教训只补一半 — **v0.1.20**
  - 修:server 读失败返 `status: 'corrupt', baks: [...]` + 新增 `/api/thread/restore-from-bak` 端点;前端 thread.js 读到 status==='corrupt' → 拦下 saveHistory + 弹 modal(列 bak.1-5 含 size_kb/mtime,选 restore 或 start-fresh);restore 时把损坏文件 rename `.corrupted.{ts}` 留诊断

### Medium / Low(顺手做)

- [ ] **A-M1** `tool_add_widget` 3 文件 + USER_WIDGETS_PATH 非事务 — staging 目录方案 (留 v0.1.21+;widget-loader try/catch 已隔离 blast radius)
- [x] **A-M2** `CLIENT_ID_PATH` 非原子(PULSE 列硬合同) — `_safe_write_text(rotate=True)` — **v0.1.20**
- [x] **A-M3** `_HB_LAST_SENT_PATH` / `_SF_CURSOR_PATH` 非原子 — 两处全走 `_safe_write_text` — **v0.1.20**
- [x] **A-M4** PULSE-mirror sync 直写 — 改 `_safe_write_text` + 每文件 try/except + 失败 silent-failure 上报 — **v0.1.20**
- [ ] **A-Low** `client_id` 重置 → DAU 多算一份 — 留 v0.1.21+;server 端去重逻辑改动跨 client/server

---

## P3 · B 网络补录 (从 v0.1.18 round transcript 还原 by Workflow wbm3z8wbk · 2026-06-07)

> v0.1.18 收口的是 3 high(stream tear-down / eval `_call_json` 分桶 / `self_evolve_run` 上报);v0.1.18-20 顺手又收口了 silent-failure ring-buffer 两条(见末尾)。下面 6 条是 transcript 还原后**仍 open** 的,内测期前修不完也要全列出来 — silent-failure 通道的盲点全在这。

### Silent-failure 通道盲点(高优先)

- [x] **B-#1** `_run_schema_migration_if_needed` 失败只走 `_push_notification`,没接 silent-failure 通道 — schema migration 是后台 startup hook,用户既不主动触发也不可见;3 次失败 + 24h cooldown 后 LLM migration channel 彻底停摆,根因丢失 — **v0.1.21**
  - 修:except block 加 `_report_silent_failure` 走 `_classify_eval_err` 分桶 → `schema_migration_auth/quota/timeout/format/failed`;`_migration_llm_call` 异常自然向外传由外层分桶

- [ ] **B-#2** `baidu_ocr_image` 拿到 `error_code` (110/111/17/18/19) 时静默返 `""`,主调点 `baidu_ocr_image(...) or ''` 检测不到 — quota / token / QPS 全绕过 `ocr_baidu_failed` 上报;AI 视角下"图里没字"就开始凭空猜内容(同 5.20 长鑫存储 → 港币事件根因) — [high]
  - cite: `ocr.py:142-147` (error_code 分支 return "") + `server.py:3057-3063` (`_ocr_text` 调用点 try/except 只捕异常);同 pattern `cutout.py:186-188`
  - 修法:定义 `BaiduOCRError(code, msg)`,error_code 分支 raise 而非 return "";调用侧 `_ocr_text` except 捕到后 `_report_silent_failure('ocr_baidu_quota'/'ocr_baidu_token'/'ocr_baidu_qps', code=...)`;PULSE 内测期已点名 OCR quota 是典型案例
  - 估时:2-3h(同改 cutout 模块)

- [x] **B-#3** 百度 OAuth `_TOKEN_CACHE` invalidation 写错 key — token 过期后 `_TOKEN_CACHE['token'] = None` 给字典加了一个野 key,真 cache_key (`f"{api_key}:{secret_key}"`) 下的 stale token 原封不动;下次 `_get_access_token` 仍命中 stale → baidu 持续 110/111 → OCR 整进程都返 "",只能重启 .app 才修 — **v0.1.21**
  - 修:ocr.py L146 改 `_TOKEN_CACHE.pop(cache_key, None)`

- [ ] **B-#4** Cloud sink 4xx 一律推进 cursor — sink endpoint 写错 / deploy key 轮换 / client_id 格式漂移 → 所有 pending silent-failure 一桶倒进 /dev/null;只 `log.warning` 到 stderr,.app 用户根本看不见,反转了反馈通道的契约 — [high]
  - cite: `server.py:791-809` (`_sf_drain_once` L802-806 4xx 分支无差别 cursor += len(pending))
  - 修法:401/403/404 → 不 advance cursor + 累计 `_sf_sink_4xx_streak` (持久化 DATA_DIR),阈值 (如 3) → `_push_notification('sink-broken', kind='auth_or_url')`;400/422 (schema/payload 不对) → 单条 advance 不整批;consent dashboard 加 sink 状态 pill
  - 估时:2-3h

- [x] **B-#5** `_qwen_classify_image` 检测到 `dashscope_api_key` 缺 + `base_url` 不是 dashscope 时 `_report_silent_failure('vision_key_config_inconsistent')` 后 **未 return**,落到 OpenAI client 调用 → 用错家 key 打错家 endpoint,每张图必 401(5.29 prod outage 同款) — **v0.1.21**
  - 修:`_report_silent_failure` 后直接 return 带 `error: "vision_key_config_inconsistent"` 的 dict;context 改用 `network_marker: "non_dashscope_base_url"` (在 `_sanitize_sf_context` 白名单内,不被 drop)
  - 留续:`_push_notification` debounce 留 v0.1.22 (避免每次 chat 都弹)

### 中优先(网络降级期 silent 退化)

- [ ] **B-#6** 百度 OAuth POST 自身网络异常(DNS / TLS / Clash blip)时 `_get_access_token` log + return None,**stale cache 不清**;下个 caller 看 token 过期再走一次同样的网络洞,走完仍 None;`baidu_ocr_image` 返 "" 不 raise → `_ocr_text` 的 `except Exception` 永不触发,整条 OAuth-network-fail 路径 0 observability — 5.29 加的 37 hooks 全在 server.py,没覆盖 `ocr.py` / `cutout.py` 这俩 library 模块 — [medium]
  - cite: `ocr.py:80-113` (OAuth POST except L111-113 仅 log + None) + `ocr.py:145-146` (stale 清错 key,同 B-#3 根因);`server.py:3025-3063` `_ocr_text` 只捕 exception
  - 修法:ocr.py / cutout.py 加薄壳上报 helper(避免 lazy import 循环) — 例如 `_emit_ocr_failure(kind, **ctx)` 通过 import-time 注入的 callable(server.py 启动时 `ocr.set_failure_sink(_report_silent_failure)`);OAuth POST except 内 `_TOKEN_CACHE.pop(cache_key, None)` + emit `baidu_oauth_network_failed`;baidu_ocr_image 顶层包一层捕获 + emit 后 raise(同时改 B-#2 的 BaiduOCRError)
  - 估时:3-4h(架构性 — 给 library 模块装"上报针脚",别再独立漂移)

### 已被 v0.1.18-20 收口

- [x] **B-#7** silent-failure sender cursor 没在 `_trim_silent_failures` 截断后回拨,cloud sink 永久哑火 — **v0.1.18-20**: trim 计 `drop_count` + `_sf_cursor_write(max(0, old_cursor - drop_count))` 全包在 `_SF_FILE_LOCK` 内
- [x] **B-#8** `silent-failures.jsonl` trim 与 append 并发吞行 — **v0.1.18-20**: 引入 `_SF_FILE_LOCK` + trim 走 `_safe_write_text` (atomic tmp+rename+fsync) + cursor 调整折入同一锁内

---

## P4 · 服务端独立部署(不在 gateway client 仓)

- [ ] **feedback-sink** v0.1.20 含两批 server 端改动:
  - v0.1.19 那批:删 `client_ip` 列 + 删 `x-forwarded-for` 解析 + schema migration
  - v0.1.20 那批:`DELETE /forget` (C-#10)、`/stats /stats/dau /recent` 加 `_require_admin` (C-#5)
  - 走 id_ed25519 非 sandbox key,操作 ssh yanpai + docker compose
  - 步骤:
    ```bash
    cd "/Users/claudecodedezhuanshumac/agents创作平台/agents"
    tar -czf /tmp/feedback-sink-v0.1.20.tar.gz feedback-sink
    scp /tmp/feedback-sink-v0.1.20.tar.gz ubuntu@101.42.108.30:/tmp/

    ssh ubuntu@101.42.108.30 << 'REMOTE'
    cd /opt/feedback-sink
    sudo cp app/main.py app/main.py.bak.pre-v0.1.20
    sudo tar -xzf /tmp/feedback-sink-v0.1.20.tar.gz -C /opt/ --strip-components=1 feedback-sink/app/main.py
    # 如果要启用应用层鉴权,设 env(可选,unset 则向后兼容)
    # echo 'FEEDBACK_ADMIN_TOKEN=<你的强 token>' | sudo tee -a /opt/yanpai/.env  # 视部署方式
    cd /opt/yanpai 2>/dev/null || cd /opt
    sudo docker compose restart feedback-sink
    sudo docker compose logs --tail=30 feedback-sink   # 验启动 + schema migration 触发
    REMOTE
    ```
  - 跑完后看:`client_ip` 列已 DROP,`/forget` 端点存在 (curl test),`/stats` 不带 token 返 401

- [ ] **Caddy 反代加 /updates/ HTTPS + /forget DELETE 路由** (P1-#2/#8 服务端那半)
  - 编辑 yanpai 的 `caddy/Caddyfile`,把 `feedback.{$DOMAIN}` 块替换成新版(模板在 [`feedback-sink/caddy-snippet.txt`](../../../agents创作平台/agents/feedback-sink/caddy-snippet.txt))
  - 4 个 handle 块:@ingest (含新增 /heartbeat)、@forget (DELETE)、@updates (GET /updates/*)、@board
  - 跑 `sudo docker compose restart caddy-edge` 触发 Caddy reload + LE 证书续期
  - 验:`curl -sI https://feedback.{$DOMAIN}/updates/latest.json` 返 200(Caddy 反代到 feedback-sink 的 StaticFiles `/data/updates/`)
  - 跑完了才能 v0.1.21 改 `tauri.conf.json` 把 updater endpoint 切 HTTPS + 关 `dangerousInsecureTransportProtocol`

---

## 工作流约定

- 一件改完:本文件勾对应行 + 注脚版本号(`v0.1.20 fixed`)
- 一组改完(比如所有 P2 写盘工具的洞):合一个版本号 ship
- 每条修法估时是粗算,实际碰到 regression 拉长不算债
- 修完不补一遍 review workflow,**先内测验证用户能不能撞到**;撞不到的留作"已知 risk 但没真用户能见"
- 跟内测节奏对齐:
  - 第一周:P1 全清,出门见人安全
  - 第二周:开始 P2,边内测边修
  - 第三周后:P2 收尾 + P3 卫生
