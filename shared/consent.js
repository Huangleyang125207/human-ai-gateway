/* consent.js · 云上报知情同意 modal
 *
 * 出现时机:
 *   - page load 检 /api/telemetry/consent,needs_consent=true 才弹
 *   - 设置 → 数据 → 云上报 section 可以手动重开:window.gateway.consent.open()
 *
 * 收两类同意:
 *   - 错误上报 failures  (识图/抠图/搜索 等失败的错误码 + 简短上下文)
 *   - 使用心跳 heartbeat (每天一次,含版本/平台/时区)
 *
 * 文案铁律:"帮我们改进软件"。不写"改 bug",太窄。
 */
(function () {
  let overlay = null;

  async function checkAndShow() {
    try {
      const r = await fetch("/api/telemetry/consent");
      const s = await r.json();
      if (s.needs_consent) show(s);
    } catch (e) {
      console.warn("consent check failed:", e);
    }
  }

  async function open() {
    try {
      const r = await fetch("/api/telemetry/consent");
      const s = await r.json();
      show(s);
    } catch (e) {
      console.warn("consent open failed:", e);
    }
  }

  function show(state) {
    if (overlay) return;
    const failuresOn = state.failures !== false; // 默认 checkbox 勾上
    const heartbeatOn = state.heartbeat !== false;

    overlay = document.createElement("div");
    overlay.className = "consent-overlay";
    overlay.innerHTML = `
      <div class="consent-panel">
        <header class="consent-head">
          <h2>关于云上报</h2>
          <p class="consent-sub">默认收集两类数据,帮我们改进软件</p>
        </header>

        <section class="consent-item">
          <label class="consent-check">
            <input type="checkbox" id="consent-failures" ${failuresOn ? 'checked' : ''}>
            <span class="consent-title">错误上报</span>
          </label>
          <div class="consent-desc">
            识图 / 抠图 / 搜索 / API 调用 等失败的错误码 + 简短上下文
            (模型 id、文件大小、网络标记等,<b>不含</b> vault 内容、文件名、聊天内容)
          </div>
        </section>

        <section class="consent-item">
          <label class="consent-check">
            <input type="checkbox" id="consent-heartbeat" ${heartbeatOn ? 'checked' : ''}>
            <span class="consent-title">使用心跳</span>
          </label>
          <div class="consent-desc">
            每天一次,含:版本 / 平台(mac / win)/ 时区。
            用来看活跃用户和版本分布,<b>不含</b>任何 vault 数据。
          </div>
        </section>

        <section class="consent-meta">
          <div>匿名 ID:<code id="consent-cid">${state.client_id || '—'}</code></div>
          <div>上报端点:腾讯云国内服务器,数据只我们看,不卖不分享。</div>
          <div>以后可以在 <b>设置 → 数据 → 云上报</b> 修改或关闭。</div>
        </section>

        <footer class="consent-actions">
          <button class="consent-btn consent-btn-secondary" id="consent-deny">全部关闭</button>
          <button class="consent-btn consent-btn-primary" id="consent-confirm">同意,继续</button>
        </footer>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelector("#consent-confirm").addEventListener("click", async () => {
      const failures = overlay.querySelector("#consent-failures").checked;
      const heartbeat = overlay.querySelector("#consent-heartbeat").checked;
      await save(failures, heartbeat);
      close();
    });
    overlay.querySelector("#consent-deny").addEventListener("click", async () => {
      await save(false, false);
      close();
    });
  }

  async function save(failures, heartbeat) {
    try {
      await fetch("/api/telemetry/consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ failures, heartbeat }),
      });
    } catch (e) {
      console.warn("consent save failed:", e);
    }
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
  }

  // auto check on load — setup.js 走完后再轮 consent(setup-status 配完才进入正常流)
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(checkAndShow, 1500));
  } else {
    setTimeout(checkAndShow, 1500);
  }

  window.gateway = window.gateway || {};
  window.gateway.consent = { open, close, checkAndShow };
})();
