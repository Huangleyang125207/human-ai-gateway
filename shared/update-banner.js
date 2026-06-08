/* update-banner.js · 自动更新 3 步 timeline banner + vault schema 迁移 toast
 *
 * v0.1.25 起 Tauri 主进程 emit `updater://progress` 事件,前端 listen 并渲染
 * 3 步 timeline:① 下载 ② 安装 ③ MD 迁移(重启后)。
 * 收起态在窗口顶部留一条 24px 条,点击展回完整 banner。
 *
 * v0.1.23 老路径保留:30s poll /api/notifications,处理 `updater-installed` /
 * `vault-schema-*` 等 kind。
 *
 * step 状态(对齐 lib.rs):
 *   found          — 检测到新版,准备下载
 *   download       — 正在下载,payload = {bytes, total}
 *   install        — 下载完毕,正在装
 *   ready_restart  — 装完,等用户点重启
 *   error          — 任一阶段失败,payload = {stage, message}
 *   migrating      — 重启后 sidecar SSE 推(T-F 接)
 *   migrated       — 迁移完毕(T-F 接)
 *
 * T-B 范围:timeline 骨架 + 收起态 + Step 1 渲染。Step 2/3 在 T-F、error UI 在 T-G。
 */
(function () {
  const POLL_MS = 30000;
  const FIRST_POLL_MS = 1500;
  const seenKinds = new Set();
  const state = {
    visible: false,
    collapsed: false,
    step: null,            // 当前 step
    version: null,
    bytes: 0,
    total: null,
    errorMessage: null,
  };
  let rootEl = null;

  // ─── DOM 构建 ────────────────────────────────────────────────

  function ensureRoot() {
    if (rootEl) return rootEl;
    rootEl = document.createElement("div");
    rootEl.className = "gateway-update-root";
    rootEl.style.cssText = [
      "position:fixed", "top:0", "left:0", "right:0", "z-index:9999",
      "background:#3b6f4a", "color:#f5efe0",
      "font-family:inherit", "font-size:14px",
      "box-shadow:0 2px 8px rgba(0,0,0,0.2)",
      "display:none",
      "transition:max-height 0.2s ease",
      "overflow:hidden",
    ].join(";");
    document.body.appendChild(rootEl);
    return rootEl;
  }

  function fmtBytes(n) {
    if (n == null) return "?";
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function stepLabel(step) {
    return {
      found: "检测到新版",
      download: "Step 1 · 下载",
      install: "Step 2 · 安装",
      ready_restart: "下载完成,等重启",
      migrating: "Step 3 · MD 迁移",
      migrated: "全部完成",
      error: "出错了",
    }[step] || step || "";
  }

  function progressPct() {
    if (!state.total || state.bytes <= 0) return 0;
    return Math.min(100, (state.bytes / state.total) * 100);
  }

  // 收起态:一条 24px 高的条,显当前 step + 进度
  function renderCollapsed() {
    const pct = progressPct();
    const ver = state.version ? ` v${state.version}` : "";
    return `
      <div style="display:flex; align-items:center; gap:10px; padding:4px 14px; cursor:pointer; height:24px; font-size:12px;"
           data-action="expand"
           title="点击展开">
        <span style="opacity:0.85;">Gateway${ver}</span>
        <span style="opacity:0.95;">${stepLabel(state.step)}</span>
        ${state.step === "download" ? `<span style="opacity:0.7;">${pct.toFixed(0)}%</span>` : ""}
        <span style="margin-left:auto; opacity:0.7;">▾</span>
      </div>`;
  }

  // 展开态:timeline + 当前 step 详情 + 进度条
  function renderExpanded() {
    const steps = [
      { key: "download", label: "下载" },
      { key: "install",  label: "安装" },
      { key: "migrating", label: "MD 迁移" },
    ];
    const currentIdx = (() => {
      if (state.step === "download" || state.step === "found") return 0;
      if (state.step === "install") return 1;
      if (state.step === "ready_restart") return 1; // 装完,等重启:Step 2 完
      if (state.step === "migrating") return 2;
      if (state.step === "migrated") return 3;
      return -1;
    })();
    const dotsHtml = steps.map((s, i) => {
      const isDone = i < currentIdx || state.step === "migrated";
      const isActive = i === currentIdx && state.step !== "migrated";
      const bg = isDone ? "#a3d9a5" : isActive ? "#f5efe0" : "rgba(245,239,224,0.3)";
      const fg = isDone || isActive ? "#3b6f4a" : "#f5efe0";
      const mark = isDone ? "✓" : (i + 1);
      return `
        <span style="display:flex; align-items:center; gap:6px;">
          <span style="display:inline-flex; align-items:center; justify-content:center;
                       width:22px; height:22px; border-radius:50%;
                       background:${bg}; color:${fg}; font-weight:600; font-size:12px;">${mark}</span>
          <span style="opacity:${isActive ? "1" : "0.7"};">${s.label}</span>
        </span>
        ${i < steps.length - 1 ? '<span style="opacity:0.4; padding:0 4px;">───</span>' : ""}`;
    }).join("");

    const pct = progressPct();
    let stepDetailHtml = "";
    if (state.step === "found") {
      stepDetailHtml = `<div style="opacity:0.85;">即将下载新版 v${state.version}</div>`;
    } else if (state.step === "download") {
      stepDetailHtml = `
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="flex:1; height:6px; background:rgba(245,239,224,0.25); border-radius:3px; overflow:hidden;">
            <div style="height:100%; width:${pct}%; background:#f5efe0; transition:width 0.3s;"></div>
          </div>
          <span style="font-variant-numeric:tabular-nums; opacity:0.9; font-size:12px;">
            ${fmtBytes(state.bytes)} / ${fmtBytes(state.total)} (${pct.toFixed(1)}%)
          </span>
        </div>`;
    } else if (state.step === "install") {
      stepDetailHtml = `<div style="opacity:0.85;">下载完毕,正在安装到 /Applications…</div>`;
    } else if (state.step === "ready_restart") {
      // T-F 完整接,这里先占位
      stepDetailHtml = `<div style="opacity:0.85;">v${state.version} 已下载,重启 app 生效。</div>`;
    } else if (state.step === "error") {
      stepDetailHtml = `<div style="opacity:0.9; color:#ffcccc;">${state.errorMessage || "出错了"}</div>`;
    }

    return `
      <div style="padding:12px 16px;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
          <div style="display:flex; align-items:center; gap:0; font-size:13px;">
            ${dotsHtml}
          </div>
          <span data-action="collapse" style="cursor:pointer; opacity:0.7; font-size:18px; padding:0 4px;" title="收起">▴</span>
        </div>
        ${stepDetailHtml}
      </div>`;
  }

  function render() {
    if (!state.visible) {
      if (rootEl) rootEl.style.display = "none";
      return;
    }
    const el = ensureRoot();
    el.style.display = "block";
    el.innerHTML = state.collapsed ? renderCollapsed() : renderExpanded();
    // delegate clicks
    el.querySelectorAll("[data-action]").forEach((node) => {
      node.addEventListener("click", (ev) => {
        const action = node.getAttribute("data-action");
        if (action === "expand") { state.collapsed = false; render(); }
        else if (action === "collapse") { state.collapsed = true; render(); }
      });
    });
  }

  // ─── 状态更新入口 ────────────────────────────────────────────

  function onProgress(payload) {
    if (!payload || typeof payload !== "object") return;
    const { step } = payload;
    state.visible = true;
    state.step = step || state.step;
    if (payload.version) state.version = payload.version;
    if (step === "download") {
      if (typeof payload.bytes === "number") state.bytes = payload.bytes;
      if (typeof payload.total === "number") state.total = payload.total;
    }
    if (step === "error") {
      state.errorMessage = payload.message ? `${payload.stage || ""}: ${payload.message}` : "出错了";
    }
    render();
  }

  // ─── Tauri events ────────────────────────────────────────────

  function bindTauriEvents() {
    const tauri = window.__TAURI__;
    const listenFn = tauri?.event?.listen;
    if (!listenFn) return;
    try {
      listenFn("updater://progress", (ev) => onProgress(ev.payload));
    } catch (e) {
      console.warn("[update-banner] Tauri event listen 失败", e);
    }
  }

  // ─── 老路径:notification poll(updater-installed / vault-schema-*) ─

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
          // 老 v0.1.23 silent updater 装完路径:把 banner 推到 ready_restart 状态
          onProgress({ step: "ready_restart", version: n.payload?.version || "新版" });
          dismissKinds.push("updater-installed");
        } else if (
          n.kind === "vault-schema-bumped" ||
          n.kind === "vault-schema-migrated" ||
          n.kind === "vault-schema-migration-skip-external-edit" ||
          n.kind === "vault-schema-migration-failed" ||
          n.kind === "vault-reference-bootstrapped" ||
          n.kind === "pulse-skip-external-edit"
        ) {
          window.gatewayToast?.(n.message);
          dismissKinds.push(n.kind);
        }
      }
      if (dismissKinds.length) {
        fetch("/api/notifications?dismiss=" + encodeURIComponent(dismissKinds.join(",")), {
          cache: "no-store",
        }).catch(() => {});
      }
    } catch (e) {
      // network blip
    }
  }

  function boot() {
    bindTauriEvents();
    setTimeout(poll, FIRST_POLL_MS);
    setInterval(poll, POLL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
