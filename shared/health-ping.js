/* health-ping.js · 每 30s ping /api/health;失败 2 次连续 → 顶部红 banner
 * 恢复后自动撤 banner。banner 自带 [刷新页面] 链接。
 */
(function () {
  const INTERVAL_MS = 30000;
  const TIMEOUT_MS = 5000;
  let consecutiveFails = 0;
  let banner = null;

  async function ping() {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
      const r = await fetch("/api/health", { signal: ctrl.signal });
      clearTimeout(t);
      if (!r.ok) throw new Error("not ok");
      consecutiveFails = 0;
      removeBanner();
    } catch {
      consecutiveFails++;
      if (consecutiveFails >= 2) showBanner();
    }
  }

  function showBanner() {
    if (banner) return;
    banner = document.createElement("div");
    banner.id = "healthBanner";
    banner.className = "health-banner";
    banner.innerHTML = `
      <span class="hb-icon">●</span>
      <span class="hb-text">连不上 server(可能进程崩了 / 端口被占)。功能全卡。</span>
      <a class="hb-action" href="/">刷新页面</a>
    `;
    document.body.insertBefore(banner, document.body.firstChild);
  }
  function removeBanner() {
    if (banner) { banner.remove(); banner = null; }
  }

  // 启动 5s 后开始 ping(让别的 init 先跑),之后每 30s
  setTimeout(() => {
    ping();
    setInterval(ping, INTERVAL_MS);
  }, 5000);

  // 切回 tab / focus 时立刻 ping 一次(用户 likely 想用)
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") ping();
  });
})();
