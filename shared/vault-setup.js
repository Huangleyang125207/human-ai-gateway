/* vault-setup.js · Obsidian-style vault picker
 *
 * 触发:
 *   - page load 检 /api/vault,setup_required=true → 强弹 modal 不可关
 *   - 设置面板里手动重开切换 vault
 *
 * 流程:
 *   1. 列 Obsidian 已知 vaults(自动 detect)
 *   2. 列已知 known_vaults(本 app 之前用过的)
 *   3. 让用户输自定义路径
 *   4. POST /api/vault/set → 提示重启 server
 */
(function () {
  let overlay = null;

  async function checkAndShow() {
    try {
      const r = await fetch("/api/vault");
      const s = await r.json();
      if (s.setup_required) {
        await show({force: true, current: s.active_vault});
      }
    } catch (e) {
      console.warn("vault status check failed", e);
    }
  }

  async function fetchObsidian() {
    try {
      const r = await fetch("/api/vault/discover_obsidian");
      const d = await r.json();
      return d.vaults || [];
    } catch { return []; }
  }

  async function show({force, current}) {
    if (overlay) return;
    const obsidian = await fetchObsidian();
    overlay = document.createElement("div");
    overlay.className = "vault-setup-overlay";
    overlay.innerHTML = `
      <div class="vault-setup-modal">
        <h2>选个 vault</h2>
        <p class="vault-setup-hint">
          gateway 把日记 / 图 / 配置都放这个文件夹里。<br>
          推荐选你已有的 Obsidian vault 路径,这样 Obsidian 跟 gateway 看的就是同一份数据。
        </p>
        ${obsidian.length ? `
          <div class="vault-section">
            <div class="vault-section-label">从 Obsidian 检测到</div>
            <div class="vault-list" id="vsObsidian">
              ${obsidian.map(v => `
                <button class="vault-item${v.currently_open ? ' currently-open' : ''}" data-path="${escapeHtml(v.path)}">
                  <span class="vault-name">${escapeHtml(v.name)}${v.currently_open ? ' · 当前打开' : ''}</span>
                  <span class="vault-path">${escapeHtml(v.path)}</span>
                </button>
              `).join("")}
            </div>
          </div>
        ` : ""}
        <div class="vault-section">
          <div class="vault-section-label">手动指定路径</div>
          <div class="vault-row">
            <input class="vault-path-input" id="vsPath" type="text" placeholder="${current ? escapeHtml(current) : "/Users/you/Documents/我的日记"}" value="${current ? escapeHtml(current) : ""}">
            <button class="vault-set" id="vsSet">用这个</button>
          </div>
        </div>
        <div class="vault-msg" id="vsMsg"></div>
        ${force ? "" : `<button class="vault-cancel" id="vsCancel">取消</button>`}
      </div>
    `;
    document.body.appendChild(overlay);

    const $msg = overlay.querySelector("#vsMsg");
    const $path = overlay.querySelector("#vsPath");
    const $set = overlay.querySelector("#vsSet");
    const $cancel = overlay.querySelector("#vsCancel");

    [...overlay.querySelectorAll(".vault-item")].forEach(btn => {
      btn.addEventListener("click", () => commit(btn.dataset.path, $msg));
    });
    $set.addEventListener("click", () => commit(($path.value || "").trim(), $msg));
    $path.addEventListener("keydown", (e) => { if (e.key === "Enter") $set.click(); });
    if ($cancel) $cancel.addEventListener("click", () => close());
  }

  async function commit(path, $msg) {
    if (!path) { $msg.textContent = "请输路径或选一个 obsidian vault"; return; }
    $msg.textContent = "保存中⋯";
    try {
      const r = await fetch("/api/vault/set", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path}),
      });
      const d = await r.json();
      if (d.detail || d.error) { $msg.textContent = "失败: " + (d.detail || d.error); return; }
      if (d.needs_restart) {
        $msg.innerHTML = "✓ 已保存。<b>请重启 gateway server(关掉 python3 server.py 重开)</b>,然后刷新本页。";
      } else {
        $msg.textContent = "✓ vault 已确认,刷新页面。";
        setTimeout(() => location.reload(), 800);
      }
    } catch (e) {
      $msg.textContent = "失败: " + e.message;
    }
  }

  function close() {
    if (overlay) { overlay.remove(); overlay = null; }
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
    );
  }

  window.gateway = window.gateway || {};
  window.gateway.vaultSetup = { check: checkAndShow, openSwitcher: () => show({force: false}) };

  // page load 自动 check
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", checkAndShow);
  } else {
    checkAndShow();
  }
})();
