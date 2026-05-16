/* entry-pretext-wrap.js · bug 2 v0 — 图自由 absolute + 文字 pretext 绕图共存
 *
 * 限制(v0):
 *   - 只处理 plain-text 的 entry body(无 <strong>/<code>/<table> 等富文本格式)
 *   - 带 markdown 富文本的 entry 暂不绕,保持原 HTML 渲染
 *   - 编辑模式:点 .entry-text 切回原 contenteditable,blur 后再 re-wrap
 *
 * 主流程:
 *   1. 找所有 .entry,跟 scrapbook .sb-wrap 算重叠
 *   2. 重叠的 entry → extract textContent + getComputedStyle 的 font/lineHeight
 *   3. 用 pretext.prepareWithSegments + layoutNextLineRange(每行变 width)
 *   4. 渲染成 absolute spans 覆盖 .entry-text;原 .entry-text display:none
 */
(function () {
  const PRETEXT_LAYER_CLASS = "entry-pretext-layer";
  const WRAPPED_FLAG = "data-pretext-wrapped";
  let pretextReady = false;
  const pending = [];

  function onPretextReady() {
    pretextReady = true;
    while (pending.length) pending.shift()();
  }
  if (window.pretext) onPretextReady();
  else document.addEventListener("pretext-ready", onPretextReady, { once: true });

  function whenReady(fn) {
    if (pretextReady) fn();
    else pending.push(fn);
  }

  /** 算一个 entry 跟所有 sb-wrap 的重叠矩形(以 entry-text 的 client coord 为基准) */
  function obstaclesForEntry(entry) {
    const textEl = entry.querySelector(".entry-text");
    if (!textEl) return [];
    const tRect = textEl.getBoundingClientRect();
    const out = [];
    document.querySelectorAll(".sb-wrap").forEach((wrap) => {
      const wRect = wrap.getBoundingClientRect();
      // 矩形相交?
      const overlapTop = Math.max(0, wRect.top - tRect.top);
      const overlapBottom = Math.min(tRect.height, wRect.bottom - tRect.top);
      const overlapLeft = Math.max(0, wRect.left - tRect.left);
      const overlapRight = Math.min(tRect.width, wRect.right - tRect.left);
      if (overlapBottom <= overlapTop || overlapRight <= overlapLeft) return;
      // padding 4px 让文字别贴图
      out.push({
        top: Math.max(0, overlapTop - 4),
        bottom: Math.min(tRect.height, overlapBottom + 4),
        left: Math.max(0, overlapLeft - 8),
        right: Math.min(tRect.width, overlapRight + 8),
      });
    });
    return out;
  }

  /** 给定 y 行的可用宽度切片([{x, width}, ...]) — 文字两侧都能流 */
  function availableSegments(width, lineTop, lineBottom, obstacles) {
    // 该行被哪些 obstacle 阻挡
    const blocking = obstacles.filter(o => !(o.bottom <= lineTop || o.top >= lineBottom));
    if (blocking.length === 0) return [{ x: 0, width }];
    // 按 left 排序,扫描合并阻挡区间 → 算 free 段
    const blockers = blocking.map(o => [Math.max(0, o.left), Math.min(width, o.right)])
                              .sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [l, r] of blockers) {
      if (merged.length && l <= merged[merged.length - 1][1]) {
        merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], r);
      } else {
        merged.push([l, r]);
      }
    }
    const segs = [];
    let cursor = 0;
    for (const [l, r] of merged) {
      if (l > cursor) segs.push({ x: cursor, width: l - cursor });
      cursor = r;
    }
    if (cursor < width) segs.push({ x: cursor, width: width - cursor });
    // 极窄的段(< 40px)丢掉,避免一两字符的孤行
    return segs.filter(s => s.width >= 40);
  }

  /** 判断 entry-text 是否纯文本(没有 strong/em/code/table/list 等子元素) */
  function isPlainText(textEl) {
    const allowed = new Set(["P", "BR", "#text"]);
    for (const node of textEl.childNodes) {
      const tag = node.nodeName;
      if (!allowed.has(tag) && tag !== "#text") return false;
      // 段内还要保证没有富文本子节点
      if (node.nodeType === Node.ELEMENT_NODE) {
        for (const child of node.childNodes) {
          if (child.nodeType === Node.ELEMENT_NODE && child.nodeName !== "BR") return false;
        }
      }
    }
    return true;
  }

  function wrapEntry(entry) {
    const textEl = entry.querySelector(".entry-text");
    if (!textEl || textEl.classList.contains("empty-body")) return;
    if (entry.hasAttribute(WRAPPED_FLAG)) return;  // 已包过 skip
    const obstacles = obstaclesForEntry(entry);
    if (obstacles.length === 0) return;
    if (!isPlainText(textEl)) return;  // 富文本 entry v0 不动

    const text = textEl.textContent.trim();
    if (!text) return;

    const cs = getComputedStyle(textEl);
    const font = `${cs.fontStyle} ${cs.fontVariant} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const lineHeight = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.6);
    const width = textEl.clientWidth;
    if (width < 50) return;

    let prepared;
    try {
      prepared = window.pretext.prepareWithSegments(text, font);
    } catch (e) {
      console.warn("[entry-pretext-wrap] prepare failed:", e);
      return;
    }

    // 走 layoutNextLineRange,每行根据 y 算可用 segment(s),fill 每个 segment
    let cursor = { segmentIndex: 0, graphemeIndex: 0 };
    let y = 0;
    const renderedLines = [];
    const MAX_LINES = 200;
    while (renderedLines.length < MAX_LINES) {
      const segs = availableSegments(width, y, y + lineHeight, obstacles);
      let advanced = false;
      for (const seg of segs) {
        let range;
        try {
          range = window.pretext.layoutNextLineRange(prepared, cursor, seg.width);
        } catch (e) {
          console.warn("[entry-pretext-wrap] layoutNextLineRange failed:", e);
          break;
        }
        if (!range) { advanced = false; break; }
        const line = window.pretext.materializeLineRange(prepared, range);
        renderedLines.push({ text: line.text || "", x: seg.x, y, width: seg.width });
        cursor = range.end;
        advanced = true;
        // 一行用完了 prepared 文字 → 退出
        if (cursor.segmentIndex >= prepared.widths.length) break;
      }
      if (!advanced) break;
      y += lineHeight;
      if (cursor.segmentIndex >= prepared.widths.length) break;
    }

    if (renderedLines.length === 0) return;

    // 渲染 — 在 textEl 上层叠一个 .entry-pretext-layer
    const parent = textEl.parentNode;
    if (!parent) return;
    let layer = parent.querySelector("." + PRETEXT_LAYER_CLASS);
    if (layer) layer.remove();
    layer = document.createElement("div");
    layer.className = PRETEXT_LAYER_CLASS;
    layer.style.cssText = `
      position: absolute;
      left: 0; top: 0;
      width: ${width}px;
      height: ${y + lineHeight}px;
      pointer-events: none;
      font: ${font};
    `;
    for (const ln of renderedLines) {
      const span = document.createElement("span");
      span.textContent = ln.text;
      span.style.cssText = `
        position: absolute;
        left: ${ln.x}px;
        top: ${ln.y}px;
        width: ${ln.width}px;
        line-height: ${lineHeight}px;
        white-space: nowrap;
        overflow: hidden;
      `;
      layer.appendChild(span);
    }
    // 父容器要 relative
    if (getComputedStyle(parent).position === "static") parent.style.position = "relative";
    parent.appendChild(layer);
    textEl.style.visibility = "hidden";       // 原 .entry-text 占位但不可见
    entry.setAttribute(WRAPPED_FLAG, "1");
    // 点 layer 任意处 → unwrap 进编辑模式(交回 contenteditable)
    layer.style.pointerEvents = "auto";
    layer.style.cursor = "text";
    layer.addEventListener("click", () => unwrapEntry(entry), { once: true });
  }

  function unwrapEntry(entry) {
    const layer = entry.querySelector("." + PRETEXT_LAYER_CLASS);
    if (layer) layer.remove();
    const textEl = entry.querySelector(".entry-text");
    if (textEl) {
      textEl.style.visibility = "";
      textEl.focus();
    }
    entry.removeAttribute(WRAPPED_FLAG);
  }

  function wrapAll() {
    whenReady(() => {
      document.querySelectorAll(".entry").forEach(wrapEntry);
    });
  }

  function unwrapAll() {
    document.querySelectorAll(".entry[" + WRAPPED_FLAG + "]").forEach(unwrapEntry);
  }

  /** 暴露 API:scrapbook drop 后 / journal refresh 后调 */
  window.gateway = window.gateway || {};
  window.gateway.entryWrap = {
    rewrap: () => { unwrapAll(); requestAnimationFrame(wrapAll); },
    unwrapAll,
  };

  // 初次 + 监听 entry-text blur(用户改完 body)
  document.addEventListener("DOMContentLoaded", () => {
    setTimeout(wrapAll, 800);
    document.addEventListener("blur", (e) => {
      if (e.target?.classList?.contains("entry-text")) {
        const entry = e.target.closest(".entry");
        if (entry) {
          entry.removeAttribute(WRAPPED_FLAG);
          requestAnimationFrame(() => wrapEntry(entry));
        }
      }
    }, true);
  });
})();
