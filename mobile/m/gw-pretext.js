// gw-pretext.js — 局部文字绕图(移动裁剪版;母本 shared/entry-pretext-wrap.js v2 逐段移植)
//
// 裁剪原则(2026-07-04 论证定):
//   · float 态贴纸(默认)靠 CSS 原生绕排,pretext 不醒 — 99% 贴纸零开销
//   · 只有用户摆过的贴纸(auto_y=false → 渲染为 absolute)才唤醒 pretext
//   · 作用域 = 单条 entry body(移动贴纸 DOM 就挂在 body 里,"判断在哪个 entry"免费)
//   · 重排纪律:拖动过程中不排,松手/重渲后 queue;翻页轨道 transform 中不量
// 与母本的差异:无 tags-row shift(移动 tag 行在 body 外)、无点击落 caret(移动编辑走 openCard)、
//   layer pointer-events:auto 保住 <a> 可点(外链 handler + openCard tap 守卫都在上层照常工作)。
(function () {
  'use strict';
  const GW = window.GW;
  const LAYER = 'gw-pretext-layer';
  let ready = false;
  const pend = [];
  function onReady() { ready = true; while (pend.length) pend.shift()(); }
  if (window.pretext) onReady();
  else document.addEventListener('pretext-ready', onReady, { once: true });

  /* 贴纸 4 角多边形(el local 坐标;旋转矩形,pad 6px 让文字别贴图) */
  function figPolygon(fig, originRect) {
    const r = fig.getBoundingClientRect();
    const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
    const rad = ((parseFloat(fig.dataset.rotation || '0') || 0) * Math.PI) / 180;
    const cos = Math.cos(rad), sin = Math.sin(rad);
    const pad = 6, PW = r.width / 2 + pad, PH = r.height / 2 + pad;
    return [[-PW, -PH], [PW, -PH], [PW, PH], [-PW, PH]].map(([x, y]) =>
      [cx + x * cos - y * sin - originRect.left, cy + x * sin + y * cos - originRect.top]);
  }
  function polyScanlineRange(poly, y) {
    let xMin = Infinity, xMax = -Infinity;
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
      const cross = (y1 <= y && y < y2) || (y2 <= y && y < y1);
      if (!cross) continue;
      const t = (y - y1) / (y2 - y1), x = x1 + t * (x2 - x1);
      if (x < xMin) xMin = x;
      if (x > xMax) xMax = x;
    }
    return xMin === Infinity ? null : { left: xMin, right: xMax };
  }
  function polyBandRange(poly, yTop, yBot) {
    let xMin = Infinity, xMax = -Infinity;
    const sample = (y) => {
      const r = polyScanlineRange(poly, y);
      if (r) { if (r.left < xMin) xMin = r.left; if (r.right > xMax) xMax = r.right; }
    };
    sample(yTop); sample(yBot - 0.01);
    for (const [, vy] of poly) if (vy > yTop && vy < yBot) sample(vy);
    return xMin === Infinity ? null : { left: xMin, right: xMax };
  }
  function availableSegments(width, lineTop, lineBottom, obstacles) {
    const blockers = [];
    for (const o of obstacles) {
      const r = polyBandRange(o.poly, lineTop, lineBottom);
      if (!r) continue;
      const l = Math.max(0, r.left), rr = Math.min(width, r.right);
      if (rr > l) blockers.push([l, rr]);
    }
    if (!blockers.length) return [{ x: 0, width }];
    blockers.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [l, r] of blockers) {
      if (merged.length && l <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], r);
      else merged.push([l, r]);
    }
    const segs = []; let cursor = 0;
    for (const [l, r] of merged) { if (l > cursor) segs.push({ x: cursor, width: l - cursor }); cursor = r; }
    if (cursor < width) segs.push({ x: cursor, width: width - cursor });
    return segs.filter((s) => s.width >= 40);   // 极窄段丢掉,避免一两字孤行
  }

  /* DOM → runs;跳过贴纸与 pretext 自身;含不支持标签则整体放弃(保持 CSS 原样) */
  const UNSUPPORTED = new Set(['TABLE', 'UL', 'OL', 'BLOCKQUOTE', 'IMG', 'PRE']);
  function extractRuns(el) {
    const runs = [];
    function walk(node, style) {
      if (node.nodeType === Node.TEXT_NODE) { if (node.textContent) runs.push({ text: node.textContent, style: { ...style } }); return; }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.classList && (node.classList.contains('gw-sticker') || node.classList.contains(LAYER))) return;
      if (node.dataset && node.dataset.pretextHidden) return;
      const tag = node.nodeName;
      if (UNSUPPORTED.has(tag)) throw new Error('unsupported:' + tag);
      if (tag === 'BR') { runs.push({ text: '\n', style: { ...style } }); return; }
      const ns = { ...style };
      if (tag === 'STRONG' || tag === 'B') ns.bold = true;
      if (tag === 'EM' || tag === 'I') ns.italic = true;
      if (tag === 'CODE') ns.code = true;
      if (tag === 'A') ns.href = node.getAttribute('href') || '';
      for (const ch of node.childNodes) walk(ch, ns);
      if (tag === 'P') runs.push({ text: '\n', style: {} });
    }
    try { for (const ch of el.childNodes) walk(ch, {}); } catch (e) { return null; }
    return runs;
  }
  function flattenRuns(runs) {
    let plain = ''; const runRanges = [];
    for (const r of runs) { const start = plain.length; plain += r.text; runRanges.push({ start, end: plain.length, style: r.style }); }
    return { plain, runRanges };
  }
  function styleSpanCSS(style) {
    const p = [];
    if (style.bold) p.push('font-weight:700');
    if (style.italic) p.push('font-style:italic');
    if (style.code) p.push('font-family:ui-monospace,"SF Mono",Menlo,monospace;background:rgba(184,122,79,0.08);padding:0 2px;border-radius:3px');
    return p.join(';');
  }

  function unwrapBody(el) {
    if (!el) return;
    const layer = el.querySelector(':scope > .' + LAYER);
    if (layer) layer.remove();
    [...el.childNodes].forEach((n) => {
      if (n.nodeType !== Node.ELEMENT_NODE) return;
      if (n.dataset && n.dataset.pretextHidden) {
        const text = n.firstChild;
        if (text) n.parentNode.insertBefore(text, n);
        n.remove();
      } else if (n.dataset && n.dataset.pretextOldVisibility !== undefined) {
        n.style.visibility = n.dataset.pretextOldVisibility;
        delete n.dataset.pretextOldVisibility;
      }
    });
    if (el.dataset.pretextOldMinHeight !== undefined) {
      el.style.minHeight = el.dataset.pretextOldMinHeight;
      delete el.dataset.pretextOldMinHeight;
    }
    delete el.dataset.gwWrapped;
  }

  function wrapBody(el) {
    if (!el || !el.isConnected || !window.pretext) return;
    unwrapBody(el);
    const figs = [...el.querySelectorAll(':scope > .gw-sticker')].filter((f) => getComputedStyle(f).position === 'absolute');
    if (!figs.length) return;
    const r0 = el.getBoundingClientRect();
    if (r0.width < 50) return;
    const obstacles = figs.map((f) => ({ poly: figPolygon(f, r0) }));
    const runs = extractRuns(el);
    if (!runs || !runs.length) return;
    const { plain, runRanges } = flattenRuns(runs);
    const text = plain.replace(/\n+$/, '');
    if (!text.trim()) return;
    const cs = getComputedStyle(el);
    const font = `${cs.fontStyle} ${cs.fontVariant} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const lineHeight = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.6;
    const width = el.clientWidth;
    let prepared;
    try { prepared = window.pretext.prepareWithSegments(text, font); } catch (e) { return; }

    let cursor = { segmentIndex: 0, graphemeIndex: 0 }, charPos = 0, y = 0;
    const lines = [];
    while (lines.length < 300) {
      const segs = availableSegments(width, y, y + lineHeight, obstacles);
      let advanced = false;
      for (const seg of segs) {
        let range;
        try { range = window.pretext.layoutNextLineRange(prepared, cursor, seg.width); } catch (e) { break; }
        if (!range) { advanced = false; break; }
        const line = window.pretext.materializeLineRange(prepared, range);
        const lineText = line.text || '';
        lines.push({ text: lineText, x: seg.x, y, width: seg.width, cStart: charPos, cEnd: charPos + lineText.length });
        charPos += lineText.length;
        cursor = range.end;
        advanced = true;
        if (cursor.segmentIndex >= prepared.widths.length) break;
      }
      if (!advanced) break;
      y += lineHeight;
      if (cursor.segmentIndex >= prepared.widths.length) break;
    }
    if (!lines.length) return;

    const layer = document.createElement('div');
    layer.className = LAYER;
    layer.style.cssText = `position:absolute;left:0;top:0;width:${width}px;height:${y + lineHeight}px;font:${font};pointer-events:auto;z-index:1;`;
    for (const ln of lines) {
      const row = document.createElement('div');
      row.style.cssText = `position:absolute;left:${ln.x}px;top:${ln.y}px;width:${ln.width}px;line-height:${lineHeight}px;white-space:nowrap;overflow:hidden;`;
      let pos = ln.cStart;
      while (pos < ln.cEnd) {
        const r = runRanges.find((rr) => rr.start <= pos && pos < rr.end);
        if (!r) break;
        const take = Math.min(r.end, ln.cEnd) - pos;
        const span = document.createElement('span');
        span.textContent = plain.slice(pos, pos + take).replace(/\n/g, '');
        const css = styleSpanCSS(r.style);
        if (css) span.style.cssText = css;
        if (r.style.href) {
          const a = document.createElement('a');
          a.href = r.style.href;
          a.appendChild(span);
          row.appendChild(a);
        } else row.appendChild(span);
        pos += take;
      }
      layer.appendChild(row);
    }

    if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
    el.dataset.pretextOldMinHeight = el.style.minHeight || '';
    el.style.minHeight = (y + lineHeight) + 'px';
    [...el.childNodes].forEach((n) => {
      if (n.nodeType === Node.ELEMENT_NODE && n.classList && (n.classList.contains(LAYER) || n.classList.contains('gw-sticker'))) return;
      if (n.nodeType === Node.TEXT_NODE) {
        const w = document.createElement('span');
        w.dataset.pretextHidden = '1';
        w.style.visibility = 'hidden';
        n.parentNode.insertBefore(w, n);
        w.appendChild(n);
      } else if (n.nodeType === Node.ELEMENT_NODE) {
        n.dataset.pretextOldVisibility = n.style.visibility || '';
        n.style.visibility = 'hidden';
      }
    });
    el.appendChild(layer);
    el.dataset.gwWrapped = '1';
  }

  /* queue:rAF 合并 + pretext ready 门;同一帧多次 queue 只排一遍 */
  const q = new Set();
  let qScheduled = false;
  function flush() {
    qScheduled = false;
    const els = [...q]; q.clear();
    els.forEach(wrapBody);
  }
  function queue(el) {
    if (!el) return;
    q.add(el);
    if (qScheduled) return;
    qScheduled = true;
    const run = () => requestAnimationFrame(flush);
    if (ready) run();
    else pend.push(run);
  }

  GW.pretextWrap = { queue, unwrap: unwrapBody };
})();
