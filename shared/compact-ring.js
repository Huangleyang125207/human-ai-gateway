/* compact-ring.js · 对话长度小圆环 — 跟 Claude Code 一样的视觉语言
 *
 * 显示:thread-head 里一颗小圆环,conic-gradient 填充表示当前 history 占
 *      compact 阈值的百分比。tooltip 显示精确数。
 * 颜色:< 80%  绿
 *      80-99% 黄
 *      ≥ 100% 朱红
 * 数据:完整 History 由 thread.js 永久保留；这里只更新 Compact checkpoint，
 *      模型上下文由“摘要 + 最近原始轮次”派生，圆环按派生上下文回弹。
 */
(function () {
  const THREAD_KEY = "gateway.thread.history.v1";
  const THRESHOLD_CHARS = 150000;  // ~75K tokens; 跟 chat 端 _trim_history_tool_volume + tool history 修后 5-10 轮深度大致对应
  const POLL_MS = 3000;
  // 自动 compact 开关 — 默认 on(对齐 CC 无缝 compact 体验:超阈值后台自动跑、
  // 期间 user 继续聊不丢消息靠 cutoffIndex snapshot)。用户可手改
  // localStorage.setItem('gateway.compact.auto','off') 关掉。失败 2+ 次自动关 off。
  const AUTO_COMPACT_KEY = "gateway.compact.auto";
  const AUTO_FIRE_AT_KEY = "gateway.compact.lastAutoFireAt";  // persist 跨 reload(#10)
  const AUTO_FAIL_COUNT_KEY = "gateway.compact.consecutiveFails";  // partial-fail 计数(#22)
  const AUTO_FIRE_COOLDOWN_MS = 10 * 60 * 1000;  // 一次成功后 10min 内不重复 fire
  const AUTO_FAIL_COOLDOWN_MS = 60 * 60 * 1000;  // 失败后 1h cooldown
  const MAX_CONVO_CHARS = 80000;  // 发给 LLM 的 conversation 上限(#28)

  let ring = null;

  function historyChars(arr) {
    let sum = 0;
    for (const m of arr) {
      sum += (m.content || "").length;
      if (m.model_messages && Array.isArray(m.model_messages)) {
        for (const replay of m.model_messages) {
          if (replay?.role === "tool") sum += (replay.content || "").length;
          if (replay?.role === "assistant") {
            sum += (replay.reasoning_content || "").length;
            if (replay.tool_calls && Array.isArray(replay.tool_calls)) {
              sum += JSON.stringify(replay.tool_calls).length;
            }
          }
        }
      } else if (m._actions && Array.isArray(m._actions)) {
        for (const a of m._actions) {
          sum += JSON.stringify(a.result || "").length + JSON.stringify(a.args || "").length;
        }
      }
      if ((!m.model_messages || !Array.isArray(m.model_messages)) && m.reasoning_content) {
        sum += m.reasoning_content.length;
      }
    }
    return sum;
  }

  function getHistoryChars() {
    try {
      const context = window.gateway?.thread?.modelContext?.()
        || JSON.parse(localStorage.getItem(THREAD_KEY) || "[]");
      return historyChars(context);
    } catch (e) {
      return 0;
    }
  }

  // 一轮从 user 消息开始,包含其后的 assistant 消息。少于 5 轮时原样保留。
  function recentConversationStart(snapshot, keepTurns) {
    const userIndexes = [];
    for (let i = 0; i < snapshot.length; i++) {
      if (snapshot[i]?.role === "user") userIndexes.push(i);
    }
    if (userIndexes.length <= keepTurns) return 0;
    return userIndexes[userIndexes.length - keepTurns];
  }

  function createCompactCheckpoint(snapshot, summary, at) {
    summary = String(summary || "").trim();
    if (!summary) return null;
    return {
      summary,
      through: recentConversationStart(snapshot, 5),
      at: at || new Date().toISOString(),
    };
  }

  function injectRing() {
    const head = document.querySelector(".thread-head");
    if (!head || head.querySelector(".compact-ring")) return false;
    ring = document.createElement("div");
    ring.className = "compact-ring";
    ring.setAttribute("role", "button");
    ring.setAttribute("tabindex", "0");
    ring.setAttribute("aria-label", "整理对话历史");
    ring.style.cursor = "pointer";
    ring.addEventListener("click", runCompact);
    ring.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); runCompact(); }
    });
    // 插在 thread-status 后,thread-reset 前
    const reset = head.querySelector(".thread-reset");
    if (reset) head.insertBefore(ring, reset);
    else head.appendChild(ring);
    return true;
  }

  let running = false;
  async function runCompact(opts) {
    opts = opts || {};
    if (running) return;
    // workflow #14 #15 闭合:streaming 中按 ring 会撕掉正在写的 AI 回复,
    // streamMsgEl detached → 后续 delta 写到空指针,用户看到回复消失。
    // auto 模式之前已经在 tryAutoCompact 拦 isStreaming,手动 click 漏了一致 guard。
    if (isStreaming()) {
      window.gatewayToast?.("AI 还在回复,等它完了再整理。");
      return;
    }
    const chars = getHistoryChars();
    if (chars === 0) {
      window.gatewayToast?.("对话还空,先聊点东西再整理。");
      return;
    }
    // 拿 history 快照 — 30-90s LLM 跑期间用户可能继续聊新消息,
    // clear 时只清 cutoff 内的旧消息(#12)
    const arrSnapshot = window.gateway?.thread?.history?.()
      || JSON.parse(localStorage.getItem(THREAD_KEY) || "[]");
    const contextSnapshot = window.gateway?.thread?.modelContext?.() || arrSnapshot;
    // tail-truncate conversation 80K 字符防 deepseek context 爆(#28)
    let conversation = contextSnapshot.map(m => {
      const role = m.role === "user" ? "用户" : "AI";
      return `[${role}] ${(m.content || "").trim()}`;
    }).join("\n\n");
    if (conversation.length > MAX_CONVO_CHARS) {
      conversation = "[... 早期对话已省略 ...]\n\n" + conversation.slice(conversation.length - MAX_CONVO_CHARS);
    }

    if (!opts.skipConfirm) {
      const kChars = (chars / 1000).toFixed(1);
      // window.confirm 在 Tauri WKWebView 里默默返 false → 整个 compact 早期 return
      // 改用项目自实现的 gatewayConfirm(同 aggregate.js:98 用法,返 Promise<boolean>)
      const ok = await window.gatewayConfirm(
        `整理对话历史(${kChars}K 字符)?\n\n` +
        `系统会自动生成 3 份摘要:\n` +
        `  · 个人快照 — 你的当下状态\n` +
        `  · 项目快照 — 项目进展\n` +
        `  · 协作约定 — 团队规则\n\n` +
        `完成后完整历史仍可回看，AI 上下文会切换为摘要加最近 5 轮。`
      );
      if (!ok) return;
    }

    running = true;
    ring.classList.add("compact-ring-running");
    window.gatewayToast?.("整理中…大约 30-90 秒。");

    const targets = [
      { ep: "/api/pulse/user-update",          name: "USER_PULSE" },
      { ep: "/api/pulse/project-update",       name: "项目 PULSE" },
      { ep: "/api/pulse/agent-context-update", name: "AGENT_CONTEXT" },
    ];
    const results = await Promise.all(targets.map(async (t) => {
      try {
        const r = await fetch(t.ep, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation }),
        });
        const j = await r.json().catch(() => ({}));
        return { ...t, ok: r.ok && j.ok, status: r.status, detail: j };
      } catch (e) {
        return { ...t, ok: false, error: String(e) };
      }
    }));

    running = false;
    ring.classList.remove("compact-ring-running");

    const ok_count = results.filter(r => r.ok).length;
    if (ok_count === targets.length) {
      // 全成功 — 让 server LLM 产 200 字 summary，只推进模型上下文 checkpoint。
      // 完整 History 永不改写；最近 5 个 user-led 轮次继续逐字重放。
      let summary = "";
      try {
        const r = await fetch("/api/pulse/compact-summary", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation }),
        });
        if (r.ok) {
          const j = await r.json();
          summary = (j.summary || "").trim();
        }
      } catch (e) {
        console.warn("[compact-ring] summary fetch fail (skip)", e);
      }

      try {
        const checkpoint = createCompactCheckpoint(arrSnapshot, summary);
        if (!checkpoint) {
          if (opts.auto) {
            const fails = readFailCount() + 1;
            writeFailCount(fails);
            if (fails >= 2) localStorage.setItem(AUTO_COMPACT_KEY, "off");
          }
          window.gatewayToast?.("整理未完成 — 摘要生成失败,对话历史未动。");
          return;
        }

        if (!await window.gateway?.thread?.setCompactCheckpoint?.(checkpoint)) {
          window.gatewayToast?.("整理摘要生成了，但 checkpoint 保存失败；完整历史没动。");
          return;
        }
      } catch {}
      writeFailCount(0);
      update();
      window.gatewayToast?.(`整理完成 — 完整历史保留，AI 上下文已压缩。`);
    } else if (ok_count > 0) {
      const failed = results.filter(r => !r.ok).map(r => `${r.name}(${r.status || r.error || "?"})`);
      if (opts.auto) {
        const fails = readFailCount() + 1;
        writeFailCount(fails);
        if (fails >= 2) {
          // 失败 2+ 次自动关 auto,1h cooldown 已 wired(#22)
          localStorage.setItem(AUTO_COMPACT_KEY, "off");
          window.gatewayToast?.(`部分完成 — ${ok_count}/3。auto 关了(失败 ${fails} 次),下次手动点圆环再试。`);
        } else {
          window.gatewayToast?.(`部分完成 — ${ok_count}/3 成功。失败 ${fails} 次,1h 后再 auto。`);
        }
      } else {
        window.gatewayToast?.(`部分完成 — ${ok_count}/3 成功。失败:${failed.join(", ")}`);
      }
    } else {
      if (opts.auto) {
        writeFailCount(readFailCount() + 1);
        localStorage.setItem(AUTO_COMPACT_KEY, "off");
      }
      window.gatewayToast?.(`整理失败 — 0/3 成功,对话历史未动。看 server 日志。`);
    }
  }

  function update() {
    if (!ring && !injectRing()) return;
    const chars = getHistoryChars();
    const pct = Math.min(150, Math.round((chars / THRESHOLD_CHARS) * 100));
    let color = "var(--ring-ok, #8cab68)";
    if (pct >= 100) color = "var(--ring-over, #b85a3b)";
    else if (pct >= 80) color = "var(--ring-warn, #d49b3b)";
    ring.style.setProperty("--pct", Math.min(100, pct));
    ring.style.setProperty("--ring-color", color);
    const kChars = (chars / 1000).toFixed(1);
    const remaining = Math.max(0, 100 - pct);
    const autoOn = localStorage.getItem(AUTO_COMPACT_KEY) !== "off";  // 默认 on,显式 "off" 才关
    ring.title = `对话 ${kChars}K / 150K · ${pct}% · 还能写 ${remaining}%${autoOn ? " · 自动整理已启用" : ""}`;
    // 超过 100% 加 pulse 微动画 (CSS)
    ring.classList.toggle("compact-ring-over", pct >= 100);
    // 自动 compact:阈 ≥ 100% + 当前没在 streaming + cooldown 过 + 开关 on
    if (autoOn && pct >= 100) tryAutoCompact();
  }

  function isStreaming() {
    // 检测当前 thread 有没有 streaming 中的 message(thread.js 给元素加 .streaming 类)
    return !!document.querySelector(".msg.streaming, .thread-stream .streaming");
  }

  function readLastAutoFireAt() {
    const v = parseInt(localStorage.getItem(AUTO_FIRE_AT_KEY) || "0", 10);
    return Number.isFinite(v) ? v : 0;
  }
  function writeLastAutoFireAt(t) {
    try { localStorage.setItem(AUTO_FIRE_AT_KEY, String(t)); } catch {}
  }
  function readFailCount() {
    const v = parseInt(localStorage.getItem(AUTO_FAIL_COUNT_KEY) || "0", 10);
    return Number.isFinite(v) ? v : 0;
  }
  function writeFailCount(n) {
    try { localStorage.setItem(AUTO_FAIL_COUNT_KEY, String(n)); } catch {}
  }

  function tryAutoCompact() {
    if (running) return;
    const last = readLastAutoFireAt();
    const fails = readFailCount();
    const now = +new Date();
    // 失败 2+ 次,延长 cooldown 到 1h(#22)
    const cooldown = fails >= 2 ? AUTO_FAIL_COOLDOWN_MS : AUTO_FIRE_COOLDOWN_MS;
    if (now - last < cooldown) return;
    if (isStreaming()) return;  // 等 stream 完
    writeLastAutoFireAt(now);
    window.gatewayToast?.("对话过长,自动整理中…");
    runCompact({ skipConfirm: true, auto: true });
  }

  function boot() {
    update();
    setInterval(update, POLL_MS);
    window.addEventListener("storage", (e) => {
      if (e.key === THREAD_KEY) update();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.gateway = window.gateway || {};
  window.gateway.compactRing = { update, historyChars, createCompactCheckpoint };
})();
