/* setup.js · 初次配置 / 改 API 向导
 *
 * 触发:
 *   - page load 检 /api/setup-status,未配置 → 强弹 modal,不可关
 *   - header ⚙ 旁边将来加按钮可手动重开(暂走 marketplace 同槽)
 *
 * 流程:
 *   1. 列 provider 模板 (MiniMax / DeepSeek / MiMo) + 用户填 key
 *   2. 每行有"测试"按钮 → 后端真发一次 chat → 通过才打勾
 *   3. 保存按钮:至少一个 LLM 通过测试才 enable
 *   4. 百度可选段(OCR + cutout 抠图),不填则跳过(图片功能禁用)
 */

(function () {
  let overlay = null;
  let templates = [];
  let providers = [];   // [{label, base_url, api_key, model, tested: bool, _testing: bool, _err: ""}]
  let baidu = { ocr_api: "", ocr_secret: "", cutout_api: "", cutout_secret: "", _ocr_tested: false, _cutout_tested: false };
  let gemini = { api_key: "", _tested: false, _err: "" };
  let canClose = false;  // 强制弹出场景下不可关

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
    if (!templates.length) await loadTemplates();
    // 预填现有 models
    try {
      const r = await fetch("/api/models");
      const d = await r.json();
      providers = (d.models || []).map(m => ({
        label: m.label || m.id,
        base_url: m.base_url,
        api_key: "",  // 服务端不返回 key,需用户重输 (或留空保留旧值,但简化:重输)
        model: m.model,
        tested: false,
        _err: "",
      }));
    } catch {}
    show(null);
  }

  async function loadTemplates() {
    try {
      const r = await fetch("/api/setup/templates");
      const d = await r.json();
      templates = d.templates || [];
    } catch (e) {
      templates = [];
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
              <small>同一个 key 在下方选不同 model 反复加,无需再开第二个 provider。</small>
            </div>
            <div class="setup-providers" id="setupProviders"></div>
            <div class="setup-add-row">
              <select id="setupTemplatePicker">
                <option value="">+ 加 provider(选 model)…</option>
                ${templates.map((t, i) => `<option value="${i}">${escape(t.label)}</option>`).join("")}
                <option value="custom">自定义 (其他 OAI 兼容)</option>
              </select>
            </div>
          </section>
          <section class="setup-section">
            <h3>百度抠图 <span class="setup-optional">(可选 — 上传水杯 / 补剂照自动去背景,百炼无此能力)</span></h3>
            <div class="setup-baidu" id="setupBaidu"></div>
          </section>
          <section class="setup-section">
            <h3>Gemini Flash <span class="setup-optional">(可选 — vision 路由;百炼已含 qwen-vl,这里基本不用配)</span></h3>
            <div class="setup-gemini" id="setupGemini"></div>
          </section>
        </div>
        <footer class="setup-foot">
          <span class="setup-hint" id="setupHint">至少一个大模型测试通过后可保存</span>
          <button class="setup-save" id="setupSaveBtn" disabled>保存并启动</button>
        </footer>
      </div>
    `;
    document.body.appendChild(overlay);

    if (canClose) {
      document.getElementById("setupCloseBtn").addEventListener("click", close);
    }
    document.getElementById("setupSaveBtn").addEventListener("click", save);
    document.getElementById("setupTemplatePicker").addEventListener("change", onAddProvider);

    renderProviders();
    renderBaidu();
    renderGemini();
  }

  function renderGemini() {
    const wrap = document.getElementById("setupGemini");
    if (!wrap) return;
    wrap.innerHTML = `
      <div class="setup-baidu-row">
        <label>API key</label>
        <input id="gmKey" type="password" value="${escape(gemini.api_key)}" placeholder="AIza... (aistudio.google.com 5 分钟免费拿)">
        <button id="gmTest">${gemini._tested ? "✓ 通过" : "测试"}</button>
      </div>
      ${gemini._err ? `<div class="setup-prov-err">${escape(gemini._err)}</div>` : ""}
    `;
    document.getElementById("gmKey").addEventListener("input", e => {
      gemini.api_key = e.target.value;
      gemini._tested = false;
      gemini._err = "";
    });
    document.getElementById("gmTest").addEventListener("click", testGemini);
  }

  async function testGemini() {
    if (!gemini.api_key) { gemini._err = "key 是空的"; renderGemini(); return; }
    gemini._err = "测试中⋯";
    renderGemini();
    try {
      const r = await fetch("/api/setup/test-gemini", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({api_key: gemini.api_key}),
      });
      const d = await r.json();
      gemini._tested = !!d.ok;
      gemini._err = d.ok ? "" : (d.reason || "失败");
      // 通过即自动保存 — 避免用户走完整 wizard 重写其他 config
      if (d.ok) {
        try {
          await fetch("/api/setup/save-gemini", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({api_key: gemini.api_key}),
          });
          gemini._err = "✓ 已保存,vision 路由可用";
        } catch (e) {
          gemini._err = "测试通过但保存失败: " + e.message;
        }
      }
    } catch (e) {
      gemini._tested = false;
      gemini._err = e.message;
    }
    renderGemini();
  }

  function close() {
    if (!canClose) return;
    overlay?.remove();
    overlay = null;
  }

  function onAddProvider(e) {
    const v = e.target.value;
    if (!v) return;
    if (v === "custom") {
      providers.push({ label: "Custom", base_url: "", api_key: "", model: "", tested: false, _err: "" });
    } else {
      const t = templates[+v];
      providers.push({ label: t.label, base_url: t.base_url, api_key: "", model: t.model, tested: false, _err: "", _note: t.note || "" });
    }
    e.target.value = "";
    renderProviders();
    refreshSaveState();
  }

  function renderProviders() {
    const wrap = document.getElementById("setupProviders");
    if (!wrap) return;
    if (!providers.length) {
      wrap.innerHTML = `<div class="setup-empty">还没加任何 provider,从上方 +加 provider</div>`;
      return;
    }
    wrap.innerHTML = "";
    providers.forEach((p, i) => {
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
        ${p._note ? `<div class="setup-prov-note">${escape(p._note)}</div>` : ""}
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
        providers.splice(i, 1);
        renderProviders();
        refreshSaveState();
      });
      row.querySelector(".setup-prov-test").addEventListener("click", () => testProvider(i));
      wrap.appendChild(row);
    });
  }

  function renderBaidu() {
    const wrap = document.getElementById("setupBaidu");
    if (!wrap) return;
    wrap.innerHTML = `
      <div class="setup-baidu-row">
        <label>OCR API key</label>
        <input id="bdOcrApi" type="password" value="${escape(baidu.ocr_api)}" placeholder="可空">
        <label>OCR secret</label>
        <input id="bdOcrSec" type="password" value="${escape(baidu.ocr_secret)}" placeholder="可空">
        <button id="bdOcrTest">${baidu._ocr_tested ? "✓ 通过" : "测试"}</button>
      </div>
      <div class="setup-baidu-row">
        <label>抠图 API key</label>
        <input id="bdCutApi" type="password" value="${escape(baidu.cutout_api)}" placeholder="可空">
        <label>抠图 secret</label>
        <input id="bdCutSec" type="password" value="${escape(baidu.cutout_secret)}" placeholder="可空">
        <button id="bdCutTest">${baidu._cutout_tested ? "✓ 通过" : "测试"}</button>
      </div>
    `;
    const $ = id => document.getElementById(id);
    $("bdOcrApi").addEventListener("input", e => { baidu.ocr_api = e.target.value; baidu._ocr_tested = false; });
    $("bdOcrSec").addEventListener("input", e => { baidu.ocr_secret = e.target.value; baidu._ocr_tested = false; });
    $("bdCutApi").addEventListener("input", e => { baidu.cutout_api = e.target.value; baidu._cutout_tested = false; });
    $("bdCutSec").addEventListener("input", e => { baidu.cutout_secret = e.target.value; baidu._cutout_tested = false; });
    $("bdOcrTest").addEventListener("click", () => testBaidu("ocr"));
    $("bdCutTest").addEventListener("click", () => testBaidu("cutout"));
  }

  async function testProvider(i) {
    const p = providers[i];
    p._testing = true; p._err = "";
    renderProviders();
    try {
      const r = await fetch("/api/setup/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: p.label, base_url: p.base_url, api_key: p.api_key, model: p.model,
        }),
      });
      const d = await r.json();
      p._testing = false;
      if (d.ok) {
        p.tested = true;
      } else {
        p.tested = false;
        p._err = d.reason || "未知错";
      }
    } catch (e) {
      p._testing = false;
      p.tested = false;
      p._err = e.message;
    }
    renderProviders();
    refreshSaveState();
  }

  async function testBaidu(kind) {
    const api = kind === "ocr" ? baidu.ocr_api : baidu.cutout_api;
    const sec = kind === "ocr" ? baidu.ocr_secret : baidu.cutout_secret;
    try {
      const r = await fetch("/api/setup/test-baidu", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: api, secret_key: sec }),
      });
      const d = await r.json();
      if (kind === "ocr") baidu._ocr_tested = !!d.ok;
      else baidu._cutout_tested = !!d.ok;
      if (!d.ok) alert(`${kind} 测试失败: ${d.reason || ""}`);
      renderBaidu();
    } catch (e) {
      alert(`${kind} 测试请求失败: ${e.message}`);
    }
  }

  function refreshSaveState() {
    const ok = providers.some(p => p.tested);
    const btn = document.getElementById("setupSaveBtn");
    const hint = document.getElementById("setupHint");
    if (btn) btn.disabled = !ok;
    if (hint) hint.textContent = ok ? "可以保存了" : "至少一个大模型测试通过后可保存";
  }

  async function save() {
    const ok_profiles = providers.filter(p => p.tested);
    if (!ok_profiles.length) {
      alert("至少要有一个大模型测试通过");
      return;
    }
    // 给 ok 的发, 没测过的也带上(用户可能想保留但跳过测试)? 严格点只发测试过的
    const payload = {
      models: ok_profiles.map(p => ({
        label: p.label,
        base_url: p.base_url,
        api_key: p.api_key,
        model: p.model,
      })),
    };
    if (baidu._ocr_tested) {
      payload.baidu_ocr_api_key = baidu.ocr_api;
      payload.baidu_ocr_secret_key = baidu.ocr_secret;
    }
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
      if (d.ok) {
        canClose = true;
        close();
        // 刷整页让所有 module 重读 config
        location.reload();
      } else {
        alert("保存失败: " + (d.detail || JSON.stringify(d)));
      }
    } catch (e) {
      alert("保存请求失败: " + e.message);
    }
  }

  function escape(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  // ── 启动:页面加载即检查 ────────────────────────────
  // 等其他 module 装完再 check, 避免抢 focus / blocking init
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(checkAndShow, 200));
  } else {
    setTimeout(checkAndShow, 200);
  }

  window.gateway = window.gateway || {};
  window.gateway.setup = { open: showManual, close, checkAndShow };
})();
