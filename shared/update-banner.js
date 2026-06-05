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
    restartBtn.addEventListener("click", async () => {
      restartBtn.disabled = true;
      restartBtn.textContent = "重启中…";
      // 优先 Tauri 2 process plugin:withGlobalTauri=true + capabilities remote URLs 后,
      // window.__TAURI__ 暴露在 webview。invoke('plugin:process|restart') 是 Tauri 2 调用。
      const tauri = window.__TAURI__;
      try {
        if (tauri?.core?.invoke) {
          await tauri.core.invoke("plugin:process|restart");
          return;
        }
        if (tauri?.process?.relaunch) {
          await tauri.process.relaunch();
          return;
        }
      } catch (e) {
        console.warn("[update-banner] Tauri relaunch 失败,走 fallback", e);
      }
      // Fallback:让 sidecar 退出,Tauri 检测 sidecar 死 → 触发 app 退出 → 用户手动重开
      try {
        await fetch("/api/quit", { method: "POST" });
        msg.textContent = "Gateway 已关闭,请手动重开";
      } catch (e) {
        msg.textContent = "请手动退出 Gateway 后重开,新版才生效";
        restartBtn.disabled = false;
        restartBtn.textContent = "立即重启";
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
        } else if (n.kind === "vault-schema-bumped") {
          // sha256 一致 → marker only:passive 通知,内容没变
          window.gatewayToast?.(n.message);
          dismissKinds.push("vault-schema-bumped");
        } else if (n.kind === "vault-schema-migrated") {
          // auto-merge:LLM 重写后直接覆盖真源,5 份 bak 兜底
          window.gatewayToast?.(n.message);
          dismissKinds.push("vault-schema-migrated");
        } else if (n.kind === "vault-schema-migration-skip-external-edit") {
          // 锁内重读发现 vault 被外部编辑,跳过 merge 保留手编
          window.gatewayToast?.(n.message);
          dismissKinds.push("vault-schema-migration-skip-external-edit");
        } else if (n.kind === "vault-schema-migration-failed") {
          window.gatewayToast?.(n.message);
          dismissKinds.push("vault-schema-migration-failed");
        } else if (n.kind === "vault-reference-bootstrapped") {
          window.gatewayToast?.(n.message);
          dismissKinds.push("vault-reference-bootstrapped");
        } else if (n.kind === "pulse-skip-external-edit") {
          window.gatewayToast?.(n.message);
          dismissKinds.push("pulse-skip-external-edit");
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
