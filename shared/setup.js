/* setup.js — desktop DeepSeek BYOK setup. */
(function () {
  let overlay = null;
  let canClose = false;
  let hasKey = false;

  async function loadCurrent() {
    try {
      const r = await fetch("/api/setup/current");
      const current = await r.json();
      hasKey = !!current.has_deepseek_api_key;
    } catch {}
  }

  async function checkAndShow() {
    try {
      const r = await fetch("/api/setup-status");
      const status = await r.json();
      if (!status.configured) { canClose = false; await loadCurrent(); show(status.reason); }
    } catch (e) { console.warn("setup-status check failed:", e); }
  }

  async function showManual() { canClose = true; await loadCurrent(); show(null); }

  function show(reason) {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.className = "setup-overlay";
    overlay.innerHTML = `
      <div class="setup-panel">
        <header class="setup-head">
          <div class="setup-title">配置 · DeepSeek 直连</div>
          ${canClose ? '<button class="setup-close" aria-label="close" id="setupCloseBtn">×</button>' : '<span class="setup-locked" title="未配置完成不能关">🔒</span>'}
        </header>
        ${reason ? `<div class="setup-reason">⚠ ${escape(reason)}</div>` : ""}
        <div class="setup-body"><section class="setup-section setup-section-primary">
          <h3>对话与视觉 · <span class="setup-role">DeepSeek 直连</span></h3>
          <div class="setup-howto">在 DeepSeek 开放平台创建 API Key。密钥保存在本机，AI 请求直接发送到 DeepSeek，并由你的 DeepSeek 账户计费。</div>
          <div class="bailian-key-row"><label for="setupDeepSeekKey">DeepSeek API Key</label><input id="setupDeepSeekKey" type="password" autocomplete="off" spellcheck="false" placeholder="${hasKey ? "已保存；留空保留" : "粘贴你的 DeepSeek API Key"}"></div>
        </section></div>
        <footer class="setup-foot"><span class="setup-hint" id="setupHint"></span><button class="setup-save" id="setupSaveBtn">保存并启动</button></footer>
      </div>`;
    document.body.appendChild(overlay);
    if (canClose) document.getElementById("setupCloseBtn").addEventListener("click", close);
    document.getElementById("setupSaveBtn").addEventListener("click", save);
    document.getElementById("setupDeepSeekKey").addEventListener("input", refreshSaveState);
    refreshSaveState();
  }

  function refreshSaveState() {
    const ready = hasKey || !!document.getElementById("setupDeepSeekKey").value.trim();
    const button = document.getElementById("setupSaveBtn");
    const hint = document.getElementById("setupHint");
    if (button) button.disabled = !ready;
    if (hint) hint.textContent = ready ? "可以保存" : "填写 DeepSeek API Key 即可启用 AI";
  }

  async function save() {
    const key = document.getElementById("setupDeepSeekKey").value.trim();
    if (!key && !hasKey) return;
    const payload = key ? { api_key: key } : {};
    try {
      const r = await fetch("/api/setup/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const result = await r.json();
      if (result.ok) { canClose = true; close(); location.reload(); }
      else gatewayAlert("保存失败: " + (result.detail || JSON.stringify(result)));
    } catch (e) { gatewayAlert("保存请求失败: " + e.message); }
  }

  function close() { if (canClose) { overlay?.remove(); overlay = null; } }
  function escape(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => setTimeout(checkAndShow, 200));
  else setTimeout(checkAndShow, 200);
  window.gateway = window.gateway || {};
  window.gateway.setup = { open: showManual, close, checkAndShow };
})();
