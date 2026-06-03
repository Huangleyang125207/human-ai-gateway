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
    ring.setAttribute("role", "progressbar");
    ring.setAttribute("aria-label", "对话长度");
    // 插在 thread-status 后,thread-reset 前
    const reset = head.querySelector(".thread-reset");
    if (reset) head.insertBefore(ring, reset);
    else head.appendChild(ring);
    return true;
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
    ring.title = `对话 ${kChars}K / 150K · ${pct}% · 距离整理 ${remaining}%`;
    // 超过 100% 加 pulse 微动画 (CSS)
    ring.classList.toggle("compact-ring-over", pct >= 100);
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
