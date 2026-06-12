/* day-paper-data.js — 纸与灯·单日页 数据层(P2b 接真)。
 * 职责:取真数据 → 按 v3 组件语汇拼 DOM → 绑真实写操作 → 调 paperInit() 起动画。
 * 数据契约:
 *   GET  /api/journal/today?date=    {file, date, blocks:[{time, h2:[{tags,title,body,commits}]}]}
 *   GET  /api/daily-tasks?date=      {tasks:[{name,daily_dose,today_intake,...}], is_today, is_writable}
 *   GET  /api/eval/list?n=30         {items:[{date,is_today,markdown}]} → 21:30 纸条
 *   POST /api/daily-tasks/check      {task_name, intake|increment, date?}
 *   POST /api/journal/insert-block   {time,tag,title,body,date?} → composer 回一句真落 md
 * md 渲染单一入口 window.gatewayMd(),无第二管线。
 */
(function () {
  "use strict";

  var qs = new URLSearchParams(location.search);
  var DATE = (qs.get("date") || "").trim();   // 空 = 今天
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function md(s) {
    try { return window.gatewayMd ? window.gatewayMd(s || "") : esc(s); }
    catch (e) { return esc(s); }
  }

  /* ── 中文日期 ───────────────────────────── */
  var NUM = ["零","一","二","三","四","五","六","七","八","九"];
  function cnNum(n) {  // 1..99
    n = parseInt(n, 10);
    if (isNaN(n)) return "";
    if (n < 10) return NUM[n];
    var t = Math.floor(n / 10), o = n % 10;
    return (t > 1 ? NUM[t] : "") + "十" + (o ? NUM[o] : "");
  }
  function cnDigits(n) { return String(n).replace(/\d/g, function (d) { return "〇一二三四五六七八九"[+d]; }); }
  var WEEK = ["日","一","二","三","四","五","六"];

  function mastheadFor(dateIso, fileRel) {
    var d = new Date(dateIso + "T12:00:00");
    $("mhDate").textContent = cnNum(d.getMonth() + 1) + "月" + cnNum(d.getDate()) + "日";
    var vol = "";
    var m = /第(\d+)天/.exec(fileRel || "");
    if (m) vol = " · 卷" + cnNum(m[1]);
    $("mhSub").textContent = cnDigits(d.getFullYear()) + "年 · 星期" + WEEK[d.getDay()] + vol;
    document.title = cnNum(d.getMonth() + 1) + "月" + cnNum(d.getDate()) + "日 · gateway";
    var col = $("colophonFile");
    if (col && fileRel) col.textContent = "在纸上改的每个字,都会写回 " + fileRel;
  }

  /* ── 条目/夹批/折叠 ─────────────────────── */
  function toMin(t) { var p = t.split(":"); return (+p[0]) * 60 + (+p[1]); }

  function authorOf(title) {
    var m = /\s*@(ai|user)\s*$/.exec(title || "");
    return { title: (title || "").replace(/\s*@(ai|user)\s*$/, ""), author: m ? m[1] : null };
  }

  function parseCommit(line) {
    // "- #commit (claude-x)：text" / "- #commit(claude-x): text" / 全半角括号冒号都兜
    var m = /#commit\s*[（(]([^)）]+)[)）]\s*[:：]?\s*(.*)$/.exec(line || "");
    if (m) return { author: m[1].trim(), text: m[2].trim() };
    return { author: "", text: String(line || "").replace(/^-?\s*#commit\s*/, "").trim() };
  }

  function pieceHtml(h2, withDropcap) {
    var a = authorOf(h2.title);
    var tags = (h2.tags || []).filter(function (t) { return t !== "commit"; });
    var html = '<article class="piece">';
    if (tags.length) {
      html += '<p class="piece-tags">' + tags.map(function (t) { return "<span>#" + esc(t) + "</span>"; }).join("") + "</p>";
    }
    if (a.title) {
      html += '<h3 class="piece-title">' + esc(a.title) +
        (a.author === "ai" ? '<span class="ai-mark" title="@ai 在读"></span>' : "") + "</h3>";
    }
    if (h2.body) {
      var bodyHtml = md(h2.body);
      if (withDropcap) bodyHtml = bodyHtml.replace("<p>", '<p class="dropcap">');
      html += '<div class="piece-body">' + bodyHtml + "</div>";
    }
    (h2.commits || []).forEach(function (c) {
      var pc = parseCommit(c);
      html += '<aside class="annot ink-in"><p class="annot-head"><span class="seal">批</span>' +
        esc(pc.author || "ai") + ' · #commit</p><p>' + esc(pc.text) + "</p></aside>";
    });
    return html + "</article>";
  }

  function gapHtml(fromMin, toMinV) {
    var f = function (m) { return Math.floor(m / 60) + ":" + ("0" + (m % 60)).slice(-2); };
    return '<div class="gap ink-in" aria-hidden="true"><div class="rail"></div>' +
      '<p class="gap-span">' + f(fromMin) + " ⋯⋯ " + f(toMinV) + "</p></div>";
  }

  function renderDay(payload) {
    var main = $("dayMain");
    var blocks = payload.blocks || [];
    if (!blocks.length) {
      main.innerHTML =
        '<div class="blank-day ink-in"><div class="blank-ruler"></div>' +
        '<p class="blank-invite">这一天还空着。</p>' +
        '<p class="blank-whale">想从哪一刻写起都行——纸不催人。</p></div>';
      return;
    }
    var html = "", firstPiece = true, prevEnd = null;
    blocks.forEach(function (b) {
      var t = toMin(b.time);
      if (prevEnd !== null && t - prevEnd > 30) html += gapHtml(prevEnd + 30, t - 30 >= prevEnd + 30 ? t - 30 : t);
      prevEnd = t;
      html += '<section class="block ink-in" data-time="' + esc(b.time) + '">' +
        '<div class="rail"><time datetime="' + esc(b.time) + '">' + esc(b.time.replace(/^0/, "")) + "</time></div>" +
        '<div class="pieces">';
      (b.h2 || []).forEach(function (h) {
        html += pieceHtml(h, firstPiece && !!h.body);
        if (h.body) firstPiece = false;
      });
      html += "</div></section>";
    });
    main.innerHTML = html;
  }

  /* ── 21:30 纸条 + 回一句(返 Promise,启动序列等它) ── */
  function renderSlip(dateIso, isToday) {
    return fetch("/api/eval/list?n=30").then(function (r) { return r.json(); }).then(function (d) {
      var item = (d.items || []).filter(function (it) { return it.date === dateIso && it.markdown; })[0];
      if (!item && !isToday) return;  // 历史日没纸条就不放空壳
      var main = $("dayMain");
      var sec = document.createElement("section");
      sec.className = "block ink-in";
      sec.innerHTML =
        '<div class="rail"><time datetime="21:30">21:30</time></div>' +
        '<div class="pieces"><article class="piece">' +
        (item
          ? '<aside class="slip" aria-label="AI 留言">' + md(item.markdown) +
            '<p class="slip-sign">—— 鲸 留<span class="seal">鲸</span></p></aside>'
          : '<aside class="slip slip-waiting" aria-label="AI 留言">' +
            '<p>今晚 21:30,它会在这里留一张纸条。</p></aside>') +
        (isToday
          ? '<div class="composer-wrap"><div class="composer">' +
            '<div class="composer-input" id="composer" contenteditable="true" data-placeholder="回一句,它明早读得到 ……" role="textbox" aria-label="回复 AI"></div></div>' +
            '<p class="composer-note" id="composerNote">选中这一页的任何一句,可以引到这里说。</p></div>'
          : "") +
        "</article></div>";
      main.appendChild(sec);
      bindComposer(dateIso);
    }).catch(function () {});
  }

  function bindComposer(dateIso) {
    var composer = $("composer"), note = $("composerNote");
    if (!composer) return;
    composer.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || e.shiftKey) return;
      e.preventDefault();
      var text = composer.textContent.trim();
      if (!text) return;
      note.textContent = "落墨中 ……";
      fetch("/api/journal/insert-block", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time: "21:30", tag: "回鲸", body: text }),
      }).then(function (r) { return r.json(); }).then(function (d) {
        if (d && d.ok) {
          note.textContent = "已夹进今天的 md。明早它会读到。";
          composer.textContent = "";
          composer.blur();
        } else {
          note.textContent = (d && d.error) ? "没写进去:" + d.error : "没写进去,稍后再试。";
        }
      }).catch(function () { note.textContent = "没写进去,网络似乎不通。"; });
    });
  }

  /* ── 晨课:补剂 + 八杯水(真打卡) ─────────── */
  function renderMorning(dateIso) {
    return fetch("/api/daily-tasks" + (DATE ? "?date=" + DATE : "")).then(function (r) { return r.json(); }).then(function (d) {
      var tasks = d.tasks || [];
      if (!tasks.length) return;
      var writable = !!d.is_writable;
      var morning = $("morning");
      var cupsTask = null, meds = [];
      tasks.forEach(function (t) {
        if (!cupsTask && /水/.test(t.name) && (t.daily_dose || 1) >= 4) cupsTask = t;
        else meds.push(t);
      });
      var html = "";
      if (meds.length) {
        html += '<div class="widget" data-widget="补剂"><h2 class="widget-label">补剂打卡</h2><ul class="widget-body meds">' +
          meds.map(function (t) {
            var dose = t.daily_dose || 1, got = Math.min(t.today_intake || 0, dose);
            var marks = "";
            for (var i = 0; i < dose; i++) marks += '<span class="mark' + (i < got ? " done" : "") + '"></span>';
            return '<li><button class="med' + (got >= dose ? " alldone" : "") + '" type="button" data-task="' + esc(t.name) + '" data-dose="' + dose + '"' +
              (writable ? "" : " disabled") + '><span class="marks">' + marks + "</span>" + esc(t.name) + "</button></li>";
          }).join("") + "</ul></div>";
      }
      if (cupsTask) {
        var dose = cupsTask.daily_dose || 8, got = Math.min(cupsTask.today_intake || 0, dose);
        var cups = "";
        for (var i = 0; i < dose; i++) {
          cups += '<button class="cup' + (i < got ? " full" : "") + '" type="button" data-i="' + (i + 1) + '" aria-label="第 ' + (i + 1) + ' 杯"' + (writable ? "" : " disabled") + "></button>";
        }
        html += '<div class="widget" data-widget="' + esc(cupsTask.name) + '"><h2 class="widget-label">' + esc(cupsTask.name === "喝水" ? "八杯水" : cupsTask.name) + '</h2>' +
          '<div class="widget-body"><div class="cups" id="cups" data-task="' + esc(cupsTask.name) + '">' + cups + "</div>" +
          '<p class="cups-tally" id="cupsTally">' + got + " / " + dose + "</p></div></div>";
      }
      html += '<p class="morning-hint" style="grid-column: 1 / -1;">想多记一件事?跟它说一句,它会替你在这里裁一个栏目。</p>';
      morning.innerHTML = html;
      morning.hidden = false;
      if (writable) bindMorning(dateIso);
    }).catch(function () {});
  }

  function postIntake(name, intake) {
    var body = { task_name: name, intake: intake };
    if (DATE) body.date = DATE;
    return fetch("/api/daily-tasks/check", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function bindMorning() {
    var cupsWrap = $("cups"), tally = $("cupsTally");
    if (cupsWrap) {
      cupsWrap.addEventListener("click", function (e) {
        var cup = e.target.closest(".cup");
        if (!cup) return;
        var k = +cup.dataset.i;
        var cur = cupsWrap.querySelectorAll(".cup.full").length;
        var next = (k === cur) ? k - 1 : k;   // 点最后一满杯=收回一杯,否则注到这杯
        var all = cupsWrap.querySelectorAll(".cup");
        all.forEach(function (c, i) { c.classList.toggle("full", i < next); });
        if (tally) tally.textContent = next + " / " + all.length;
        postIntake(cupsWrap.dataset.task, next).catch(function () {});
      });
    }
    Array.prototype.forEach.call(document.querySelectorAll(".med[data-task]"), function (medBtn) {
      medBtn.addEventListener("click", function () {
        var dose = +medBtn.dataset.dose || 1;
        var marks = medBtn.querySelectorAll(".mark");
        var got = medBtn.querySelectorAll(".mark.done").length;
        var next = got >= dose ? 0 : got + 1;   // 满了再点=清零重计
        marks.forEach ? marks.forEach(function (m, i) { m.classList.toggle("done", i < next); })
          : Array.prototype.forEach.call(marks, function (m, i) { m.classList.toggle("done", i < next); });
        medBtn.classList.toggle("alldone", next >= dose);
        postIntake(medBtn.dataset.task, next).catch(function () {});
      });
    });
  }

  /* ── 启动:三路数据齐 → DOM 定型 → 才起动画/行为(paperInit) ── */
  fetch("/api/journal/today" + (DATE ? "?date=" + DATE : ""))
    .then(function (r) { return r.json(); })
    .then(function (payload) {
      var jobs = [];
      if (payload.error) {
        mastheadFor(DATE || new Date().toISOString().slice(0, 10), "");
        renderDay({ blocks: [] });
      } else {
        mastheadFor(payload.date, payload.file);
        renderDay(payload);
        jobs.push(renderSlip(payload.date, !DATE || payload.date === new Date().toISOString().slice(0, 10)));
      }
      jobs.push(renderMorning());
      return Promise.all(jobs);
    })
    .catch(function () {
      $("mhDate").textContent = "纸还没铺开";
      $("mhSub").textContent = "数据没接上,稍后再来";
    })
    .then(function () { window.paperInit && window.paperInit(); });
})();
