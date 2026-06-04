/* consent.js · 隐私协议同意 modal
 *
 * 出现时机:
 *   - 首启动 + localStorage 没标记 → 弹一次
 *   - 设置里"撤回隐私同意" → 清 localStorage + 把 telemetry 关 → 下次首启动重弹
 *   - 手动:window.gateway.consent.open()
 *
 * 同意 = 默认开启两类匿名诊断(错误诊断 + 每日心跳),帮我们改进软件。
 *   - 设置里可整体撤回(撤回 = failures + heartbeat 全关)
 *   - 不再细粒度勾选每一类 — 用户只决定"要不要装在这台机器上"这一个选项
 *
 * 文案铁律:"帮我们改进软件"。不写"改 bug",太窄。
 */
(function () {
  let overlay = null;
  const LS_KEY = "gateway.consent.agreed.v2";

  async function checkAndShow() {
    // localStorage 兜底:同意过的本地标记一次,page reload / 填完 key 后不会再弹。
    // server 端持久化偶发丢(容器重建 / config 路径问题)时也兜得住。
    if (localStorage.getItem(LS_KEY) === "1") return;
    try {
      const r = await fetch("/api/telemetry/consent");
      const s = await r.json();
      if (s.needs_consent) show(s);
      else localStorage.setItem(LS_KEY, "1");  // server 说不需要 = 同意过,本地也标
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

    overlay = document.createElement("div");
    overlay.className = "consent-overlay";
    overlay.innerHTML = `
      <div class="consent-panel">
        <header class="consent-head">
          <h2>云端数据收集说明</h2>
          <p class="consent-sub">Gateway 默认收集两类匿名诊断数据,帮我们改进软件。同意后两类全开,后续可在设置中随时撤回。</p>
        </header>

        <section class="consent-item">
          <div class="consent-title">错误诊断</div>
          <div class="consent-desc">
            <b>收集</b>:API 调用 / 识图 / 抠图 / 全文搜索 等操作失败时的错误码、调用元数据
            (模型标识、文件尺寸、网络层标记)。
            <br><b>不收集</b>:日记内容、对话记录、文件名、附件、密钥。
          </div>
        </section>

        <section class="consent-item">
          <div class="consent-title">使用统计(每日心跳)</div>
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
          <button class="consent-btn consent-btn-secondary consent-btn-disabled" id="consent-deny">不参与</button>
          <button class="consent-btn consent-btn-primary consent-btn-disabled" id="consent-confirm">同意并启用</button>
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
      // 同意 = 两类全开
      await save(true, true);
      localStorage.setItem(LS_KEY, "1");
      close();
    });
    overlay.querySelector("#consent-deny").addEventListener("click", async () => {
      if (!isAgreed()) { shakeAgreement(); return; }
      // 不参与 = 两类全关,但隐私协议本身已勾,不会再弹
      await save(false, false);
      localStorage.setItem(LS_KEY, "1");
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
