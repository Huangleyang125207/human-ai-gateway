/* update-banner.js · 自动更新 + vault schema 迁移 通知 banner
 *
 * 30s poll /api/notifications,见特定 kind 显示顶部 banner / toast。
 * 显示后通过 ?dismiss=kind 一次性清掉(server 侧 dequeue)。
 *
 * 处理 kind:
 *   - updater-installed         → 顶部 sticky banner "新版 vX 已下载,重启生效"
 *                                  + 「立即重启」按钮(尝试调 Tauri quit + relaunch)
 *   - vault-schema-migrated     → toast (passive)
 *   - vault-schema-migration-failed → toast (warn)
 */
(function () {
  const POLL_MS = 30000;
  const FIRST_POLL_MS = 1500;   // 启动 1.5s 后第一次 poll(让 sidecar 起来)
  let bannerEl = null;
  let seenKinds = new Set();    // 同 kind 同 ts 不要重复显示

  function ensureBanner() {
    if (bannerEl) return bannerEl;
    bannerEl = document.createElement("div");
    bannerEl.className = "gateway-update-banner";
    bannerEl.style.cssText = [
      "position:fixed", "top:0", "left:0", "right:0", "z-index:9999",
      "background:#3b6f4a", "color:#f5efe0", "font-family:inherit",
      "padding:10px 16px", "display:none", "align-items:center",
      "justify-content:space-between", "gap:12px",
      "box-shadow:0 2px 8px rgba(0,0,0,0.2)",
      "font-size:14px",
    ].join(";");
    document.body.appendChild(bannerEl);
    return bannerEl;
  }

  function showUpdateBanner(version) {
    const el = ensureBanner();
    el.innerHTML = "";
    const msg = document.createElement("span");
    msg.textContent = `Gateway ${version} 已下载,重启 app 生效`;
    const btnGroup = document.createElement("span");
    btnGroup.style.cssText = "display:flex; gap:8px;";
    const restartBtn = document.createElement("button");
    restartBtn.textContent = "立即重启";
    restartBtn.style.cssText = "background:#f5efe0; color:#3b6f4a; border:0; padding:6px 14px; border-radius:4px; cursor:pointer; font-weight:600;";
    restartBtn.addEventListener("click", () => {
      restartBtn.disabled = true;
      restartBtn.textContent = "重启中…";
      // Tauri 2 process plugin:relaunch
      try {
        // 优先用 @tauri-apps/api 暴露(若有)
        const tauriProcess = window.__TAURI__?.process;
        if (tauriProcess?.relaunch) {
          tauriProcess.relaunch();
          return;
        }
        // fallback:让 sidecar 关闭进程,Tauri 单实例会启动一次新的
        fetch("/api/quit", { method: "POST" }).catch(() => {});
      } catch (e) {
        console.warn("[update-banner] relaunch fail", e);
      }
    });
    const laterBtn = document.createElement("button");
    laterBtn.textContent = "稍后";
    laterBtn.style.cssText = "background:transparent; color:#f5efe0; border:1px solid rgba(245,239,224,0.5); padding:6px 14px; border-radius:4px; cursor:pointer;";
    laterBtn.addEventListener("click", () => { el.style.display = "none"; });
    btnGroup.appendChild(restartBtn);
    btnGroup.appendChild(laterBtn);
    el.appendChild(msg);
    el.appendChild(btnGroup);
    el.style.display = "flex";
  }

  async function poll() {
    try {
      const r = await fetch("/api/notifications", { cache: "no-store" });
      if (!r.ok) return;
      const j = await r.json();
      const list = Array.isArray(j.notifications) ? j.notifications : [];
      const dismissKinds = [];
      for (const n of list) {
        const key = `${n.kind}::${n.ts}`;
        if (seenKinds.has(key)) continue;
        seenKinds.add(key);
        if (n.kind === "updater-installed") {
          const v = n.payload?.version || "新版";
          showUpdateBanner(v);
          dismissKinds.push("updater-installed");
        } else if (n.kind === "vault-schema-migrated") {
          window.gatewayToast?.(n.message);
          dismissKinds.push("vault-schema-migrated");
        } else if (n.kind === "vault-schema-migration-failed") {
          window.gatewayToast?.(n.message + "(看 server log)");
          dismissKinds.push("vault-schema-migration-failed");
        }
      }
      if (dismissKinds.length) {
        fetch("/api/notifications?dismiss=" + encodeURIComponent(dismissKinds.join(",")), {
          cache: "no-store",
        }).catch(() => {});
      }
    } catch (e) {
      // network blip,下次再 poll
    }
  }

  function boot() {
    setTimeout(poll, FIRST_POLL_MS);
    setInterval(poll, POLL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
