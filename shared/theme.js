/* theme.js — 双皮肤 + 日夜三态,全站单一真源。
 *
 * 皮肤(gateway-skin):整套前端的切换,不是配色。
 *   "classic" = 现版·私印小报(默认,monolith 页面族,永远是安全岛)
 *   "paper"   = 新版·纸与灯(cd 重设计,独立 *-paper.html 页面族,逐页组装)
 *   切换 = 跳到当前页在另一族的孪生页;孪生页还没组装出来就留在原地。
 *
 * 日夜(gateway-theme,只对 paper 皮肤有意义):
 *   "day" / "night" → html[data-theme] 定死
 *   缺省            → 摘掉 data-theme,design-tokens 里的
 *                     prefers-color-scheme 跟系统
 *
 * classic 页面没有任何 CSS 消费 data-theme/data-skin → 默认态零视觉影响。
 * 切换入口:设置「皮肤」节(marketplace.js)+ paper 页报头昼夜小印。
 */
(function () {
  var SKIN_KEY = "gateway-skin";
  var THEME_KEY = "gateway-theme";

  // 孪生页映射:classic 文件名 ↔ paper 文件名。
  // paper 族逐页组装,组装好一页就把它加进 PAPER_READY(没在列表里的不跳)。
  var TWINS = {
    "day.html": "day-paper.html",
    "index.html": "index-paper.html",
    "history.html": "history-paper.html",
    "": "index-paper.html",            // 根路径 = index
  };
  var PAPER_READY = ["day-paper.html", "index-paper.html"];  // 组装一页加一页

  function pageName() {
    var p = location.pathname.split("/").pop() || "";
    try { p = decodeURIComponent(p); } catch (e) {}
    return p;
  }

  function isPaperPage(name) {
    name = name === undefined ? pageName() : name;
    return /-paper\.html$/.test(name);
  }

  function classicTwin(paperName) {
    for (var c in TWINS) { if (TWINS[c] === paperName && c) return c; }
    return "index.html";
  }

  // ── theme(日夜)────────────────────────────────────────────
  function readTheme() {
    try { return localStorage.getItem(THEME_KEY) || "system"; } catch (e) { return "system"; }
  }

  function applyTheme(mode) {
    var root = document.documentElement;
    if (mode === "day" || mode === "night") root.setAttribute("data-theme", mode);
    else { root.removeAttribute("data-theme"); mode = "system"; }
    return mode;
  }

  function setTheme(mode) {
    mode = applyTheme(mode);
    try {
      if (mode === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, mode);
    } catch (e) {}
    try { window.dispatchEvent(new CustomEvent("gateway-theme-change", { detail: { mode: mode } })); } catch (e) {}
    return mode;
  }

  // ── skin(整套前端)────────────────────────────────────────
  function readSkin() {
    try { return localStorage.getItem(SKIN_KEY) === "paper" ? "paper" : "classic"; }
    catch (e) { return "classic"; }
  }

  function navigateForSkin(skin, onLoad) {
    var name = pageName();
    var carry = location.search + location.hash;  // ?date= 等参数跟着走
    if (skin === "paper" && !isPaperPage(name)) {
      var twin = TWINS[name];
      if (twin && PAPER_READY.indexOf(twin) >= 0) { location.href = "./" + twin + carry; return true; }
    }
    // paper→classic 只在显式切换/跨页同步时跳;进页(onLoad)不弹——
    // 直接打开 paper 页是用户意图,默认皮肤不该把人请出去(headless/分享链接同理)。
    if (!onLoad && skin === "classic" && isPaperPage(name)) {
      location.href = "./" + classicTwin(name) + carry;
      return true;
    }
    return false;
  }

  function setSkin(skin) {
    skin = skin === "paper" ? "paper" : "classic";
    try {
      if (skin === "classic") localStorage.removeItem(SKIN_KEY);
      else localStorage.setItem(SKIN_KEY, skin);
    } catch (e) {}
    try { window.dispatchEvent(new CustomEvent("gateway-skin-change", { detail: { skin: skin } })); } catch (e) {}
    navigateForSkin(skin);
    return skin;
  }

  // 跨标签页同步
  window.addEventListener("storage", function (e) {
    if (e.key === THEME_KEY) applyTheme(e.newValue || "system");
    if (e.key === SKIN_KEY) navigateForSkin(e.newValue === "paper" ? "paper" : "classic");
  });

  applyTheme(readTheme());
  // 进页路由:skin=paper 且当前在 classic → 跳孪生页;反向进页不弹(见上)
  navigateForSkin(readSkin(), true);

  window.gatewayTheme = { get: readTheme, set: setTheme, apply: applyTheme, KEY: THEME_KEY };
  window.gatewaySkin = {
    get: readSkin, set: setSkin, KEY: SKIN_KEY,
    twins: TWINS, ready: PAPER_READY, isPaperPage: isPaperPage,
  };
})();
