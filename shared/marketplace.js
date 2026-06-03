/* marketplace.js · gateway 设置面板(tabbed)
 *
 * 入口: header 的 ⚙ icon (id="marketBtn")
 * 两 tab:
 *   1. 插件市场 — widget catalog,GET /api/widgets/catalog
 *   2. API 钥匙 — DeepSeek (chat) + 阿里云百炼 (vision) + 百度抠图 (可选) 配置,GET /api/setup/current
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
    } else {
      const resp = await fetch("/api/setup/current");
      const cfg = await resp.json();
      renderKeys(cfg);
    }
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
        vault 自动 git commit 出的 markdown 是这个产品的"训练语料"——
        人和 AI 在日记里写的每一笔都是带作者签名的 jsonl,可以喂回模型做 DPO,也可以纯当备份。
        训练语料全部在你机器上,不传第三方。
      </div>

      <section class="setup-section setup-section-primary">
        <h3>① 训练语料浏览 / 导出</h3>
        <div class="setup-howto">
          时间线 + 标签 + 作者(@user / @ai / @system)三个维度拆。
          一键 rebuild 全部 jsonl(all / by-tag / by-author / 含 reasoning_content)。
          <br><br>
          <button class="key-add-btn" id="corpusOpenHistory">打开训练语料浏览</button>
        </div>
      </section>

      <section class="setup-section">
        <h3>② 训练授权</h3>
        <div class="setup-howto setup-howto-secondary">
          按 source / tag / author 筛选,预览匹配 commit 数,定一份"哪些段允许导出"的 license 配置。
          默认全部允许,改了之后语料导出按这份白名单走。
          <br><br>
          <button class="key-add-btn" id="corpusOpenConsent">打开授权配置</button>
        </div>
      </section>

      <section class="setup-section">
        <h3>③ 云端数据收集</h3>
        <div class="setup-howto setup-howto-secondary">
          Gateway 默认收集两类匿名诊断数据,用于改进产品质量。完整政策见 <a href="/PRIVACY.md" target="_blank" rel="noopener">PRIVACY.md</a>。
          <br><br>
          <label class="consent-check" style="margin-bottom:8px;">
            <input type="checkbox" id="tm-failures" ${telemetry.failures ? 'checked' : ''}>
            <span class="consent-title">错误诊断</span>
          </label>
          <div class="consent-desc" style="margin-bottom:12px;">
            <b>收集</b>:API 调用 / 识图 / 抠图 / 搜索 失败时的错误码、调用元数据(模型标识、文件尺寸、网络层标记)。
            <br><b>不收集</b>:日记内容、对话记录、文件名、附件、密钥。
          </div>

          <label class="consent-check" style="margin-bottom:8px;">
            <input type="checkbox" id="tm-heartbeat" ${telemetry.heartbeat ? 'checked' : ''}>
            <span class="consent-title">使用统计(每日心跳)</span>
          </label>
          <div class="consent-desc" style="margin-bottom:12px;">
            <b>收集</b>:应用版本、操作系统平台、UTC 时区偏移,每 24 小时一次。
            <br><b>不收集</b>:任何 vault 数据或可关联到个人身份的信息。
          </div>

          <div class="consent-meta" style="margin:12px 0;">
            <div><span class="consent-meta-k">匿名标识</span><code id="tm-cid">${telemetry.client_id || '—'}</code>
              <button class="km-test" style="margin-left:8px;font-size:11px;" id="tm-reset">重置</button>
            </div>
            <div><span class="consent-meta-k">已上报</span>错误 ${telemetry.silent_failures_local || 0} 条 · 最后心跳 ${telemetry.heartbeat_last_day || '从未'}</div>
            <div><span class="consent-meta-k">接收端</span>腾讯云国内服务器(自托管)</div>
          </div>

          <button class="key-add-btn" id="tm-save">保存</button>
          <span class="tm-saved-msg" id="tm-saved" style="margin-left:10px;color:var(--ink-3);font-size:12px;display:none;">已保存</span>
        </div>
      </section>
    `;

    document.getElementById("corpusOpenHistory").addEventListener("click", () => {
      window.open("/history.html", "_blank", "noopener");
    });
    document.getElementById("corpusOpenConsent").addEventListener("click", () => {
      window.open("/consent.html", "_blank", "noopener");
    });
    document.getElementById("tm-save").addEventListener("click", async () => {
      const failures = document.getElementById("tm-failures").checked;
      const heartbeat = document.getElementById("tm-heartbeat").checked;
      await fetch("/api/telemetry/consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ failures, heartbeat }),
      });
      const msg = document.getElementById("tm-saved");
      msg.style.display = "inline";
      setTimeout(() => { msg.style.display = "none"; }, 2000);
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
    body.innerHTML = `
      <div class="market-hint">本地服务,key 仅落本机 config.json,不传任何第三方。任何输入框 paste 完点旁边按钮即可保存/测试。</div>

      <section class="setup-section setup-section-primary">
        <h3>① 说话的 · <span class="setup-role">DeepSeek 直连</span></h3>
        <div class="setup-howto">
          跟你聊天、写日记的 AI。<b>直接到 DeepSeek 官方充值。</b>
          <br><br>
          V4 Pro 现在永久 <b>2.5 折</b>(原价的 1/4),10-20 元够用很久。
          <ol>
            <li>访问 <a href="https://platform.deepseek.com/" target="_blank" rel="noopener">platform.deepseek.com</a> 注册/登录</li>
            <li>左侧菜单 <b>API Keys</b> → <b>Create new API key</b></li>
            <li>充值</li>
            <li>复制 sk-... 粘贴到下方,测试通过即可</li>
          </ol>
        </div>
        <div id="keysModels"></div>
        <button class="key-add-btn" id="keysAddModel">+ 加 provider</button>
      </section>

      <section class="setup-section">
        <h3>② 眼睛 · <span class="setup-role">阿里云百炼(给 DeepSeek 装视觉)</span></h3>
        <div class="setup-howto setup-howto-secondary">
          根据指引获取阿里云百炼 API,为你的 DeepSeek 装上眼睛。
          <ol>
            <li>访问 <a href="https://www.aliyun.com/benefit/scene/ai-discount" target="_blank" rel="noopener">aliyun.com / AI 优惠场景</a> 注册,百炼新用户每个模型送 <b>100 万 token / 90 天</b></li>
            <li>进 <a href="https://bailian.console.aliyun.com/" target="_blank" rel="noopener">百炼控制台</a> → 开通服务(免费)</li>
            <li>左侧 <b>API-KEY</b> → 创建</li>
            <li>每张图 ~0.03 分(qwen3-vl-flash 实测),10 元能识约 3.6 万张;新用户 100 万免费 token 够识 ~800 张</li>
            <li>免费额度用完后 → <a href="https://expense.console.aliyun.com/finance/recharge" target="_blank" rel="noopener">阿里云充值入口</a></li>
          </ol>
        </div>
        ${keyRow("百炼 · API key", "dashscope_api_key", cfg.dashscope_api_key, "sk-... · bailian.console.aliyun.com")}
      </section>

      <details class="setup-details setup-section">
        <summary>③ 百度抠图(可选 · 折叠) — Win/Linux 用户兜底</summary>
        <div class="setup-howto setup-howto-secondary">
          macOS 优先用系统 Subject Lift(本地、免费、220ms)。<b>只在 Win/Linux 上跑 + 抠图质量不够时才填。</b>
          新用户:跳过这一段。
        </div>
        ${keyRow("百度抠图 · API key", "baidu_cutout_api_key", cfg.baidu_cutout_api_key)}
        ${keyRow("百度抠图 · Secret",   "baidu_cutout_secret_key", cfg.baidu_cutout_secret_key)}
      </details>
    `;

    const allModels = cfg.models || [];
    hiddenVisionModels = allModels.filter(isVisionModel);
    renderModels(allModels.filter(m => !isVisionModel(m)));
    document.getElementById("keysAddModel").addEventListener("click", () => addModel());

    // dashscope / baidu key inputs auto-save on blur
    [...body.querySelectorAll("input.key-input")].forEach(inp => {
      inp.addEventListener("blur", async () => {
        const k = inp.dataset.key;
        const v = inp.value.trim();
        if (k.startsWith("baidu_") || k === "dashscope_api_key") {
          await saveSinglePartial({[k]: v});
          flashStatus(inp.closest(".key-row"), "✓ 已存");
        }
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

  let editingModels = [];
  // vision models (base_url 含 dashscope) 不出现在 ① chat list,但 save 时保留
  let hiddenVisionModels = [];
  const isVisionModel = (m) => (m.base_url || "").includes("dashscope");
  function renderModels(models) {
    editingModels = models.map(m => ({...m}));
    const wrap = document.getElementById("keysModels");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!editingModels.length) {
      wrap.innerHTML = `<div class="market-empty">还没配 LLM,点下面 + 加 provider</div>`;
      return;
    }
    editingModels.forEach((m, i) => {
      const row = document.createElement("div");
      row.className = "key-model-row";
      row.innerHTML = `
        <div class="key-model-head">
          <input class="km-label" value="${escape(m.label || "")}" placeholder="标签">
          <button class="km-del" title="删">✕</button>
        </div>
        <input class="km-base" value="${escape(m.base_url || "")}" placeholder="base_url">
        <input class="km-model" value="${escape(m.model || "")}" placeholder="model id">
        <input class="km-key" type="password" value="${escape(m.api_key || "")}" placeholder="api_key">
        <div class="key-model-actions">
          <button class="km-test">测试</button>
          <button class="km-save">保存全部 LLM</button>
          <span class="key-status"></span>
        </div>
      `;
      const inputs = row.querySelectorAll("input");
      const [labI, baseI, modI, keyI] = inputs;
      labI.addEventListener("input", () => editingModels[i].label = labI.value);
      baseI.addEventListener("input", () => editingModels[i].base_url = baseI.value);
      modI.addEventListener("input", () => editingModels[i].model = modI.value);
      keyI.addEventListener("input", () => editingModels[i].api_key = keyI.value);
      row.querySelector(".km-del").addEventListener("click", () => {
        editingModels.splice(i, 1);
        renderModels(editingModels);
      });
      row.querySelector(".km-test").addEventListener("click", () => testModel(i, row));
      row.querySelector(".km-save").addEventListener("click", () => saveAllModels(row));
      wrap.appendChild(row);
    });
  }

  function addModel() {
    editingModels.push({label: "", base_url: "", model: "", api_key: ""});
    renderModels(editingModels);
  }

  async function testModel(idx, row) {
    const m = editingModels[idx];
    const status = row.querySelector(".key-status");
    status.textContent = "测试中⋯";
    try {
      const r = await fetch("/api/setup/test", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({label: m.label, base_url: m.base_url, model: m.model, api_key: m.api_key}),
      });
      const d = await r.json();
      status.textContent = d.ok ? "✓ 通过" : ("✕ " + (d.reason || ""));
      status.className = "key-status " + (d.ok ? "ok" : "err");
    } catch (e) {
      status.textContent = "✕ " + e.message;
      status.className = "key-status err";
    }
  }

  async function saveAllModels(row) {
    const status = row.querySelector(".key-status");
    status.textContent = "保存中⋯";
    try {
      // 自动给没 id 的生成 id
      const cleaned = editingModels.filter(m => m.label && m.base_url && m.api_key && m.model).map((m, i) => ({
        ...m,
        id: m.id || (m.label.toLowerCase().replace(/\s+/g, "-") || `p${i}`),
      }));
      // 合并 ① 列表里的 chat 模型 + 隐藏的 vision 模型(避免 save 时把 vision 删了)
      const merged = [...cleaned, ...hiddenVisionModels];
      const r = await fetch("/api/setup/save-partial", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({models: merged}),
      });
      const d = await r.json();
      status.textContent = d.ok ? "✓ 已保存" : ("✕ " + (d.detail || ""));
      status.className = "key-status " + (d.ok ? "ok" : "err");
    } catch (e) {
      status.textContent = "✕ " + e.message;
      status.className = "key-status err";
    }
  }

  async function saveSinglePartial(obj) {
    try {
      await fetch("/api/setup/save-partial", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(obj),
      });
    } catch (e) { console.warn("partial save failed", e); }
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
