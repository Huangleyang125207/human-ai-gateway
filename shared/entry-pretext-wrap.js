/* entry-pretext-wrap.js · bug 2 v2 — 完整收尾
 *
 * v2 增量(相对 v1.1):
 *   1. obstacle 用 polygon(支持旋转图的真实多边形,告别 axis-aligned bbox 近似)
 *   2. tags chips 行用 shift-container(padding-left / max-width)绕图
 *   3. 点击 pretext layer → 不只 unwrap,还把 caret 精确落到点击位置(caretRangeFromPoint)
 *   4. 暴露 liveRewrap(rAF-throttled,scrapbook drag 中调用)
 *
 * v1 增量:支持 strong/em/code/a 富文本。
 * 仍不支持:table / ul / ol / blockquote / img 嵌入(检测到则跳过)。
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

  /** sb-wrap 的 4 角多边形(client 坐标)。
   * sb-wrap 本身 axis-aligned w×h,sb-wrap-inner rotate(N deg) 绕 wrap 中心。
   * 所以视觉上的矩形 = wrap 的 4 角绕中心旋转 N 度。
   */
  function wrapPolygonClient(wrap) {
    const r = wrap.getBoundingClientRect();
    const cx = (r.left + r.right) / 2;
    const cy = (r.top + r.bottom) / 2;
    const rotation = parseFloat(wrap.dataset.rotation || "0") || 0;
    const rad = rotation * Math.PI / 180;
    const cos = Math.cos(rad), sin = Math.sin(rad);
    const hw = r.width / 2, hh = r.height / 2;
    // padding:让文字别贴图
    const pad = 6;
    const PW = hw + pad, PH = hh + pad;
    const corners = [[-PW, -PH], [PW, -PH], [PW, PH], [-PW, PH]];
    return corners.map(([x, y]) => [cx + x * cos - y * sin, cy + x * sin + y * cos]);
  }

  /** 把 client 多边形转到 el 的 local 坐标 */
  function polyToLocal(poly, originRect) {
    return poly.map(([x, y]) => [x - originRect.left, y - originRect.top]);
  }

  /** 算 el 跟所有 sb-wrap 的 obstacle polygons(local 坐标) */
  function obstaclesForElement(el) {
    const r = el.getBoundingClientRect();
    const out = [];
    document.querySelectorAll(".sb-wrap").forEach((wrap) => {
      const polyC = wrapPolygonClient(wrap);
      // 快筛:polygon bbox 跟 el 矩形相交?
      let pxMin = Infinity, pxMax = -Infinity, pyMin = Infinity, pyMax = -Infinity;
      for (const [x, y] of polyC) {
        if (x < pxMin) pxMin = x;
        if (x > pxMax) pxMax = x;
        if (y < pyMin) pyMin = y;
        if (y > pyMax) pyMax = y;
      }
      if (pxMax <= r.left || pxMin >= r.right) return;
      if (pyMax <= r.top || pyMin >= r.bottom) return;
      out.push({ poly: polyToLocal(polyC, r) });
    });
    return out;
  }

  /** 凸多边形 + 水平扫线 y → x range (left, right) 或 null */
  function polyScanlineRange(poly, y) {
    let xMin = Infinity, xMax = -Infinity;
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i];
      const [x2, y2] = poly[(i + 1) % poly.length];
      // 边跨越 y?
      const cross = (y1 <= y && y < y2) || (y2 <= y && y < y1);
      if (!cross) continue;
      const t = (y - y1) / (y2 - y1);
      const x = x1 + t * (x2 - x1);
      if (x < xMin) xMin = x;
      if (x > xMax) xMax = x;
    }
    if (xMin === Infinity) return null;
    return { left: xMin, right: xMax };
  }

  /** y 带 [yTop, yBot] 跟凸多边形求并 x range — 端点 + 内部顶点取 envelope */
  function polyBandRange(poly, yTop, yBot) {
    let xMin = Infinity, xMax = -Infinity;
    const sample = (y) => {
      const r = polyScanlineRange(poly, y);
      if (r) {
        if (r.left < xMin) xMin = r.left;
        if (r.right > xMax) xMax = r.right;
      }
    };
    sample(yTop);
    sample(yBot - 0.01);  // 避免恰好命中下边界判失
    for (const [, vy] of poly) {
      if (vy > yTop && vy < yBot) sample(vy);
    }
    if (xMin === Infinity) return null;
    return { left: xMin, right: xMax };
  }

  /** 给定 y 行的可用宽度切片([{x, width}, ...]) — 文字两侧都能流 */
  function availableSegments(width, lineTop, lineBottom, obstacles) {
    // 该行被哪些 obstacle 阻挡 → 算每个的 x range(polygon scanline 精确,非 bbox)
    const blockers = [];
    for (const o of obstacles) {
      const r = polyBandRange(o.poly, lineTop, lineBottom);
      if (!r) continue;
      const l = Math.max(0, r.left);
      const rr = Math.min(width, r.right);
      if (rr <= l) continue;
      blockers.push([l, rr]);
    }
    if (blockers.length === 0) return [{ x: 0, width }];
    blockers.sort((a, b) => a[0] - b[0]);
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

  /** Walk DOM,产 [{text, style}],style = {bold,italic,code,href} */
  function extractRuns(textEl) {
    const runs = [];
    const UNSUPPORTED = new Set(["TABLE", "UL", "OL", "BLOCKQUOTE", "IMG", "PRE"]);
    function walk(node, style) {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.textContent) runs.push({ text: node.textContent, style: { ...style } });
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.nodeName;
      // pretext 自身的渲染层 / hidden wrapper 不算
      if (node.classList?.contains(PRETEXT_LAYER_CLASS)) return;
      if (node.dataset?.pretextHidden) return;
      if (UNSUPPORTED.has(tag)) throw new Error("unsupported:" + tag);
      if (tag === "BR") { runs.push({ text: "\n", style: { ...style } }); return; }
      const ns = { ...style };
      if (tag === "STRONG" || tag === "B") ns.bold = true;
      if (tag === "EM" || tag === "I") ns.italic = true;
      if (tag === "CODE") ns.code = true;
      if (tag === "A") ns.href = node.getAttribute("href") || "";
      for (const ch of node.childNodes) walk(ch, ns);
      if (tag === "P") runs.push({ text: "\n", style: {} });
    }
    try {
      for (const ch of textEl.childNodes) walk(ch, {});
    } catch (e) {
      return null;  // 含 unsupported tag → 整 el 跳过
    }
    return runs;
  }

  function flattenRuns(runs) {
    let plain = "";
    const runRanges = [];
    for (const r of runs) {
      const start = plain.length;
      plain += r.text;
      runRanges.push({ start, end: plain.length, style: r.style });
    }
    return { plain, runRanges };
  }

  function styleSpanCSS(style) {
    const parts = [];
    if (style.bold) parts.push("font-weight:700");
    if (style.italic) parts.push("font-style:italic");
    if (style.code) parts.push(
      'font-family:ui-monospace,"SF Mono",Menlo,monospace;' +
      "background:rgba(184,122,79,0.08);padding:0 2px;border-radius:3px"
    );
    return parts.join(";");
  }

  /** shiftTagsRow — 用 padding-left / max-width 把 chip 行让开 obstacle */
  function shiftTagsRow(entry) {
    const tagsEl = entry.querySelector(".entry-tags");
    if (!tagsEl) return;
    // 先复位再算(否则反复触发会累加)
    tagsEl.style.paddingLeft = "";
    tagsEl.style.maxWidth = "";
    const r = tagsEl.getBoundingClientRect();
    if (r.height < 1) return;
    let padLeft = 0, maxRight = Infinity;
    document.querySelectorAll(".sb-wrap").forEach((wrap) => {
      const polyC = wrapPolygonClient(wrap);
      // 投影到 tags 行 y 带
      const local = polyToLocal(polyC, r);
      const band = polyBandRange(local, 0, r.height);
      if (!band) return;
      const oLeft = Math.max(0, band.left);
      const oRight = Math.min(r.width, band.right);
      if (oRight <= oLeft) return;
      // obstacle 在左半 → 把行向右推
      if (oLeft < r.width * 0.5) {
        padLeft = Math.max(padLeft, oRight + 8);
      } else {
        maxRight = Math.min(maxRight, oLeft - 8);
      }
    });
    if (padLeft > 0) tagsEl.style.paddingLeft = padLeft + "px";
    if (maxRight < Infinity) tagsEl.style.maxWidth = maxRight + "px";
  }

  function unshiftTagsRow(entry) {
    const tagsEl = entry.querySelector(".entry-tags");
    if (!tagsEl) return;
    tagsEl.style.paddingLeft = "";
    tagsEl.style.maxWidth = "";
  }

  /** wrapEl(el, entry) — 对任意文本类元素应用 pretext 绕图(支持 polygon 精确 obstacle) */
  function wrapEl(el, entry) {
    if (!el) return false;
    if (el.classList.contains("empty-body")) return false;
    if (el.hasAttribute("data-pretext-wrapped-el")) return false;
    const obstacles = obstaclesForElement(el);
    if (obstacles.length === 0) return false;

    const runs = extractRuns(el);
    if (!runs || runs.length === 0) return false;
    const { plain, runRanges } = flattenRuns(runs);
    const text = plain.replace(/\n+$/, "");
    if (!text.trim()) return false;

    const cs = getComputedStyle(el);
    const font = `${cs.fontStyle} ${cs.fontVariant} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const lineHeight = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.6);
    const width = el.clientWidth;
    if (width < 50) return false;

    let prepared;
    try { prepared = window.pretext.prepareWithSegments(text, font); }
    catch (e) { console.warn("[wrap] prepare failed:", e); return false; }

    let cursor = { segmentIndex: 0, graphemeIndex: 0 };
    let charPos = 0;
    let y = 0;
    const renderedLines = [];
    const MAX_LINES = 300;
    while (renderedLines.length < MAX_LINES) {
      const segs = availableSegments(width, y, y + lineHeight, obstacles);
      let advanced = false;
      for (const seg of segs) {
        let range;
        try { range = window.pretext.layoutNextLineRange(prepared, cursor, seg.width); }
        catch (e) { console.warn("[wrap] layout failed:", e); break; }
        if (!range) { advanced = false; break; }
        const line = window.pretext.materializeLineRange(prepared, range);
        const lineText = line.text || "";
        const cStart = charPos;
        const cEnd = charPos + lineText.length;
        renderedLines.push({ text: lineText, x: seg.x, y, width: seg.width, cStart, cEnd });
        charPos = cEnd;
        cursor = range.end;
        advanced = true;
        if (cursor.segmentIndex >= prepared.widths.length) break;
      }
      if (!advanced) break;
      y += lineHeight;
      if (cursor.segmentIndex >= prepared.widths.length) break;
    }

    if (renderedLines.length === 0) return false;

    let layer = el.querySelector(":scope > ." + PRETEXT_LAYER_CLASS);
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
      const row = document.createElement("div");
      row.style.cssText = `
        position: absolute;
        left: ${ln.x}px;
        top: ${ln.y}px;
        width: ${ln.width}px;
        line-height: ${lineHeight}px;
        white-space: nowrap;
        overflow: hidden;
      `;
      let pos = ln.cStart;
      while (pos < ln.cEnd) {
        const r = runRanges.find(rr => rr.start <= pos && pos < rr.end);
        if (!r) break;
        const take = Math.min(r.end, ln.cEnd) - pos;
        const slice = plain.slice(pos, pos + take);
        const span = document.createElement("span");
        span.textContent = slice.replace(/\n/g, "");
        const css = styleSpanCSS(r.style);
        if (css) span.style.cssText = css;
        if (r.style.href) {
          const a = document.createElement("a");
          a.href = r.style.href;
          a.appendChild(span);
          row.appendChild(a);
        } else {
          row.appendChild(span);
        }
        pos += take;
      }
      layer.appendChild(row);
    }

    if (getComputedStyle(el).position === "static") el.style.position = "relative";
    // 关键:layer 是 absolute 的,不撑高父元素 → 让原 el 至少跟 layer 一样高,
    // 否则 layer 会溢出到下条 entry,把 `.entry + .entry` 的分割线吃掉
    const layerHeight = y + lineHeight;
    el.dataset.pretextOldMinHeight = el.style.minHeight || "";
    el.style.minHeight = layerHeight + "px";
    [...el.childNodes].forEach(n => {
      if (n.nodeType === Node.ELEMENT_NODE && n.classList?.contains(PRETEXT_LAYER_CLASS)) return;
      if (n.nodeType === Node.TEXT_NODE) {
        const w = document.createElement("span");
        w.dataset.pretextHidden = "1";
        w.style.visibility = "hidden";
        n.parentNode.insertBefore(w, n);
        w.appendChild(n);
      } else if (n.nodeType === Node.ELEMENT_NODE) {
        n.dataset.pretextOldVisibility = n.style.visibility || "";
        n.style.visibility = "hidden";
      }
    });
    el.appendChild(layer);
    el.setAttribute("data-pretext-wrapped-el", "1");
    if (entry) entry.setAttribute(WRAPPED_FLAG, "1");

    layer.style.pointerEvents = "auto";
    layer.style.cursor = "text";
    // 点击 → unwrap + caret 落到点击位置(精确编辑入口)
    layer.addEventListener("mousedown", (e) => {
      const cx = e.clientX, cy = e.clientY;
      e.preventDefault();
      unwrapEl(el, entry);
      requestAnimationFrame(() => {
        if (el.contentEditable !== "true") el.contentEditable = "true";
        el.focus();
        let range = null;
        if (document.caretRangeFromPoint) {
          range = document.caretRangeFromPoint(cx, cy);
        } else if (document.caretPositionFromPoint) {
          const cp = document.caretPositionFromPoint(cx, cy);
          if (cp) {
            range = document.createRange();
            range.setStart(cp.offsetNode, cp.offset);
            range.collapse(true);
          }
        }
        if (range) {
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        }
      });
    }, { once: true });
    return true;
  }

  function unwrapEl(el, entry) {
    const layer = el.querySelector(":scope > ." + PRETEXT_LAYER_CLASS);
    if (layer) layer.remove();
    [...el.childNodes].forEach(n => {
      if (n.nodeType !== Node.ELEMENT_NODE) return;
      if (n.dataset.pretextHidden) {
        const text = n.firstChild;
        if (text) n.parentNode.insertBefore(text, n);
        n.remove();
      } else if (n.dataset.pretextOldVisibility !== undefined) {
        n.style.visibility = n.dataset.pretextOldVisibility;
        delete n.dataset.pretextOldVisibility;
      }
    });
    if (el.dataset.pretextOldMinHeight !== undefined) {
      el.style.minHeight = el.dataset.pretextOldMinHeight;
      delete el.dataset.pretextOldMinHeight;
    }
    el.removeAttribute("data-pretext-wrapped-el");
    if (entry && !entry.querySelector("[data-pretext-wrapped-el]")) {
      entry.removeAttribute(WRAPPED_FLAG);
    }
  }

  function unwrapEntry(entry) {
    entry.querySelectorAll("[data-pretext-wrapped-el]").forEach(el => unwrapEl(el, entry));
    unshiftTagsRow(entry);
  }

  /** wrapEntry — title + body + tags chips 全套 */
  function wrapEntry(entry) {
    shiftTagsRow(entry);  // chip 行先 shift,再算 title/body 的 y(布局会跟着变)
    const title = entry.querySelector(".entry-title");
    if (title) wrapEl(title, entry);
    const text = entry.querySelector(".entry-text");
    if (text) wrapEl(text, entry);
  }

  function wrapAll() {
    whenReady(() => {
      document.querySelectorAll(".entry").forEach(wrapEntry);
    });
  }

  function unwrapAll() {
    document.querySelectorAll(".entry").forEach(entry => {
      if (entry.hasAttribute(WRAPPED_FLAG)) unwrapEntry(entry);
      else unshiftTagsRow(entry);  // 即使 body 没 wrap,tag shift 也要清
    });
  }

  // liveRewrap — rAF 节流,drag/rotate/scale 过程中调用
  let livePending = false;
  function liveRewrap() {
    if (livePending) return;
    livePending = true;
    requestAnimationFrame(() => {
      livePending = false;
      unwrapAll();
      // wrapAll 内部 whenReady → 同步触发(pretext 已 ready 时)
      document.querySelectorAll(".entry").forEach(wrapEntry);
    });
  }

  window.gateway = window.gateway || {};
  window.gateway.entryWrap = {
    rewrap: () => { unwrapAll(); requestAnimationFrame(wrapAll); },
    liveRewrap,
    unwrapAll,
  };

  document.addEventListener("DOMContentLoaded", () => {
    setTimeout(wrapAll, 800);
    // blur 自动 rewrap(用户改完 text 内容)
    document.addEventListener("blur", (e) => {
      const t = e.target;
      if (t?.classList?.contains("entry-text") || t?.classList?.contains("entry-title")) {
        const entry = t.closest(".entry");
        if (entry) {
          entry.removeAttribute(WRAPPED_FLAG);
          requestAnimationFrame(() => wrapEntry(entry));
        }
      }
    }, true);
  });
})();
