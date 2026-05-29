/**
 * Tauri webview `target="_blank"` 哑火兜底。
 *
 * WKWebView 不开新 window/tab,_blank anchor 静默失效。
 * 拦所有 _blank + http(s) 点击 → POST /api/open-external → server 调系统 open。
 * 真浏览器里跑这套代码也无害(走 server 比 _blank 多一跳但效果一样)。
 */
(function () {
  document.addEventListener(
    "click",
    async (e) => {
      const a = e.target.closest('a[target="_blank"]');
      if (!a) return;
      const href = a.href || "";
      if (!/^https?:\/\//i.test(href)) return; // 非 http(s) 不接管
      e.preventDefault();
      try {
        const r = await fetch("/api/open-external", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: href }),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          console.warn("open-external failed:", d);
        }
      } catch (err) {
        console.warn("open-external error:", err);
      }
    },
    true // capture 阶段 — 抢在其他 handler 之前
  );
})();
