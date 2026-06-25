// gw-widgets.js — 关怀区 4 widget(交付 #2):八杯水 · 今日打卡 · 今日 PULSE · 今天心情
// 竖向小报栏目,不卡片化。各 widget 读写 GW.state,自管 DOM + 手势。
(function () {
  'use strict';
  const GW = window.GW;
  const LP_MS = 480; // 长按阈值(与桌面肌肉记忆一致)

  /* ── 杯子 SVG(钢笔速写;水裹在 .water 里以便倒水动画)── */
  function cupSVG(filled, idx, scope) {
    const cid = scope + '-clip-' + idx;
    const waterH = 15;
    const water = filled
      ? `<g class="water" clip-path="url(#${cid})"><rect x="3" y="${36 - waterH}" width="16" height="${waterH + 2}" fill="var(--fill-water)"/><path d="M3 ${37 - waterH} q4 -2 8 0 t8 0" fill="none" stroke="var(--fill-water)" stroke-width="1.6" opacity="0.7"/></g>`
      : '';
    const glassPath = 'M4 4 L18 4 L16.4 34 Q16.2 36 14.4 36 L7.6 36 Q5.8 36 5.6 34 Z';
    return `<svg viewBox="0 0 22 38" preserveAspectRatio="none">
      <defs><clipPath id="${cid}"><path d="${glassPath}"/></clipPath></defs>
      ${water}
      <path d="${glassPath}" fill="none" stroke="${filled ? 'var(--ink-soft)' : 'var(--ink-faint)'}" stroke-width="1.3" stroke-linejoin="round"/>
    </svg>`;
  }

  /* ════ 八杯水 ════ */
  function renderCups(host, st, scope) {
    const N = 8;
    const block = el('div', 'gw-care-block' + (st.readonly ? ' readonly' : ''));
    block.innerHTML =
      `<div class="gw-care-label">八杯水 <span class="whisper">${st.readonly ? '历史日只读' : '睡前一抹点亮'}</span></div>
       <div class="gw-cups"></div>
       <div class="gw-cups-foot"><b>${st.water}</b> / ${N} 杯 · <span class="hint"></span></div>`;
    const row = block.querySelector('.gw-cups');
    const foot = block.querySelector('.gw-cups-foot');
    let justIdx = -1, focusIdx = -1;
    function paint() {
      row.innerHTML = '';
      for (let i = 0; i < N; i++) {
        const cup = el('div', 'gw-cup' + (i === focusIdx ? ' focus' : (Math.abs(i - focusIdx) === 1 && focusIdx >= 0 ? ' near' : '')) + (i === justIdx ? ' just' : ''));
        cup.innerHTML = cupSVG(i < st.water, i, scope);
        row.appendChild(cup);
      }
      foot.querySelector('b').textContent = st.water;
      foot.querySelector('.hint').textContent = st.readonly ? '' : (st.water >= N ? '今天喝够了' : `还差 ${N - st.water} 杯`);
    }
    function idxAt(clientX) {
      const cups = row.querySelectorAll('.gw-cup'); let best = -1, bd = 1e9;
      cups.forEach((c, i) => { const r = c.getBoundingClientRect(); const d = Math.abs(clientX - (r.left + r.width / 2)); if (d < bd) { bd = d; best = i; } });
      return best;
    }
    function apply(clientX) {
      if (st.readonly) return;
      const i = idxAt(clientX); if (i < 0) return;
      focusIdx = i;
      if (i + 1 > st.water) justIdx = i;
      st.water = i + 1;
      paint();
    }
    if (!st.readonly) {
      row.addEventListener('pointerdown', (e) => { try { row.setPointerCapture(e.pointerId); } catch (x) {} apply(e.clientX); });
      row.addEventListener('pointermove', (e) => { if (row.hasPointerCapture && row.hasPointerCapture(e.pointerId)) apply(e.clientX); });
      const end = () => { focusIdx = -1; paint(); setTimeout(() => { justIdx = -1; paint(); }, 900); GW.bus.emit('pulse'); };
      row.addEventListener('pointerup', end); row.addEventListener('pointercancel', end);
    }
    paint();
    host.appendChild(block);
  }

  /* ════ 今日打卡 ════ */
  function renderTasks(host, st) {
    const block = el('div', 'gw-care-block' + (st.readonly ? ' readonly' : ''));
    block.innerHTML = `<div class="gw-care-label">今日打卡</div><div class="gw-tasks"></div>`;
    const row = block.querySelector('.gw-tasks');
    st.tasks.forEach((t) => {
      const done = t.today_intake >= t.daily_dose;
      const btn = el('button', 'gw-task' + (done ? ' done' : ''));
      const ring = done
        ? `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--umber)" stroke-width="1.4"/></svg>`
        : `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--line-strong)" stroke-width="1.2" stroke-dasharray="2 3"/></svg>`;
      const check = done ? `<svg class="gw-task-check" width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3.5 9.5 Q6 12 7.5 14 Q10 8 15 4" stroke="var(--vermilion)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>` : '';
      const badge = (t.days_left != null && t.days_left <= 3) ? `<span class="gw-task-badge">${t.days_left}d</span>` : '';
      const dose = t.daily_dose >= 2 ? `${t.today_intake}/${t.daily_dose}` : (done ? '✓' : '\u00a0');
      btn.innerHTML = `<span class="gw-task-disc">${ring}${check}${badge}<span class="gw-task-glyph">${t.glyph}</span></span>
        <span class="gw-task-name">${GW.esc(t.name)}</span><span class="gw-task-dose">${dose}</span>`;
      // tap = 打卡(clamp 0..dose)
      let lpTimer = null, moved = false, downXY = null;
      btn.addEventListener('pointerdown', (e) => { moved = false; downXY = [e.clientX, e.clientY]; lpTimer = setTimeout(() => { lpTimer = null; if (!moved) GW.openTaskSheet(t); }, LP_MS); });
      btn.addEventListener('pointermove', (e) => { if (downXY && (Math.abs(e.clientX - downXY[0]) > 8 || Math.abs(e.clientY - downXY[1]) > 8)) { moved = true; clearTimeout(lpTimer); lpTimer = null; } });
      btn.addEventListener('pointerup', () => {
        if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; if (!moved && !st.readonly) toggle(); }
      });
      function toggle() {
        if (t.today_intake >= t.daily_dose) t.today_intake = 0; else t.today_intake += 1;
        const nowDone = t.today_intake >= t.daily_dose;
        btn.classList.toggle('done', nowDone);
        if (nowDone) { btn.classList.add('confirm'); setTimeout(() => btn.classList.remove('confirm'), 520); }
        // 重画该 chip
        const disc = btn.querySelector('.gw-task-disc');
        disc.querySelector('.ring').outerHTML = nowDone
          ? `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--umber)" stroke-width="1.4"/></svg>`
          : `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--line-strong)" stroke-width="1.2" stroke-dasharray="2 3"/></svg>`;
        let chk = btn.querySelector('.gw-task-check'); if (chk) chk.remove();
        if (nowDone) disc.insertAdjacentHTML('afterbegin', `<svg class="gw-task-check" width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3.5 9.5 Q6 12 7.5 14 Q10 8 15 4" stroke="var(--vermilion)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`);
        btn.querySelector('.gw-task-dose').textContent = t.daily_dose >= 2 ? `${t.today_intake}/${t.daily_dose}` : (nowDone ? '✓' : '\u00a0');
        GW.bus.emit('pulse');
      }
      row.appendChild(btn);
    });
    host.appendChild(block);
  }

  /* ════ 今日 PULSE(一行小报,纯本地派生)════ */
  function renderPulse(host, st) {
    const done = st.tasks.filter((t) => t.today_intake >= t.daily_dose).length;
    const total = st.tasks.length;
    const entries = (GW.journal[st.dayKey] || []).filter((e) => !e.isNote && (e.title || e.body)).length;
    const full = done === total && st.water >= 8;
    const block = el('div', 'gw-care-block');
    block.dataset.pulse = '1';
    block.innerHTML = `<div class="gw-care-label">今日</div>
      <div class="gw-pulse${full ? ' full' : ''}">
        <span class="cell"><b>${done}</b>/${total} 打卡</span><span class="sep">·</span>
        <span class="cell"><b>${st.water}</b>/8 水</span><span class="sep">·</span>
        <span class="cell"><b>${entries}</b> 段</span><span class="sep">·</span>
        <span class="cell ${st.noteWritten ? '' : 'wait'}">21:30 ${st.noteWritten ? '已写' : '待写'}</span>
      </div>`;
    host.appendChild(block);
  }

  /* ════ 今天心情(单行 7 emoji,本机 only)════ */
  function renderMood(host, st) {
    const block = el('div', 'gw-care-block');
    block.innerHTML = `<div class="gw-care-label">今天心情 <span class="whisper">点一下选 · 不留档</span></div><div class="gw-moods"></div>`;
    const row = block.querySelector('.gw-moods');
    GW.MOODS.forEach((emo) => {
      const b = el('button', 'gw-mood' + (st.mood === emo ? ' on' : ''));
      b.textContent = emo;
      b.addEventListener('click', () => {
        st.mood = (st.mood === emo) ? null : emo;
        row.querySelectorAll('.gw-mood').forEach((m) => m.classList.remove('on'));
        if (st.mood) { b.classList.add('on'); }
        try { st.mood ? localStorage.setItem('gateway.mobile.setting/mood/' + st.dayKey, st.mood) : localStorage.removeItem('gateway.mobile.setting/mood/' + st.dayKey); } catch (e) {}
      });
      row.appendChild(b);
    });
    host.appendChild(block);
  }

  /* ════ 动态 widget(AI 装的)默认外观 ════ */
  function renderDyn(host, w, st, firstMount) {
    const block = el('div', 'gw-care-block gw-widget-dyn' + (firstMount ? ' first-mount' : ''));
    const vars = {
      tasks_done: st.tasks.filter((t) => t.today_intake >= t.daily_dose).length,
      tasks_total: st.tasks.length,
      water_filled: st.water,
      entries_count: (GW.journal[st.dayKey] || []).filter((e) => !e.isNote && (e.title || e.body)).length,
      date: st.dayKey,
      minutes_to_2130: 92,
      note_state: st.noteWritten ? '已写' : '待写',
    };
    const body = String(w.template).replace(/\{\{(\w+)\}\}/g, (_, k) => (k in vars ? GW.esc(vars[k] + '') : ''));
    block.innerHTML = `<div class="gw-care-label">${GW.esc(w.title)}</div><div class="gw-widget-body">${body}</div>`;
    host.appendChild(block);
  }

  /* ── 装配关怀区 ── */
  GW.renderCare = function (container, st) {
    container.innerHTML = '';
    renderCups(container, st, container.id || 'cups');
    renderTasks(container, st);
    if (st.enabled.indexOf('pulse') >= 0) renderPulse(container, st);
    if (st.enabled.indexOf('mood') >= 0) renderMood(container, st);
    (st.dynWidgets || []).forEach((w) => renderDyn(container, w, st, w._new));
  };
  GW.renderPulseInPlace = function (container, st) {
    const old = container.querySelector('[data-pulse]'); if (!old) return;
    const tmp = document.createElement('div'); renderPulse(tmp, st);
    old.replaceWith(tmp.firstElementChild);
  };

  function el(tag, cls) { const e = document.createElement(tag); if (cls) e.className = cls; return e; }
})();
