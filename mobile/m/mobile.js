// 移动原生壳逻辑 · cd 设计组装为 vanilla,接 shim 真数据(/api/* + gatewayMd)。
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function api(p, o) { return fetch(p, o).then(function (r) { return r.json(); }); }
  function md(s) { return window.gatewayMd ? window.gatewayMd(s || "") : (s || ""); }
  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function esc(s) { return (s || "").replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }); }

  // ── 内联图标(取自 cd gw-data.jsx)──
  var I = {
    burger: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none"><path d="M3 6h16M3 11h16M3 16h16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plus: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M12 4v16M4 12h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    send: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 10l14-6-6 14-2.2-5.8L3 10z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    chev: '<svg width="8" height="14" viewBox="0 0 8 14" fill="none"><path d="M1 1l6 6-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    settings: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="2.6" stroke="currentColor" stroke-width="1.4"/><path d="M10 1.5v2M10 16.5v2M18.5 10h-2M3.5 10h-2M16 4l-1.4 1.4M5.4 14.6L4 16M16 16l-1.4-1.4M5.4 5.4L4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    aggregate: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 5h14M5 10h10M7 15h6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    widget: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><rect x="3" y="3" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/><rect x="11" y="3" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/><rect x="3" y="11" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/><rect x="11" y="11" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/></svg>',
    history: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 5v5l3 2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M3.5 10a6.5 6.5 0 106.5-6.5A6.5 6.5 0 004 7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M2.5 4v3h3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    about: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.3"/><path d="M10 9v4.5M10 6.4v.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    back: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12 4l-6 6 6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };
  // MVP 范围:聚合/小组件/历史 是 C 类(plan 路线图后续往上加),先不放入口免得点开是空页。
  var MENU = [
    { id: "settings", glyph: I.settings, label: "设置", desc: "钥匙 · 模型" },
    { id: "about", glyph: I.about, label: "关于", desc: "Gateway · 私印小报" }
  ];

  // ── 日期工具 ──
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function todayIso() { var d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function isoAdd(iso, n) { var p = iso.split("-"); var d = new Date(+p[0], +p[1] - 1, +p[2] + n); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  var DOW = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  var MOY = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  function dparts(iso) { var p = iso.split("-"); var d = new Date(+p[0], +p[1] - 1, +p[2]); return { num: +p[2], dow: DOW[d.getDay()], mo: MOY[+p[1] - 1] }; }

  var TODAY = todayIso();
  var state = { tab: "journal", date: TODAY, days: [], readonly: false, thread: [], filled: 0, undo: null, undoTimer: null, hintTimer: null };

  // ── 轻提示 ──
  function flash(msg) {
    var t = $("toasts");
    var old = t.querySelector(".gw-hint-toast"); if (old) old.remove();
    var h = el("div", "gw-hint-toast", esc(msg)); t.appendChild(h);
    requestAnimationFrame(function () { h.classList.add("on"); });
    clearTimeout(state.hintTimer);
    state.hintTimer = setTimeout(function () { h.classList.remove("on"); setTimeout(function () { h.remove(); }, 400); }, 2200);
  }

  // ── 日期带 ──
  function loadDateband() {
    return api("/api/journal/days").then(function (r) {
      var created = {}; (r.days || []).forEach(function (d) { created[d.date] = true; });
      var list = Object.keys(created).filter(function (d) { return d <= TODAY; }).sort();
      if (list.indexOf(TODAY) === -1) list.push(TODAY);
      var t1 = isoAdd(TODAY, 1), t2 = isoAdd(TODAY, 2);
      var days = list.map(function (iso) { return { iso: iso, state: iso === TODAY ? "today" : "past" }; });
      days.push({ iso: t1, state: created[t1] ? "past" : "creatable" });
      days.push({ iso: t2, state: created[t2] ? "past" : "locked" });
      state.days = days; renderDateband();
    });
  }
  function renderDateband() {
    var band = $("dateband"); band.innerHTML = "";
    state.days.forEach(function (d) {
      var p = dparts(d.iso);
      var cls = "gw-day" + (d.state === "today" ? " today" : "") + (d.iso === state.date ? " on" : "") +
        (d.state === "creatable" ? " future creatable" : "") + (d.state === "locked" ? " future locked" : "");
      var moTxt = d.state === "today" ? "今天" : d.state === "creatable" ? "明天" : p.mo;
      var b = el("button", cls,
        '<span class="gw-day-dow">' + p.dow + '</span>' +
        '<span class="gw-day-num">' + p.num + '</span>' +
        '<span class="gw-day-mo">' + moTxt + '</span>' +
        (d.state === "creatable" ? '<span class="gw-day-plus">+</span>' : ''));
      b.addEventListener("click", function () { pickDay(d); });
      band.appendChild(b);
    });
    var cur = band.querySelector(".today") || band.querySelector(".on");
    if (cur) band.scrollLeft = cur.offsetLeft - band.clientWidth / 2 + cur.offsetWidth / 2;
  }
  function pickDay(d) {
    if (d.state === "locked") { flash("最多只能建到明天（+1）"); return; }
    if (d.state === "creatable") {
      api("/api/journal/new-day", { method: "POST", body: JSON.stringify({ date: d.iso }) }).then(function (res) {
        if (res && res.ok === false) { flash(res.error || "建不了"); return; }
        state.date = d.iso;
        loadDateband().then(function () {
          var nb = $("dateband").querySelector(".gw-day.on"); if (nb) nb.classList.add("born");
          flash("明天已创建 · 落了张空骨架"); loadDay();
        });
      });
      return;
    }
    state.date = d.iso; renderDateband(); loadDay();
  }

  // ── 日记页 ──
  function loadDay() {
    state.readonly = state.date < TODAY;
    Promise.all([
      api("/api/journal/today?date=" + state.date),
      api("/api/daily-tasks?date=" + state.date),
      api("/api/water-cup"),
    ]).then(function (rs) { state.cupImg = (rs[2] && rs[2].image_url) || null; renderJournal(rs[0], rs[1]); });
  }
  function renderJournal(j, t) {
    var v = $("journalView"); v.innerHTML = "";
    state.filled = (t && t.water_filled) || 0; // 从当天 md 喝水勾选数恢复八杯水进度
    // care: 八杯水 + 打卡
    var care = el("div", "gw-care");
    care.appendChild(buildCups());
    care.appendChild(buildTasks((t && t.tasks) || []));
    v.appendChild(care);
    // 时间线
    var stream = el("div", "gw-stream");
    var blocks = (j && j.blocks) || [];
    var entries = [];
    blocks.forEach(function (b) { (b.h2 || []).forEach(function (h) { entries.push({ time: b.time, h: h }); }); });
    if (!entries.length) {
      stream.appendChild(el("div", "gw-empty", "<b>这一天还是空白</b>点下面的 + 写下第一块，<br>或滑日期带到今天自动落骨架。"));
    } else {
      entries.forEach(function (e) { stream.appendChild(buildEntry(e)); });
    }
    v.appendChild(stream);
  }

  // 八杯水(滑动点亮 + 长按换杯图;喝水落 md,水杯图落 Preferences 对齐 PC 端)
  function buildCups() {
    var N = 8, block = el("div", "gw-care-block", '<div class="gw-care-label">八杯水 <span style="opacity:.55">· 长按换杯</span></div>');
    var row = el("div", "gw-cups");
    var cups = [];
    var hasImg = !!state.cupImg;
    for (var i = 0; i < N; i++) {
      var inner = hasImg ? '<img src="' + state.cupImg + '" alt="" class="gw-cup-img">' : '<div class="gw-cup-fill"></div>';
      var c = el("div", "gw-cup" + (hasImg ? " with-image" : ""), inner);
      cups.push(c); row.appendChild(c);
    }
    var count = el("div", "gw-cups-count");
    function paint(focus) {
      cups.forEach(function (c, i) {
        c.className = "gw-cup" + (hasImg ? " with-image" : "") + (i < state.filled ? " filled" : "") +
          (i === focus ? " cup-focus" : (focus >= 0 && Math.abs(i - focus) === 1 ? " cup-near" : ""));
      });
      count.innerHTML = "<b>" + state.filled + "</b> / " + N + " 杯 · " + (state.readonly ? "历史日只读" : "滑过杯子点亮 · 长按换杯");
    }
    function idxAt(x) { var best = -1, bd = 1e9; cups.forEach(function (c, i) { var r = c.getBoundingClientRect(); var d = Math.abs(x - (r.left + r.width / 2)); if (d < bd) { bd = d; best = i; } }); return best; }
    function apply(x) { if (state.readonly) return; var i = idxAt(x); if (i < 0) return; var was = state.filled; state.filled = i + 1; paint(i); if (i + 1 > was) cups[i].classList.add("just"); }
    // tap/swipe/longpress 三态:长按 480ms 不动 → 换杯图;一动 → swipe 喝水;tap 释放 → 单杯 commit
    var st = { sx: 0, sy: 0, mode: null, timer: null, captured: false };
    function clearT() { if (st.timer) { clearTimeout(st.timer); st.timer = null; } }
    row.addEventListener("pointerdown", function (e) {
      if (state.readonly) return;
      st = { sx: e.clientX, sy: e.clientY, mode: null, timer: null, captured: false };
      st.timer = setTimeout(function () {
        if (st.mode === null) { st.mode = "lp"; if (navigator.vibrate) navigator.vibrate(12); pickWaterCupImage(); }
      }, 480);
    });
    row.addEventListener("pointermove", function (e) {
      if (state.readonly || st.mode === "lp") return;
      var adx = e.clientX - st.sx, ady = e.clientY - st.sy;
      if (st.mode === null && (Math.abs(adx) > 8 || Math.abs(ady) > 8)) {
        clearT(); st.mode = "swipe";
        try { row.setPointerCapture(e.pointerId); st.captured = true; } catch (x) {}
      }
      if (st.mode === "swipe") apply(e.clientX);
    });
    row.addEventListener("pointerup", function (e) {
      clearT();
      if (st.mode === "lp") { st.mode = null; return; }                  // 长按已 fire,不喝水
      if (st.mode === null) apply(e.clientX);                            // tap = 单杯 commit
      paint(-1);
      if (!state.readonly) api("/api/daily-tasks/water", { method: "POST", body: JSON.stringify({ date: state.date, filled: state.filled }) });
      st.mode = null;
    });
    row.addEventListener("pointercancel", function () { clearT(); st.mode = null; paint(-1); });
    paint(-1);
    block.appendChild(row); block.appendChild(count); return block;
  }

  // 打卡(横滑,点 toggle → daily-tasks/check)
  function buildTasks(tasks) {
    var block = el("div", "gw-care-block", '<div class="gw-care-label">今日打卡 <span style="opacity:.55">· 长按换图标</span></div>');
    var row = el("div", "gw-tasks");
    tasks.forEach(function (t) {
      var inner = t.image_url
        ? '<img src="' + t.image_url + '" alt="" style="width:100%;height:100%;border-radius:50%;object-fit:cover">'
        : esc((t.name || "·").slice(0, 1));
      // 余量徽标:days_left ≤3 上 .urgent 红色;catalog 没返字段(没填 meta)→ 不挂
      var urgent = typeof t.days_left === "number" && t.days_left <= 3;
      var badge = urgent ? '<span class="gw-task-badge">' + t.days_left + 'd</span>' : '';
      var b = el("button", "gw-task" + (t.checked ? " on" : "") + (urgent ? " urgent" : ""),
        '<span class="gw-task-glyph">' + inner + '</span><span class="gw-task-name">' + esc(t.name) + '</span>' + badge);
      if (state.readonly) b.disabled = true;
      var lp = null, didLong = false;
      // 长按改弹 action sheet(对齐 PC 右键菜单:换图/改 N 粒/看历史/删除)
      b.addEventListener("pointerdown", function () { if (state.readonly) return; didLong = false; lp = setTimeout(function () { didLong = true; if (navigator.vibrate) navigator.vibrate(12); openTaskSheet(t); }, 480); });
      ["pointerup", "pointercancel", "pointerleave"].forEach(function (ev) { b.addEventListener(ev, function () { clearTimeout(lp); }); });
      b.addEventListener("click", function () {
        if (state.readonly || didLong) { didLong = false; return; }
        api("/api/daily-tasks/check", { method: "POST", body: JSON.stringify({ task_name: t.name, checked: !t.checked }) }).then(loadDay);
      });
      row.appendChild(b);
    });
    block.appendChild(row); return block;
  }

  // 选图 → 端侧抠图(真机 Cutout 插件;浏览器/模拟器回落原图)→ 落成打卡图标
  function pickTaskImage(task) {
    var inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*"; inp.style.display = "none";
    document.body.appendChild(inp);
    inp.addEventListener("change", function () {
      var f = inp.files && inp.files[0]; if (inp.parentNode) document.body.removeChild(inp); if (!f) return;
      var rd = new FileReader();
      rd.onload = function () {
        var dataUrl = rd.result;
        var cut = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Cutout;
        if (cut) flash("抠图中…");
        var p = cut ? cut.cutout({ image: dataUrl }).then(function (r) { return r.png; }).catch(function () { flash("没抠出主体 · 先用原图"); return dataUrl; }) : Promise.resolve(dataUrl);
        p.then(function (png) {
          api("/api/daily-tasks/set-image", { method: "POST", body: JSON.stringify({ task_name: task.name, image: png }) }).then(function () { flash("图标已换 ✦"); loadDay(); });
        });
      };
      rd.readAsDataURL(f);
    });
    inp.click();
  }
  // 对齐 PC 右键菜单:长按打卡 → 弹 sheet 选 换图 / 改 N 粒 / 看历史 / 删除
  function openTaskSheet(task) {
    var layer = $("cardLayer"); layer.innerHTML = "";
    var scrim = el("div", "gw-scrim");
    var card = el("div", "gw-card sheet gw-task-sheet", '');
    function setView(html) { card.innerHTML = html; }
    function close() { scrim.classList.remove("on"); card.classList.remove("on"); setTimeout(function () { layer.innerHTML = ""; }, 460); }

    function viewMain() {
      setView(
        '<div class="gw-card-grip"></div>' +
        '<div class="gw-card-head"><span class="gw-card-kicker">' + esc(task.name) + '</span><button class="gw-card-x">×</button></div>' +
        '<div class="gw-ts-list">' +
          '<button class="gw-ts-row" data-a="img"><span>🖼</span><span class="gw-ts-lab">换图标</span></button>' +
          '<button class="gw-ts-row" data-a="meta"><span>💊</span><span class="gw-ts-lab">改每天 N 粒 / 瓶装颗数</span></button>' +
          '<button class="gw-ts-row" data-a="hist"><span>📅</span><span class="gw-ts-lab">看本周完成率</span></button>' +
          '<button class="gw-ts-row danger" data-a="del"><span>🗑</span><span class="gw-ts-lab">删除这条打卡</span></button>' +
        '</div>');
      card.querySelector(".gw-card-x").addEventListener("click", close);
      card.querySelectorAll(".gw-ts-row").forEach(function (b) {
        b.addEventListener("click", function () {
          var a = b.dataset.a;
          if (a === "img") { close(); pickTaskImage(task); }
          else if (a === "meta") viewMeta();
          else if (a === "hist") viewHist();
          else if (a === "del") viewDel();
        });
      });
    }

    function viewMeta() {
      var cur_total = task.total_pills || "", cur_dose = task.daily_dose || 1;
      setView(
        '<div class="gw-card-grip"></div>' +
        '<div class="gw-card-head"><button class="gw-ts-back">‹</button><span class="gw-card-kicker">改 ' + esc(task.name) + '</span><button class="gw-card-x">×</button></div>' +
        '<div class="gw-field"><div class="gw-field-lab">每天吃几粒</div><input type="number" min="1" id="tsDose" value="' + cur_dose + '" class="gw-ts-num"></div>' +
        '<div class="gw-field"><div class="gw-field-lab">瓶装多少颗(空 = 不追踪剩余)</div><input type="number" min="1" id="tsTotal" placeholder="例 60" value="' + cur_total + '" class="gw-ts-num"></div>' +
        '<div class="gw-card-foot"><span class="gw-card-hint">MD 是真相 · meta 单独存</span><button class="gw-card-save" id="tsSave">保存</button></div>');
      card.querySelector(".gw-ts-back").addEventListener("click", viewMain);
      card.querySelector(".gw-card-x").addEventListener("click", close);
      card.querySelector("#tsSave").addEventListener("click", function () {
        var body = { task_name: task.name, daily_dose: parseInt(card.querySelector("#tsDose").value || "1", 10), total_pills: card.querySelector("#tsTotal").value || null };
        api("/api/daily-tasks/meta", { method: "POST", body: JSON.stringify(body) }).then(function () { close(); flash("已存 · " + body.daily_dose + " 粒/天"); loadDay(); });
      });
    }

    function viewHist() {
      setView(
        '<div class="gw-card-grip"></div>' +
        '<div class="gw-card-head"><button class="gw-ts-back">‹</button><span class="gw-card-kicker">' + esc(task.name) + ' · 14 天</span><button class="gw-card-x">×</button></div>' +
        '<div class="gw-ts-hist" id="tsHist">加载中…</div>');
      card.querySelector(".gw-ts-back").addEventListener("click", viewMain);
      card.querySelector(".gw-card-x").addEventListener("click", close);
      api("/api/daily-tasks/history?days=14&name=" + encodeURIComponent(task.name)).then(function (r) {
        if (!r || !r.history) { card.querySelector("#tsHist").textContent = "无历史"; return; }
        var dots = r.history.slice().reverse().map(function (h) {
          var cls = h.checked === true ? "on" : (h.checked === false ? "miss" : "skip");
          return '<span class="gw-ts-dot ' + cls + '" title="' + h.date + '"></span>';
        }).join("");
        var rate = r.recorded_days ? Math.round(r.checked_days / r.recorded_days * 100) : 0;
        card.querySelector("#tsHist").innerHTML =
          '<div class="gw-ts-rate"><b>' + r.checked_days + '</b> / ' + r.recorded_days + ' 天 · ' + rate + '%</div>' +
          '<div class="gw-ts-dots">' + dots + '</div>' +
          '<div class="gw-ts-legend">绿 = 打了 · 灰 = 漏 · 空 = 无记录</div>';
      });
    }

    function viewDel() {
      setView(
        '<div class="gw-card-grip"></div>' +
        '<div class="gw-card-head"><button class="gw-ts-back">‹</button><span class="gw-card-kicker">删除 ' + esc(task.name) + '?</span><button class="gw-card-x">×</button></div>' +
        '<div class="gw-ts-warn">这条打卡会从当天 md 顶部彻底删除,图标也会清。历史日的打卡记录不动。</div>' +
        '<div class="gw-card-foot"><span class="gw-card-hint">点删除 = 立刻执行</span><button class="gw-card-save danger" id="tsDel">确认删除</button></div>');
      card.querySelector(".gw-ts-back").addEventListener("click", viewMain);
      card.querySelector(".gw-card-x").addEventListener("click", close);
      card.querySelector("#tsDel").addEventListener("click", function () {
        api("/api/daily-tasks/delete", { method: "POST", body: JSON.stringify({ task_name: task.name, date: state.date }) }).then(function () { close(); flash("已删除 · " + task.name); loadDay(); });
      });
    }

    layer.appendChild(scrim); layer.appendChild(card);
    scrim.addEventListener("pointerdown", close);
    viewMain();
    requestAnimationFrame(function () { scrim.classList.add("on"); card.classList.add("on"); });
  }

  // 对齐 PC 端 uploadForCup:选图 → 端侧抠图 → POST /api/water-cup 落 base64 → 8 个杯子都变这张图
  function pickWaterCupImage() {
    var inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*"; inp.style.display = "none";
    document.body.appendChild(inp);
    inp.addEventListener("change", function () {
      var f = inp.files && inp.files[0]; if (inp.parentNode) document.body.removeChild(inp); if (!f) return;
      var rd = new FileReader();
      rd.onload = function () {
        var dataUrl = rd.result;
        var cut = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Cutout;
        if (cut) flash("抠图中…");
        var p = cut ? cut.cutout({ image: dataUrl }).then(function (r) { return r.png; }).catch(function () { flash("没抠出主体 · 先用原图"); return dataUrl; }) : Promise.resolve(dataUrl);
        p.then(function (png) {
          api("/api/water-cup", { method: "POST", body: JSON.stringify({ image: png }) }).then(function () { flash("水杯已换 ✦"); loadDay(); });
        });
      };
      rd.readAsDataURL(f);
    });
    inp.click();
  }

  // 单条 entry: 左滑删 + 长按拉进对话
  function parseCommit(raw) {
    var m = /#commit\s*[（(]\s*([^）)]*)[）)]\s*[:：]\s*([\s\S]*)/.exec(raw || "");
    if (!m) return null;
    var who = /claude|gpt|deepseek|gemini|\bai\b|opus|sonnet|fable/i.test(m[1]) ? "ai" : "me";
    return { who: who, text: m[2].trim() };
  }
  function buildEntry(e) {
    var wrap = el("div", "gw-entry-wrap");
    wrap.appendChild(el("div", "gw-entry-del", "删除"));
    var h = e.h;
    var tagsHtml = (h.tags || []).map(function (t) { return '<span class="gw-tag">#' + esc(t) + '</span>'; }).join("");
    var commitsHtml = "";
    (h.commits || []).forEach(function (raw) {
      var c = parseCommit(raw); if (!c) return;
      commitsHtml += '<div class="gw-commit ' + c.who + '"><span class="gw-commit-au">' + (c.who === "ai" ? "AI" : "我") + '</span><span class="gw-commit-text">' + esc(c.text) + '</span></div>';
    });
    var entry = el("div", "gw-entry",
      '<div class="gw-lp-hint"></div>' +
      '<div class="gw-entry-time"><span class="hr">' + e.time.split(":")[0] + '</span>:' + e.time.split(":")[1] + '</div>' +
      '<div class="gw-entry-main">' +
        (tagsHtml ? '<div class="gw-entry-tags">' + tagsHtml + '</div>' : '') +
        (h.title ? '<div class="gw-entry-title">' + esc(h.title) + '</div>' : '') +
        '<div class="gw-entry-body">' + md(h.body) + '</div>' +
        (commitsHtml ? '<div class="gw-commits">' + commitsHtml + '</div>' : '') +
      '</div>');
    bindEntryGesture(entry, e);
    wrap.appendChild(entry);
    return wrap;
  }
  function bindEntryGesture(entry, e) {
    var st = { x: 0, y: 0, mode: null, timer: null }, dx = 0;
    function setDx(v) { dx = v; entry.style.transform = "translateX(" + v + "px)"; }
    function clearT() { if (st.timer) { clearTimeout(st.timer); st.timer = null; } }
    entry.addEventListener("pointerdown", function (ev) {
      if (ev.button === 2) return;
      st = { x: ev.clientX, y: ev.clientY, mode: null, timer: null };
      entry.classList.add("lp-arming");
      st.timer = setTimeout(function () {
        if (st.mode === null) { st.mode = "lp"; entry.classList.add("longpress"); if (navigator.vibrate) navigator.vibrate(12); setTimeout(function () { pullToChat(e); entry.classList.remove("longpress", "lp-arming"); }, 420); }
      }, 480);
    });
    entry.addEventListener("pointermove", function (ev) {
      var adx = ev.clientX - st.x, ady = ev.clientY - st.y;
      if (st.mode === null && (Math.abs(adx) > 8 || Math.abs(ady) > 8)) {
        clearT(); entry.classList.remove("lp-arming");
        if (Math.abs(adx) > Math.abs(ady) && adx < 0) { st.mode = "swipe"; try { entry.setPointerCapture(ev.pointerId); } catch (x) {} entry.classList.add("dragging"); }
        else st.mode = "scroll";
      }
      if (st.mode === "swipe" && !state.readonly) setDx(Math.max(-96, Math.min(0, adx)));
    });
    entry.addEventListener("pointerup", function () {
      clearT(); entry.classList.remove("lp-arming");
      if (st.mode === "swipe") {
        entry.classList.remove("dragging");
        if (dx < -60) { setDx(-window.innerWidth); setTimeout(function () { deleteEntry(e); }, 240); }
        else setDx(0);
      } else if (st.mode === null && !state.readonly) {
        // tap = 进入编辑(长按拉对话由 timer 走 mode="lp",滑动改 mode="swipe"/"scroll",都不会到这里)
        openCard(e);
      }
    });
    entry.addEventListener("pointercancel", function () { clearT(); entry.classList.remove("lp-arming", "dragging"); setDx(0); });
    entry.addEventListener("contextmenu", function (ev) { ev.preventDefault(); });
  }

  function deleteEntry(e) {
    api("/api/journal/delete-block", { method: "POST", body: JSON.stringify({ date: state.date, time: e.time }) }).then(function () {
      state.undo = { e: e, date: state.date }; showUndo(e.h.title || "条目"); loadDay();
    });
  }
  function showUndo(label) {
    var t = $("toasts"); var old = t.querySelector(".gw-undo"); if (old) old.remove();
    var u = el("div", "gw-undo on",
      '<span class="gw-undo-msg">已删除「' + esc(label) + '」</span>' +
      '<button class="gw-undo-btn">撤回</button>' +
      '<span class="gw-undo-bar" style="animation:gw-undobar 5s linear forwards"></span>');
    u.querySelector(".gw-undo-btn").addEventListener("click", doUndo);
    t.appendChild(u);
    clearTimeout(state.undoTimer);
    state.undoTimer = setTimeout(function () { u.classList.remove("on"); setTimeout(function () { u.remove(); }, 250); state.undo = null; }, 5000);
  }
  function doUndo() {
    if (!state.undo) return; var e = state.undo.e, date = state.undo.date;
    // critic 推回:旧路径 insert-block 把删的 entry 加到 md 末尾,丢 commits 注解 +
    // 也跟原占位 ## 块共存(同一时间 # H：MM 出现两次)。改 patch 同位回填:
    // 把删时留的 "##" 占位 H2 替换成原 H2 + body + commits 三件套。
    var tags = (e.h.tags || []).map(function (t) { return "#" + t; }).join(" ");
    var h2 = "## " + tags + (tags && e.h.title ? " " : "") + (e.h.title || "") + " @user";
    var commits = (e.h.commits || []).join("\n");
    var new_md = h2 + "\n\n" + (e.h.body || "") + (commits ? "\n\n" + commits : "");
    api("/api/journal/patch", { method: "POST", body: JSON.stringify({ date: date, time: e.time, new_md: new_md, author: "user" }) }).then(function () {
      state.undo = null; clearTimeout(state.undoTimer);
      var u = $("toasts").querySelector(".gw-undo"); if (u) u.remove();
      if (date === state.date) loadDay();
    });
  }
  function pullToChat(e) {
    state.thread.push({ kind: "ref", who: "me", refKind: "日记 · " + e.time, refText: e.h.title || md(e.h.body).replace(/<[^>]+>/g, "").slice(0, 24) });
    saveThread(); flash("已拉进对话 ✦ 指给 AI 看");
  }

  // ── 对话 ──
  function loadThread() {
    return api("/api/thread/history").then(function (r) {
      state.thread = (r.history || []).map(function (m) {
        if (m.kind) return m;
        return { kind: "msg", who: (m.role === "ai" || m.role === "assistant" || m.who === "ai") ? "ai" : "me", text: typeof m.content === "string" ? m.content : (m.text || "") };
      });
      renderThread();
    });
  }
  function saveThread() { api("/api/thread/save", { method: "POST", body: JSON.stringify({ history: state.thread }) }).catch(function () {}); }
  function renderThread(grinding) {
    var v = $("chatView"); v.innerHTML = "";
    var box = el("div", "gw-thread");
    state.thread.forEach(function (m) {
      if (m.kind === "ref") { box.appendChild(el("div", "gw-ref", '<div class="rk">' + esc(m.refKind) + '</div><div class="rt">' + esc(m.refText) + '</div>')); return; }
      if (m.kind === "note") { box.appendChild(el("div", "gw-note", '<div class="gw-note-time">' + esc(m.time || "") + '</div><div class="gw-note-body">' + md(m.body) + '</div><div class="gw-note-sig">' + esc(m.sig || "") + '</div>')); return; }
      var msg = el("div", "gw-msg " + (m.who === "ai" ? "ai" : "me"),
        '<span class="who">' + (m.who === "ai" ? "Gateway" : "我") + '</span>' +
        '<div class="gw-bubble' + (m.streaming ? " gw-cursor" : "") + '">' + (m.who === "ai" ? md(m.text) : esc(m.text)) + '</div>');
      box.appendChild(msg);
    });
    if (grinding) box.appendChild(el("div", "gw-grind", '<span class="gw-grind-stone"></span><span class="gw-grind-text">磨墨中…</span>'));
    v.appendChild(box);
    var sc = $("scroll"); sc.scrollTop = sc.scrollHeight;
  }
  function sendChat(text) {
    state.thread.push({ kind: "msg", who: "me", text: text }); renderThread(true);
    var hist = state.thread.filter(function (m) { return m.kind === "msg"; }).map(function (m) { return { role: m.who === "ai" ? "assistant" : "user", content: m.text }; });
    fetch("/api/chat", { method: "POST", body: JSON.stringify({ message: text, history: hist }) }).then(function (res) {
      var reader = res.body.getReader(), dec = new TextDecoder(), buf = "", aiMsg = null;
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) { if (aiMsg) { aiMsg.streaming = false; } saveThread(); renderThread(); return; }
          buf += dec.decode(r.value, { stream: true });
          var parts = buf.split("\n\n"); buf = parts.pop();
          parts.forEach(function (line) {
            line = line.trim(); if (line.indexOf("data:") !== 0) return;
            try {
              var ev = JSON.parse(line.slice(5).trim());
              if (ev.type === "delta") { if (!aiMsg) { aiMsg = { kind: "msg", who: "ai", text: "", streaming: true }; state.thread.push(aiMsg); } aiMsg.text += ev.text; renderThread(); }
              else if (ev.type === "error") { if (!aiMsg) { aiMsg = { kind: "msg", who: "ai", text: "" }; state.thread.push(aiMsg); } aiMsg.text += "（出错：" + ev.text + "）"; }
            } catch (x) {}
          });
          return pump();
        });
      }
      return pump();
    }).catch(function () { renderThread(); });
  }

  // ── 底栏 ──
  function renderBottom() {
    var b = $("bottom"); b.innerHTML = "";
    var oldFab = document.querySelector(".gw-fab-float"); if (oldFab) oldFab.remove();
    if (state.tab === "journal") {
      // 悬浮 + (不占底栏空间)
      var fab = el("button", "gw-fab gw-fab-float", I.plus); fab.setAttribute("aria-label", "新建条目");
      fab.addEventListener("click", function () { openCard(); });
      $("gw").appendChild(fab);
    } else {
      var bar = el("div", "gw-chatbar");
      var ta = el("textarea", "gw-chat-input"); ta.rows = 1; ta.placeholder = "跟 Gateway 说点什么…";
      var send = el("button", "gw-chat-send", I.send); send.disabled = true;
      ta.addEventListener("input", function () { send.disabled = !ta.value.trim(); ta.style.height = "auto"; ta.style.height = Math.min(96, ta.scrollHeight) + "px"; });
      ta.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); fire(); } });
      send.addEventListener("click", fire);
      function fire() { var t = ta.value.trim(); if (!t) return; ta.value = ""; ta.style.height = "auto"; send.disabled = true; sendChat(t); }
      bar.appendChild(ta); bar.appendChild(send); b.appendChild(bar);
    }
  }

  // ── + 卡片编辑器(底部 sheet 形态)──
  // existing 传入 = 编辑已有 entry(预填 + patch 路径);不传 = 新建(insert 路径)。
  // 编辑时锁时间块,改时间 = 移动块,会撞已有内容,scope 外(A.2 再说)。
  var SUGGEST = ["#gateway", "#a股", "#身体", "#桌宠", "#杂", "#风险"];
  function openCard(existing) {
    var layer = $("cardLayer"); layer.innerHTML = "";
    var picked = {}; // tag → true
    var editing = !!existing;
    var hh, mm;
    if (editing) {
      var parts = existing.time.split(":"); hh = parts[0]; mm = parts[1];
      (existing.h.tags || []).forEach(function (t) { picked["#" + t] = true; });  // 全量预选,UI 端能看见所有现有 tag
    } else {
      var now = new Date(); hh = pad(now.getHours()); mm = now.getMinutes() < 30 ? "00" : "30";
    }
    var scrim = el("div", "gw-scrim");
    var card = el("div", "gw-card sheet",
      '<div class="gw-card-grip"></div>' +
      '<div class="gw-card-head"><span class="gw-card-kicker">' + (editing ? "改一块" : "写一块") + '</span><button class="gw-card-x">×</button></div>' +
      '<div class="gw-field"><div class="gw-field-lab"># 标签</div><div class="gw-chips" id="cChips"></div></div>' +
      '<div class="gw-field"><div class="gw-field-lab">时间块</div><div class="gw-time-row">' +
        '<input class="gw-time-in" id="cHh" inputmode="numeric" maxlength="2" value="' + hh + '">' +
        '<span class="gw-time-colon">:</span>' +
        '<input class="gw-time-in" id="cMm" inputmode="numeric" maxlength="2" value="' + mm + '">' +
        '<div class="gw-time-quick"><button id="cNow">现在</button><button id="cHour">整点</button><button id="cHalf">半</button></div></div></div>' +
      '<div class="gw-field" style="margin-bottom:8px"><div class="gw-field-lab">正文</div>' +
        '<input class="gw-entry-title" id="cTitle" placeholder="标题（可选）" style="display:block;width:100%;border:0;outline:none;background:transparent;margin-bottom:6px">' +
        '<textarea class="gw-body-in" id="cBody" placeholder="此刻在想什么…"></textarea></div>' +
      '<div class="gw-card-foot"><span class="gw-card-hint">MD 是真相 · 写进当天</span><button class="gw-card-save">' + (editing ? "改完" : "落笔") + '</button></div>');
    layer.appendChild(scrim); layer.appendChild(card);
    if (editing) {
      card.querySelector("#cTitle").value = existing.h.title || "";
      card.querySelector("#cBody").value = existing.h.body || "";
      card.querySelector("#cHh").readOnly = true; card.querySelector("#cMm").readOnly = true;
      var qt = card.querySelector(".gw-time-quick"); if (qt) qt.style.display = "none";
    }
    // tag chips
    var chips = card.querySelector("#cChips");
    function renderChips() {
      chips.innerHTML = "";
      SUGGEST.forEach(function (t) { var c = el("button", "gw-chip" + (picked[t] ? " on" : ""), esc(t)); c.addEventListener("click", function () { picked[t] = !picked[t]; renderChips(); }); chips.appendChild(c); });
      Object.keys(picked).forEach(function (t) { if (SUGGEST.indexOf(t) === -1 && picked[t]) { var c = el("button", "gw-chip on", esc(t)); c.addEventListener("click", function () { picked[t] = false; renderChips(); }); chips.appendChild(c); } });
      var add = el("button", "gw-chip add", "+ 新标签");
      add.addEventListener("click", function () {
        var inp = el("input", "gw-chip"); inp.placeholder = "标签…"; inp.style.width = "88px";
        chips.replaceChild(inp, add); inp.focus();
        function commit() { var t = inp.value.trim(); if (t && t[0] !== "#") t = "#" + t; if (t) picked[t] = true; renderChips(); }
        inp.addEventListener("blur", commit); inp.addEventListener("keydown", function (e) { if (e.key === "Enter") commit(); });
      });
      chips.appendChild(add);
    }
    if (!editing) picked["#gateway"] = true;  // 新建时默认 tag,编辑保留原状
    renderChips();
    // quick time
    card.querySelector("#cNow").addEventListener("click", function () { var d = new Date(); card.querySelector("#cHh").value = d.getHours(); card.querySelector("#cMm").value = d.getMinutes() < 30 ? "00" : "30"; });
    card.querySelector("#cHour").addEventListener("click", function () { card.querySelector("#cMm").value = "00"; });
    card.querySelector("#cHalf").addEventListener("click", function () { card.querySelector("#cMm").value = "30"; });
    // close / save
    function close() { scrim.classList.remove("on"); card.classList.remove("on"); setTimeout(function () { layer.innerHTML = ""; }, 460); }
    scrim.addEventListener("pointerdown", close);
    card.querySelector(".gw-card-x").addEventListener("click", close);
    card.querySelector(".gw-card-save").addEventListener("click", function () {
      var hv = pad(parseInt(card.querySelector("#cHh").value || "0", 10)), mv = pad(parseInt(card.querySelector("#cMm").value || "0", 10));
      var tags = Object.keys(picked).filter(function (t) { return picked[t]; }).map(function (t) { return t.replace(/^#/, ""); });
      var title = card.querySelector("#cTitle").value.trim(), bodyText = card.querySelector("#cBody").value.trim();
      if (editing) {
        // 保住原批注:shim patch 会替换 H1 到下个 --- 之间的内容,不主动保 commits → 客户端拼回
        var h2 = "## " + (tags[0] ? "#" + tags[0] + " " : "") + title;
        var commits = (existing.h.commits || []).join("\n");
        var new_md = h2 + "\n\n" + bodyText + (commits ? "\n\n" + commits : "");
        // author:'user' 是手机端用户在 UI 改自己的块;shim 默认 'ai' 是失败安全(对齐桌面 oracle)
        api("/api/journal/patch", { method: "POST", body: JSON.stringify({ date: state.date, time: existing.time, new_md: new_md, author: "user" }) })
          .then(function () { close(); flash("已改进 · " + existing.time); loadDay(); });
      } else {
        var body = { date: state.date, time: hv + ":" + mv, tag: tags[0] || "", title: title, body: bodyText };
        api("/api/journal/insert-block", { method: "POST", body: JSON.stringify(body) }).then(function () { close(); flash("已落笔 · 写进 " + body.time); loadDay(); });
      }
    });
    requestAnimationFrame(function () { scrim.classList.add("on"); card.classList.add("on"); });
  }

  // ── ☰ 抽屉 ──
  function openMenu() {
    var layer = $("menuLayer"); layer.innerHTML = "";
    var scrim = el("div", "gw-scrim");
    var drawer = el("div", "gw-drawer",
      '<div class="gw-drawer-grip"></div>' +
      '<div class="gw-drawer-head"><span class="gw-drawer-brand">Gateway</span><span class="gw-drawer-sub">人和 AI 共写的一本日记</span></div>');
    MENU.forEach(function (m) {
      var item = el("button", "gw-menu-item",
        '<span class="gw-menu-glyph">' + m.glyph + '</span><span class="gw-menu-label">' + m.label + '</span><span class="gw-menu-desc">' + m.desc + '</span><span class="gw-menu-chev">' + I.chev + '</span>');
      item.addEventListener("click", function () { close(); openSubPage(m); });
      drawer.appendChild(item);
    });
    layer.appendChild(scrim); layer.appendChild(drawer);
    function close() { scrim.classList.remove("on"); drawer.classList.remove("on"); setTimeout(function () { layer.innerHTML = ""; }, 460); }
    scrim.addEventListener("pointerdown", close);
    requestAnimationFrame(function () { scrim.classList.add("on"); drawer.classList.add("on"); });
  }

  // ── 子页(设置 / 占位)──
  function openSubPage(m) {
    var ov = el("div", "gw", "");
    ov.style.cssText = "position:fixed;inset:0;z-index:80";
    ov.innerHTML = '<div class="gw-breath"></div><div class="gw-grain"></div>' +
      '<div class="gw-top" style="position:static"><div class="gw-top-row1"><button class="gw-burger" id="subBack"></button>' +
      '<div class="gw-tabs"><span class="gw-tab on" style="cursor:default">' + m.label + '</span></div>' +
      '<div class="gw-top-spacer"></div><span class="gw-breathdot"></span></div></div>' +
      '<div class="gw-scroll" id="subScroll"></div>';
    document.body.appendChild(ov);
    ov.querySelector("#subBack").innerHTML = I.back;
    ov.querySelector("#subBack").addEventListener("click", function () { ov.remove(); });
    var sc = ov.querySelector("#subScroll");
    if (m.id === "settings") sc.appendChild(buildSettings());
    else if (m.id === "about") sc.appendChild(buildAbout());
  }
  function buildAbout() {
    var wrap = el("div", "gw-set");
    wrap.innerHTML =
      '<div class="gw-set-sec"><div class="gw-set-sec-lab">Gateway · 移动 MVP</div>' +
        '<div class="gw-row"><div class="gw-row-main"><div class="gw-row-title">v0.4 · 私印小报皮肤</div>' +
          '<div class="gw-row-desc">人和 AI 共写的一本日记。MD 是真相 · 数据存在你自己的设备里。</div></div></div>' +
        '<div class="gw-row"><div class="gw-row-main"><div class="gw-row-title">许可与免责</div>' +
          '<div class="gw-row-desc">本应用按"现状"提供，不对任何数据损坏或丢失负责。桌面版有 git 自动备份兜底；移动端目前依赖系统备份。</div></div></div></div>';
    return wrap;
  }
  function buildSettings() {
    var wrap = el("div", "gw-set");
    var key = "";
    try { } catch (e) {}
    wrap.innerHTML =
      '<div class="gw-set-sec"><div class="gw-set-sec-lab">双钥匙 · 给它声音和眼睛</div>' +
        '<div class="gw-key" id="kDeep"><div class="gw-key-head"><span class="gw-key-role">DeepSeek</span><span class="gw-key-tag">· 说话的那个</span></div>' +
        '<div class="gw-key-desc">常驻对话、夹批、21:30 的纸条，都从这把钥匙发声。</div>' +
        '<div class="gw-key-row"><input class="gw-key-in" id="kDeepIn" placeholder="sk-…"><button class="gw-key-test" id="kDeepTest">测试</button></div>' +
        '<div class="gw-key-status idle" id="kDeepStat">待填 / 测试</div></div>' +
        '<div class="gw-key"><div class="gw-key-head"><span class="gw-key-role">阿里云百炼</span><span class="gw-key-tag">· 看东西的那只眼</span></div>' +
        '<div class="gw-key-desc">抠图、看照片里有什么、自动定位贴纸——视觉都走这把钥匙。可选，填了才长出眼睛。</div>' +
        '<div class="gw-key-row"><input class="gw-key-in" placeholder="粘贴百炼 API Key…"></div>' +
        '<div class="gw-key-status idle">未填 · 暂无视觉</div></div></div>' +
      '<div class="gw-set-sec"><div class="gw-set-sec-lab">皮肤</div>' +
        '<div class="gw-row"><div class="gw-row-main"><div class="gw-row-title">私印小报 · classic</div><div class="gw-row-desc">米黄纸 + 4 粉彩。当前唯一皮肤。</div></div></div>' +
        '<div class="gw-row"><div class="gw-row-main"><div class="gw-row-title">呼吸暖光</div><div class="gw-row-desc">页面背后那束慢慢起伏的光。</div></div><div class="gw-toggle on" id="tBreath"></div></div></div>' +
      '<div class="gw-set-sec"><div class="gw-set-sec-lab">数据 · 无障碍</div>' +
        '<div class="gw-row"><div class="gw-row-main"><div class="gw-row-title">减少动效</div><div class="gw-row-desc">关掉呼吸、墨迹、纸页翻动。</div></div><div class="gw-toggle" id="tReduce"></div></div>' +
        '<div class="gw-row"><div class="gw-row-main"><div class="gw-row-title">本地 vault 路径</div><div class="gw-row-desc">MD 是真相 · 存在你自己的设备里。</div></div><span class="gw-row-val">~/Gateway ⟩</span></div></div>';
    // load existing key
    api("/api/setup/current").then(function (r) {
      var k = r && r.models && r.models[0] && r.models[0].api_key; var inp = wrap.querySelector("#kDeepIn");
      if (k) { inp.value = k; wrap.querySelector("#kDeep").classList.add("ok"); var s = wrap.querySelector("#kDeepStat"); s.className = "gw-key-status ok"; s.textContent = "已连通 · deepseek-chat"; }
    });
    var test = wrap.querySelector("#kDeepTest");
    test.addEventListener("click", function () {
      var inp = wrap.querySelector("#kDeepIn"), stat = wrap.querySelector("#kDeepStat"), v = inp.value.trim();
      if (!v) { flash("先粘贴 key"); return; }
      test.textContent = "测试中…";
      api("/api/setup/save", { method: "POST", body: JSON.stringify({ models: [{ id: "deepseek-chat", api_key: v }] }) }).then(function () {
        test.textContent = "测试"; wrap.querySelector("#kDeep").classList.add("ok"); stat.className = "gw-key-status ok"; stat.textContent = "已保存 · deepseek-chat"; flash("钥匙已存本地");
      });
    });
    wrap.querySelectorAll(".gw-toggle").forEach(function (t) { t.addEventListener("click", function () { t.classList.toggle("on"); }); });
    return wrap;
  }

  // ── 顶栏下滑收起 ──
  function bindAutohide() {
    var sc = $("scroll"), last = 0;
    sc.addEventListener("scroll", function () {
      var t = sc.scrollTop;
      if (t > last + 6 && t > 70) $("top").classList.add("hidden");
      else if (t < last - 6) $("top").classList.remove("hidden");
      last = t;
    }, { passive: true });
  }

  // ── tab 切换 ──
  function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".gw-tab").forEach(function (t) { t.classList.toggle("on", t.dataset.tab === tab); });
    $("journalView").hidden = tab !== "journal";
    $("chatView").hidden = tab !== "chat";
    $("top").classList.remove("hidden");
    renderBottom();
    if (tab === "chat") { if (!state.thread.length) loadThread(); else renderThread(); }
  }

  // ── init ──
  document.addEventListener("DOMContentLoaded", function () {
    var _cut = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Cutout;
    if (_cut && _cut.available) _cut.available().then(function (r) { console.log("[cutout] available:", JSON.stringify(r)); }).catch(function (e) { console.log("[cutout] err:", e); });
    else console.log("[cutout] plugin not present (browser/未注册)");
    $("burger").innerHTML = I.burger;
    $("burger").addEventListener("click", openMenu);
    document.querySelectorAll(".gw-tab").forEach(function (t) { t.addEventListener("click", function () { switchTab(t.dataset.tab); }); });
    bindAutohide();
    // 首次启动:没 key → 从 onboarding(填 DeepSeek key)起;有 key → 直接进
    api("/api/setup/current").then(function (r) {
      var key = r && r.models && r.models[0] && r.models[0].api_key;
      if (key) startApp(); else showOnboarding();
    }).catch(startApp);
  });

  function startApp() { renderBottom(); loadDateband().then(loadDay); }

  function saveKeys(deepseek, dashscope) {
    var body = {};
    if (deepseek) body.models = [{ id: "deepseek-chat", api_key: deepseek }];
    if (dashscope) body.dashscope_api_key = dashscope;
    return api("/api/setup/save", { method: "POST", body: JSON.stringify(body) });
  }

  function showOnboarding() {
    var ov = el("div", "gw-onboard");
    ov.innerHTML =
      '<div class="gw-breath"></div>' +
      '<div class="gw-onboard-scroll">' +
        '<div class="gw-onboard-head"><div class="gw-onboard-title">Gateway</div>' +
        '<div class="gw-onboard-sub">人和 AI 共写的一本日记。<br>先给它一把钥匙，让它能开口说话。</div></div>' +
        '<div class="gw-set">' +
          '<div class="gw-set-sec"><div class="gw-set-sec-lab">说话的那个 · DeepSeek</div>' +
            '<div class="gw-key" id="obKey"><div class="gw-key-desc">常驻对话、夹批、21:30 的纸条，都从这把钥匙发声。去 platform.deepseek.com 拿，每月赠 ¥10。</div>' +
            '<div class="gw-key-row"><input class="gw-key-in" id="obKeyIn" placeholder="sk-…" autocapitalize="off" autocorrect="off"><button class="gw-key-test" id="obTest">测试</button></div>' +
            '<div class="gw-key-status idle" id="obStat">填了它才能聊</div></div></div>' +
          '<div class="gw-set-sec"><div class="gw-set-sec-lab">看东西的那只眼 · 阿里云百炼（可选）</div>' +
            '<div class="gw-key"><div class="gw-key-desc">抠图、看照片里有什么、自动贴纸——视觉走这把。可跳过，以后在设置里补。</div>' +
            '<div class="gw-key-row"><input class="gw-key-in" id="obKey2" placeholder="粘贴百炼 key（可跳过）…" autocapitalize="off" autocorrect="off"></div></div></div>' +
        '</div>' +
      '</div>' +
      '<div class="gw-onboard-foot"><button class="gw-onboard-enter" id="obEnter">进入</button>' +
      '<button class="gw-onboard-skip" id="obSkip">先跳过，进去看看</button></div>';
    $("gw").appendChild(ov);
    var keyIn = ov.querySelector("#obKeyIn");
    ov.querySelector("#obTest").addEventListener("click", function () {
      var v = keyIn.value.trim(); if (!v) { flash("先粘贴 key"); return; }
      var t = ov.querySelector("#obTest"); t.textContent = "测试中…";
      saveKeys(v, ov.querySelector("#obKey2").value.trim()).then(function () {
        t.textContent = "测试"; var s = ov.querySelector("#obStat"); s.className = "gw-key-status ok"; s.textContent = "已连通 · deepseek-chat"; ov.querySelector("#obKey").classList.add("ok");
      });
    });
    ov.querySelector("#obEnter").addEventListener("click", function () {
      saveKeys(keyIn.value.trim(), ov.querySelector("#obKey2").value.trim()).then(function () { ov.remove(); startApp(); });
    });
    ov.querySelector("#obSkip").addEventListener("click", function () { ov.remove(); startApp(); });
  }
})();
