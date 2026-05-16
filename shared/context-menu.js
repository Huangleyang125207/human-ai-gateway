/* context-menu.js · gateway 右键菜单
 *
 * 单例。任何代码调:
 *   window.gateway.menu.show(evt, items)
 *     items = [{label, action, disabled?}, ...] | [{divider:true}]
 * 自动 preventDefault native menu, 点空白 / Esc 关闭。
 */

(function () {
  const menu = document.createElement("div");
  menu.className = "ctx-menu hidden";
  menu.setAttribute("role", "menu");
  document.body.appendChild(menu);

  let open = false;

  function close() {
    if (!open) return;
    menu.classList.add("hidden");
    open = false;
  }

  function show(evt, items) {
    evt.preventDefault();
    evt.stopPropagation();
    menu.innerHTML = "";
    for (const it of items) {
      if (it.divider) {
        const hr = document.createElement("div");
        hr.className = "ctx-divider";
        menu.appendChild(hr);
        continue;
      }
      const btn = document.createElement("button");
      btn.className = "ctx-item" + (it.disabled ? " disabled" : "");
      btn.type = "button";
      btn.textContent = it.label;
      if (it.title) btn.title = it.title;
      if (!it.disabled) {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          close();
          try { it.action(); } catch (err) { console.error(err); }
        });
      }
      menu.appendChild(btn);
    }
    // position: clamp inside viewport
    const x = evt.clientX, y = evt.clientY;
    menu.style.left = x + "px";
    menu.style.top = y + "px";
    menu.classList.remove("hidden");
    open = true;
    // measure + flip if overflow
    requestAnimationFrame(() => {
      const r = menu.getBoundingClientRect();
      const vw = window.innerWidth, vh = window.innerHeight;
      if (r.right > vw - 8) menu.style.left = Math.max(8, vw - r.width - 8) + "px";
      if (r.bottom > vh - 8) menu.style.top = Math.max(8, vh - r.height - 8) + "px";
    });
  }

  // dismiss on outside-click / Esc / scroll
  document.addEventListener("click", (e) => {
    if (open && !menu.contains(e.target)) close();
  }, true);
  document.addEventListener("contextmenu", (e) => {
    // if another contextmenu opens, close current first; let the handler reshow
    if (open && !menu.contains(e.target)) close();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (open && e.key === "Escape") close();
  });
  window.addEventListener("scroll", close, true);
  window.addEventListener("resize", close);

  window.gateway = window.gateway || {};
  window.gateway.menu = { show, close };
})();
