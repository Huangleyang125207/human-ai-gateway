/* ctrl-c-v-bridge widget · v2 (M2)
 *
 * M1: 装机指引 (复制 2 条 /plugin 命令)
 * M2: 读 /api/pulse → 项目 PULSE dashboard (并列卡片,emoji + tagline + 心跳)
 */

(function () {
  const DISMISS_KEY = "gateway.ccvb.setup.dismissed";

  function init() {
    const setup = document.getElementById("ccvbSetup");
    const dismissBtn = document.getElementById("ccvbDismissSetup");
    if (!setup || !dismissBtn) return;

    // restore dismissed state
    if (localStorage.getItem(DISMISS_KEY) === "1") {
      setup.style.display = "none";
      dismissBtn.style.display = "none";
    }

    dismissBtn.addEventListener("click", () => {
      setup.style.display = "none";
      dismissBtn.style.display = "none";
      localStorage.setItem(DISMISS_KEY, "1");
      window.gatewayToast?.("已收起。要再看,刷新页或清 localStorage。");
    });

    // copy buttons
    document.querySelectorAll(".ccvb-copy").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sel = btn.dataset.copy;
        const codeEl = document.querySelector(sel);
        if (!codeEl) return;
        try {
          await navigator.clipboard.writeText(codeEl.textContent.trim());
          const orig = btn.textContent;
          btn.textContent = "✓ 已复制";
          setTimeout(() => { btn.textContent = orig; }, 1200);
        } catch (e) {
          window.gatewayToast?.("复制失败,手动选中再 ⌘C");
        }
      });
    });

    // PULSE dashboard
    loadPulse();
    document.getElementById("ccvbPulseRefresh")?.addEventListener("click", loadPulse);
  }

  async function loadPulse() {
    const grid = document.getElementById("ccvbPulseGrid");
    if (!grid) return;
    grid.innerHTML = '<div class="ccvb-pulse-loading">载入中⋯</div>';
    try {
      const r = await fetch("/api/pulse");
      const data = await r.json();
      const projects = data.projects || [];
      if (!projects.length) {
        grid.innerHTML = `<div class="ccvb-pulse-empty">${escape(data.warning || "暂无 PULSE 数据")}</div>`;
        return;
      }
      grid.innerHTML = "";
      for (const p of projects) {
        grid.appendChild(card(p));
      }
    } catch (e) {
      grid.innerHTML = `<div class="ccvb-pulse-empty">载入失败: ${escape(e.message)}</div>`;
    }
  }

  function card(p) {
    const el = document.createElement("article");
    el.className = "ccvb-card folded";
    const hbHtml = (p.heartbeat || []).slice(0, 5).map(h => `<li>${escape(h)}</li>`).join("");
    el.innerHTML = `
      <div class="ccvb-card-row" role="button" tabindex="0">
        <span class="ccvb-card-emoji">${p.status_emoji || "·"}</span>
        <span class="ccvb-card-name">${escape(p.name)}</span>
        <span class="ccvb-card-refreshed">${p.last_refreshed || "—"}</span>
        <span class="ccvb-card-chevron">›</span>
      </div>
      <div class="ccvb-card-expanded">
        ${p.tagline ? `<div class="ccvb-card-tagline">${escape(p.tagline)}</div>` : ""}
        ${hbHtml ? `<ul class="ccvb-card-heartbeat">${hbHtml}</ul>` : ""}
        <button class="ccvb-card-detail" data-name="${escape(p.name)}">详情 →</button>
      </div>
    `;
    const row = el.querySelector(".ccvb-card-row");
    row.addEventListener("click", () => el.classList.toggle("folded"));
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        el.classList.toggle("folded");
      }
    });
    el.querySelector(".ccvb-card-detail")?.addEventListener("click", (e) => {
      e.stopPropagation();
      openDetail(p.name);
    });
    return el;
  }

  async function openDetail(name) {
    try {
      const r = await fetch(`/api/pulse/${encodeURIComponent(name)}`);
      if (!r.ok) {
        window.gatewayToast?.(`详情拉取失败 (${r.status})`);
        return;
      }
      const data = await r.json();
      showDetailModal(data.name, data.markdown || "");
    } catch (e) {
      window.gatewayToast?.("详情拉取失败: " + e.message);
    }
  }

  function showDetailModal(name, markdown) {
    const overlay = document.createElement("div");
    overlay.className = "ccvb-detail-overlay";
    overlay.innerHTML = `
      <div class="ccvb-detail-panel">
        <header class="ccvb-detail-head">
          <span class="ccvb-detail-title">${escape(name)} · PULSE</span>
          <button class="ccvb-detail-close" aria-label="close">×</button>
        </header>
        <div class="ccvb-detail-body">${renderMd(markdown)}</div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector(".ccvb-detail-close").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", function onEsc(e) {
      if (e.key === "Escape") {
        close();
        document.removeEventListener("keydown", onEsc);
      }
    });
  }

  function renderMd(text) {
    // 走全局 gatewayMd (marked + DOMPurify),fallback 到 escape
    return window.gatewayMd
      ? window.gatewayMd(text)
      : escape(text).replace(/\n/g, "<br>");
  }

  function escape(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
