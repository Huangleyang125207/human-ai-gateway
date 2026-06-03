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
          <h2>云端数据收集说明</h2>
          <p class="consent-sub">Gateway 默认收集两类匿名诊断数据,用于改进产品质量。两类数据可独立开关,默认启用,后续可在设置中随时撤回。</p>
        </header>

        <section class="consent-item">
          <label class="consent-check">
            <input type="checkbox" id="consent-failures" ${failuresOn ? 'checked' : ''}>
            <span class="consent-title">错误诊断</span>
          </label>
          <div class="consent-desc">
            <b>收集</b>:API 调用 / 识图 / 抠图 / 全文搜索 等操作失败时的错误码、调用元数据
            (模型标识、文件尺寸、网络层标记)。
            <br><b>不收集</b>:日记内容、对话记录、文件名、附件、密钥。
          </div>
        </section>

        <section class="consent-item">
          <label class="consent-check">
            <input type="checkbox" id="consent-heartbeat" ${heartbeatOn ? 'checked' : ''}>
            <span class="consent-title">使用统计(每日心跳)</span>
          </label>
          <div class="consent-desc">
            <b>收集</b>:应用版本、操作系统平台、UTC 时区偏移,每 24 小时一次。
            <br><b>不收集</b>:任何 vault 数据或可关联到个人身份的信息。
          </div>
        </section>

        <section class="consent-meta">
          <div><span class="consent-meta-k">接收端</span>腾讯云国内服务器(自托管),不接入第三方分析平台。</div>
          <div><span class="consent-meta-k">匿名标识</span><code>${state.client_id || '—'}</code> · 设备级 UUID,可随时重置或撤销</div>
          <div><span class="consent-meta-k">撤回入口</span>设置 → 数据 → 云上报</div>
        </section>

        <section class="consent-agreement" id="consent-agreement-box">
          <label class="consent-check">
            <input type="checkbox" id="consent-agreed">
            <span>我已阅读并同意
              <a href="/PRIVACY.md" target="_blank" rel="noopener">《隐私政策》</a>
              与
              <a href="/LICENSE" target="_blank" rel="noopener">《许可协议》</a>
            </span>
          </label>
        </section>

        <footer class="consent-actions">
          <button class="consent-btn consent-btn-secondary consent-btn-disabled" id="consent-deny">撤回全部</button>
          <button class="consent-btn consent-btn-primary consent-btn-disabled" id="consent-confirm">我已了解,启用</button>
        </footer>
      </div>
    `;

    function shakeAgreement() {
      const box = overlay.querySelector("#consent-agreement-box");
      box.classList.remove("consent-shake");
      // force reflow to restart animation
      void box.offsetWidth;
      box.classList.add("consent-shake");
    }
    function isAgreed() {
      return overlay.querySelector("#consent-agreed").checked;
    }
    function refreshButtonState() {
      const btns = overlay.querySelectorAll(".consent-btn");
      btns.forEach(b => b.classList.toggle("consent-btn-disabled", !isAgreed()));
    }
    overlay.querySelector("#consent-agreed").addEventListener("change", refreshButtonState);
    document.body.appendChild(overlay);

    overlay.querySelector("#consent-confirm").addEventListener("click", async () => {
      if (!isAgreed()) { shakeAgreement(); return; }
      const failures = overlay.querySelector("#consent-failures").checked;
      const heartbeat = overlay.querySelector("#consent-heartbeat").checked;
      await save(failures, heartbeat);
      close();
    });
    overlay.querySelector("#consent-deny").addEventListener("click", async () => {
      if (!isAgreed()) { shakeAgreement(); return; }
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
