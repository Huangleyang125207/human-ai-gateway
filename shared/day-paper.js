/* gateway · 单日页 · 交互(vanilla)
   方向:呼吸、墨迹晕开、纸页起身;绝不闪烁弹跳
   P2b 起包成 window.paperInit():数据层(day-paper-data.js)渲染完 DOM 再调,
   行为绑定才有东西可绑。打卡/水杯的真实写入也在 data 层,这里只管手感。 */
window.paperInit = function () {
  "use strict";
  if (window.paperInit._done) { return; }
  window.paperInit._done = true;
  document.documentElement.classList.add("has-js");

  var motionOK = window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
  function motionOn() {
    return motionOK && document.body.dataset.motion !== "off";
  }

  /* ── 墨迹落纸:入场 ───────────────────────── */
  var inks = Array.prototype.slice.call(document.querySelectorAll(".ink-in"));
  inks.forEach(function (el) {
    var d = el.getAttribute("data-delay");
    if (d) { el.style.transitionDelay = d + "ms"; }
  });
  var pending = inks.slice();
  function reveal(el) {
    el.classList.add("is-in");
    window.setTimeout(function () { el.style.transitionDelay = ""; }, 2400);
  }
  function checkReveal() {
    var vh = window.innerHeight;
    for (var i = pending.length - 1; i >= 0; i--) {
      var r = pending[i].getBoundingClientRect();
      if (r.top < vh * 0.94 && r.bottom > -40) {
        reveal(pending[i]);
        pending.splice(i, 1);
      }
    }
  }
  var ticking = false;
  function onScroll() {
    if (ticking || pending.length === 0) { return; }
    ticking = true;
    window.requestAnimationFrame(function () { ticking = false; checkReveal(); });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });

  /* 启动门:先确认这个环境真的在跳帧,再开始藏→显的入场。
     打印、被节流的 iframe、奇怪的内嵌宿主里 rAF 不走——
     那就判定为无帧环境,直接以终态示人,不赌一个永远不会完成的过渡 */
  var revealStarted = false;
  function startReveal() {
    if (revealStarted) { return; }
    revealStarted = true;
    checkReveal();
    window.setTimeout(checkReveal, 250);
    window.setTimeout(checkReveal, 900);
  }
  window.requestAnimationFrame(function () {
    window.requestAnimationFrame(function () { startReveal(); });
  });
  window.setTimeout(function () {
    if (!revealStarted) {
      document.body.setAttribute("data-frozen", "1");
      revealStarted = true;
    }
  }, 500);

  /* ── 光标的气息 ──────────────────────────── */
  var glow = document.querySelector(".cursor-glow");
  if (glow && window.matchMedia("(pointer: fine)").matches) {
    var gx = window.innerWidth / 2, gy = window.innerHeight / 3;
    var tx = gx, ty = gy, rafId = null;
    var step = function () {
      gx += (tx - gx) * 0.06;
      gy += (ty - gy) * 0.06;
      glow.style.transform = "translate(" + gx.toFixed(1) + "px," + gy.toFixed(1) + "px)";
      if (Math.abs(tx - gx) + Math.abs(ty - gy) > 0.4) {
        rafId = window.requestAnimationFrame(step);
      } else {
        rafId = null;
      }
    };
    window.addEventListener("pointermove", function (e) {
      tx = e.clientX; ty = e.clientY;
      if (motionOn()) {
        glow.classList.add("awake");
        if (rafId === null) { rafId = window.requestAnimationFrame(step); }
      } else {
        glow.classList.remove("awake");
      }
    }, { passive: true });
  }

  /* ── 压缩圆环 ────────────────────────────── */
  var ring = document.getElementById("memoryRing");
  var arc = document.getElementById("ringArc");
  if (ring && arc) {
    ring.addEventListener("click", function () {
      if (ring.classList.contains("compressed")) { return; }
      arc.style.strokeDashoffset = "53.4";
      ring.classList.add("compressed");
    });
  }

  /* ── 选中即引用:@引用 进对话的入口 ──────── */
  var chip = document.getElementById("quoteChip");
  var composer = document.getElementById("composer");
  var note = document.getElementById("composerNote");
  var lastQuote = "";

  function hideChip() {
    if (chip) { chip.classList.remove("show"); }
  }

  function maybeShowChip() {
    if (!chip) { return; }
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) { hideChip(); return; }
    var text = sel.toString().trim();
    if (text.length < 4 || text.length > 300) { hideChip(); return; }
    var range = sel.getRangeAt(0);
    var node = range.commonAncestorContainer;
    var el = node.nodeType === 1 ? node : node.parentElement;
    if (!el || !el.closest(".day, .morning")) { hideChip(); return; }
    if (el.closest(".composer-input")) { hideChip(); return; }
    var rect = range.getBoundingClientRect();
    lastQuote = text;
    chip.style.left = Math.min(window.innerWidth - 150, Math.max(12, rect.left + rect.width / 2 - 56)) + "px";
    chip.style.top = (window.scrollY + rect.bottom + 14) + "px";
    chip.classList.add("show");
  }

  document.addEventListener("pointerup", function () {
    window.setTimeout(maybeShowChip, 10);
  });
  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) { hideChip(); }
  });

  if (chip) {
    chip.addEventListener("click", function () {
      var text = (lastQuote || "").replace(/\s+/g, " ").trim();
      hideChip();
      var sel = window.getSelection();
      if (sel) { sel.removeAllRanges(); }
      if (!text) { return; }
      // 引入对话:选中的话当 quote ref 推进 thread(同 classic「指给AI看」,addRef 自带开页)。
      // 旧版往 #composer 塞,但 composer 由纸条异步渲染、init 时为 null → chip 一直是死的;改打 thread。
      if (window.gateway && window.gateway.thread) {
        window.gateway.thread.addRef({
          kind: "quote",
          label: text.slice(0, 18) + (text.length > 18 ? "…" : ""),
          payload: "「" + text + "」",
        });
        return;
      }
      // 兜底:thread 没起来时(理论不会)落进当晚「回一句」composer
      var c = document.getElementById("composer");
      if (c) {
        c.textContent = (c.textContent ? c.textContent + " " : "") + "「" + text + "」 ";
        c.focus();
      }
    });
  }

};
