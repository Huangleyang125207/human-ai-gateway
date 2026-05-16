/* entry-pretext-wrap.js · bug 2 v1 — 图自由 absolute + 文字 pretext 绕图共存(含富文本)
 *
 * v1 增量:支持 strong/em/code/a 富文本(walk DOM 提取 runs,layout 后按字符 offset 切回带 style 的 spans)。
 * 仍不支持:table / ul / ol / blockquote / img 嵌入(检测到则跳过,保持原 HTML 渲染)。
 *
 * 主流程:
 *   1. 找所有 .entry,跟 scrapbook .sb-wrap 算重叠
 *   2. 重叠 entry → extractRuns 抽 (text, style)[] 序列(walk DOM 保留格式)
 *   3. pretext.prepareWithSegments(纯文本) + layoutNextLineRange 算每行宽
 *   4. 按每行字符长度从 runs 切片 → 渲染成 absolute container,内嵌 inline <span> 带 style
 *   5. 原 .entry-text display:none 让位
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
      return null;  // 含 unsupported tag → 整 entry 跳过
    }
    return runs;
  }

  /** 把 raw text 串起来,同时算每个 run 的 [startChar, endChar) */
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

  /** 给定一段 [absStart, absEnd) 字符区间,切出所有覆盖到的 run 子片,返 [{text, style}] */
  function sliceRunsRange(runRanges, absStart, absEnd) {
    const out = [];
    for (const r of runRanges) {
      if (r.end <= absStart) continue;
      if (r.start >= absEnd) break;
      const s = Math.max(0, absStart - r.start);
      const e = Math.min(r.end - r.start, absEnd - r.start);
      // 实际 text 在原 run 的 text 中切
      // 但 r 里没存 text;runRanges 跟 runs 同 index,所以用 r.style + 计算 text:
      // 反查 plain → 不够准,因为 normalization。简单办法:把 text 也存进 runRanges。
      out.push({ s, e, style: r.style, runStart: r.start });
    }
    return out;
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

  /** 算一个任意元素 el 跟所有 sb-wrap 的重叠矩形(以 el 的 client coord 为基准) */
  function obstaclesForElement(el) {
    const tRect = el.getBoundingClientRect();
    const out = [];
    document.querySelectorAll(".sb-wrap").forEach((wrap) => {
      const wRect = wrap.getBoundingClientRect();
      const overlapTop = Math.max(0, wRect.top - tRect.top);
      const overlapBottom = Math.min(tRect.height, wRect.bottom - tRect.top);
      const overlapLeft = Math.max(0, wRect.left - tRect.left);
      const overlapRight = Math.min(tRect.width, wRect.right - tRect.left);
      if (overlapBottom <= overlapTop || overlapRight <= overlapLeft) return;
      out.push({
        top: Math.max(0, overlapTop - 4),
        bottom: Math.min(tRect.height, overlapBottom + 4),
        left: Math.max(0, overlapLeft - 8),
        right: Math.min(tRect.width, overlapRight + 8),
      });
    });
    return out;
  }

  /** wrapEl(el) — 对任意文本类元素(plain/rich text)应用 pretext 绕图。
   * 跟 wrapEntry 不同:不区分 entry,任何 el 重叠图就 wrap。
   * el 可以是 .entry-text / .entry-title h3 / etc。失败/不适用静默返。
   */
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

    // layout — 每行根据 y 算可用 segments,fill 每个 segment;同步记录该 line 在原 plain 中的字符 range
    let cursor = { segmentIndex: 0, graphemeIndex: 0 };
    let charPos = 0;       // 当前已经渲染到 plain 的字符 offset
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
        // 该行在 plain 中的 char range:从 charPos 起,长度 = lineText.length
        // (pretext 的 materialize 给的 text 跟 plain substring 等长,除非 grapheme normalization)
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

    // 渲染 — 每行一个 div,内嵌 inline spans 带 style。layer 作为 el 自身的子元素(absolute 内部)
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
      // 切 runs(ln.cStart, ln.cEnd)
      let pos = ln.cStart;
      while (pos < ln.cEnd) {
        // 找包含 pos 的 run
        const r = runRanges.find(rr => rr.start <= pos && pos < rr.end);
        if (!r) break;
        const take = Math.min(r.end, ln.cEnd) - pos;
        // 切 run 的原 text (runs[i].text):用 plain.slice 拿
        const slice = plain.slice(pos, pos + take);
        const span = document.createElement("span");
        span.textContent = slice.replace(/\n/g, "");  // 行内不留换行
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
    // 隐藏 el 内原有 text children(layer 自己保留不被隐藏)
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
    layer.addEventListener("click", () => unwrapEl(el, entry), { once: true });
    return true;
  }

  function unwrapEl(el, entry) {
    const layer = el.querySelector(":scope > ." + PRETEXT_LAYER_CLASS);
    if (layer) layer.remove();
    // 恢复原有 children 的 visibility
    [...el.childNodes].forEach(n => {
      if (n.nodeType !== Node.ELEMENT_NODE) return;
      if (n.dataset.pretextHidden) {
        // unwrap the wrapper span,让 text 节点回到原位
        const text = n.firstChild;
        if (text) n.parentNode.insertBefore(text, n);
        n.remove();
      } else if (n.dataset.pretextOldVisibility !== undefined) {
        n.style.visibility = n.dataset.pretextOldVisibility;
        delete n.dataset.pretextOldVisibility;
      }
    });
    el.removeAttribute("data-pretext-wrapped-el");
    // entry 里若还有别的 wrapped el → flag 不清;否则清
    if (entry && !entry.querySelector("[data-pretext-wrapped-el]")) {
      entry.removeAttribute(WRAPPED_FLAG);
    }
    if (el.classList.contains("entry-text") || el.tagName === "P") el.focus?.();
  }

  function unwrapEntry(entry) {
    entry.querySelectorAll("[data-pretext-wrapped-el]").forEach(el => unwrapEl(el, entry));
  }

  /** wrapEntry — 扫 entry 内所有可 wrap 的 text 类元素(body + title) */
  function wrapEntry(entry) {
    // 顺序:title 先(在前),body 后(在后)。各自独立判断是否重叠图。
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
