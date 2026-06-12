/* theme.js — 皮肤三态(day / night / system),全站单一真源。
 * 真源键:localStorage["gateway-theme"](跟 cd 交付的 mode-toggle 同一把钥匙)。
 * - "day" / "night" → html[data-theme] 定死
 * - 其他/缺省      → 摘掉 data-theme,交给 design-tokens 里的
 *                     prefers-color-scheme 媒体查询(跟系统)
 * 旧页面没有任何 CSS 消费 data-theme → 引本文件零视觉影响(组装期安全)。
 * 切换入口:设置「皮肤」行(marketplace.js)+ 新页面报头的昼夜小印。
 */
(function () {
  var KEY = "gateway-theme";

  function read() {
    try { return localStorage.getItem(KEY) || "system"; } catch (e) { return "system"; }
  }

  function apply(mode) {
    var root = document.documentElement;
    if (mode === "day" || mode === "night") {
      root.setAttribute("data-theme", mode);
    } else {
      root.removeAttribute("data-theme");
      mode = "system";
    }
    return mode;
  }

  function set(mode) {
    mode = apply(mode);
    try {
      if (mode === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch (e) { /* localStorage 不可用时只生效本页 */ }
    try {
      window.dispatchEvent(new CustomEvent("gateway-theme-change", { detail: { mode: mode } }));
    } catch (e) {}
    return mode;
  }

  // 跨标签页同步(设置页改了,单日页跟着变)
  window.addEventListener("storage", function (e) {
    if (e.key === KEY) apply(e.newValue || "system");
  });

  apply(read());

  window.gatewayTheme = { get: read, set: set, apply: apply, KEY: KEY };
})();
