/* compact-ring.js · 对话长度小圆环 — 跟 Claude Code 一样的视觉语言
 *
 * 显示:thread-head 里一颗小圆环,conic-gradient 填充表示当前 history 占
 *      compact 阈值的百分比。tooltip 显示精确数。
 * 颜色:< 80%  绿
 *      80-99% 黄
 *      ≥ 100% 朱红
 * 数据:localStorage 里的 thread.history.v1。content + _actions 累计字符。
 *      compact 后被动条会回弹。
 */
(function () {
  const THREAD_KEY = "gateway.thread.history.v1";
  const THRESHOLD_CHARS = 150000;  // ~75K tokens; 跟 chat 端 _trim_history_tool_volume + tool history 修后 5-10 轮深度大致对应
  const POLL_MS = 3000;
  // 自动 compact 开关 — 默认 off(用户主动开,设置面板未来可加 toggle);
  // 值在 localStorage,用户可手改 localStorage.setItem('gateway.compact.auto','on')
  const AUTO_COMPACT_KEY = "gateway.compact.auto";
  const AUTO_FIRE_COOLDOWN_MS = 10 * 60 * 1000;  // 一次成功后 10min 内不重复 fire
  let lastAutoFireAt = 0;

  let ring = null;

  function getHistoryChars() {
    try {
      const arr = JSON.parse(localStorage.getItem(THREAD_KEY) || "[]");
      let sum = 0;
      for (const m of arr) {
        sum += (m.content || "").length;
        if (m._actions && Array.isArray(m._actions)) {
          for (const a of m._actions) {
            sum += JSON.stringify(a.result || "").length + JSON.stringify(a.args || "").length;
          }
        }
        if (m.reasoning_content) sum += m.reasoning_content.length;
      }
      return sum;
    } catch (e) {
      return 0;
    }
  }

  function injectRing() {
    const head = document.querySelector(".thread-head");
    if (!head || head.querySelector(".compact-ring")) return false;
    ring = document.createElement("div");
    ring.className = "compact-ring";
    ring.setAttribute("role", "button");
    ring.setAttribute("tabindex", "0");
    ring.setAttribute("aria-label", "整理对话(更新 3 份 md + 重置历史)");
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
    const chars = getHistoryChars();
    if (chars === 0) {
      window.gatewayToast?.("对话还空,先聊点东西再整理。");
      return;
    }
    const arr = JSON.parse(localStorage.getItem(THREAD_KEY) || "[]");
    const conversation = arr.map(m => {
      const role = m.role === "user" ? "用户" : "AI";
      return `[${role}] ${(m.content || "").trim()}`;
    }).join("\n\n");

    if (!opts.skipConfirm) {
      const kChars = (chars / 1000).toFixed(1);
      const ok = window.confirm(
        `整理对话历史(${kChars}K 字符)?\n\n` +
        `LLM 会重写 3 份 md:\n` +
        `  · USER_PULSE — 你的当下快照\n` +
        `  · 项目 PULSE — 项目状态\n` +
        `  · AGENT_CONTEXT — vault 协作约定\n\n` +
        `完成后对话历史会重置,3 份 md 自动 backup + git。`
      );
      if (!ok) return;
    }

    running = true;
    ring.classList.add("compact-ring-running");
    window.gatewayToast?.("整理中...3 份 md 同时跑,大约 30-90 秒。");

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
      // 全成功 — 清 history + ring 自动回弹
      try { window.gateway?.thread?.clear?.(); } catch {}
      update();
      window.gatewayToast?.(`整理完成 — 3 份 md 已更新,对话历史重置。`);
    } else if (ok_count > 0) {
      const failed = results.filter(r => !r.ok).map(r => `${r.name}(${r.status || r.error || "?"})`);
      window.gatewayToast?.(`部分完成 — ${ok_count}/3 成功。失败:${failed.join(", ")}`);
    } else {
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
    const autoOn = localStorage.getItem(AUTO_COMPACT_KEY) === "on";
    ring.title = `对话 ${kChars}K / 150K · ${pct}% · 距离整理 ${remaining}%${autoOn ? " · 自动整理: 开" : ""}`;
    // 超过 100% 加 pulse 微动画 (CSS)
    ring.classList.toggle("compact-ring-over", pct >= 100);
    // 自动 compact:阈 ≥ 100% + 当前没在 streaming + cooldown 过 + 开关 on
    if (autoOn && pct >= 100) tryAutoCompact();
  }

  function isStreaming() {
    // 检测当前 thread 有没有 streaming 中的 message(thread.js 给元素加 .streaming 类)
    return !!document.querySelector(".msg.streaming, .thread-stream .streaming");
  }

  function tryAutoCompact() {
    if (running) return;
    if (Date.now() - lastAutoFireAt < AUTO_FIRE_COOLDOWN_MS) return;
    if (isStreaming()) return;  // 等 stream 完
    lastAutoFireAt = Date.now();
    // 用 toast 告知 user 自动开始(不弹 confirm — auto 模式就是 user 已授权)
    window.gatewayToast?.("对话超阈值,自动整理中…");
    runCompact({ skipConfirm: true });
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
  window.gateway.compactRing = { update };
})();
