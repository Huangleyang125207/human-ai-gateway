/* gateway · 总览 · 排版稿交互(vanilla)
   方向不变:呼吸、墨迹晕开、纸页折叠;绝不闪烁弹跳
   本页特有:折页↔信笺的开合、样张切换(评审用)、更新条折叠离场 */
(function () {
  "use strict";
  document.documentElement.classList.add("has-js");

  var motionOK = window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
  function motionOn() {
    return motionOK && document.body.dataset.motion !== "off";
  }

  /* ── 昼夜(与单日页同一把钥匙) ─────────────────── */
  var THEME_KEY = "gateway-theme";
  var modeToggle = document.getElementById("modeToggle");
  function applyTheme(mode) {
    if (mode === "day" || mode === "night") {
      document.documentElement.setAttribute("data-theme", mode);
    } else {
      document.documentElement.removeAttribute("data-theme");
      mode = "system";
    }
    if (modeToggle) { modeToggle.setAttribute("data-mode", mode); }
  }
  function setTheme(mode) {
    try {
      if (mode === "day" || mode === "night") {
        window.localStorage.setItem(THEME_KEY, mode);
      } else {
        window.localStorage.removeItem(THEME_KEY);
      }
    } catch (e) { /* 私隐模式等 */ }
    applyTheme(mode);
  }
  window.gatewayTheme = { set: setTheme };
  var savedTheme = null;
  try { savedTheme = window.localStorage.getItem(THEME_KEY); } catch (e) {}
  applyTheme(savedTheme);
  if (modeToggle) {
    modeToggle.addEventListener("click", function (e) {
      var cur = modeToggle.getAttribute("data-mode");
      if (e.target.closest(".mt-day")) { setTheme(cur === "day" ? "system" : "day"); }
      else if (e.target.closest(".mt-night")) { setTheme(cur === "night" ? "system" : "night"); }
      else { setTheme(cur === "day" ? "night" : cur === "night" ? "system" : "day"); }
    });
  }

  /* ── 样张切换(评审用,vendor 时删) ─────────────── */
  document.querySelectorAll(".proof-toggle button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.body.setAttribute("data-state", btn.dataset.proof);
      document.querySelectorAll(".proof-toggle button").forEach(function (b) {
        b.setAttribute("aria-pressed", b === btn ? "true" : "false");
      });
      /* 切样张后,把还没入场的都直接以终态示人 */
      document.querySelectorAll(".ink-in:not(.is-in)").forEach(function (el) {
        el.classList.add("is-in");
      });
    });
  });

  /* ── 折页 ↔ 信笺 ────────────────────────────────── */
  var fold = document.getElementById("chatFold");
  var pane = document.getElementById("chatPane");
  var closeBtn = document.getElementById("chatClose");
  var letters = document.getElementById("letters");
  function openChat() {
    document.body.setAttribute("data-chat", "open");
    if (fold) { fold.removeAttribute("data-unread"); }
    if (letters) {
      window.setTimeout(function () { letters.scrollTop = letters.scrollHeight; }, 60);
    }
  }
  function closeChat() {
    document.body.removeAttribute("data-chat");
  }
  if (fold) { fold.addEventListener("click", openChat); }
  if (closeBtn) { closeBtn.addEventListener("click", closeChat); }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.body.getAttribute("data-chat") === "open" &&
        !(document.activeElement && document.activeElement.isContentEditable)) {
      closeChat();
    }
  });

  /* ── 更新通知条:换上 / 先不(折叠离场) ─────────── */
  function foldAway(el) {
    el.style.height = el.scrollHeight + "px";
    el.style.overflow = "hidden";
    void el.offsetHeight;
    el.style.transition = "height 0.8s var(--ease-ink), opacity 0.8s var(--ease-ink), margin 0.8s var(--ease-ink), padding 0.8s var(--ease-ink), transform 0.8s var(--ease-ink)";
    el.style.opacity = "0";
    el.style.transform = "rotate(-0.5deg) rotateX(62deg) scaleY(0.6)";
    el.style.transformOrigin = "50% 0";
    el.style.height = "0px";
    el.style.margin = "0 auto";
    el.style.paddingTop = "0";
    el.style.paddingBottom = "0";
    window.setTimeout(function () { el.remove(); }, motionOn() ? 820 : 0);
  }
  var slip = document.getElementById("updateSlip");
  if (slip) {
    slip.addEventListener("click", function (e) {
      if (e.target.closest(".us-later")) { foldAway(slip); }
      else if (e.target.closest(".us-act")) {
        slip.querySelector("p").textContent = "记下了,下次启动就换上。";
        e.target.remove();
        var later = slip.querySelector(".us-later");
        if (later) { later.remove(); }
        window.setTimeout(function () { foldAway(slip); }, 1800);
      }
    });
  }

  /* ── 压缩圆环:收进匣子 ─────────────────────────── */
  var paneRing = document.getElementById("paneRing");
  var paneArc = document.getElementById("paneArc");
  if (paneRing && paneArc) {
    paneRing.addEventListener("click", function () {
      if (paneRing.classList.contains("compressed") ||
          paneRing.classList.contains("compressing")) { return; }
      paneRing.classList.add("compressing");
      paneArc.style.strokeDashoffset = "53.4";
      paneRing.title = "已收进快照";
      window.setTimeout(function () {
        paneRing.classList.remove("compressing");
        paneRing.classList.add("compressed");
      }, motionOn() ? 1450 : 0);
    });
  }

  /* ── 信笺 composer:回一句(演示) ────────────────── */
  var composer = document.getElementById("paneComposer");
  var note = document.getElementById("paneNote");
  function appendLetter(cls, metaHTML, bodyHTML) {
    var div = document.createElement("div");
    div.className = "letter " + cls;
    div.innerHTML = "<p class=\"letter-meta\">" + metaHTML + "</p><div class=\"letter-body\">" + bodyHTML + "</div>";
    letters.appendChild(div);
    letters.scrollTop = letters.scrollHeight;
    return div;
  }
  if (composer && letters) {
    composer.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || e.shiftKey) { return; }
      e.preventDefault();
      var text = composer.textContent.trim();
      if (!text) { return; }
      composer.textContent = "";
      var now = new Date();
      var hm = now.getHours() + ":" + String(now.getMinutes()).padStart(2, "0");
      appendLetter("me", hm + " · 我", "<p></p>");
      letters.lastChild.querySelector("p").textContent = text;
      if (note) { note.textContent = "已夹进今天的 md。"; }
      var wait = appendLetter("ai", "<span class=\"seal\">鲸</span>它在落笔",
        "<span class=\"ink-grind\"><i></i><i></i><i></i></span>");
      window.setTimeout(function () {
        wait.querySelector(".letter-meta").innerHTML = "<span class=\"seal\">鲸</span>" + hm + " · 鲸";
        wait.querySelector(".letter-body").innerHTML = "<p>记下了。这页是排版稿——接上真线之后,我才真的会回。</p>";
        letters.scrollTop = letters.scrollHeight;
      }, motionOn() ? 2600 : 50);
    });
  }

  /* ── 选中即引用:引到信笺里说 ──────────────────── */
  var chip = document.getElementById("quoteChip");
  var lastQuote = "";
  function hideChip() { if (chip) { chip.classList.remove("show"); } }
  document.addEventListener("pointerup", function () {
    window.setTimeout(function () {
      if (!chip) { return; }
      if (document.activeElement && document.activeElement.isContentEditable) { hideChip(); return; }
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) { hideChip(); return; }
      var text = sel.toString().trim();
      if (text.length < 4 || text.length > 300) { hideChip(); return; }
      var node = sel.getRangeAt(0).commonAncestorContainer;
      var el = node.nodeType === 1 ? node : node.parentElement;
      if (!el || !el.closest(".sheet")) { hideChip(); return; }
      var rect = sel.getRangeAt(0).getBoundingClientRect();
      lastQuote = text;
      chip.style.left = Math.min(window.innerWidth - 150, Math.max(12, rect.left + rect.width / 2 - 56)) + "px";
      chip.style.top = (window.scrollY + rect.bottom + 14) + "px";
      chip.classList.add("show");
    }, 10);
  });
  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) { hideChip(); }
  });
  if (chip && composer) {
    chip.addEventListener("click", function () {
      hideChip();
      var sel = window.getSelection();
      if (sel) { sel.removeAllRanges(); }
      openChat();
      composer.textContent = (composer.textContent ? composer.textContent + " " : "") +
        "「" + lastQuote.replace(/\s+/g, " ") + "」 ";
      window.setTimeout(function () {
        composer.focus();
        var r = document.createRange();
        r.selectNodeContents(composer);
        r.collapse(false);
        var s = window.getSelection();
        s.removeAllRanges();
        s.addRange(r);
      }, motionOn() ? 500 : 0);
    });
  }

  /* ── 晨课的轻交互(总览只读打卡,管理在单日页) ─── */
  document.addEventListener("click", function (e) {
    var med = e.target.closest(".med");
    if (med) {
      var marks = med.querySelectorAll(".mark");
      var next = med.querySelector(".mark:not(.done)");
      if (next) { next.classList.add("done"); }
      else { marks.forEach(function (m) { m.classList.remove("done"); }); }
      med.classList.toggle("alldone",
        med.querySelectorAll(".mark.done").length === marks.length);
      return;
    }
    var cup = e.target.closest(".cup");
    if (cup) {
      cup.classList.toggle("full");
      var wrap = document.getElementById("cups");
      var tally = document.getElementById("cupsTally");
      if (wrap && tally) {
        var n = wrap.querySelectorAll(".cup.full").length;
        var total = wrap.querySelectorAll(".cup").length;
        tally.textContent = n + " / " + total + (n < total ? " · 宿醉的日子多喝两杯" : " · 喝满了");
      }
    }
  });

  /* ── 墨迹落纸:入场(与单日页同一套门) ─────────── */
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
      document.querySelectorAll(".ink-in").forEach(function (el) {
        el.style.transition = "none";
        el.style.transitionDelay = "";
        el.classList.add("is-in");
      });
      revealStarted = true;
    }
  }, 500);

  /* ── 光标的气息 ─────────────────────────────────── */
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
      } else { rafId = null; }
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
})();
