/* marketplace.js · gateway 设置面板(tabbed)
 *
 * 入口: header 的 ⚙ icon (id="marketBtn")
 * 两 tab:
 *   1. 插件市场 — widget catalog,GET /api/widgets/catalog
 *   2. API 钥匙 — DeepSeek (chat + vision) + 百度抠图 (可选) 配置,GET /api/setup/current
 *   3. 数据 — 训练语料浏览/导出(history.html)+ 训练授权(consent.html)+ 云上报开关(/api/telemetry/consent)
 */

(function () {
  const btn = document.getElementById("marketBtn");
  if (!btn) return;

  let overlay = null;
  let activeTab = "widgets";   // "widgets" | "keys" | "corpus"

  async function open(initialTab) {
    if (overlay) return;
    activeTab = initialTab || "widgets";
    renderShell();
    await loadActiveTab();
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
  }

  function renderShell() {
    overlay = document.createElement("div");
    overlay.className = "market-overlay";
    overlay.innerHTML = `
      <div class="market-panel">
        <header class="market-head">
          <div class="market-title">设置</div>
          <button class="market-close" id="marketClose" aria-label="close">×</button>
        </header>
        <nav class="market-tabs">
          <button class="market-tab${activeTab==='widgets' ? ' on':''}" data-tab="widgets">插件市场</button>
          <button class="market-tab${activeTab==='keys' ? ' on':''}" data-tab="keys">API 钥匙</button>
          <button class="market-tab${activeTab==='corpus' ? ' on':''}" data-tab="corpus">数据</button>
          <button class="market-tab${activeTab==='about' ? ' on':''}" data-tab="about">关于</button>
        </nav>
        <div class="market-body" id="marketBody"></div>
      </div>
    `;
    document.body.appendChild(overlay);
    document.getElementById("marketClose").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey);
    [...overlay.querySelectorAll(".market-tab")].forEach(t => {
      t.addEventListener("click", async () => {
        activeTab = t.dataset.tab;
        [...overlay.querySelectorAll(".market-tab")].forEach(x => x.classList.toggle("on", x.dataset.tab === activeTab));
        await loadActiveTab();
      });
    });
  }

  async function loadActiveTab() {
    const body = document.getElementById("marketBody");
    body.innerHTML = '<div class="market-loading">⋯</div>';
    if (activeTab === "widgets") {
      const resp = await fetch("/api/widgets/catalog");
      const data = await resp.json();
      renderWidgets(data.widgets || []);
    } else if (activeTab === "corpus") {
      renderCorpus();
    } else if (activeTab === "about") {
      renderAbout();
    } else {
      const resp = await fetch("/api/setup/current");
      const cfg = await resp.json();
      renderKeys(cfg);
    }
  }

  async function renderAbout() {
    const body = document.getElementById("marketBody");
    let ver = "⋯";
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      ver = (await r.json()).version || "?";
    } catch (e) { ver = "?"; }
    // 只有 Tauri 桌面壳里才有自动更新;浏览器/dev 模式没有 __TAURI__
    const tauri = window.__TAURI__;
    const canUpdate = !!(tauri && tauri.core && tauri.core.invoke);
    body.innerHTML = `
      <div class="market-hint">数据 100% 留在你电脑(~/.human-ai/vault/),Obsidian 兼容。这是人 + AI 共写日记的本地优先桌面应用。</div>
      <div class="market-section" style="padding:14px 0;">
        <h3>版本</h3>
        <p style="margin:6px 0;">当前版本 <b>v${ver}</b></p>
        ${canUpdate ? `
          <button class="key-add-btn" id="checkUpdateBtn">检查更新</button>
          <span id="checkUpdateStatus" style="margin-left:10px;font-size:12px;color:var(--ink-4,#8a7f72);"></span>
        ` : `
          <p style="font-size:12px;color:var(--ink-4,#8a7f72);">自动更新仅桌面版支持。浏览器里打开请到下载页拿最新版。</p>
        `}
      </div>
    `;
    if (!canUpdate) return;
    const btn = document.getElementById("checkUpdateBtn");
    const status = document.getElementById("checkUpdateStatus");
    let unlisten = null;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      status.textContent = "检查中⋯";
      // 监听一次结果:有新版 → banner 接管下载;无新版 → "已是最新";出错 → 显错
      try {
        if (tauri.event && tauri.event.listen) {
          unlisten = await tauri.event.listen("updater://progress", (ev) => {
            const step = ev.payload && ev.payload.step;
            if (step === "uptodate") { status.textContent = "已是最新版本 ✓"; btn.disabled = false; }
            else if (step === "found") { status.textContent = "发现新版,开始下载⋯"; }
            else if (step === "error") { status.textContent = "检查失败,稍后再试"; btn.disabled = false; }
          });
        }
        await tauri.core.invoke("check_updates_now");
        // 兜底:8s 没任何事件回来(理论不会)→ 解锁按钮
        setTimeout(() => { if (btn.disabled && status.textContent === "检查中⋯") { status.textContent = ""; btn.disabled = false; } }, 8000);
      } catch (e) {
        status.textContent = "检查失败:" + (e && e.message ? e.message : e);
        btn.disabled = false;
      }
    });
  }

  async function renderCorpus() {
    const body = document.getElementById("marketBody");
    body.innerHTML = '<div class="market-loading">⋯</div>';
    let telemetry = {};
    try {
      const r = await fetch("/api/telemetry/consent");
      telemetry = await r.json();
    } catch (e) { /* keep empty */ }

    body.innerHTML = `
      <div class="market-hint">
        你的日记笔记是这个产品的"训练数据",存在你的电脑里,用来持续改进 AI 回复——
        每一条笔记都记录了作者信息,可用于训练改进,可用于 AI 训练,也是你的备份。
        训练语料全部在你机器上,不传第三方。
      </div>

      <section class="setup-section setup-section-primary">
        <h3>① 训练语料浏览 / 导出</h3>
        <div class="setup-howto">
          时间线 + 标签 + 作者(@user / @ai / @system)三个维度拆。
          一键重新生成所有训练数据(all / by-tag / by-author / 含 reasoning_content)。
          <br><br>
          <button class="key-add-btn" id="corpusOpenHistory">打开训练语料浏览</button>
        </div>
      </section>

      <section class="setup-section">
        <h3>② 训练授权</h3>
        <div class="setup-howto setup-howto-secondary">
          按来源、标签、作者筛选,预览匹配的条目数,定一份"哪些段允许导出"的 license 配置。
          默认全部允许。修改后导出时会遵循这份授权配置。
          <br><br>
          <button class="key-add-btn" id="corpusOpenConsent">打开授权配置</button>
        </div>
      </section>

      <section class="setup-section">
        <h3>③ 云端数据收集</h3>
        <div class="setup-howto setup-howto-secondary">
          同意隐私协议时默认开启两类匿名诊断(错误诊断 + 每日检测),帮我们改进软件。完整说明见 <a href="/PRIVACY.md" target="_blank" rel="noopener">PRIVACY.md</a>。
          <br><br>

          <div class="consent-meta" style="margin:12px 0;">
            <div><span class="consent-meta-k">当前状态</span>${(telemetry.failures || telemetry.heartbeat) ? '已同意,正常上报' : '未同意,不上报'}</div>
            <div><span class="consent-meta-k">匿名标识</span><code id="tm-cid">${telemetry.client_id || '—'}</code>
              <button class="km-test" style="margin-left:8px;font-size:11px;" id="tm-reset">重置</button>
            </div>
            <div><span class="consent-meta-k">已上报</span>错误 ${telemetry.silent_failures_local || 0} 条 · 最后心跳 ${telemetry.heartbeat_last_day || '从未'}</div>
            <div><span class="consent-meta-k">接收端</span>腾讯云国内服务器(自托管)</div>
          </div>

          <button class="key-add-btn" id="tm-revoke">撤回隐私同意</button>
          <button class="key-add-btn" id="tm-reagree" style="margin-left:8px;">重新同意</button>
          <span class="tm-saved-msg" id="tm-saved" style="margin-left:10px;color:var(--ink-3);font-size:12px;display:none;">已更新</span>
        </div>
      </section>
    `;

    document.getElementById("corpusOpenHistory").addEventListener("click", () => {
      window.open("/history.html", "_blank", "noopener");
    });
    document.getElementById("corpusOpenConsent").addEventListener("click", () => {
      window.open("/consent.html", "_blank", "noopener");
    });
    // 撤回隐私同意 = 关掉两类上报 + 清 localStorage 同意标记 → 下次启动重弹 modal
    document.getElementById("tm-revoke").addEventListener("click", async () => {
      await fetch("/api/telemetry/consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ failures: false, heartbeat: false }),
      });
      localStorage.removeItem("gateway.consent.agreed.v2");
      const msg = document.getElementById("tm-saved");
      msg.style.display = "inline";
      msg.textContent = "已撤回 · 下次启动会重新询问";
      setTimeout(() => { msg.style.display = "none"; }, 2500);
    });
    // 重新同意 = 直接开两类(不重弹 modal,设置里一键即可)
    document.getElementById("tm-reagree").addEventListener("click", async () => {
      await fetch("/api/telemetry/consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ failures: true, heartbeat: true }),
      });
      localStorage.setItem("gateway.consent.agreed.v2", "1");
      const msg = document.getElementById("tm-saved");
      msg.style.display = "inline";
      msg.textContent = "已同意 · 两类上报开启";
      setTimeout(() => { msg.style.display = "none"; }, 2500);
    });
    document.getElementById("tm-reset").addEventListener("click", async () => {
      if (!confirm("重置 client_id 后,云上报会把你看作新设备(对你没任何影响,只是 DAU 重算)。确定?")) return;
      const r = await fetch("/api/telemetry/reset-client-id", { method: "POST" });
      const d = await r.json();
      if (d.client_id) document.getElementById("tm-cid").textContent = d.client_id;
    });
  }

  function renderWidgets(widgets) {
    const body = document.getElementById("marketBody");
    body.innerHTML = `<div class="market-hint">日记基础默认装好。项目管理类按需开启。开关后页面会刷新。</div>`;
    const groups = {};
    for (const w of widgets) {
      const c = w.category || "uncategorized";
      (groups[c] = groups[c] || []).push(w);
    }
    const order = ["diary-core", "project-mgmt", "uncategorized"];
    const labels = {
      "diary-core": "日记基础",
      "project-mgmt": "项目管理",
      "uncategorized": "其他",
    };
    for (const cat of order) {
      const arr = groups[cat];
      if (!arr || !arr.length) continue;
      const sec = document.createElement("section");
      sec.className = "market-cat";
      sec.innerHTML = `<div class="market-cat-label">${labels[cat] || cat}</div>`;
      for (const w of arr) {
        sec.appendChild(card(w));
      }
      body.appendChild(sec);
    }
  }

  function renderKeys(cfg) {
    const body = document.getElementById("marketBody");
    const themeNow = (window.gatewayTheme && window.gatewayTheme.get()) || "system";
    const skinNow = (window.gatewaySkin && window.gatewaySkin.get()) || "classic";
    body.innerHTML = `
      <div class="market-hint">DeepSeek API Key 保存在本机，AI 请求直连 DeepSeek。</div>

      <section class="setup-section" id="skinSection">
        <h3>皮肤</h3>
        <div class="setup-howto setup-howto-secondary">两套前端整体切换。新版正在逐页完善:完成的页面使用新版,未完成的仍使用当前版。</div>
        <div class="skin-row" role="radiogroup" aria-label="皮肤">
          ${[["classic","现版 · 私印小报"],["paper","新版 · 纸与灯"]].map(([v,label]) => `
            <label class="skin-opt" style="margin-right:14px;cursor:pointer;">
              <input type="radio" name="skinKind" value="${v}" ${skinNow===v?"checked":""}> ${label}
            </label>`).join("")}
        </div>
        <div class="skin-row skin-theme-row" role="radiogroup" aria-label="新版日夜"
             style="margin-top:8px;${skinNow==="paper"?"":"display:none;"}">
          <span style="opacity:.6;margin-right:10px;">新版的纸色:</span>
          ${[["day","日间"],["night","夜间"],["system","跟系统"]].map(([v,label]) => `
            <label class="skin-opt" style="margin-right:14px;cursor:pointer;">
              <input type="radio" name="skinMode" value="${v}" ${themeNow===v?"checked":""}> ${label}
            </label>`).join("")}
        </div>
      </section>

      <section class="setup-section setup-section-primary">
        <h3>① 对话与视觉 · <span class="setup-role">DeepSeek 直连</span></h3>
        <div class="setup-howto">
          对话和识图使用你自己的 DeepSeek API Key，由你的 DeepSeek 账户计费。
        </div>
        <div class="key-row"><label class="key-label" for="marketDeepSeekKey">DeepSeek API Key</label><input class="key-input" id="marketDeepSeekKey" type="password" autocomplete="off" spellcheck="false" placeholder="${cfg.has_deepseek_api_key ? "已保存；粘贴新密钥可更换" : "粘贴你的 DeepSeek API Key"}"><button class="km-save" id="marketDeepSeekSave">保存</button><span class="key-status" id="marketDeepSeekStatus"></span></div>
      </section>

      <details class="setup-details setup-section">
        <summary>② 百度抠图(可选 · 折叠) — Win/Linux 用户兜底</summary>
        <div class="setup-howto setup-howto-secondary">
          macOS 优先用系统 Subject Lift(本地、免费、220ms)。<b>只在 Win/Linux 上跑 + 抠图质量不够时才填。</b>
          新用户:跳过这一段。
        </div>
        ${keyRow("百度抠图 · API key", "baidu_cutout_api_key", cfg.baidu_cutout_api_key)}
        ${keyRow("百度抠图 · Secret",   "baidu_cutout_secret_key", cfg.baidu_cutout_secret_key)}
      </details>
    `;

    const deepSeekSave = body.querySelector("#marketDeepSeekSave");
    deepSeekSave.addEventListener("click", async () => {
      const input = body.querySelector("#marketDeepSeekKey");
      const key = input.value.trim();
      const status = body.querySelector("#marketDeepSeekStatus");
      if (!key) {
        status.textContent = cfg.has_deepseek_api_key ? "保留已保存的密钥" : "请填写 DeepSeek API Key";
        return;
      }
      status.textContent = "保存中⋯";
      deepSeekSave.disabled = true;
      const ok = await saveSinglePartial({ api_key: key });
      deepSeekSave.disabled = false;
      status.textContent = ok ? "✓ 已保存" : "✕ 保存失败";
      if (ok) {
        cfg.has_deepseek_api_key = true;
        input.value = "";
        input.placeholder = "已保存；粘贴新密钥可更换";
      }
    });

    // 百度 key inputs auto-save on blur
    [...body.querySelectorAll("input.key-input")].forEach(inp => {
      inp.addEventListener("blur", async () => {
        const k = inp.dataset.key;
        const v = inp.value.trim();
        if (k?.startsWith("baidu_")) {
          await saveSinglePartial({[k]: v});
          flashStatus(inp.closest(".key-row"), "✓ 已存");
        }
      });
    });

    // 皮肤切换(两层) — skin 真源 gateway-skin,日夜真源 gateway-theme(theme.js)
    [...body.querySelectorAll('input[name="skinKind"]')].forEach(r => {
      r.addEventListener("change", () => {
        const themeRow = body.querySelector(".skin-theme-row");
        if (themeRow) themeRow.style.display = r.value === "paper" ? "" : "none";
        if (window.gatewaySkin) window.gatewaySkin.set(r.value);
      });
    });
    [...body.querySelectorAll('input[name="skinMode"]')].forEach(r => {
      r.addEventListener("change", () => {
        if (window.gatewayTheme) window.gatewayTheme.set(r.value);
      });
    });
  }

  function keyRow(label, key, value, placeholder) {
    return `
      <div class="key-row">
        <label class="key-label">${escape(label)}</label>
        <input class="key-input" type="password" data-key="${key}" value="${escape(value || "")}" placeholder="${escape(placeholder || "可空")}">
        <span class="key-status"></span>
      </div>
    `;
  }

  async function saveSinglePartial(obj) {
    try {
      const r = await fetch("/api/setup/save-partial", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(obj),
      });
      const d = await r.json();
      return !!d.ok;
    } catch (e) { console.warn("partial save failed", e); return false; }
  }

  function flashStatus(row, msg) {
    const s = row.querySelector(".key-status");
    if (!s) return;
    s.textContent = msg;
    setTimeout(() => { s.textContent = ""; }, 1800);
  }

  function card(w) {
    const el = document.createElement("article");
    const wip = w.status === "wip";
    el.className = "market-card" + (w.active && !wip ? " on" : "") + (wip ? " wip" : "");
    el.innerHTML = `
      <div class="market-card-main">
        <div class="market-card-title">${escape(w.title)}</div>
        <div class="market-card-desc">${escape(w.description || "")}</div>
        <div class="market-card-meta">
          ${w.audience ? `<span>受众:${escape(w.audience)}</span>` : ""}
          ${w.slot ? `<span>位置:${escape(w.slot)}</span>` : ""}
          ${w.default_loaded && !wip ? `<span class="market-tag-default">默认</span>` : ""}
          ${wip ? `<span class="market-tag-wip">开发中</span>` : ""}
        </div>
      </div>
      <div class="market-card-action">
        <label class="market-toggle" title="${wip ? "审核通过后才能启用" : ""}">
          <input type="checkbox" ${w.active && !wip ? "checked" : ""} ${wip ? "disabled" : ""}>
          <span class="market-toggle-slider"></span>
        </label>
      </div>
    `;
    if (wip) return el;  // wip 不挂 toggle handler
    const cb = el.querySelector("input");
    cb.addEventListener("change", async () => {
      cb.disabled = true;
      try {
        const r = await fetch("/api/widgets/toggle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: w.name, enable: cb.checked }),
        });
        const d = await r.json();
        if (!d.ok) throw new Error(d.detail || "toggle failed");
        // 整页刷新让 widget-loader 重新装载
        location.reload();
      } catch (e) {
        cb.checked = !cb.checked;
        cb.disabled = false;
        gatewayAlert("切换失败:" + e.message);
      }
    });
    return el;
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  function onKey(e) {
    if (e.key === "Escape") close();
  }

  btn.addEventListener("click", open);
  window.gateway = window.gateway || {};
  window.gateway.marketplace = { open, close };
})();
