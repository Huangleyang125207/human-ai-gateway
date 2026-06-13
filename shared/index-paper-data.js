/* index-paper-data.js — 纸与灯·总览页 数据层(P3 接真,只读面)。
 * 渲染:报头日期 / 今天的入口(摘自真日记) / 晨课 widget(真打卡) / 脉搏(项目 PULSE)
 *       / 往日天列表。两态:有内容(filled) / 空白首屏(first)。
 * 对话 chatfold:点击暂回落标准版(working thread 在那),等信笺 paper 化再替换。
 * md 渲染走 window.gatewayMd();打卡复用 day 的真写端点。
 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function md(s) { try { return window.gatewayMd ? window.gatewayMd(s || "") : esc(s); } catch (e) { return esc(s); } }
  function txt(s) { var d = document.createElement("div"); d.innerHTML = md(s); return (d.textContent || "").trim(); }

  /* 两态显隐:有内容 → 显 filled 藏 first;空 → 反之 */
  function setState(filled) {
    document.querySelectorAll('[data-only="filled"]').forEach(function (el) { el.hidden = !filled; });
    document.querySelectorAll('[data-only="first"]').forEach(function (el) { el.hidden = filled; });
  }

  /* 中文日期 */
  function cnNum(n) { var N = "零一二三四五六七八九"; n = +n; if (n < 10) return N[n]; var t = (n / 10) | 0, o = n % 10; return (t > 1 ? N[t] : "") + "十" + (o ? N[o] : ""); }
  function cnDigits(n) { return String(n).replace(/\d/g, function (d) { return "〇一二三四五六七八九"[+d]; }); }
  var WEEK = ["日", "一", "二", "三", "四", "五", "六"];
  function cnDate(iso) { var d = new Date(iso + "T12:00:00"); return cnNum(d.getMonth() + 1) + "月" + cnNum(d.getDate()) + "日"; }

  function authorClean(title) { return (title || "").replace(/\s*@(ai|user)\s*$/, ""); }

  /* ── 今天的入口:摘真日记 ── */
  function renderToday(payload) {
    var a = $("__today_anchor") || document.querySelector("a.today");
    if (!a) return false;
    var blocks = (payload && payload.blocks) || [];
    if (!blocks.length) return false;
    // lede = 第一条有标题的;excerpt = 第一条有正文的
    var lede = "", excerpt = "", firstTime = blocks[0].time, pieceCount = 0, annotCount = 0, hasSlip = false;
    blocks.forEach(function (b) {
      (b.h2 || []).forEach(function (h) {
        pieceCount++;
        annotCount += (h.commits || []).length;
        if (!lede && authorClean(h.title)) lede = authorClean(h.title);
        if (!excerpt && h.body) excerpt = txt(h.body);
      });
    });
    var le = a.querySelector(".today-lede"); if (le) le.textContent = lede || "今天，从这里写起";
    var ex = a.querySelector(".today-excerpt"); if (ex) ex.textContent = excerpt ? excerpt.slice(0, 96) + (excerpt.length > 96 ? "…" : "") : "";
    var meta = a.querySelector(".today-meta span:first-child");
    if (meta) meta.textContent = firstTime.replace(/^0/, "") + " 起笔 · " + pieceCount + " 条" + (annotCount ? " · " + annotCount + " 夹批" : "");
    a.setAttribute("href", "./day-paper.html");
    return true;
  }

  /* ── 晨课 widget(真打卡,复用 day 的端点) ── */
  function renderMorning() {
    return fetch("/api/daily-tasks").then(function (r) { return r.json(); }).then(function (d) {
      var tasks = d.tasks || [], writable = !!d.is_writable;
      var flow = document.querySelector(".widget-flow");
      if (!flow || !tasks.length) return;
      var cupsTask = null, meds = [];
      tasks.forEach(function (t) { if (!cupsTask && /水/.test(t.name) && (t.daily_dose || 1) >= 4) cupsTask = t; else meds.push(t); });
      var html = "";
      if (meds.length) {
        html += '<div class="widget" data-widget="补剂"><div class="widget-side"><h3 class="widget-label">补剂打卡</h3></div><ul class="widget-body meds">' +
          meds.map(function (t) {
            var dose = t.daily_dose || 1, got = Math.min(t.today_intake || 0, dose), m = "";
            for (var i = 0; i < dose; i++) m += '<span class="mark' + (i < got ? " done" : "") + '"></span>';
            return '<li class="med-row"><button class="med' + (got >= dose ? " alldone" : "") + '" type="button" data-task="' + esc(t.name) + '" data-dose="' + dose + '"' + (writable ? "" : " disabled") + '><span class="marks">' + m + "</span>" + esc(t.name) + "</button></li>";
          }).join("") + "</ul></div>";
      }
      if (cupsTask) {
        var dose = cupsTask.daily_dose || 8, got = Math.min(cupsTask.today_intake || 0, dose), cups = "";
        for (var i = 0; i < dose; i++) cups += '<button class="cup' + (i < got ? " full" : "") + '" type="button" data-i="' + (i + 1) + '"' + (writable ? "" : " disabled") + "></button>";
        html += '<div class="widget" data-widget="水"><div class="widget-side"><h3 class="widget-label">八杯水</h3></div><div class="widget-body"><div class="cups" id="cups" data-task="' + esc(cupsTask.name) + '">' + cups + '</div><p class="cups-tally"><span id="cupsTally">' + got + " / " + dose + "</span></p></div></div>";
      }
      flow.innerHTML = html;
      if (writable) bindMorning();
    }).catch(function () {});
  }
  function postIntake(name, intake) {
    return fetch("/api/daily-tasks/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_name: name, intake: intake }) });
  }
  function bindMorning() {
    var cupsWrap = $("cups"), tally = $("cupsTally");
    if (cupsWrap) cupsWrap.addEventListener("click", function (e) {
      var cup = e.target.closest(".cup"); if (!cup) return;
      var k = +cup.dataset.i, cur = cupsWrap.querySelectorAll(".cup.full").length, next = (k === cur) ? k - 1 : k;
      cupsWrap.querySelectorAll(".cup").forEach(function (c, i) { c.classList.toggle("full", i < next); });
      if (tally) tally.textContent = next + " / " + cupsWrap.querySelectorAll(".cup").length;
      postIntake(cupsWrap.dataset.task, next).catch(function () {});
    });
    document.querySelectorAll(".med[data-task]").forEach(function (b) {
      b.addEventListener("click", function () {
        var dose = +b.dataset.dose || 1, marks = b.querySelectorAll(".mark"), got = b.querySelectorAll(".mark.done").length, next = got >= dose ? 0 : got + 1;
        marks.forEach(function (m, i) { m.classList.toggle("done", i < next); });
        b.classList.toggle("alldone", next >= dose);
        postIntake(b.dataset.task, next).catch(function () {});
      });
    });
  }

  /* ── 脉搏:项目 PULSE ── */
  function renderPulse() {
    return fetch("/api/pulse").then(function (r) { return r.json(); }).then(function (d) {
      var projs = (d && d.projects) || [];
      var ul = document.querySelector("ul.pulse");
      if (!ul || !projs.length) { var s = ul && ul.closest("section"); if (s) s.hidden = true; return; }
      ul.innerHTML = projs.slice(0, 6).map(function (p) {
        var word = (p.tagline || p.now_line || "").replace(/^[🟡🔴🟢⚪🔵]\s*/, "").slice(0, 40);
        var live = /🟡|🔴/.test(p.status_emoji || "") ? " data-live" : "";
        return '<li class="pulse-row"' + live + '><span class="pulse-name">' + esc(p.name || "") + '</span>' +
          '<span class="pulse-word">' + esc(word) + '</span><span class="pulse-spark">▂▃▃▅▆▇</span>' +
          '<span class="pulse-when">' + esc(p.last_refreshed || "") + "</span></li>";
      }).join("");
    }).catch(function () { var ul = document.querySelector("ul.pulse"); var s = ul && ul.closest("section"); if (s) s.hidden = true; });
  }

  /* ── 往日:天列表(date + 有没有纸条) ── */
  function renderDays() {
    return Promise.all([
      fetch("/api/journal/days").then(function (r) { return r.json(); }).catch(function () { return { days: [] }; }),
      fetch("/api/eval/list?n=30").then(function (r) { return r.json(); }).catch(function () { return { items: [] }; }),
    ]).then(function (res) {
      var days = (res[0].days || []).slice().reverse();       // 最近在前
      var slipDates = {};
      (res[1].items || []).forEach(function (it) { if (it.markdown) slipDates[it.date] = true; });
      var today = new Date().toISOString().slice(0, 10);
      var recent = days.filter(function (d) { return d.date !== today; }).slice(0, 6);
      var ol = document.querySelector("ol.days-list");
      if (!ol) return;
      if (!recent.length) { var s = ol.closest("section"); if (s) s.hidden = true; return; }
      ol.innerHTML = recent.map(function (d) {
        var whale = slipDates[d.date] ? ' <i class="whale-dot" title="鲸留过纸条"></i>' : "";
        return '<li><a class="day-row" href="./day-paper.html?date=' + d.date + '">' +
          "<time>" + cnDate(d.date) + "</time>" +
          '<span class="day-gist"></span>' +
          '<span class="day-counts">翻这一天' + whale + "</span></a></li>";
      }).join("");
      var more = document.querySelector(".days-more a");
      if (more) more.setAttribute("href", "./day-paper.html?date=" + recent[recent.length - 1].date);
    });
  }

  /* ── mode-toggle 昼·夜:点定调,再点当前的回跟随系统(共用 gateway-theme) ── */
  function wireModeToggle() {
    var tg = $("modeToggle");
    if (!tg || !window.gatewayTheme) return;
    function paint() { tg.dataset.mode = window.gatewayTheme.get(); }
    tg.addEventListener("click", function (e) {
      var hitDay = e.target.closest(".mt-day"), hitNight = e.target.closest(".mt-night");
      var cur = window.gatewayTheme.get();
      var want = hitDay ? "day" : hitNight ? "night" : null;
      if (!want) return;
      window.gatewayTheme.set(cur === want ? "system" : want);  // 再点当前的 → 回系统
      paint();
    });
    window.addEventListener("gateway-theme-change", paint);
    paint();
  }

  /* ── 对话:thread.js 自绑(折页/面板/流式/留言板),这里不接管。留空占位 ── */
  function wireChatFold() { /* thread.js 接管 #thread / #threadTab,无需在此 wire */ }

  /* ── 启动 ── */
  fetch("/api/journal/today").then(function (r) { return r.json(); }).then(function (payload) {
    var d = new Date();
    var iso = (payload && payload.date) || d.toISOString().slice(0, 10);
    var dd = new Date(iso + "T12:00:00");
    var sub = $("mhSub");
    if (sub) sub.textContent = cnDigits(dd.getFullYear()) + "年" + cnNum(dd.getMonth() + 1) + "月" + cnNum(dd.getDate()) + "日 · 星期" + WEEK[dd.getDay()];
    var filled = renderToday(payload);
    setState(filled);
    return Promise.all([renderMorning(), renderPulse(), renderDays()]);
  }).catch(function () { setState(false); })
    .then(function () { wireModeToggle(); wireChatFold(); window.paperInit && window.paperInit(); });
})();
