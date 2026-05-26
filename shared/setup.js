/* setup.js · v3 ritual setup
 *
 * 双角色:
 *   · DeepSeek 直连(主对话)— api.deepseek.com,你直接给 DeepSeek 充值
 *   · 阿里云百炼(视觉助手)— 给 deepseek 装上眼睛(qwen3-vl 看图)
 *
 * 流程(每个独立 test):
 *   1. 填 DeepSeek key + 测试 → 选 default model
 *   2. (可选)填百炼 key + 测试 → 拖图能用了
 *   3. (可选,折叠)百度抠图 — 端侧 Subject Lift 优先,百度只是 Win/Linux 兜底
 *
 * Gemini → 已搬到 .env 文件,UI 不再露
 *
 * 触发:
 *   - page load 检 /api/setup-status,未配置 → 强弹 modal,不可关
 *   - 手动重开 → window.gateway.setup.open()
 */
(function () {
  let overlay = null;

  // 主对话 — DeepSeek 直连
  let deepseek = {
    api_key: "",
    tested: false,
    _testing: false,
    _err: "",
    base_url: "https://api.deepseek.com/v1",
    models: [],          // [{id, label, tag, default}]
    selected: {},
    default_model_id: "",
  };

  // 视觉助手 — 阿里云百炼,只用 vision model
  let bailian = {
    api_key: "",
    tested: false,
    _testing: false,
    _err: "",
    base_url: "",
    models: [],          // [{id, label, tag, default}] — vision only
    selected: {},
  };

  // 百度抠图(可选,折叠)
  let baidu = { cutout_api: "", cutout_secret: "", _tested: false };

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
    // preload 现有 config(把已有的 deepseek / bailian 标记出来)
    try {
      const r = await fetch("/api/models");
      const d = await r.json();
      const existing = d.models || [];
      // deepseek 现有 profile
      const dsExisting = existing.filter(m => (m.base_url || "").includes("deepseek"));
      if (dsExisting.length) {
        for (const m of dsExisting) deepseek.selected[m.model] = true;
        if (d.default_model_id && deepseek.models.find(x => x.id === d.default_model_id)) {
          deepseek.default_model_id = d.default_model_id;
        }
      }
      const blExisting = existing.filter(m => (m.base_url || "").includes("dashscope"));
      if (blExisting.length) {
        for (const m of blExisting) bailian.selected[m.model] = true;
      }
    } catch {}
    show(null);
  }

  async function loadTemplates() {
    try {
      const r = await fetch("/api/setup/templates");
      const d = await r.json();
      const ds = d.deepseek || {};
      deepseek.base_url = ds.base_url || "https://api.deepseek.com/v1";
      deepseek.models = ds.models || [];
      if (Object.keys(deepseek.selected).length === 0) {
        for (const m of deepseek.models) if (m.default) deepseek.selected[m.id] = true;
      }
      if (!deepseek.default_model_id) {
        const def = deepseek.models.find(m => m.default);
        if (def) deepseek.default_model_id = def.id;
      }
      const bl = d.bailian || {};
      bailian.base_url = bl.base_url || "https://dashscope.aliyuncs.com/compatible-mode/v1";
      bailian.models = bl.models || [];
      if (Object.keys(bailian.selected).length === 0) {
        for (const m of bailian.models) if (m.default) bailian.selected[m.id] = true;
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
          <div class="setup-title">配置 — 跟你聊天的 AI + 给它装眼睛</div>
          ${canClose ? `<button class="setup-close" aria-label="close" id="setupCloseBtn">×</button>` : `<span class="setup-locked" title="未配置完成不能关">🔒</span>`}
        </header>
        ${reason ? `<div class="setup-reason">⚠ ${escape(reason)}</div>` : ""}
        <div class="setup-body">

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
            <div class="bailian-card" id="deepseekCard"></div>
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
            <div class="bailian-card" id="bailianCard"></div>
          </section>

          <details class="setup-details setup-section">
            <summary>③ 百度抠图(可选 · 折叠) — Win/Linux 用户兜底</summary>
            <div class="setup-howto setup-howto-secondary">
              macOS 优先用系统 Subject Lift(本地、免费、220ms)。<b>只在 Win/Linux 上跑 + 抠图质量不够时才填。</b>
              新用户:跳过这一段。
            </div>
            <div class="setup-baidu" id="setupBaidu"></div>
          </details>

        </div>
        <footer class="setup-foot">
          <span class="setup-hint" id="setupHint">填 DeepSeek key + 测试通过即可保存</span>
          <button class="setup-save" id="setupSaveBtn" disabled>保存并启动</button>
        </footer>
      </div>
    `;
    document.body.appendChild(overlay);

    if (canClose) document.getElementById("setupCloseBtn").addEventListener("click", close);
    document.getElementById("setupSaveBtn").addEventListener("click", save);

    renderDeepseek();
    renderBailian();
    renderBaidu();
    refreshSaveState();
  }

  // ── ① DeepSeek 卡 ─────────────────────────────────────
  function renderDeepseek() {
    const wrap = document.getElementById("deepseekCard");
    if (!wrap) return;
    const checks = deepseek.models.map(m => {
      const checked = !!deepseek.selected[m.id];
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
        <input id="dsKey" type="password" value="${escape(deepseek.api_key)}" placeholder="sk-...">
        <button id="dsTest" class="bailian-test-btn">${deepseek._testing ? "⋯ 测试中" : (deepseek.tested ? "✓ 通过" : "测试")}</button>
      </div>
      ${deepseek._err ? `<div class="setup-prov-err">${escape(deepseek._err)}</div>` : ""}
      <div class="bailian-models-label">启用 model(运行时可在 thread header 切换)</div>
      <div class="bailian-models">${checks}</div>
      <div class="bailian-default-row">
        <label>默认 model</label>
        <select id="dsDefault">
          ${deepseek.models.filter(m => deepseek.selected[m.id]).map(m =>
            `<option value="${escape(m.id)}" ${m.id === deepseek.default_model_id ? "selected" : ""}>${escape(m.label)}</option>`
          ).join("")}
        </select>
      </div>
    `;
    document.getElementById("dsKey").addEventListener("input", e => {
      deepseek.api_key = e.target.value; deepseek.tested = false; deepseek._err = "";
      refreshSaveState();
    });
    document.getElementById("dsTest").addEventListener("click", testDeepseek);
    [...wrap.querySelectorAll('input[type="checkbox"][data-mid]')].forEach(cb => {
      cb.addEventListener("change", e => {
        const id = e.target.dataset.mid;
        deepseek.selected[id] = e.target.checked;
        renderDeepseek();
        refreshSaveState();
      });
    });
    document.getElementById("dsDefault")?.addEventListener("change", e => {
      deepseek.default_model_id = e.target.value;
    });
  }

  async function testDeepseek() {
    if (!deepseek.api_key) { deepseek._err = "key 是空的"; renderDeepseek(); return; }
    deepseek._testing = true; deepseek._err = "";
    renderDeepseek();
    const testModel = deepseek.default_model_id ||
                      deepseek.models.find(m => deepseek.selected[m.id])?.id ||
                      "deepseek-v4-pro";
    try {
      const r = await fetch("/api/setup/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: "DeepSeek 测试", base_url: deepseek.base_url, api_key: deepseek.api_key, model: testModel }),
      });
      const d = await r.json();
      deepseek._testing = false;
      if (d.ok) { deepseek.tested = true; deepseek._err = ""; }
      else { deepseek.tested = false; deepseek._err = d.reason || "未知错"; }
    } catch (e) {
      deepseek._testing = false; deepseek.tested = false; deepseek._err = e.message;
    }
    renderDeepseek();
    refreshSaveState();
  }

  // ── ② 百炼(视觉助手)卡 ──────────────────────────────
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
        <input id="bailianKey" type="password" value="${escape(bailian.api_key)}" placeholder="sk-... (没填的话拖图会瘸,但 chat 仍能用)">
        <button id="bailianTest" class="bailian-test-btn">${bailian._testing ? "⋯ 测试中" : (bailian.tested ? "✓ 通过" : "测试")}</button>
      </div>
      ${bailian._err ? `<div class="setup-prov-err">${escape(bailian._err)}</div>` : ""}
      <div class="bailian-models-label">视觉 model(可多选,默认 flash 够用)</div>
      <div class="bailian-models">${checks}</div>
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
        renderBailian();
        refreshSaveState();
      });
    });
  }

  async function testBailian() {
    if (!bailian.api_key) { bailian._err = "key 是空的"; renderBailian(); return; }
    bailian._testing = true; bailian._err = "";
    renderBailian();
    const testModel = bailian.models.find(m => bailian.selected[m.id])?.id || "qwen3-vl-flash";
    try {
      const r = await fetch("/api/setup/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: "百炼视觉测试", base_url: bailian.base_url, api_key: bailian.api_key, model: testModel }),
      });
      const d = await r.json();
      bailian._testing = false;
      if (d.ok) { bailian.tested = true; bailian._err = ""; }
      else { bailian.tested = false; bailian._err = d.reason || "未知错"; }
    } catch (e) {
      bailian._testing = false; bailian.tested = false; bailian._err = e.message;
    }
    renderBailian();
    refreshSaveState();
  }

  // ── ③ 百度(折叠区)──────────────────────────────────
  function renderBaidu() {
    const wrap = document.getElementById("setupBaidu");
    if (!wrap) return;
    wrap.innerHTML = `
      <div class="setup-baidu-row">
        <label>抠图 API key</label>
        <input id="bdCutApi" type="password" value="${escape(baidu.cutout_api)}" placeholder="可空">
        <label>抠图 secret</label>
        <input id="bdCutSec" type="password" value="${escape(baidu.cutout_secret)}" placeholder="可空">
        <button id="bdCutTest">${baidu._tested ? "✓ 通过" : "测试"}</button>
      </div>
    `;
    const $ = id => document.getElementById(id);
    $("bdCutApi").addEventListener("input", e => { baidu.cutout_api = e.target.value; baidu._tested = false; });
    $("bdCutSec").addEventListener("input", e => { baidu.cutout_secret = e.target.value; baidu._tested = false; });
    $("bdCutTest").addEventListener("click", testBaidu);
  }

  async function testBaidu() {
    try {
      const r = await fetch("/api/setup/test-baidu", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: baidu.cutout_api, secret_key: baidu.cutout_secret }),
      });
      const d = await r.json();
      baidu._tested = !!d.ok;
      if (!d.ok) alert(`抠图测试失败: ${d.reason || ""}`);
      renderBaidu();
    } catch (e) {
      alert(`测试请求失败: ${e.message}`);
    }
  }

  function close() {
    if (!canClose) return;
    overlay?.remove(); overlay = null;
  }

  function refreshSaveState() {
    // 至少 DeepSeek tested + 选一个 model 才能保存
    const dsOk = deepseek.tested && Object.values(deepseek.selected).some(v => v);
    const btn = document.getElementById("setupSaveBtn");
    const hint = document.getElementById("setupHint");
    if (btn) btn.disabled = !dsOk;
    if (hint) {
      if (!deepseek.tested) hint.textContent = "填 DeepSeek key + 测试通过即可保存";
      else if (!Object.values(deepseek.selected).some(v=>v)) hint.textContent = "至少勾选一个 DeepSeek model";
      else if (!bailian.tested) hint.textContent = "可以保存了(视觉助手没配的话拖图会瘸)";
      else hint.textContent = "全部就绪 — 保存";
    }
  }

  async function save() {
    const profiles = [];
    // DeepSeek 主对话 profile
    if (deepseek.tested) {
      for (const m of deepseek.models) {
        if (!deepseek.selected[m.id]) continue;
        profiles.push({
          id: m.id,
          label: m.tag ? `${m.label} (${m.tag})` : m.label,
          base_url: deepseek.base_url,
          api_key: deepseek.api_key,
          model: m.id,
        });
      }
    }
    // 百炼视觉 profile(允许 backup chat 用,但主要是 vision 路用)
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
    if (!profiles.length) { alert("没有可保存的 profile"); return; }
    const def = deepseek.default_model_id || profiles[0].id;
    const payload = {
      models: profiles,
      default_model_id: def,
    };
    // 视觉助手专用字段(让 _qwen_classify_image 走对的 key)
    if (bailian.tested && bailian.api_key) {
      payload.dashscope_api_key = bailian.api_key;
      payload.dashscope_base_url = bailian.base_url;
      payload.dashscope_vision_model = Object.keys(bailian.selected).find(k => bailian.selected[k]) || "qwen3-vl-flash";
    }
    if (baidu._tested) {
      payload.baidu_cutout_api_key = baidu.cutout_api;
      payload.baidu_cutout_secret_key = baidu.cutout_secret;
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
