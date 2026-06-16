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

  // 可变数据模型:渲染后留着,写操作改它再 reconstruct→patch(防多 piece 块互相覆盖)。
  var STATE = { date: "", file: "", blocks: [], writable: true };

  /* ── 轻提示(whisper):AI 说带朱点,系统说不带 ── */
  var whisperT = null;
  function whisper(text, ai) {
    var w = $("whisper"), t = $("whisperText");
    if (!w || !t) return;
    t.textContent = text;
    var dot = w.querySelector(".whale-dot");   // AI 说带朱点,系统说不带
    if (dot) dot.style.display = ai ? "" : "none";
    w.classList.add("show");
    if (whisperT) clearTimeout(whisperT);
    whisperT = setTimeout(function () { w.classList.remove("show"); }, 2600);
  }

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

  function pieceHtml(h2, bi, pi, withDropcap) {
    var a = authorOf(h2.title);
    var tags = (h2.tags || []).filter(function (t) { return t !== "commit"; });
    var editable = STATE.writable;
    var html = '<article class="piece" data-bi="' + bi + '" data-pi="' + pi + '">';
    // 拖图贴纸暂缓:走 AI 中介(对话流接好后,文档级拖图→thread→place_scrapbook_image),不在此另造直连。
    // tags:每个 chip 可改(空=删),末尾「＋」加 tag
    if (tags.length || editable) {
      html += '<p class="piece-tags">' +
        tags.map(function (t, ti) {
          return '<span class="tag-chip' + (editable ? " editable" : "") + '"' +
            (editable ? ' data-field="tag" data-ti="' + ti + '" data-placeholder="tag"' : "") + ">#" + esc(t) + "</span>";
        }).join("") +
        (editable ? '<button class="tag-add" type="button" title="加 tag" style="background:none;border:none;cursor:pointer;color:var(--cinnabar-soft);font:inherit;">＋</button>' : "") + "</p>";
    }
    if (a.title || editable) {
      html += '<h3 class="piece-title"><span class="title-text' + (editable ? " editable" : "") + '"' +
        (editable ? ' data-field="title" data-placeholder="标题…"' : "") + ">" + esc(a.title) + "</span>" +
        (a.author === "ai" ? '<span class="ai-mark" title="@ai 在读"></span>' : "") + "</h3>";
    }
    var bodyHtml = h2.body ? md(h2.body) : "";
    if (withDropcap && bodyHtml) bodyHtml = bodyHtml.replace("<p>", '<p class="dropcap">');
    html += '<div class="piece-body' + (editable ? " editable" : "") + '"' +
      (editable ? ' data-field="body" data-placeholder="点一下,在纸上改 ……"' : "") + ">" + bodyHtml + "</div>";
    (h2.commits || []).forEach(function (c, ci) {
      var pc = parseCommit(c);
      html += '<aside class="annot ink-in"><p class="annot-head"><span class="seal">批</span>' +
        esc(pc.author || "ai") + ' · #commit</p><p class="annot-body' + (editable ? " editable" : "") + '"' +
        (editable ? ' data-field="commit" data-ci="' + ci + '" data-author="' + esc(pc.author || "ai") + '" data-placeholder="空=删去这条批"' : "") +
        ">" + esc(pc.text) + "</p></aside>";
    });
    if (editable) {
      html += '<button class="strike-aff" type="button" title="划掉这一段">划</button>' +
        '<p class="strike-actions"><button class="strike-undo" type="button">还原</button>' +
        '<button class="strike-go" type="button">收起 · 删去</button></p>';
    }
    return html + '<p class="piece-note" aria-hidden="true"></p></article>';
  }

  function gapHtml(fromMin, toMinV) {
    var f = function (m) { return Math.floor(m / 60) + ":" + ("0" + (m % 60)).slice(-2); };
    var add = STATE.writable
      ? '<button class="gap-add" type="button" data-time="' + f(fromMin) + '">＋ 落一笔</button>' : "";
    return '<div class="gap ink-in"><div class="rail"></div>' +
      '<p class="gap-span">' + f(fromMin) + " ⋯⋯ " + f(toMinV) + add + "</p></div>";
  }

  function renderDay(payload) {
    var main = $("dayMain");
    var blocks = payload.blocks || [];
    STATE.blocks = blocks;            // 留作写操作的真源模型
    if (!blocks.length) {
      main.innerHTML =
        '<div class="blank-day ink-in"><div class="blank-ruler"></div>' +
        '<p class="blank-invite">这一天还空着。</p>' +
        (STATE.writable ? '<button class="blank-start" type="button" id="blankAdd">＋ 落第一笔</button>' : "") +
        '<p class="blank-whale">想从哪一刻写起都行——纸不催人。</p></div>';
      var ba = $("blankAdd");
      if (ba) ba.onclick = function () { openAddEntry(); };
      return;
    }
    var html = "", firstPiece = true, prevEnd = null;
    blocks.forEach(function (b, bi) {
      var t = toMin(b.time);
      if (prevEnd !== null && t - prevEnd > 30) html += gapHtml(prevEnd + 30, t - 30 >= prevEnd + 30 ? t - 30 : t);
      prevEnd = t;
      html += '<section class="block ink-in" data-time="' + esc(b.time) + '" data-bi="' + bi + '">' +
        '<div class="rail"><time datetime="' + esc(b.time) + '">' + esc(b.time.replace(/^0/, "")) + "</time></div>" +
        '<div class="pieces">';
      (b.h2 || []).forEach(function (h, pi) {
        html += pieceHtml(h, bi, pi, firstPiece && !!h.body);
        if (h.body) firstPiece = false;
      });
      html += "</div></section>";
    });
    main.innerHTML = html;
    if (STATE.writable) wireWrites();
  }

  /* ── 写操作:行内编辑 + 划掉收纸删除(事件委托) ── */
  function reconstructBlockMd(b) {
    var lines = [];
    (b.h2 || []).forEach(function (h) {
      var tagStr = (h.tags || []).map(function (t) { return "#" + t; }).join(" ");
      lines.push(("## " + (tagStr ? tagStr + " " : "") + (h.title || "")).trim());
      lines.push("");
      if (h.body) lines.push(h.body);
      if (h.commits && h.commits.length) {
        lines.push("");
        h.commits.forEach(function (c) { lines.push(c); });
      }
      lines.push("");
    });
    return lines.join("\n").replace(/\s+$/, "");
  }

  function saveBlock(bi) {
    var b = STATE.blocks[bi];
    if (!b) return Promise.resolve();
    var payload = { time: b.time, new_md: reconstructBlockMd(b) };
    if (STATE.date) payload.date = STATE.date;
    return fetch("/api/journal/patch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.error) { whisper("没存上 — " + d.error); return false; }
      whisper("已写回 " + b.time + " 的纸");
      return true;
    }).catch(function (e) { whisper("没存上 — " + e.message); return false; });
  }

  function hOf(art) {
    var b = STATE.blocks[+art.dataset.bi];
    return b && b.h2 ? b.h2[+art.dataset.pi] : null;
  }

  function flashSaved(art) {
    art.classList.add("saved");
    setTimeout(function () { art.classList.remove("saved"); }, 2300);
  }

  // 结构变了(tag/commit 增删)→ 按 STATE 重渲染这一条 piece。事件走委托,无需重绑。
  function rerenderPiece(art) {
    var bi = +art.dataset.bi, pi = +art.dataset.pi;
    var b = STATE.blocks[bi];
    if (!b || !b.h2[pi]) return art;
    var tmp = document.createElement("div");
    tmp.innerHTML = pieceHtml(b.h2[pi], bi, pi, art.querySelector(".dropcap") ? true : false);
    var fresh = tmp.firstChild;
    art.parentNode.replaceChild(fresh, art);
    return fresh;
  }

  function deleteBlockAt(bi, sec) {
    var b = STATE.blocks[bi];
    if (!b) return;
    var payload = { time: b.time };
    if (STATE.date) payload.date = STATE.date;
    fetch("/api/journal/delete-block", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && (d.error || d.detail)) { whisper("删除失败 — " + (d.error || d.detail)); sec.style.display = ""; return; }
      sec.parentNode && sec.parentNode.removeChild(sec);
      whisper("收起了 " + b.time + " 的纸");
    }).catch(function (e) { whisper("删除失败 — " + e.message); sec.style.display = ""; });
  }

  /* ── 落一笔:加新条目(tag + 标题 + 时间,tag-stats 建议)。参照 classic showTagInsertModal ── */
  function openAddEntry(defaultTime) {
    if (document.querySelector(".slipnote.show")) return;
    var now = new Date();
    var p = (defaultTime || "").split(":");
    var hh = p[0] || String(now.getHours());
    var mm = p[1] || (now.getMinutes() < 30 ? "00" : "30");
    var inS = "font-family:var(--font-song);font-size:14px;color:var(--ink);background:transparent;" +
              "border:none;border-bottom:1px solid var(--hairline-strong);padding:0.3em 0.2em;";
    var scrim = document.createElement("div");
    scrim.className = "slipnote-scrim";
    var note = document.createElement("aside");
    note.className = "slipnote";
    note.setAttribute("role", "dialog");
    note.innerHTML =
      '<p style="font-weight:600;letter-spacing:.08em;margin-bottom:1rem;">落一笔 · 加一条</p>' +
      '<div id="addChips" style="display:flex;flex-wrap:wrap;gap:0.45em;margin-bottom:0.8rem;font-size:13px;color:var(--ink-faint);"></div>' +
      '<div style="margin-bottom:0.7rem;"><input id="addTag" placeholder="tag(不带 #),如 探索 / 工作" style="' + inS + 'width:100%;"></div>' +
      '<div style="margin-bottom:0.7rem;"><input id="addTitle" placeholder="标题(可空,之后点正文写)" style="' + inS + 'width:100%;"></div>' +
      '<div style="margin-bottom:0.4rem;">时间 <input id="addHH" value="' + hh + '" maxlength="2" inputmode="numeric" style="' + inS + 'width:2em;text-align:center;">：' +
      '<input id="addMM" value="' + mm + '" maxlength="2" inputmode="numeric" style="' + inS + 'width:2em;text-align:center;"></div>' +
      '<p id="addMsg" style="min-height:1.1em;font-size:12.5px;color:var(--cinnabar-soft);"></p>' +
      '<p class="slipnote-acts"><button class="sn-quiet" id="addCancel" type="button">算了</button>' +
      '<button class="sn-main" id="addOk" type="button">落下</button></p>';
    document.body.appendChild(scrim);
    document.body.appendChild(note);
    requestAnimationFrame(function () { scrim.classList.add("show"); note.classList.add("show"); });
    var tagEl = note.querySelector("#addTag");
    setTimeout(function () { tagEl.focus(); }, 200);
    fetch("/api/journal/tag-stats?limit=5").then(function (r) { return r.json(); }).then(function (d) {
      var chips = note.querySelector("#addChips");
      (d.tags || []).forEach(function (t) {
        var c = document.createElement("button");
        c.type = "button"; c.textContent = "#" + (t.tag || t);
        c.style.cssText = "background:var(--cinnabar-wash);border:1px solid var(--hairline);border-radius:3px;cursor:pointer;color:var(--ink-soft);padding:.1em .5em;font:inherit;";
        c.onclick = function () { tagEl.value = (t.tag || t); tagEl.focus(); };
        chips.appendChild(c);
      });
    }).catch(function () {});
    function close() {
      scrim.classList.remove("show"); note.classList.remove("show");
      setTimeout(function () { scrim.remove(); note.remove(); }, 600);
    }
    note.querySelector("#addCancel").onclick = close;
    scrim.onclick = close;
    note.querySelector("#addOk").onclick = function () {
      var tag = tagEl.value.trim().replace(/^#/, "");
      var msg = note.querySelector("#addMsg");
      if (!tag) { msg.textContent = "给个 tag 吧"; tagEl.focus(); return; }
      var h = (note.querySelector("#addHH").value.trim() || "0");
      var m = (note.querySelector("#addMM").value.trim() || "0");
      var time = parseInt(h, 10) + ":" + ("0" + (parseInt(m, 10) || 0)).slice(-2);
      var payload = { time: time, tag: tag, title: note.querySelector("#addTitle").value.trim() };
      if (STATE.date) payload.date = STATE.date;
      msg.textContent = "落墨中 ……";
      fetch("/api/journal/insert-block", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (r) { return r.json(); }).then(function (d) {
        if (d && d.ok) { close(); whisper("落了一笔 · " + time); location.reload(); }
        else msg.textContent = (d && d.error) ? d.error : "没落上,换个时间试试";
      }).catch(function (e) { msg.textContent = "没落上 — " + e.message; });
    };
  }

  function wireWrites() {
    var main = $("dayMain");

    // 落一笔:gap 上「＋ 落一笔」→ 开加条目模态(默认填那段空白的起始时间)
    main.addEventListener("click", function (e) {
      var add = e.target.closest(".gap-add");
      if (add) { e.preventDefault(); openAddEntry(add.dataset.time); }
    });

    // 行内编辑:title / body / tag / commit 都走 .editable + data-field
    function rawFor(ed, h) {
      var f = ed.dataset.field;
      if (f === "title") return authorOf(h.title).title;
      if (f === "tag") return (h.tags || [])[+ed.dataset.ti] || "";
      if (f === "commit") return parseCommit((h.commits || [])[+ed.dataset.ci] || "").text;
      return h.body || "";
    }
    main.addEventListener("click", function (e) {
      if (e.target.closest(".tag-add")) {       // 加 tag:push 空 tag → 重渲染 → 聚焦新 chip
        var art0 = e.target.closest(".piece"), h0 = hOf(art0);
        if (!h0) return;
        h0.tags = h0.tags || []; h0.tags.push("");
        var fresh = rerenderPiece(art0);
        var chip = fresh && fresh.querySelector('.tag-chip[data-ti="' + (h0.tags.length - 1) + '"]');
        if (chip) chip.click();
        return;
      }
      var ed = e.target.closest(".editable");
      if (!ed || ed.isContentEditable) return;
      var art = ed.closest(".piece");
      if (art.classList.contains("struck")) return;
      var h = hOf(art);
      if (!h) return;
      ed.dataset.raw = rawFor(ed, h);
      ed.textContent = ed.dataset.raw;
      ed.contentEditable = "true";
      art.classList.add("editing");
      ed.focus();
    });
    main.addEventListener("blur", function (e) {
      var ed = e.target.closest && e.target.closest(".editable");
      if (!ed || !ed.isContentEditable) return;
      var art = ed.closest(".piece"), h = hOf(art);
      ed.contentEditable = "false";
      art.classList.remove("editing");
      var next = ed.textContent.replace(/ /g, " ").trim();
      if (!h) return;
      var field = ed.dataset.field || "body", bi = +art.dataset.bi;
      var changed = next !== (ed.dataset.raw || "");
      if (field === "body") {
        if (changed) { h.body = next; ed.innerHTML = next ? md(next) : ""; flashSaved(art); saveBlock(bi); }
        else ed.innerHTML = h.body ? md(h.body) : "";
      } else if (field === "title") {
        if (changed) { var au = authorOf(h.title).author; h.title = next + (au ? " @" + au : ""); ed.textContent = next; flashSaved(art); saveBlock(bi); }
      } else if (field === "tag") {
        var ti = +ed.dataset.ti, cleaned = next.replace(/^#+/, "").replace(/\s+/g, "");
        if (!cleaned) h.tags.splice(ti, 1); else h.tags[ti] = cleaned;
        rerenderPiece(art); saveBlock(bi);
      } else if (field === "commit") {
        var ci = +ed.dataset.ci;
        if (!next) h.commits.splice(ci, 1); else h.commits[ci] = "- #commit（" + (ed.dataset.author || "ai") + "）：" + next;
        rerenderPiece(art); saveBlock(bi);
      }
    }, true);

    // 划掉 · 收纸:strike-aff → struck;还原 / 收起删去
    main.addEventListener("click", function (e) {
      var art = e.target.closest(".piece");
      if (!art) return;
      if (e.target.closest(".strike-aff")) { art.classList.add("struck"); return; }
      if (e.target.closest(".strike-undo")) { art.classList.remove("struck"); return; }
      if (e.target.closest(".strike-go")) {
        var sec = art.closest(".block");
        art.classList.add("folding");
        setTimeout(function () { deleteBlockAt(+sec.dataset.bi, sec); }, 700);
      }
    });
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
            return '<li class="med-row"><button class="med' + (got >= dose ? " alldone" : "") + '" type="button" data-task="' + esc(t.name) + '" data-dose="' + dose + '"' +
              (writable ? "" : " disabled") + '><span class="marks">' + marks + "</span>" + esc(t.name) + "</button>" +
              (writable ? '<button class="med-x" type="button" data-task="' + esc(t.name) + '" title="划掉这项追踪">划</button>' : "") + "</li>";
          }).join("") +
          (writable ? '<li class="med-add"><div class="med-add-line" contenteditable="true" data-placeholder="添一项 · 回车" role="textbox" aria-label="添一项追踪"></div></li>' : "") +
          "</ul></div>";
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
      html += '<p class="morning-hint" style="grid-column: 1 / -1;">想多记一件事?跟它说一句,它会替你在这里裁一个栏目。' +
        (writable ? ' <button id="morningManage" type="button" style="background:none;border:none;cursor:pointer;font:inherit;letter-spacing:.1em;color:var(--cinnabar-soft);">· 管理</button>' : "") + '</p>';
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
      medBtn.addEventListener("click", function (e) {
        var w = medBtn.closest(".widget");
        var marks = medBtn.querySelectorAll(".mark");
        // 管理态:点第 N 个 mark → 设每天 N 粒(meta)。增到现有粒数之上找 AI("改成每天3粒")。
        if (w && w.classList.contains("managing")) {
          var mk = e.target.closest(".mark");
          if (!mk) return;
          var n = Array.prototype.indexOf.call(marks, mk) + 1;
          if (n < 1) return;
          whisper("改成每天 " + n + " ……");
          fetch("/api/daily-tasks/meta", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task_name: medBtn.dataset.task, daily_dose: n }),
          }).then(function (r) { return r.json(); }).then(function (d) {
            if (d && !d.error && !d.detail) { whisper("每天 " + n + " 了 · " + medBtn.dataset.task); location.reload(); }
            else whisper("没改上 — " + (d.error || d.detail || ""));
          }).catch(function (err) { whisper("没改上 — " + err.message); });
          return;
        }
        var dose = +medBtn.dataset.dose || 1;
        var got = medBtn.querySelectorAll(".mark.done").length;
        var next = got >= dose ? 0 : got + 1;   // 满了再点=清零重计
        marks.forEach ? marks.forEach(function (m, i) { m.classList.toggle("done", i < next); })
          : Array.prototype.forEach.call(marks, function (m, i) { m.classList.toggle("done", i < next); });
        medBtn.classList.toggle("alldone", next >= dose);
        postIntake(medBtn.dataset.task, next).catch(function () {});
      });
    });

    // ── 晨课管理态:管理 toggle / 划掉任务 / 添一项(参照 classic ritual 管理) ──
    var mgBtn = $("morningManage");
    if (mgBtn) {
      mgBtn.addEventListener("click", function () {
        var on = !document.querySelector("#morning .widget.managing");
        document.querySelectorAll("#morning .widget").forEach(function (w) { w.classList.toggle("managing", on); });
        mgBtn.textContent = on ? "· 完成" : "· 管理";
      });
    }
    document.querySelectorAll(".med-x[data-task]").forEach(function (x) {
      x.addEventListener("click", function () {
        var name = x.dataset.task, row = x.closest(".med-row");
        row.classList.add("struck");
        fetch("/api/daily-tasks/delete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_name: name }),
        }).then(function (r) { return r.json(); }).then(function (d) {
          if (d && !d.error && !d.detail) { whisper("划掉了 · " + name); setTimeout(function () { location.reload(); }, 550); }
          else { row.classList.remove("struck"); whisper("没删掉 — " + (d.error || d.detail || "")); }
        }).catch(function (e) { row.classList.remove("struck"); whisper("没删掉 — " + e.message); });
      });
    });
    var addLine = document.querySelector(".med-add-line");
    if (addLine) {
      addLine.addEventListener("keydown", function (e) {
        if (e.key !== "Enter") return;
        e.preventDefault();
        var text = addLine.textContent.trim();
        if (!text) return;
        addLine.textContent = "添中 ……";
        fetch("/api/template/task", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "add", text: text }),
        }).then(function (r) { return r.json(); }).then(function (d) {
          if (d && !d.error && !d.detail) { whisper("添了一项 · " + text); location.reload(); }
          else { addLine.textContent = text; whisper("没添上 — " + (d.error || d.detail || "")); }
        }).catch(function (e) { addLine.textContent = text; whisper("没添上 — " + e.message); });
      });
    }
  }

  /* ── 贴纸渲染层:把持久化的 scrapbook item 按 anchor_time 浮进对应块 ──
   * 创建走总览 thread 的 AI 中介(place_scrapbook_image);这里只渲染 + 移除。
   * anchor_time 作语义挂点(挂哪条),不当像素定位用(守 5.19 红线)。 */
  function renderStickers() {
    if (!STATE.date && !DATE) return;
    var date = STATE.date || DATE;
    fetch("/api/scrapbook?date=" + encodeURIComponent(date)).then(function (r) { return r.json(); }).then(function (d) {
      (d.items || []).forEach(function (it) {
        if (!it.src) return;
        var t = (it.anchor_time || "").replace(/^(\d):/, "0$1:");   // 9:00 → 09:00
        var sec = t ? document.querySelector('.block[data-time="' + t + '"]') : null;
        if (!sec) sec = document.querySelector(".block:last-of-type");   // 没锚就挂末块
        if (!sec) return;
        var piece = sec.querySelector(".piece");
        if (!piece || piece.querySelector('.sticker[data-id="' + it.id + '"]')) return;
        var fig = document.createElement("div");
        fig.className = "sticker landing";
        fig.setAttribute("data-id", it.id || "");
        fig.title = "双击取下";
        fig.innerHTML = '<img src="' + esc(it.src) + '" alt="贴纸">';
        piece.insertBefore(fig, piece.firstChild);
        fig.addEventListener("dblclick", function () { removeSticker(date, it.id, fig); });
      });
    }).catch(function () {});
  }
  function removeSticker(date, id, fig) {
    fig.classList.add("folding");
    fetch("/api/scrapbook/delete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: date, id: id }),
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && (d.error || d.detail)) { whisper("取不下来 — " + (d.error || d.detail)); fig.classList.remove("folding"); return; }
      setTimeout(function () { fig.parentNode && fig.parentNode.removeChild(fig); }, 600);
      whisper("取下了一张贴纸");
    }).catch(function (e) { whisper("取不下来 — " + e.message); fig.classList.remove("folding"); });
  }

  /* ── 翻日:跳到存在的相邻日(跳过空缺),走 URL reload 保 STATE 干净 ── */
  function addDay(iso, n) {
    var d = new Date(iso + "T12:00:00");
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function cnDate(iso) {
    var d = new Date(iso + "T12:00:00");
    return cnNum(d.getMonth() + 1) + "月" + cnNum(d.getDate()) + "日";
  }

  // 补建目标:永远是"你看的这天的紧邻后一天"(cur+1),逐天往前填断档。
  // 上限到今天(不建未来);已存在则不补。"创建今天"只是 cur+1 恰好等于今天的特例。
  // 例:停在 6.13、6.14 缺 → 补 6.14(不跳到今天 6.15);到了 6.14 再补 6.15。
  function newDayTarget(existing, cur, today) {
    var target = addDay(cur, 1);
    if (target > today) return null;                       // 不建未来,补建只到今天为止
    return existing.indexOf(target) < 0 ? target : null;   // 紧邻后一天已存在 → 这儿没断档,不显示
  }

  function createDay(target) {
    var today = new Date().toISOString().slice(0, 10);
    whisper("起一页 ……");
    fetch("/api/journal/new-day", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: target }),
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.ok) location.href = "./day-paper.html" + (target === today ? "" : "?date=" + target);
      else whisper("没建成 — " + ((d && (d.error || d.message)) || "未知"));
    }).catch(function (e) { whisper("没建成 — " + e.message); });
  }

  function wireDayFlip() {
    var prev = $("flipPrev"), next = $("flipNext"), newBtn = $("flipNew");
    if (!prev || !next) return;
    fetch("/api/journal/days").then(function (r) { return r.json(); }).then(function (d) {
      var existing = (d.days || []).map(function (x) { return x.date; }).sort();  // 真有文件的天
      var today = new Date().toISOString().slice(0, 10);
      var nav = existing.slice();
      if (nav.indexOf(today) < 0) nav.push(today);   // 今天即便没文件也可达
      nav.sort();
      var cur = STATE.date || today;
      var i = nav.indexOf(cur);
      function link(el, date, label) {
        if (!date) { el.hidden = true; return; }
        el.hidden = false;
        el.textContent = label;
        el.setAttribute("href", "./day-paper.html" + (date === today ? "" : "?date=" + date));
      }
      link(prev, i > 0 ? nav[i - 1] : null, "‹ 前一日");
      link(next, i >= 0 && i < nav.length - 1 ? nav[i + 1] : null, "后一日 ›");

      // 补建:只在有"该建却没建"的目标时露出
      if (newBtn) {
        var target = newDayTarget(existing, cur, today);
        if (!target || existing.indexOf(target) >= 0) {
          newBtn.hidden = true;
        } else {
          newBtn.hidden = false;
          newBtn.textContent = target === today ? "+ 起今天一页" : "+ 补建 " + cnDate(target);
          newBtn.onclick = function (e) { e.preventDefault(); createDay(target); };
        }
      }
    }).catch(function () {});
  }

  /* ── 昼夜小印:报头快翻日/夜(跟设置的三态共用 gateway-theme 真源) ── */
  function wireModeSeal() {
    var seal = $("modeSeal");
    if (!seal || !window.gatewayTheme) return;
    function paint() {
      // 当前生效的明暗(system 态读系统)→ 印上显示"另一面"可切到的灯
      var cur = document.documentElement.getAttribute("data-theme");
      if (!cur) cur = window.matchMedia("(prefers-color-scheme: dark)").matches ? "night" : "day";
      var ch = seal.querySelector(".ms-char");
      if (ch) ch.textContent = cur === "night" ? "昼" : "夜";  // 印面是"去往的那盏灯"
      seal.dataset.cur = cur;
    }
    seal.addEventListener("click", function () {
      var cur = seal.dataset.cur === "night" ? "night" : "day";
      seal.classList.add("flipping");
      setTimeout(function () {
        window.gatewayTheme.set(cur === "night" ? "day" : "night");
        paint();
        seal.classList.remove("flipping");
      }, 200);
    });
    window.addEventListener("gateway-theme-change", paint);
    paint();
  }

  /* ── 启动:三路数据齐 → DOM 定型 → 才起动画/行为(paperInit) ── */
  fetch("/api/journal/today" + (DATE ? "?date=" + DATE : ""))
    .then(function (r) { return r.json(); })
    .then(function (payload) {
      var jobs = [];
      STATE.writable = true;   // 单日页散文随时可改(跟 classic 一致,patch 端点 date-aware)
      if (payload.error) {
        STATE.date = DATE || new Date().toISOString().slice(0, 10);
        mastheadFor(STATE.date, "");
        renderDay({ blocks: [] });
      } else {
        STATE.date = DATE || payload.date;
        STATE.file = payload.file;
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
    .then(function () { wireModeSeal(); wireDayFlip(); renderStickers(); window.paperInit && window.paperInit(); });
})();
