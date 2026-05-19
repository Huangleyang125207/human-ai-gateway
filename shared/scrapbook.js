/* scrapbook.js v3 · 自由 absolute 拖
 *
 * 图浮在 .page 之上,position:absolute,left=x_pct% top=y_px。
 * 用户想拖哪儿就在哪儿 — 不绕文字,纯叠加。
 *
 * 数据:
 *   {id, src, anchor_time, x_pct, y_px, w, h, rotation}
 *   anchor_time 仍保留 — 用于"图属于哪一条 entry"的语义(future viewer/filter)
 *   x_pct / y_px = 真实位置(相对 .sb-layer 的尺寸)
 *
 * 兼容:
 *   旧 {align: 'left'|'right'} → 转 x_pct (left=3%, right=78%)
 *     y_px 从 anchor_time entry 的 offsetTop 取,fallback 0
 *   旧 absolute 字段 {x, y} (legacy v1) → 转 x_pct = x / page.width * 100, y_px = y
 *
 * 删除 / 旋转 / 缩放 handle 跟之前一样,改 transform / w/h,写盘
 */
(function () {
  let items = [];
  let currentDate = null;
  let saveTimers = {};

  async function fetchAndRender(date) {
    if (!date) return;
    currentDate = date;
    try {
      const r = await fetch(`/api/scrapbook?date=${encodeURIComponent(date)}`);
      const data = await r.json();
      items = (data.items || []).map(normalizeItem);
    } catch {
      items = [];
    }
    render();
  }

  /** 兼容老数据 → 统一成 {x_pct, y_px} */
  function normalizeItem(it) {
    // auto_y=true:AI 调 place_scrapbook_image 没指定 y → 按 anchor_time 算到对应 entry 旁边。
    // 用户拖完后 upsert 清掉 auto_y,之后 reload 不再覆盖用户拖拽位置。
    if (it.auto_y && it.anchor_time) {
      it.y_px = computeYFromAnchor(it.anchor_time);
      if (it.x_pct == null) it.x_pct = 75;
      return it;
    }
    if (it.x_pct != null && it.y_px != null) return it;
    // legacy v2: align → x_pct
    if (it.align === "left" || it.align === "right") {
      it.x_pct = (it.align === "left") ? 3 : 78;
      it.y_px = computeYFromAnchor(it.anchor_time);
      return it;
    }
    // legacy v1: 绝对 x / y (px)
    if (it.x != null && it.y != null) {
      const layer = ensureLayer();
      const w = layer.clientWidth || 800;
      it.x_pct = Math.max(0, Math.min(95, (it.x / w) * 100));
      it.y_px = it.y;
      return it;
    }
    // 全空 → 默认右上
    it.x_pct = 75;
    it.y_px = computeYFromAnchor(it.anchor_time);
    return it;
  }

  function computeYFromAnchor(time) {
    if (!time) return 0;
    const e = [...document.querySelectorAll(".entry")].find(x => x.dataset.time === time);
    if (!e) return 0;
    const layer = ensureLayer();
    const layerRect = layer.getBoundingClientRect();
    const entryRect = e.getBoundingClientRect();
    return Math.max(0, entryRect.top - layerRect.top);
  }

  /** 取/建 .sb-layer 父容器 */
  function ensureLayer() {
    let layer = document.querySelector(".sb-layer");
    if (layer) return layer;
    const page = document.querySelector("main.page") || document.body;
    layer = document.createElement("div");
    layer.className = "sb-layer";
    // 插到 page 内部最前,这样它作为 absolute 子元素覆盖整个 page
    page.appendChild(layer);
    return layer;
  }

  function render() {
    // 清旧
    document.querySelectorAll(".sb-wrap").forEach(el => el.remove());
    // 清 legacy float spacer
    document.querySelectorAll('.entry[data-sb-spacer="1"]').forEach(e => {
      e.style.marginTop = "";
      delete e.dataset.sbSpacer;
    });
    const layer = ensureLayer();
    for (const it of items) {
      placeWrap(it, layer);
    }
    // 图重新 render 之后,触发文字 re-wrap(pretext)
    window.gateway?.entryWrap?.rewrap?.();
    // 二次 + 三次 pass:pretext 把文字绕图是异步的,首次定位用的是 pretext 前的
    // entry top,wrap 完了 entry 整体下移 → 图错位。等 200ms / 600ms 让 pretext
    // 都跑完再 reposition。两次是因为第一次 reposition 可能又触发一次 rewrap。
    const repositionPass = () => {
      let moved = false;
      for (const it of items) {
        if (!it.auto_y || !it.anchor_time) continue;
        const newY = computeYFromAnchor(it.anchor_time);
        if (Math.abs(newY - (it.y_px || 0)) < 2) continue;
        it.y_px = newY;
        const wrap = document.querySelector(`.sb-wrap[data-id="${it.id}"]`);
        if (wrap) wrap.style.top = newY + "px";
        moved = true;
      }
      if (moved) window.gateway?.entryWrap?.rewrap?.();
      return moved;
    };
    setTimeout(repositionPass, 200);
    setTimeout(repositionPass, 600);
  }

  function placeWrap(it, layer) {
    const wrap = document.createElement("div");
    wrap.className = "sb-wrap";
    wrap.dataset.id = it.id;
    applyPos(wrap, it);
    wrap.style.width = (it.w || 200) + "px";
    wrap.style.height = (it.h || 200) + "px";

    wrap.dataset.rotation = String(it.rotation || 0);
    const inner = document.createElement("div");
    inner.className = "sb-wrap-inner";
    inner.style.transform = `rotate(${it.rotation || 0}deg)`;

    const img = document.createElement("img");
    img.src = it.src;
    img.alt = "";
    img.draggable = false;
    inner.appendChild(img);

    const rotH = mkHandle("sb-rotate", "拖动旋转");
    const scaleH = mkHandle("sb-scale", "拖动缩放");
    const delH = mkHandle("sb-del", "删除", "×");
    inner.appendChild(rotH);
    inner.appendChild(scaleH);
    inner.appendChild(delH);

    wrap.appendChild(inner);
    layer.appendChild(wrap);

    bindDrag(wrap, it);
    bindRotate(rotH, inner, it);
    bindScale(scaleH, wrap, it);
    bindDelete(delH, it);
  }

  function applyPos(wrap, it) {
    wrap.style.left = (it.x_pct ?? 50) + "%";
    wrap.style.top = (it.y_px ?? 0) + "px";
  }

  function mkHandle(extraClass, title, text) {
    const h = document.createElement("div");
    h.className = "sb-handle " + extraClass;
    h.title = title;
    if (text) h.textContent = text;
    return h;
  }

  function bindDrag(wrap, it) {
    let startCX, startCY, startLeftPx, startTopPx, layerW, dragging = false;
    wrap.addEventListener("pointerdown", (e) => {
      if (e.target.classList.contains("sb-handle")) return;
      e.preventDefault();
      const layer = wrap.parentElement;
      const layerRect = layer.getBoundingClientRect();
      layerW = layerRect.width;
      startCX = e.clientX; startCY = e.clientY;
      // 当前像素位置(把 % 解算为 px,drag 中用 px 计算更准)
      const wrapRect = wrap.getBoundingClientRect();
      startLeftPx = wrapRect.left - layerRect.left;
      startTopPx = wrapRect.top - layerRect.top;
      dragging = true;
      wrap.setPointerCapture(e.pointerId);
      wrap.classList.add("dragging");
    });
    wrap.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const newLeftPx = startLeftPx + (e.clientX - startCX);
      const newTopPx = startTopPx + (e.clientY - startCY);
      wrap.style.left = newLeftPx + "px";
      wrap.style.top = newTopPx + "px";
      // live drag reflow — rAF throttled inside entryWrap
      window.gateway?.entryWrap?.liveRewrap?.();
    });
    wrap.addEventListener("pointerup", async (e) => {
      if (!dragging) return;
      dragging = false;
      try { wrap.releasePointerCapture(e.pointerId); } catch {}
      wrap.classList.remove("dragging");
      // 落定:把 px 换算成 % (x) + px (y);约束在 0~95% 之间防漂出页
      const layerRect = wrap.parentElement.getBoundingClientRect();
      const finalLeftPx = parseFloat(wrap.style.left);
      const finalTopPx = parseFloat(wrap.style.top);
      const xPct = Math.max(0, Math.min(95, (finalLeftPx / layerRect.width) * 100));
      const yPx = Math.max(0, finalTopPx);
      it.x_pct = Math.round(xPct * 10) / 10;
      it.y_px = Math.round(yPx);
      it.auto_y = false;  // 用户手动定了位置,下次 reload 不再按 anchor 重算
      applyPos(wrap, it);  // 重置回 % 表达式(响应式)
      // 更新 anchor_time:看落点 y 离哪个 entry 最近,记下来
      const newAnchor = inferAnchorByY(it.y_px);
      if (newAnchor) it.anchor_time = newAnchor;
      scheduleSave(it);
      // bug 2:触发 pretext re-wrap,文字绕图重排
      window.gateway?.entryWrap?.rewrap?.();
    });
  }

  /** 根据 y_px 找最近的 entry 的 anchor_time(用于 entry 删除/恢复时定位) */
  function inferAnchorByY(yPx) {
    const layer = document.querySelector(".sb-layer");
    if (!layer) return null;
    const layerTop = layer.getBoundingClientRect().top;
    let bestE = null, bestDist = Infinity;
    for (const e of document.querySelectorAll(".entry")) {
      const eTop = e.getBoundingClientRect().top - layerTop;
      const d = Math.abs(eTop - yPx);
      if (d < bestDist) { bestDist = d; bestE = e; }
    }
    return bestE?.dataset.time || null;
  }

  function bindRotate(handle, inner, it) {
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault(); e.stopPropagation();
      const r = inner.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const startAng = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
      const origRot = it.rotation || 0;
      handle.setPointerCapture(e.pointerId);
      const onMove = (ev) => {
        const ang = Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180 / Math.PI;
        it.rotation = Math.round((origRot + (ang - startAng)) * 10) / 10;
        inner.style.transform = `rotate(${it.rotation}deg)`;
        // 同步给 obstacle 用的 polygon
        const wrap = inner.closest(".sb-wrap");
        if (wrap) wrap.dataset.rotation = String(it.rotation);
        window.gateway?.entryWrap?.liveRewrap?.();
      };
      const onUp = () => {
        try { handle.releasePointerCapture(e.pointerId); } catch {}
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        scheduleSave(it);
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
    });
  }

  function bindScale(handle, wrap, it) {
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault(); e.stopPropagation();
      const startX = e.clientX;
      const origW = it.w || 200, origH = it.h || 200;
      const ratio = origH / origW;
      handle.setPointerCapture(e.pointerId);
      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        let nw = Math.max(60, origW + dx);
        let nh = nw * ratio;
        it.w = Math.round(nw);
        it.h = Math.round(nh);
        wrap.style.width = it.w + "px";
        wrap.style.height = it.h + "px";
        window.gateway?.entryWrap?.liveRewrap?.();
      };
      const onUp = () => {
        try { handle.releasePointerCapture(e.pointerId); } catch {}
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        scheduleSave(it);
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
    });
  }

  function bindDelete(handle, it) {
    handle.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("删掉这张图?")) return;
      try {
        await fetch("/api/scrapbook/delete", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({date: currentDate, id: it.id}),
        });
        await fetchAndRender(currentDate);
      } catch (e) {
        window.gateway?.whisper?.("删除失败 — " + e.message);
      }
    });
  }

  function scheduleSave(it) {
    if (saveTimers[it.id]) clearTimeout(saveTimers[it.id]);
    saveTimers[it.id] = setTimeout(async () => {
      delete saveTimers[it.id];
      try {
        await fetch("/api/scrapbook/upsert", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({date: currentDate, ...it}),
        });
      } catch (e) {
        window.gateway?.whisper?.("scrapbook 没存上 — " + e.message);
      }
    }, 600);
  }

  window.gateway = window.gateway || {};
  window.gateway.scrapbook = {
    refresh: (date) => fetchAndRender(date || currentDate),
  };
})();
