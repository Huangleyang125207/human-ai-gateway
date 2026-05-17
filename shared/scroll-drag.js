/* scroll-drag.js · 横向拖动滚 + 边缘渐变(暴露 window.gateway.dragScroll)
 *
 * 用法:
 *   gateway.dragScroll(element)   — 给一个横向溢出的容器套上拖动 + fade。
 *   返一个 updateFade(),用于内容变化后手动刷渐变(否则只在 scroll 时更新)。
 *
 * CSS 要求:.scroll-drag 类(已在 style.css 定义,JS 自动加)。
 */
(function () {
  function dragScroll(el) {
    if (!el || el.dataset.scrollDragInit) return () => {};
    el.dataset.scrollDragInit = "1";
    el.classList.add("scroll-drag");

    let dragging = false, startX = 0, startScrollLeft = 0, didDrag = false;

    el.addEventListener("mousedown", (e) => {
      // 只接受左键
      if (e.button !== 0) return;
      dragging = true; didDrag = false;
      startX = e.clientX;
      startScrollLeft = el.scrollLeft;
      el.classList.add("dragging");
    });

    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      if (Math.abs(dx) > 3) didDrag = true;
      el.scrollLeft = startScrollLeft - dx;
      e.preventDefault();
    });

    document.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      el.classList.remove("dragging");
      // 拖动距离 > 3px → 拦截后续一次 click(避免拖完误触发 button onclick)
      if (didDrag) {
        const blockOnce = (ev) => {
          ev.stopPropagation(); ev.preventDefault();
          document.removeEventListener("click", blockOnce, true);
        };
        document.addEventListener("click", blockOnce, true);
      }
    });

    // 鼠标滚轮:垂直 wheel 转横向 scroll
    el.addEventListener("wheel", (e) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        el.scrollLeft += e.deltaY;
        e.preventDefault();
      }
    }, { passive: false });

    function updateFade() {
      const maxScroll = el.scrollWidth - el.clientWidth - 1;
      el.classList.toggle("no-fade-left",  el.scrollLeft <= 0);
      el.classList.toggle("no-fade-right", el.scrollLeft >= maxScroll);
    }
    el.addEventListener("scroll", updateFade);
    // 第一帧 + 后续重绘前各跑一次(防内容刚渲完 scrollWidth 还没就绪)
    updateFade();
    requestAnimationFrame(updateFade);
    return updateFade;
  }

  window.gateway = window.gateway || {};
  window.gateway.dragScroll = dragScroll;
})();
