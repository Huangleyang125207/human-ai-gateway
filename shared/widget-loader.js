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
  // 注:user-widgets 历史在 gateway/.user-widgets.json 走静态 mount;
  // 后来搬到 APP_STATE_DIR(frozen 模式 _MEIPASS 只读),改走 API。
  let config;
  try {
    config = await fetch('/api/user-widgets').then(r => r.json());
  } catch (e) {
    console.warn('[gateway] /api/user-widgets failed — running with empty widget set');
    config = { active: [] };
  }

  for (const widgetName of (config.active || [])) {
    try {
      await loadWidget(widgetName);
    } catch (e) {
      console.error(`[gateway] failed to load widget "${widgetName}":`, e);
    }
  }

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

    const html = await fetch(`./widgets/${name}/widget.html`).then(r => r.text());
    const wrapper = document.createElement('div');
    wrapper.className = `widget widget-${name}`;
    // make widget right-clickable via contextmenu.js
    wrapper.dataset.context = 'widget';
    wrapper.dataset.widgetName = name;
    wrapper.innerHTML = html;
    slotEl.appendChild(wrapper);

    if (manifest.script) {
      const s = document.createElement('script');
      s.src = `./widgets/${name}/widget.js`;
      s.defer = true;
      document.body.appendChild(s);
    }
  }
})();
