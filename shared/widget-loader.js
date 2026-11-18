/* gateway widget loader
 *
 * 怎么用：在 HTML 页面写 <div data-slot="some-slot-name"></div>
 *         widget 的 manifest.json 声明它进哪个 slot
 *         widget-loader.js 加载 .user-widgets.json + 对应 widget 文件 → 拼装
 *
 * 怎么扩展：未来 AI 加新 widget 时
 *   1. 读 agents/human-ai-schedule/gateway-extension/WIDGET_AUTHORING.md
 *   2. 在 widgets/<name>/ 写 manifest.json + widget.html + widget.js
 *   3. 把 <name> 加进 .user-widgets.json 的 active 数组
 *   4. 用户下次开页面 widget 自动出现，无需重 build
 */

(async function gatewayWidgetLoader() {
  const mountedSpecIds = new Set();
  // 注:user-widgets 历史在 gateway/.user-widgets.json 走静态 mount;
  // 后来搬到 APP_STATE_DIR(frozen 模式 _MEIPASS 只读),改走 API。
  let config;
  try {
    config = await fetch('/api/user-widgets').then(r => r.json());
  } catch (e) {
    console.warn('[gateway] /api/user-widgets failed — running with empty widget set');
    config = { active: [] };
  }

  // Product-owned stable defaults use the safe WidgetSpec runtime. Explicit
  // legacy selections remain supported; WIP widgets never auto-mount.
  let defaultLoaded = [];
  try {
    const catalog = await fetch('/api/widgets/catalog').then(r => r.json());
    defaultLoaded = (catalog.widgets || [])
      .filter(w => w.default_loaded && w.status === 'stable')
      .map(w => w.name);
  } catch (e) {
    console.warn('[gateway] widget catalog failed — using explicit selection only');
  }

  const disabled = new Set(config.disabled || []);
  const selected = [...new Set([...(config.active || []), ...defaultLoaded])]
    .filter(name => !disabled.has(name));
  for (const widgetName of selected) {
    try {
      await loadWidget(widgetName);
    } catch (e) {
      console.error(`[gateway] failed to load widget "${widgetName}":`, e);
    }
  }

  // AI-installed WidgetSpec documents live in writable app state, not the
  // packaged widgets directory. They enter through the same fixed renderer.
  await refreshInstalledSpecs();
  document.addEventListener('gateway:widget-spec-installed', refreshInstalledSpecs);

  // toast utility — widgets call window.gatewayToast('msg')
  window.gatewayToast = function(msg) {
    const t = document.getElementById('toast') || (() => {
      const el = document.createElement('div');
      el.id = 'toast';
      el.className = 'toast';
      document.body.appendChild(el);
      return el;
    })();
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('show'), 1800);
  };

  async function loadWidget(name) {
    const manifest = await fetch(`./widgets/${name}/manifest.json`).then(r => r.json());
    const slotEl = document.querySelector(`[data-slot="${manifest.slot}"]`);
    if (!slotEl) {
      console.warn(`[gateway] widget "${name}" wants slot "${manifest.slot}" but no such slot on this page`);
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = `widget widget-${name}`;
    // make widget right-clickable via contextmenu.js
    wrapper.dataset.context = 'widget';
    wrapper.dataset.widgetName = name;
    if (manifest.spec) {
      if (!window.gatewayWidgetSpec) {
        throw new Error('WidgetSpec renderer is not loaded');
      }
      const spec = await fetch(`./widgets/${name}/${manifest.spec}`).then(r => r.json());
      slotEl.appendChild(wrapper);
      await window.gatewayWidgetSpec.mount(wrapper, spec);
      mountedSpecIds.add(spec.id);
      return;
    }

    const html = await fetch(`./widgets/${name}/widget.html`).then(r => r.text());
    // ★ legacy 审计疤:旧版 add_widget/patch_widget 曾可逐字落 widget.html。旧文件仍需
    //   DOMPurify 防护；新 WidgetSpec 路径不进入这里，也不使用 innerHTML。
    //   <img onerror> 类 payload 经 innerHTML 会执行 →
    //   偷读 API key 外传。渲染前过 DOMPurify(与 shared/md.js 同一把;widget 的 JS 走
    //   manifest.script 的独立 <script src>,不靠内联脚本,消毒不损功能)。
    wrapper.innerHTML = (typeof DOMPurify !== 'undefined' && DOMPurify.sanitize)
      ? DOMPurify.sanitize(html) : html;
    slotEl.appendChild(wrapper);

    if (manifest.script) {
      const s = document.createElement('script');
      s.src = `./widgets/${name}/widget.js`;
      s.defer = true;
      document.body.appendChild(s);
    }
  }

  async function loadInstalledSpec(spec) {
    if (mountedSpecIds.has(spec.id)) return;
    if (!window.gatewayWidgetSpec) {
      throw new Error('WidgetSpec renderer is not loaded');
    }
    const slotEl = document.querySelector('[data-slot="top-strip"]');
    if (!slotEl) return;
    const wrapper = document.createElement('div');
    wrapper.className = `widget widget-${spec.id}`;
    wrapper.dataset.context = 'widget';
    wrapper.dataset.widgetName = spec.id;
    slotEl.appendChild(wrapper);
    await window.gatewayWidgetSpec.mount(wrapper, spec);
    mountedSpecIds.add(spec.id);
  }

  async function refreshInstalledSpecs() {
    try {
      const installed = await fetch('/api/widget-runtime/installed', { cache: 'no-store' })
        .then(r => r.json());
      for (const item of (installed.widgets || [])) {
        if (item.enabled !== false && item.spec) {
          await loadInstalledSpec(item.spec);
        }
      }
    } catch (e) {
      console.warn('[gateway] installed WidgetSpec list failed:', e);
    }
  }
})();
