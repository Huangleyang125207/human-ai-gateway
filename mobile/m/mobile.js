// 移动原生壳逻辑。数据全走 /api/*(被 mobile-api.js shim 本地服务)。
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function api(path, opts) { return fetch(path, opts).then(function (r) { return r.json(); }); }
  function md(s) { return window.gatewayMd ? window.gatewayMd(s || "") : (s || ""); }

  // ── 日期工具 ──
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function todayIso() { var d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function isoAdd(iso, n) { var p = iso.split("-"); var d = new Date(+p[0], +p[1] - 1, +p[2] + n); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function md_(iso) { var p = iso.split("-"); return +p[1] + "/" + +p[2]; }
  var WK = ["日", "一", "二", "三", "四", "五", "六"];
  function wk(iso) { var p = iso.split("-"); return "周" + WK[new Date(+p[0], +p[1] - 1, +p[2]).getDay()]; }

  var TODAY = todayIso();
  var state = { date: TODAY, view: "journal" };

  // ── 日期渐变滑动条 ──
  function renderDateStrip() {
    return api("/api/journal/days").then(function (r) {
      var created = {}; (r.days || []).forEach(function (d) { created[d.date] = true; });
      // 过去+今天:只列已建的(<=今天);未来:今天+1(可建) + 今天+2(灰边界)
      var list = Object.keys(created).filter(function (d) { return d <= TODAY; }).sort();
      if (list.indexOf(TODAY) === -1) list.push(TODAY);
      var t1 = isoAdd(TODAY, 1), t2 = isoAdd(TODAY, 2);
      list.push(t1); list.push(t2);
      var strip = $("dateRow"); strip.innerHTML = "";
      list.forEach(function (iso) {
        var el = document.createElement("div"); el.className = "day"; el.dataset.iso = iso;
        var kind = "normal";
        if (iso > TODAY) { kind = (iso === t1 && !created[t1]) ? "creatable" : "future"; el.classList.add(iso === t1 ? "creatable" : "future"); }
        if (iso === state.date) el.classList.add("is-current");
        el.dataset.kind = created[iso] ? "open" : kind;
        var label = iso === TODAY ? "今天" : (iso === t1 ? "明天" : md_(iso));
        el.innerHTML = '<span class="d-day">' + label + '</span><span class="d-sub">' + wk(iso) + '</span>';
        el.addEventListener("click", function () { onDayTap(iso, el.dataset.kind); });
        strip.appendChild(el);
      });
      // 居中当前
      var cur = strip.querySelector(".is-current");
      if (cur) cur.scrollIntoView({ inline: "center", block: "nearest" });
    });
  }

  function onDayTap(iso, kind) {
    if (kind === "future") return;               // 今天+2:灰,不可建
    if (kind === "creatable") {                   // 明天:滑/点 → 创建
      api("/api/journal/new-day", { method: "POST", body: JSON.stringify({ date: iso }) })
        .then(function () { state.date = iso; renderDateStrip().then(function () { loadDay(iso); }); });
      return;
    }
    state.date = iso; markCurrent(iso); loadDay(iso);
  }
  function markCurrent(iso) {
    var strip = $("dateRow");
    Array.prototype.forEach.call(strip.children, function (c) { c.classList.toggle("is-current", c.dataset.iso === iso); });
  }
  // 滑动停下时,若停在"明天"格 → 创建(滑动创建新日记)
  var stripScrollT;
  function bindStripCreate() {
    var strip = $("dateRow");
    strip.addEventListener("scroll", function () {
      clearTimeout(stripScrollT);
      stripScrollT = setTimeout(function () {
        var mid = strip.scrollLeft + strip.clientWidth / 2, best = null, bd = 1e9;
        Array.prototype.forEach.call(strip.children, function (c) {
          var cc = c.offsetLeft + c.offsetWidth / 2, dd = Math.abs(cc - mid);
          if (dd < bd) { bd = dd; best = c; }
        });
        if (best && best.dataset.kind === "creatable") onDayTap(best.dataset.iso, "creatable");
      }, 220);
    }, { passive: true });
  }

  // ── 日记页 ──
  function loadDay(iso) {
    api("/api/journal/today?date=" + iso).then(function (j) { renderTimeline(j); });
    api("/api/daily-tasks?date=" + iso).then(function (t) { renderCheckins(t); });
  }
  function renderTimeline(j) {
    var tl = $("timeline"); tl.innerHTML = "";
    var blocks = (j && j.blocks) || [];
    if (!blocks.length) { tl.innerHTML = '<div class="empty-hint">这天还空着。<br>底下「记一笔」写第一条。</div>'; return; }
    blocks.forEach(function (b) {
      b.h2.forEach(function (h) {
        var e = document.createElement("div"); e.className = "entry";
        var tags = (h.tags || []).map(function (t) { return "#" + t; }).join(" ");
        e.innerHTML =
          '<div class="t">' + b.time + '</div>' +
          '<div class="ebody">' +
            (tags ? '<div class="tags">' + tags + '</div>' : '') +
            (h.title ? '<div class="title">' + h.title + '</div>' : '') +
            '<div class="prose">' + md(h.body) + '</div>' +
          '</div>';
        tl.appendChild(e);
      });
    });
  }
  function renderCheckins(t) {
    var box = $("checkins"); box.innerHTML = "";
    (t && t.tasks || []).forEach(function (task) {
      var c = document.createElement("div"); c.className = "checkin" + (task.checked ? " done" : "");
      c.innerHTML = '<div class="dot">' + (task.checked ? "✓" : "") + '</div><div class="nm">' + task.name + '</div>';
      c.addEventListener("click", function () {
        api("/api/daily-tasks/check", { method: "POST", body: JSON.stringify({ task_name: task.name, checked: !task.checked }) })
          .then(function () { loadDay(state.date); });
      });
      box.appendChild(c);
    });
  }

  // ── 对话页 ──
  function loadThread() {
    api("/api/thread/history").then(function (r) {
      var box = $("thread"); box.innerHTML = "";
      (r.history || []).forEach(function (m) { appendMsg(box, m.role === "ai" || m.role === "assistant" ? "ai" : "user", typeof m.content === "string" ? m.content : (m.text || "")); });
    });
  }
  function appendMsg(box, who, text) {
    var m = document.createElement("div"); m.className = "msg " + who;
    m.innerHTML = who === "ai" ? md(text) : text.replace(/</g, "&lt;");
    box.appendChild(m); m.scrollIntoView({ block: "nearest" });
  }

  // ── tab 切换 ──
  function switchView(v) {
    state.view = v;
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) { t.classList.toggle("is-active", t.dataset.view === v); });
    $("journalView").hidden = v !== "journal";
    $("chatView").hidden = v !== "chat";
    $("dateRow").style.display = v === "journal" ? "" : "none";
    $("composerPlaceholder").textContent = v === "journal" ? "记一笔…" : "说点什么…";
    if (v === "chat") loadThread();
  }

  // ── 顶栏下滑收起 / 上滑唤回 ──
  function bindAutohide() {
    var sc = $("content"), last = 0;
    sc.addEventListener("scroll", function () {
      var y = sc.scrollTop;
      if (y > last && y > 40) $("topbar").classList.add("collapsed");
      else if (y < last) $("topbar").classList.remove("collapsed");
      last = y;
    }, { passive: true });
  }

  // ── 底部输入:点击展开 → 写入 ──
  function curBlock() { var d = new Date(); return pad(d.getHours()) + ":" + (d.getMinutes() < 30 ? "00" : "30"); }
  function bindComposer() {
    var pill = $("composerPill"), send = $("sendBtn");
    pill.addEventListener("click", function () {
      if (pill.querySelector("textarea")) return;
      pill.innerHTML = '<textarea rows="1" style="flex:1;border:none;background:transparent;font:inherit;color:inherit;resize:none;outline:none;"></textarea>';
      var ta = pill.querySelector("textarea"); ta.focus(); send.hidden = false;
    });
    send.addEventListener("click", function () {
      var ta = pill.querySelector("textarea"); if (!ta) return;
      var text = ta.value.trim(); if (!text) return;
      if (state.view === "journal") {
        api("/api/journal/insert-block", { method: "POST", body: JSON.stringify({ date: state.date, time: curBlock(), body: text }) })
          .then(function () { resetComposer(); loadDay(state.date); });
      } else {
        var box = $("thread"); appendMsg(box, "user", text); resetComposer();
        sendChat(text, box);
      }
    });
  }
  function resetComposer() { $("composerPill").innerHTML = '<span id="composerPlaceholder">' + (state.view === "journal" ? "记一笔…" : "说点什么…") + '</span>'; $("sendBtn").hidden = true; }
  function sendChat(text, box) {
    fetch("/api/chat", { method: "POST", body: JSON.stringify({ message: text, history: [] }) }).then(function (res) {
      var reader = res.body.getReader(), dec = new TextDecoder(), buf = "", el = null;
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) return;
          buf += dec.decode(r.value, { stream: true });
          var parts = buf.split("\n\n"); buf = parts.pop();
          parts.forEach(function (line) {
            line = line.trim(); if (line.indexOf("data:") !== 0) return;
            try { var ev = JSON.parse(line.slice(5).trim());
              if (ev.type === "delta") { if (!el) { el = document.createElement("div"); el.className = "msg ai"; box.appendChild(el); } el.innerHTML = md((el.dataset.raw = (el.dataset.raw || "") + ev.text)); el.scrollIntoView({ block: "nearest" }); }
            } catch (e) {}
          });
          return pump();
        });
      }
      return pump();
    }).catch(function () {});
  }

  // ── 菜单 ──
  function bindMenu() {
    $("menuBtn").addEventListener("click", function () { $("menuSheet").hidden = false; });
    $("sheetScrim").addEventListener("click", function () { $("menuSheet").hidden = true; });
  }

  // ── init ──
  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) { t.addEventListener("click", function () { switchView(t.dataset.view); }); });
    bindAutohide(); bindComposer(); bindMenu(); bindStripCreate();
    renderDateStrip().then(function () { loadDay(state.date); });
  });
})();
