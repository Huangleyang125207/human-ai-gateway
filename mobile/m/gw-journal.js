// gw-journal.js — 时间线 + 5 套写操作习语(交付 #4)
// ① tap→openCard 编辑 ② 长按→纸感 action sheet ③ 左滑→撕痕删除 ④ 撤回纸条 ⑤ 悬浮提笔→openCard 新建
(function () {
  'use strict';
  const GW = window.GW;
  const LP_MS = 480, SWIPE_TRIG = 60;

  /* ── 通用模态:scrim + sheet 升起(纸感,可下滑/点空白关)── */
  GW.mountModal = function (sheetEl, opts) {
    opts = opts || {};
    const root = GW.root;
    const scrim = document.createElement('div'); scrim.className = 'gw-scrim';
    root.appendChild(scrim); root.appendChild(sheetEl);
    // 强制 reflow 触发过渡(rAF 在截图/后台环境会被节流,不可靠)
    void sheetEl.offsetHeight; void scrim.offsetHeight;
    scrim.classList.add('on'); sheetEl.classList.add('on');
    let closed = false;
    function close() {
      if (closed) return; closed = true;
      scrim.classList.remove('on'); sheetEl.classList.remove('on');
      setTimeout(() => { scrim.remove(); sheetEl.remove(); opts.onClose && opts.onClose(); }, 460);
    }
    scrim.addEventListener('pointerdown', close);
    // 下滑关(sheet 顶部抓手区)
    const grip = sheetEl.querySelector('.gw-grip');
    if (grip) {
      let sy = null;
      grip.parentElement.addEventListener('pointerdown', (e) => { sy = e.clientY; });
      grip.parentElement.addEventListener('pointermove', (e) => { if (sy != null && e.clientY - sy > 50) { sy = null; close(); } });
      grip.parentElement.addEventListener('pointerup', () => { sy = null; });
    }
    return { close, scrim, sheet: sheetEl };
  };

  /* ════ 时间线 ════ */
  GW.renderTimeline = function (container, st) {
    container.innerHTML = '';
    const entries = (GW.journal[st.dayKey] || []).filter((e) => !e.isNote).slice().sort((a, b) => a.time.localeCompare(b.time));
    if (!entries.length) {
      container.innerHTML = `<div class="gw-empty"><b>这一天还是空白</b>提笔写下第一块，<br>或滑日期带到今天落一张骨架。</div>`;
      return;
    }
    entries.forEach((entry) => container.appendChild(buildEntry(entry, st)));
  };

  function buildEntry(entry, st) {
    const wrap = document.createElement('div'); wrap.className = 'gw-entry-wrap';
    const del = document.createElement('div'); del.className = 'gw-entry-del'; del.innerHTML = '<span>松手 · 收纸</span>';
    const row = document.createElement('div'); row.className = 'gw-entry' + (entry.struck ? ' struck' : '');
    const tagsHtml = (entry.tags || []).map((t) => `<span class="gw-entry-tag">${GW.esc(t)}</span>`).join('') + (entry.author ? `<span class="gw-entry-author">${GW.esc(entry.author)}</span>` : '');
    let bodyHtml = GW.gatewayMd(entry.body);
    if (entry.dropcap) bodyHtml = bodyHtml.replace(/^<p>(.)/, '<p><span class="dropcap">$1</span>');
    const commits = (entry.commits || []).map((c) => `<div class="gw-commit ${c.who}"><span class="gw-seal">${c.who === 'ai' ? '批' : '我'}</span><span class="gw-commit-text">${GW.esc(c.text)}</span></div>`).join('');
    row.innerHTML = `<div class="gw-lp-hint"></div>
      <div class="gw-entry-time"><div class="hh">${entry.time.split(':')[0]}</div><div class="mm">${entry.time.split(':')[1]}</div></div>
      <div class="gw-entry-main">
        <div class="gw-entry-tags">${tagsHtml}</div>
        ${entry.title ? `<div class="gw-entry-title">${GW.esc(entry.title)}</div>` : ''}
        <div class="gw-entry-body">${bodyHtml}</div>
        ${commits}
      </div>`;
    wrap.appendChild(del); wrap.appendChild(row);
    if (!st.readonly) wireEntryGestures(row, wrap, entry, st);
    return wrap;
  }

  /* ── 手势:tap 编辑 / 长按 sheet / 左滑删 ── */
  function wireEntryGestures(row, wrap, entry, st) {
    let dx = 0, dragging = false, mode = null, lpTimer = null, downX = 0, downY = 0;
    function clearLp() { if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; } }
    row.addEventListener('pointerdown', (e) => {
      if (e.button === 2) return;
      downX = e.clientX; downY = e.clientY; mode = null; dx = 0;
      row.classList.add('lp-arming');
      lpTimer = setTimeout(() => {
        if (mode === null) { mode = 'lp'; row.classList.remove('lp-arming'); row.classList.add('longpress'); haptic(); GW.openEntrySheet(entry, st); setTimeout(() => row.classList.remove('longpress'), 300); }
      }, LP_MS);
    });
    row.addEventListener('pointermove', (e) => {
      const adx = e.clientX - downX, ady = e.clientY - downY;
      if (mode === null && (Math.abs(adx) > 8 || Math.abs(ady) > 8)) {
        clearLp(); row.classList.remove('lp-arming');
        if (Math.abs(adx) > Math.abs(ady) && adx < 0) { mode = 'swipe'; dragging = true; row.classList.add('dragging'); try { row.setPointerCapture(e.pointerId); } catch (x) {} }
        else mode = 'scroll';
      }
      if (mode === 'swipe') { dx = Math.max(-96, Math.min(0, adx)); row.style.transform = `translateX(${dx}px)`; }
    });
    function up() {
      clearLp(); row.classList.remove('lp-arming');
      if (mode === 'swipe') {
        dragging = false; row.classList.remove('dragging');
        if (dx < -SWIPE_TRIG) { row.style.transform = `translateX(-110%)`; setTimeout(() => GW.deleteEntry(entry, st), 220); }
        else { row.style.transform = ''; }
      } else if (mode === null) { /* tap */ if (!st.readonly) GW.openCard({ entry: entry, st: st }); }
    }
    row.addEventListener('pointerup', up); row.addEventListener('pointercancel', up);
    row.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  function haptic() { try { navigator.vibrate && navigator.vibrate(12); } catch (e) {} } // iOS 走 Capacitor Haptics

  /* ════ ② 长按 action sheet(纸感便签,非 iOS 圆角白卡)════ */
  GW.openEntrySheet = function (entry, st) {
    const sheet = document.createElement('div'); sheet.className = 'gw-sheet';
    const I = GW.ICON;
    const hasTask = false; // 仅当这块含打卡时长出"管理 daily-task"
    sheet.innerHTML = `<div class="gw-grip"></div>
      <div class="gw-sheet-head">${entry.time} · ${GW.esc((entry.tags || [])[0] || '')}<span class="sub">这块要做点什么</span></div>
      <button class="gw-sheet-item" data-act="edit"><span class="glyph">${I.edit}</span>改一块</button>
      <button class="gw-sheet-item" data-act="append"><span class="glyph">${I.append}</span>加内容</button>
      <button class="gw-sheet-item" data-act="strike"><span class="glyph">${I.strike}</span>${entry.struck ? '撤销划掉' : '划掉收纸'}</button>
      <button class="gw-sheet-item" data-act="sticker"><span class="glyph">${I.sticker}</span>贴张图</button>
      <button class="gw-sheet-item" data-act="point"><span class="glyph ai-mark">${I.point}</span>指给 AI 看 <span class="ai-mark" style="margin-left:4px">✦</span></button>
      ${hasTask ? `<button class="gw-sheet-item" data-act="task"><span class="glyph">${I.pill}</span>管理打卡项</button>` : ''}`;
    const m = GW.mountModal(sheet);
    sheet.addEventListener('click', (e) => {
      const b = e.target.closest('.gw-sheet-item'); if (!b) return;
      const act = b.dataset.act; m.close();
      setTimeout(() => {
        if (act === 'edit') GW.openCard({ entry: entry, st: st });
        else if (act === 'strike') { entry.struck = !entry.struck; GW.bus.emit('reloadDay'); GW.whisper(entry.struck ? '已划掉收纸 · 痕迹留着' : '划痕已抹去'); }
        else if (act === 'point') { GW.bus.emit('point', entry); }
        else if (act === 'append') GW.openCard({ entry: entry, st: st, append: true });
        else if (act === 'sticker') GW.whisper('选张图贴上来…（端侧抠图）', true);
      }, 320);
    });
  };

  /* ════ ③+④ 删除 + 撤回纸条 ════ */
  let undoNode = null, undoTimer = null;
  GW.deleteEntry = function (entry, st) {
    const arr = GW.journal[st.dayKey] || [];
    const idx = arr.indexOf(entry);
    if (idx >= 0) arr.splice(idx, 1);
    GW.bus.emit('reloadDay');
    showUndo(entry, st, idx);
  };
  function showUndo(entry, st, idx) {
    if (undoNode) { clearTimeout(undoTimer); undoNode.remove(); }
    const n = document.createElement('div'); n.className = 'gw-undo';
    n.innerHTML = `<span class="gw-undo-msg">已删除「<b>${GW.esc(entry.title || entry.body.slice(0, 10))}</b>」</span>
      <button class="gw-undo-btn">撤回</button><span class="gw-undo-bar" style="animation:gw-undobar 5s linear forwards"></span>`;
    GW.root.appendChild(n); undoNode = n;
    void n.offsetHeight; n.classList.add('on');
    n.querySelector('.gw-undo-btn').addEventListener('click', () => {
      const arr = GW.journal[st.dayKey] || []; arr.splice(Math.min(idx, arr.length), 0, entry);
      GW.bus.emit('reloadDay'); hideUndo();
    });
    undoTimer = setTimeout(hideUndo, 5000);
  }
  function hideUndo() { if (!undoNode) return; undoNode.classList.remove('on'); const n = undoNode; undoNode = null; setTimeout(() => n.remove(), 240); }

  /* ════ ⑤ openCard 编辑器(底部升起信笺;新建 / 编辑两 mode)════ */
  GW.openCard = function (o) {
    o = o || {}; const st = o.st; const editing = !!o.entry; const ent = o.entry || {};
    const now = new Date();
    let picked = new Set(editing ? (ent.tags || []) : ['#gateway']);
    let hh = editing ? ent.time.split(':')[0] : String(now.getHours()).padStart(2, '0');
    let mm = editing ? ent.time.split(':')[1] : (now.getMinutes() < 30 ? '00' : '30');
    const sheet = document.createElement('div'); sheet.className = 'gw-card';
    const kicker = o.append ? '加一段 · 接着写' : editing ? '改这一块' : '提笔 · 写一块';
    sheet.innerHTML = `
      <div class="gw-card-head"><span class="gw-card-kicker">${kicker}</span><button class="gw-card-x">×</button></div>
      <div class="gw-card-scroll">
        <div class="gw-field"><div class="gw-field-lab"># 标签</div><div class="gw-chips"></div></div>
        <div class="gw-field"><div class="gw-field-lab">时间块 · 半小时</div>
          <div class="gw-time-row">
            <input class="gw-time-in hh" inputmode="numeric" maxlength="2" value="${hh}" ${editing ? 'readonly' : ''}>
            <span class="gw-time-colon">:</span>
            <input class="gw-time-in mm" inputmode="numeric" maxlength="2" value="${mm}" ${editing ? 'readonly' : ''}>
            ${editing ? '' : `<div class="gw-time-quick"><button data-q="now">现在</button><button data-q="00">整点</button><button data-q="30">半</button></div>`}
          </div>
        </div>
        <div class="gw-field" style="margin-bottom:8px"><div class="gw-field-lab">正文</div>
          <input class="gw-title-in" placeholder="标题（可选）" value="${editing && ent.title ? GW.esc(ent.title) : ''}">
          <textarea class="gw-body-in" placeholder="此刻在想什么…">${editing && !o.append ? GW.esc(ent.body || '') : ''}</textarea>
        </div>
      </div>
      <div class="gw-card-foot">
        <button class="gw-card-attach">${GW.ICON.attach} 贴张图</button>
        <button class="gw-save">${editing ? '改完' : '落笔'}</button>
      </div>`;
    const chipsBox = sheet.querySelector('.gw-chips');
    function paintChips() {
      chipsBox.innerHTML = '';
      const all = GW.SUGGEST_TAGS.slice();
      picked.forEach((t) => { if (all.indexOf(t) < 0) all.push(t); });
      all.forEach((t) => { const c = document.createElement('button'); c.className = 'gw-chip' + (picked.has(t) ? ' on' : ''); c.textContent = t; c.addEventListener('click', () => { picked.has(t) ? picked.delete(t) : picked.add(t); paintChips(); }); chipsBox.appendChild(c); });
      const add = document.createElement('button'); add.className = 'gw-chip add'; add.textContent = '+ 新标签';
      add.addEventListener('click', () => {
        const inp = document.createElement('input'); inp.className = 'gw-chip-input'; inp.placeholder = '标签…';
        add.replaceWith(inp); inp.focus();
        const commit = () => { let v = inp.value.trim(); if (v && v[0] !== '#') v = '#' + v; if (v) picked.add(v); paintChips(); };
        inp.addEventListener('blur', commit); inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') commit(); });
      });
      chipsBox.appendChild(add);
    }
    paintChips();
    const m = GW.mountModal(sheet);
    sheet.querySelector('.gw-card-x').addEventListener('click', m.close);
    const hhIn = sheet.querySelector('.hh'), mmIn = sheet.querySelector('.mm');
    [hhIn, mmIn].forEach((i) => i.addEventListener('input', () => { i.value = i.value.replace(/\D/g, ''); }));
    sheet.querySelectorAll('.gw-time-quick button').forEach((b) => b.addEventListener('click', () => {
      const q = b.dataset.q;
      if (q === 'now') { const d = new Date(); hhIn.value = String(d.getHours()).padStart(2, '0'); mmIn.value = d.getMinutes() < 30 ? '00' : '30'; }
      else mmIn.value = q;
    }));
    sheet.querySelector('.gw-card-attach').addEventListener('click', () => GW.whisper('选张图贴进正文…', false));
    sheet.querySelector('.gw-save').addEventListener('click', () => {
      const title = sheet.querySelector('.gw-title-in').value.trim();
      const body = sheet.querySelector('.gw-body-in').value.trim();
      const time = `${(hhIn.value || '00').padStart(2, '0')}:${(mmIn.value || '00').padStart(2, '0')}`;
      const tags = Array.from(picked);
      if (editing) {
        if (o.append) { ent.body = (ent.body || '') + (body ? '\n\n' + body : ''); }
        else { ent.tags = tags; ent.title = title; ent.body = body || ent.body; }
      } else {
        (GW.journal[st.dayKey] = GW.journal[st.dayKey] || []).push({ id: 'n' + Date.now(), time: time, tags: tags.length ? tags : ['#杂'], author: '@我', title: title, body: body || '（空白条目）' });
      }
      m.close(); GW.bus.emit('reloadDay'); GW.whisper(editing ? '改好了 · 写进 ' + (editing ? ent.time : time) : '已落笔 · 写进 ' + time);
    });
  };

  /* ════ 打卡管理 sheet(长按 chip)════ */
  GW.openTaskSheet = function (task) {
    haptic();
    const sheet = document.createElement('div'); sheet.className = 'gw-sheet'; const I = GW.ICON;
    sheet.innerHTML = `<div class="gw-grip"></div>
      <div class="gw-sheet-head">${GW.esc(task.name)}<span class="sub">${task.daily_dose >= 2 ? '每天 ' + task.daily_dose + ' 粒' : ''}${task.days_left != null ? ' · 还能吃 ' + task.days_left + ' 天' : ''}</span></div>
      <button class="gw-sheet-item"><span class="glyph">${I.sticker}</span>换图标</button>
      <button class="gw-sheet-item"><span class="glyph">${I.settings}</span>改每天几粒 / 一瓶几粒</button>
      <button class="gw-sheet-item"><span class="glyph">${I.layers}</span>看本周完成率</button>
      <button class="gw-sheet-item danger"><span class="glyph">${I.trash_no}</span>删除这项</button>
      <button class="gw-sheet-soft" data-act="want">想要新打卡项 · 跟 AI 商量 →</button>`;
    const m = GW.mountModal(sheet);
    sheet.addEventListener('click', (e) => {
      const soft = e.target.closest('.gw-sheet-soft');
      const item = e.target.closest('.gw-sheet-item');
      if (soft) { m.close(); setTimeout(() => GW.bus.emit('wantNewTask'), 320); }
      else if (item) { m.close(); setTimeout(() => GW.whisper('（demo）这一项接 daily-task API', false), 320); }
    });
  };
})();
