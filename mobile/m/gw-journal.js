// gw-journal.js — 时间线 + 5 套写操作习语(交付 #4)
// ① tap→openCard 编辑 ② 长按→纸感 action sheet ③ 左滑→撕痕删除 ④ 撤回纸条 ⑤ 悬浮提笔→openCard 新建
(function () {
  'use strict';
  const GW = window.GW;
  const LP_MS = 480, SWIPE_TRIG = 60;
  // anchor_time 容错归一:AI/桌面可能给 '9:00' / '21：30',entry.time 是补零半角 '09:00'
  const normT = (t) => String(t || '').replace('：', ':').split(':').map((x) => x.padStart(2, '0')).join(':');

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
    // ★ Android System WebView:开模态那下 tap 会 bleed 一个 pointerdown 到刚渲染的 scrim → 秒关
    //   (iOS WKWebView 无此问题)。延迟挂监听,忽略开场 ~450ms 内的杂散事件(对真用户点空白关无害)。
    setTimeout(function () { scrim.addEventListener('pointerdown', close); }, 450);
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
    wrap.dataset.time = entry.time;  // 贴纸拖完按落点找挂点(inferAnchor)用
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
    // ★ scrapbook 贴纸:anchor_time 命中本块 → float:right 浮一张,正文文字绕图(对照 PC paper renderStickers)
    const stickers = (GW.scrapbook || []).filter((s) => normT(s.anchor_time) === normT(entry.time) && s.src);
    if (stickers.length) {
      const body = row.querySelector('.gw-entry-body');
      stickers.forEach((s) => {
        const fig = document.createElement('figure');
        fig.className = 'gw-sticker landing';
        fig.style.width = Math.max(24, Math.min(48, (s.size_pct || 18) * 1.6)) + '%';
        fig.style.setProperty('--rot', (s.rotation || 1.5) + 'deg');
        fig.dataset.skId = s.id;
        fig.innerHTML = `<img src="${GW.esc(s.src)}" alt="">`;  // esc:防 src 属性注入(防御纵深)
        if (body) body.insertBefore(fig, body.firstChild);
        setTimeout(() => fig.classList.remove('landing'), 760);
        GW.bindStickerEdit(fig, s);  // Phase3:长按→拖拽/缩放/删除
      });
    }
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
        // 滑动删除已移除(整页滑动切 tab 后误删率高,用户拍板)— 删除走长按 sheet
        mode = 'scroll';
      }
    });
    function up(e) {
      clearLp(); row.classList.remove('lp-arming');
      if (mode === null) { /* tap */
        // 正文里的外链归外链 handler(开系统浏览器);tap 手势走 pointer 事件,
        // click 上的 preventDefault 拦不住这里 — 不让点链接同时弹编辑卡
        const a = e && e.target && e.target.closest && e.target.closest('a[href]');
        if (a && /^https?:\/\//i.test(a.getAttribute('href') || '')) return;
        if (!st.readonly) GW.openCard({ entry: entry, st: st });
      }
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
      <button class="gw-sheet-item" data-act="del"><span class="glyph">删</span>删除</button>
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
        else if (act === 'del') GW.deleteEntry(entry, st);
        else if (act === 'point') { GW.bus.emit('point', entry); }
        else if (act === 'append') GW.openCard({ entry: entry, st: st, append: true });
        else if (act === 'sticker') GW.whisper('选张图贴上来…', true);
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
      <button class="gw-sheet-item" data-act="icon"><span class="glyph">${I.sticker}</span>换图标</button>
      <button class="gw-sheet-item"><span class="glyph">${I.settings}</span>改每天几粒 / 一瓶几粒</button>
      <button class="gw-sheet-item"><span class="glyph">${I.layers}</span>看本周完成率</button>
      <button class="gw-sheet-item danger"><span class="glyph">${I.trash_no}</span>删除这项</button>
      <button class="gw-sheet-soft" data-act="want">想要新打卡项 · 跟 AI 商量 →</button>`;
    const m = GW.mountModal(sheet);
    sheet.addEventListener('click', (e) => {
      const soft = e.target.closest('.gw-sheet-soft');
      const item = e.target.closest('.gw-sheet-item');
      if (soft) { m.close(); setTimeout(() => GW.bus.emit('wantNewTask'), 320); }
      else if (item && item.dataset.act === 'icon') { m.close(); setTimeout(() => GW.setTaskIcon(task), 320); }
      else if (item) { m.close(); setTimeout(() => GW.whisper('（demo）改剂量 / 完成率 / 删除 待接(Phase 3)', false), 320); }
    });
  };

  /* ★招牌:换图标 — 取图 → 端侧抠图(iOS 17+ Vision)→ /api/cutout(顺带 OCR 颗数 + 写图标)→ 重画 chip */
  GW.setTaskIcon = async function (task) {
    const dataUrl = await GW.pickPhotoVia();
    if (!dataUrl) return;                       // 用户取消
    GW.whisper('处理中…', true);            // 等待禁 spinner,用文字
    let icon = dataUrl;
    try {
      const C = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Cutout;
      if (C && C.cutout) { const r = await C.cutout({ image: dataUrl }); if (r && r.png) icon = r.png; }
    } catch (e) { /* 抠图失败(非 iOS17 / 无主体)→ 原图兜底 */ }
    let ok = false, pill = null;
    try {
      const resp = await fetch('/api/cutout', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_name: task.name, image: icon }),
      });
      const j = await resp.json().catch(() => ({}));
      ok = resp.ok && j && j.ok !== false;
      pill = j && j.ocr_pill_count;
    } catch (e) { /* 网络/解析失败 → ok 留 false */ }
    if (ok) {
      task.image_url = icon;                    // 乐观更新 → 立即重画
      GW.bus.emit('reloadCare');
      GW.whisper(pill ? `图标贴好了 · 顺手认出 ${pill} 粒` : '图标贴好了 · ' + task.name, false);
    } else {
      GW.whisper('设图标没成,稍后再试', false);
    }
  };

  /* ════ Phase3 scrapbook 贴纸编辑态:长按→拖拽/缩放/删除(对照 PC sb-wrap pointer 交互)════
     触屏红线:长按先进编辑态(把拖拽跟滚动消歧),再拖;pointer 事件 touch 通用。           */
  function persistSticker(s, patch) {
    const b = Object.assign({ id: s.id }, patch);
    if (GW.scrapbookDate) b.date = GW.scrapbookDate;
    window.fetch('/api/scrapbook/upsert', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).catch(() => {});
  }
  function deleteSticker(fig, s) {
    fig.classList.add('removing');                 // CSS:淡出 + 缩小
    let undone = false;
    const bar = document.createElement('div'); bar.className = 'gw-sk-undo';
    bar.innerHTML = '<span>贴纸已撕下</span><button type="button">撤回</button>';
    GW.root.appendChild(bar); void bar.offsetHeight; bar.classList.add('on');
    const cleanup = () => { bar.classList.remove('on'); setTimeout(() => bar.remove(), 300); };
    bar.querySelector('button').addEventListener('click', () => { undone = true; fig.classList.remove('removing'); cleanup(); });
    setTimeout(() => {
      if (undone) return;
      cleanup(); fig.remove();
      GW.scrapbook = (GW.scrapbook || []).filter((x) => x.id !== s.id);
      const b = { id: s.id }; if (GW.scrapbookDate) b.date = GW.scrapbookDate;
      window.fetch('/api/scrapbook/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).catch(() => {});
    }, 3000);
  }
  GW.bindStickerEdit = function (fig, s) {
    let lpTimer = null, editing = false;
    const cancelLP = () => { if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; } };
    // stopPropagation:贴纸自己消化长按手势,不让 entry 的长按(action sheet)也触发
    fig.addEventListener('pointerdown', (e) => { e.stopPropagation(); if (!editing) lpTimer = setTimeout(enterEdit, LP_MS); });
    fig.addEventListener('pointerup', cancelLP);
    fig.addEventListener('pointercancel', cancelLP);
    fig.addEventListener('pointermove', cancelLP);  // 拖动中(滚动/误触)取消长按

    function enterEdit() {
      if (editing) return; editing = true;
      const body = fig.parentElement;
      body.style.position = 'relative';
      const bRect = body.getBoundingClientRect(), fRect = fig.getBoundingClientRect();
      fig.style.cssFloat = 'none';
      fig.style.position = 'absolute';
      fig.style.left = Math.max(0, fRect.left - bRect.left) + 'px';
      fig.style.top = Math.max(0, fRect.top - bRect.top) + 'px';
      fig.classList.add('editing');
      const del = document.createElement('button'); del.className = 'gw-sk-del'; del.type = 'button'; del.textContent = '×'; del.setAttribute('aria-label', '删除贴纸');
      const scl = document.createElement('button'); scl.className = 'gw-sk-scale'; scl.type = 'button'; scl.textContent = '⤡'; scl.setAttribute('aria-label', '缩放贴纸');
      const rot = document.createElement('button'); rot.className = 'gw-sk-rot'; rot.type = 'button'; rot.textContent = '⟳'; rot.setAttribute('aria-label', '旋转贴纸');
      fig.appendChild(del); fig.appendChild(scl); fig.appendChild(rot);
      if (GW.whisper) GW.whisper('编辑贴纸 · 拖移位 · ⤡缩放 · ⟳旋转 · ×撕下', false);
      bindDrag(); bindScale(scl); bindRotate(rot);
      del.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); exitEdit(); deleteSticker(fig, s); });
      const exit = (e) => { if (!fig.contains(e.target)) { exitEdit(); document.removeEventListener('pointerdown', exit, true); } };
      setTimeout(() => document.addEventListener('pointerdown', exit, true), 60);
    }
    function exitEdit() {
      if (!editing) return; editing = false;
      fig.classList.remove('editing');
      fig.querySelectorAll('.gw-sk-del,.gw-sk-scale').forEach((h) => h.remove());
    }
    function bindDrag() {
      let dragging = false, sx, sy, sl, st;
      fig.addEventListener('pointerdown', (e) => {
        if (!editing || e.target.classList.contains('gw-sk-del') || e.target.classList.contains('gw-sk-scale')) return;
        e.preventDefault();
        dragging = true; sx = e.clientX; sy = e.clientY;
        sl = parseFloat(fig.style.left) || 0; st = parseFloat(fig.style.top) || 0;
        try { fig.setPointerCapture(e.pointerId); } catch (err) {}
        fig.classList.add('dragging');
      });
      fig.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        fig.style.left = (sl + e.clientX - sx) + 'px';
        fig.style.top = Math.max(0, st + e.clientY - sy) + 'px';
      });
      fig.addEventListener('pointerup', (e) => {
        if (!dragging) return; dragging = false;
        try { fig.releasePointerCapture(e.pointerId); } catch (err) {}
        fig.classList.remove('dragging');
        const bw = (fig.parentElement.getBoundingClientRect().width) || 1;
        s.x_pct = Math.round(Math.max(0, Math.min(85, (parseFloat(fig.style.left) / bw) * 100)) * 10) / 10;
        s.y_px = Math.round(Math.max(0, parseFloat(fig.style.top) || 0));
        s.auto_y = false;
        // 拖完按落点找挂点(对照 PC inferAnchorByY):贴纸中心落进别的 entry → 换 anchor 真搬家
        const fr = fig.getBoundingClientRect();
        const cy = fr.top + fr.height / 2;
        let hit = null;
        document.querySelectorAll('.gw-entry-wrap').forEach((w) => {
          const r = w.getBoundingClientRect();
          if (cy >= r.top && cy <= r.bottom) hit = w;
        });
        const t = hit && hit.dataset.time;
        if (t && normT(t) !== normT(s.anchor_time)) {
          s.anchor_time = t;
          persistSticker(s, { x_pct: s.x_pct, y_px: s.y_px, anchor_time: t });
          if (GW.whisper) GW.whisper('贴到 ' + t + ' 那块了', false);
          exitEdit();
          GW.bus.emit('reloadDay');
        } else {
          persistSticker(s, { x_pct: s.x_pct, y_px: s.y_px });
        }
      });
    }
    function bindRotate(handle) {
      // 照抄 PC bindRotate(atan2 圆周拖):绕贴纸中心转,松手落 rotation
      let rotating = false, cx0, cy0, startA, startRot;
      handle.addEventListener('pointerdown', (e) => {
        e.preventDefault(); e.stopPropagation();
        rotating = true;
        const r = fig.getBoundingClientRect();
        cx0 = r.left + r.width / 2; cy0 = r.top + r.height / 2;
        startA = Math.atan2(e.clientY - cy0, e.clientX - cx0);
        startRot = s.rotation || 0;
        try { handle.setPointerCapture(e.pointerId); } catch (err) {}
      });
      handle.addEventListener('pointermove', (e) => {
        if (!rotating) return; e.preventDefault();
        const a = Math.atan2(e.clientY - cy0, e.clientX - cx0);
        s.rotation = Math.round((startRot + (a - startA) * 180 / Math.PI) * 10) / 10;
        fig.style.setProperty('--rot', s.rotation + 'deg');
      });
      handle.addEventListener('pointerup', (e) => {
        if (!rotating) return; rotating = false;
        try { handle.releasePointerCapture(e.pointerId); } catch (err) {}
        persistSticker(s, { rotation: s.rotation });
      });
    }
    function bindScale(handle) {
      let scaling = false, sx, sw;
      handle.addEventListener('pointerdown', (e) => {
        e.preventDefault(); e.stopPropagation();
        scaling = true; sx = e.clientX; sw = fig.getBoundingClientRect().width;
        try { handle.setPointerCapture(e.pointerId); } catch (err) {}
      });
      handle.addEventListener('pointermove', (e) => {
        if (!scaling) return; e.preventDefault();
        const bw = (fig.parentElement.getBoundingClientRect().width) || 1;
        const newW = Math.max(40, Math.min(bw * 0.9, sw + (e.clientX - sx)));
        fig.style.width = Math.max(15, Math.min(90, (newW / bw) * 100)) + '%';
      });
      handle.addEventListener('pointerup', (e) => {
        if (!scaling) return; scaling = false;
        try { handle.releasePointerCapture(e.pointerId); } catch (err) {}
        const bw = (fig.parentElement.getBoundingClientRect().width) || 1;
        const widthPct = Math.max(15, Math.min(90, (fig.getBoundingClientRect().width / bw) * 100));
        s.size_pct = Math.round((widthPct / 1.6) * 10) / 10;  // 逆 Phase1 render 映射(width%=size_pct*1.6)
        persistSticker(s, { size_pct: s.size_pct });
      });
    }
  };
})();
