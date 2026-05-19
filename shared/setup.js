/* setup.js · 初次配置 / 改 API 向导
 *
 * v2 设计:
 *   - 阿里云百炼作主 provider — 1 个 API key + 复选 model 启用,不重复填 base+key
 *   - 自定义 OpenAI 兼容 provider 留作折叠选项(power user 才需要)
 *   - 百度抠图 / Gemini 都是可选(百炼已含 vision/OCR,基本不用)
 *
 * 流程:
 *   1. 弹 modal
 *   2. 用户填百炼 key + 点测试(只测一个 default model 通就过)
 *   3. 勾选要启用的 models(默认 3-5 个)+ 选 default model
 *   4. 保存 → 选中的每个 model 展成一个 profile,共用同 key + base_url
 *
 * 触发:
 *   - page load 检 /api/setup-status,未配置 → 强弹 modal,不可关
 *   - 手动重开 → window.gateway.setup.open()
 */

(function () {
  let overlay = null;
  // bailian:1 key + 多 model 复选
  let bailian = {
    api_key: "",
    tested: false,
    _testing: false,
    _err: "",
    base_url: "",
    models: [],          // [{id, label, tag, default}]
    selected: {},         // {model_id: bool}
    default_model_id: "",
  };
  // custom providers — 折叠区,默认为空,power user 加
  let custom_providers = [];  // [{label, base_url, api_key, model, tested, _err}]
  let baidu = { ocr_api: "", ocr_secret: "", cutout_api: "", cutout_secret: "",
                _ocr_tested: false, _cutout_tested: false };
  let gemini = { api_key: "", _tested: false, _err: "" };
  let canClose = false;

  async function checkAndShow() {
    try {
      const r = await fetch("/api/setup-status");
      const s = await r.json();
      if (!s.configured) {
        canClose = false;
        await loadTemplates();
        show(s.reason);
      }
    } catch (e) {
      console.warn("setup-status check failed:", e);
    }
  }

  async function showManual() {
    canClose = true;
    await loadTemplates();
    // preload 现有 config(把已有的百炼 models 标记 selected)
    try {
      const r = await fetch("/api/models");
      const d = await r.json();
      const existing = d.models || [];
      // 找含 dashscope 的 profile 当作百炼现状
      const bailianExisting = existing.filter(m => (m.base_url || "").includes("dashscope"));
      if (bailianExisting.length) {
        bailian.api_key = "";  // server 不返 key,要重输
        for (const m of bailianExisting) {
          bailian.selected[m.model] = true;
        }
        if (d.default_model_id) bailian.default_model_id = d.default_model_id;
      }
      // 非百炼的 → custom_providers
      custom_providers = existing.filter(m => !(m.base_url || "").includes("dashscope")).map(m => ({
        label: m.label || m.id, base_url: m.base_url, api_key: "", model: m.model,
        tested: false, _err: "",
      }));
    } catch {}
    show(null);
  }

  async function loadTemplates() {
    try {
      const r = await fetch("/api/setup/templates");
      const d = await r.json();
      const b = d.bailian || {};
      bailian.base_url = b.base_url || "https://dashscope.aliyuncs.com/compatible-mode/v1";
      bailian.models = b.models || [];
      // 没 selected 状态 → 默认勾选 .default=true 的
      if (Object.keys(bailian.selected).length === 0) {
        for (const m of bailian.models) {
          if (m.default) bailian.selected[m.id] = true;
        }
      }
      if (!bailian.default_model_id) {
        const def = bailian.models.find(m => m.default);
        if (def) bailian.default_model_id = def.id;
      }
    } catch (e) {
      console.warn("loadTemplates failed:", e);
    }
  }

  function show(reason) {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.className = "setup-overlay";
    overlay.innerHTML = `
      <div class="setup-panel">
        <header class="setup-head">
          <div class="setup-title">配置 API</div>
          ${canClose ? `<button class="setup-close" aria-label="close" id="setupCloseBtn">×</button>` : `<span class="setup-locked" title="未配置完成不能关">🔒</span>`}
        </header>
        ${reason ? `<div class="setup-reason">⚠ ${escape(reason)}</div>` : ""}
        <div class="setup-body">
          <section class="setup-section">
            <h3>大模型 · 阿里云百炼 (推荐)</h3>
            <div class="setup-aliyun-howto">
              一个 API key 覆盖 Qwen + DeepSeek + GLM + Kimi + MiniMax + OCR/Vision。
              <ol>
                <li>访问 <a href="https://www.aliyun.com/benefit/scene/ai-discount" target="_blank" rel="noopener">aliyun.com / AI 优惠场景</a> 注册或登录,可领新用户 token 福利</li>
                <li>进 <a href="https://bailian.console.aliyun.com/" target="_blank" rel="noopener">百炼控制台</a> → 开通服务(免费)</li>
                <li>左侧 "API-KEY" → 创建,sk-xxx 复制粘贴到下方</li>
              </ol>
            </div>
            <div class="bailian-card" id="bailianCard"></div>
            <details class="setup-details">
              <summary>+ 加自定义 OpenAI 兼容 endpoint(可选,自建/第三方时用)</summary>
              <div class="setup-providers" id="customProviders"></div>
              <button class="setup-add-custom" id="addCustomBtn">+ 加一项自定义 provider</button>
            </details>
          </section>
          <section class="setup-section">
            <h3>百度抠图 <span class="setup-optional">(可选 — 上传图自动去背景,百炼无此能力)</span></h3>
            <div class="setup-baidu" id="setupBaidu"></div>
          </section>
          <section class="setup-section">
            <h3>Gemini Flash <span class="setup-optional">(可选 — 百炼已含 qwen-vl,基本不用)</span></h3>
            <div class="setup-gemini" id="setupGemini"></div>
          </section>
        </div>
        <footer class="setup-foot">
          <span class="setup-hint" id="setupHint">填百炼 key + 测试通过即可保存</span>
          <button class="setup-save" id="setupSaveBtn" disabled>保存并启动</button>
        </footer>
      </div>
    `;
    document.body.appendChild(overlay);

    if (canClose) document.getElementById("setupCloseBtn").addEventListener("click", close);
    document.getElementById("setupSaveBtn").addEventListener("click", save);
    document.getElementById("addCustomBtn").addEventListener("click", addCustomProvider);

    renderBailian();
    renderCustomProviders();
    renderBaidu();
    renderGemini();
    refreshSaveState();
  }

  // ── 百炼卡片(主) ────────────────────────────────────
  function renderBailian() {
    const wrap = document.getElementById("bailianCard");
    if (!wrap) return;
    const checks = bailian.models.map(m => {
      const checked = !!bailian.selected[m.id];
      return `
        <label class="bailian-model" data-id="${escape(m.id)}">
          <input type="checkbox" ${checked ? "checked" : ""} data-mid="${escape(m.id)}">
          <span class="bailian-mname">${escape(m.label)}</span>
          ${m.tag ? `<span class="bailian-mtag">${escape(m.tag)}</span>` : ""}
        </label>
      `;
    }).join("");
    wrap.innerHTML = `
      <div class="bailian-key-row">
        <label>API key</label>
        <input id="bailianKey" type="password" value="${escape(bailian.api_key)}" placeholder="sk-...">
        <button id="bailianTest" class="bailian-test-btn">${bailian._testing ? "⋯ 测试中" : (bailian.tested ? "✓ 通过" : "测试")}</button>
      </div>
      ${bailian._err ? `<div class="setup-prov-err">${escape(bailian._err)}</div>` : ""}
      <div class="bailian-models-label">启用 model(可多选,运行时随用随切)</div>
      <div class="bailian-models">${checks}</div>
      <div class="bailian-default-row">
        <label>默认 model</label>
        <select id="bailianDefault">
          ${bailian.models.filter(m => bailian.selected[m.id]).map(m =>
            `<option value="${escape(m.id)}" ${m.id === bailian.default_model_id ? "selected" : ""}>${escape(m.label)}</option>`
          ).join("")}
        </select>
      </div>
    `;
    document.getElementById("bailianKey").addEventListener("input", e => {
      bailian.api_key = e.target.value; bailian.tested = false; bailian._err = "";
      refreshSaveState();
    });
    document.getElementById("bailianTest").addEventListener("click", testBailian);
    [...wrap.querySelectorAll('input[type="checkbox"][data-mid]')].forEach(cb => {
      cb.addEventListener("change", e => {
        const id = e.target.dataset.mid;
        bailian.selected[id] = e.target.checked;
        // 重渲 default 下拉(可选 model 变了)
        renderBailian();
        refreshSaveState();
      });
    });
    document.getElementById("bailianDefault")?.addEventListener("change", e => {
      bailian.default_model_id = e.target.value;
    });
  }

  async function testBailian() {
    if (!bailian.api_key) { bailian._err = "key 是空的"; renderBailian(); return; }
    bailian._testing = true; bailian._err = "";
    renderBailian();
    // 用 default model(没选就用第一个 selected 的;还没有就 qwen3-max)
    const testModel = bailian.default_model_id ||
                      bailian.models.find(m => bailian.selected[m.id])?.id ||
                      "qwen3-max";
    try {
      const r = await fetch("/api/setup/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: "百炼测试", base_url: bailian.base_url,
          api_key: bailian.api_key, model: testModel,
        }),
      });
      const d = await r.json();
      bailian._testing = false;
      if (d.ok) {
        bailian.tested = true; bailian._err = "";
      } else {
        bailian.tested = false; bailian._err = d.reason || "未知错";
      }
    } catch (e) {
      bailian._testing = false; bailian.tested = false; bailian._err = e.message;
    }
    renderBailian();
    refreshSaveState();
  }

  // ── 自定义 provider(折叠) ─────────────────────────
  function addCustomProvider() {
    custom_providers.push({ label: "", base_url: "", api_key: "", model: "", tested: false, _err: "" });
    renderCustomProviders();
  }

  function renderCustomProviders() {
    const wrap = document.getElementById("customProviders");
    if (!wrap) return;
    if (!custom_providers.length) {
      wrap.innerHTML = `<div class="setup-empty">无 — 点下方按钮加一项</div>`;
      return;
    }
    wrap.innerHTML = "";
    custom_providers.forEach((p, i) => {
      const row = document.createElement("div");
      row.className = "setup-prov" + (p.tested ? " ok" : "") + (p._err ? " err" : "");
      row.innerHTML = `
        <div class="setup-prov-head">
          <input class="setup-prov-label" value="${escape(p.label)}" placeholder="标签">
          <button class="setup-prov-del" title="删">✕</button>
        </div>
        <input class="setup-prov-base" value="${escape(p.base_url)}" placeholder="base_url 例 https://api.deepseek.com/v1">
        <input class="setup-prov-model" value="${escape(p.model)}" placeholder="model 例 deepseek-v4-flash">
        <input class="setup-prov-key" type="password" value="${escape(p.api_key)}" placeholder="api_key sk-...">
        <div class="setup-prov-actions">
          <button class="setup-prov-test">${p._testing ? "⋯ 测试中" : (p.tested ? "✓ 通过" : "测试连通")}</button>
          ${p._err ? `<span class="setup-prov-err">${escape(p._err)}</span>` : ""}
        </div>
      `;
      const [labelI, baseI, modelI, keyI] = row.querySelectorAll("input");
      labelI.addEventListener("input", () => { p.label = labelI.value; });
      baseI.addEventListener("input",  () => { p.base_url = baseI.value; p.tested = false; refreshSaveState(); });
      modelI.addEventListener("input", () => { p.model = modelI.value; p.tested = false; refreshSaveState(); });
      keyI.addEventListener("input",   () => { p.api_key = keyI.value; p.tested = false; refreshSaveState(); });
      row.querySelector(".setup-prov-del").addEventListener("click", () => {
        custom_providers.splice(i, 1); renderCustomProviders(); refreshSaveState();
      });
      row.querySelector(".setup-prov-test").addEventListener("click", () => testCustom(i));
      wrap.appendChild(row);
    });
  }

  async function testCustom(i) {
    const p = custom_providers[i];
    p._testing = true; p._err = ""; renderCustomProviders();
    try {
      const r = await fetch("/api/setup/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({label: p.label, base_url: p.base_url, api_key: p.api_key, model: p.model}),
      });
      const d = await r.json();
      p._testing = false;
      if (d.ok) p.tested = true;
      else { p.tested = false; p._err = d.reason || "未知错"; }
    } catch (e) {
      p._testing = false; p.tested = false; p._err = e.message;
    }
    renderCustomProviders(); refreshSaveState();
  }

  // ── 百度抠图 ─────────────────────────────────────────
  function renderBaidu() {
    const wrap = document.getElementById("setupBaidu");
    if (!wrap) return;
    wrap.innerHTML = `
      <div class="setup-baidu-row">
        <label>抠图 API key</label>
        <input id="bdCutApi" type="password" value="${escape(baidu.cutout_api)}" placeholder="可空">
        <label>抠图 secret</label>
        <input id="bdCutSec" type="password" value="${escape(baidu.cutout_secret)}" placeholder="可空">
        <button id="bdCutTest">${baidu._cutout_tested ? "✓ 通过" : "测试"}</button>
      </div>
    `;
    const $ = id => document.getElementById(id);
    $("bdCutApi").addEventListener("input", e => { baidu.cutout_api = e.target.value; baidu._cutout_tested = false; });
    $("bdCutSec").addEventListener("input", e => { baidu.cutout_secret = e.target.value; baidu._cutout_tested = false; });
    $("bdCutTest").addEventListener("click", () => testBaidu("cutout"));
  }

  async function testBaidu(kind) {
    const api = baidu.cutout_api;
    const sec = baidu.cutout_secret;
    try {
      const r = await fetch("/api/setup/test-baidu", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: api, secret_key: sec }),
      });
      const d = await r.json();
      baidu._cutout_tested = !!d.ok;
      if (!d.ok) alert(`抠图测试失败: ${d.reason || ""}`);
      renderBaidu();
    } catch (e) {
      alert(`测试请求失败: ${e.message}`);
    }
  }

  // ── Gemini(可选,基本不用) ────────────────────────
  function renderGemini() {
    const wrap = document.getElementById("setupGemini");
    if (!wrap) return;
    wrap.innerHTML = `
      <div class="setup-baidu-row">
        <label>API key</label>
        <input id="gmKey" type="password" value="${escape(gemini.api_key)}" placeholder="AIza... (可空)">
        <button id="gmTest">${gemini._tested ? "✓ 通过" : "测试"}</button>
      </div>
      ${gemini._err ? `<div class="setup-prov-err">${escape(gemini._err)}</div>` : ""}
    `;
    document.getElementById("gmKey").addEventListener("input", e => {
      gemini.api_key = e.target.value; gemini._tested = false; gemini._err = "";
    });
    document.getElementById("gmTest").addEventListener("click", testGemini);
  }

  async function testGemini() {
    if (!gemini.api_key) { gemini._err = "key 空"; renderGemini(); return; }
    gemini._err = "测试中⋯"; renderGemini();
    try {
      const r = await fetch("/api/setup/test-gemini", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({api_key: gemini.api_key}),
      });
      const d = await r.json();
      gemini._tested = !!d.ok;
      gemini._err = d.ok ? "✓ 已保存" : (d.reason || "失败");
      if (d.ok) {
        await fetch("/api/setup/save-gemini", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({api_key: gemini.api_key}),
        });
      }
    } catch (e) {
      gemini._tested = false; gemini._err = e.message;
    }
    renderGemini();
  }

  function close() {
    if (!canClose) return;
    overlay?.remove(); overlay = null;
  }

  function refreshSaveState() {
    const bailianOk = bailian.tested &&
                      Object.values(bailian.selected).some(v => v);
    const customOk  = custom_providers.some(p => p.tested);
    const ok = bailianOk || customOk;
    const btn = document.getElementById("setupSaveBtn");
    const hint = document.getElementById("setupHint");
    if (btn) btn.disabled = !ok;
    if (hint) {
      if (!bailian.tested && !customOk) hint.textContent = "填百炼 key + 测试通过即可保存";
      else if (bailian.tested && !Object.values(bailian.selected).some(v=>v))
        hint.textContent = "至少勾选一个 model";
      else hint.textContent = "可以保存了";
    }
  }

  async function save() {
    const profiles = [];
    if (bailian.tested) {
      for (const m of bailian.models) {
        if (!bailian.selected[m.id]) continue;
        profiles.push({
          id: m.id,
          label: m.tag ? `${m.label} (${m.tag})` : m.label,
          base_url: bailian.base_url,
          api_key: bailian.api_key,
          model: m.id,
        });
      }
    }
    for (const p of custom_providers) {
      if (!p.tested) continue;
      profiles.push({
        id: p.label || p.model || "custom",
        label: p.label || p.model,
        base_url: p.base_url, api_key: p.api_key, model: p.model,
      });
    }
    if (!profiles.length) { alert("没有可保存的 profile"); return; }
    const def = bailian.default_model_id ||
                profiles[0].id;
    const payload = {
      models: profiles,
      default_model_id: def,
    };
    if (baidu._cutout_tested) {
      payload.baidu_cutout_api_key = baidu.cutout_api;
      payload.baidu_cutout_secret_key = baidu.cutout_secret;
    }
    if (gemini._tested && gemini.api_key) {
      payload.gemini_api_key = gemini.api_key;
    }
    try {
      const r = await fetch("/api/setup/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (d.ok) { canClose = true; close(); location.reload(); }
      else alert("保存失败: " + (d.detail || JSON.stringify(d)));
    } catch (e) {
      alert("保存请求失败: " + e.message);
    }
  }

  function escape(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(checkAndShow, 200));
  } else {
    setTimeout(checkAndShow, 200);
  }

  window.gateway = window.gateway || {};
  window.gateway.setup = { open: showManual, close, checkAndShow };
})();
