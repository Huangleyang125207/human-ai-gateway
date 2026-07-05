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
    // ★对照 PC ritual.js:有上传水杯图 → 渲真图(满=彩色/空=灰度);emoji 值不当 <img>
    const rawCup = (typeof GW !== 'undefined' && GW.cupImageUrl) || null;
    const cupImg = (rawCup && /^(data:|https?:|\/)/.test(rawCup)) ? rawCup : null;
    const block = el('div', 'gw-care-block' + (st.readonly ? ' readonly' : ''));
    block.innerHTML =
      `<div class="gw-care-label">八杯水 <span class="whisper">${st.readonly ? '历史日只读' : '睡前一抹点亮'}</span></div>
       <div class="gw-cups"><div class="gw-cups-strip"></div></div>
       <div class="gw-cups-foot"><b>${st.water}</b> / ${N} 杯 · <span class="hint"></span></div>`;
    const row = block.querySelector('.gw-cups');
    const strip = block.querySelector('.gw-cups-strip');
    const foot = block.querySelector('.gw-cups-foot');
    let justIdx = -1;
    function paintFoot() {
      foot.querySelector('b').textContent = st.water;
      foot.querySelector('.hint').textContent = st.readonly ? '' : (st.water >= N ? '今天喝够了' : `还差 ${N - st.water} 杯`);
    }
    function paint() {
      strip.innerHTML = '';
      for (let i = 0; i < N; i++) {
        const cupFilled = i < st.water;
        const cup = el('div', 'gw-cup' + (i === justIdx ? ' just' : '') + (cupImg ? ' with-image' : '') + (cupFilled ? ' filled' : ''));
        cup.innerHTML = cupImg ? `<img src="${cupImg}" alt="" draggable="false">` : cupSVG(cupFilled, i, scope);
        strip.appendChild(cup);
      }
      paintFoot();
    }
    function idxAt(clientX) {
      const cups = strip.querySelectorAll('.gw-cup'); let best = -1, bd = 1e9;
      cups.forEach((c, i) => { const r = c.getBoundingClientRect(); const d = Math.abs(clientX - (r.left + r.width / 2)); if (d < bd) { bd = d; best = i; } });
      return best;
    }
    if (!st.readonly) {
      // ★ 按住即放大(7.5 对齐拍板):pointerdown → 杯带原地长高、一屏 3 只、居中在按下的杯
      //   (快点一下 = 点亮到该杯,旧"一抹点亮"语义兼容);拖动 = 杯带 1:1 跟手滚动,
      //   过中心即点亮/回退(滚动位置=杯数);松手结算回缩。
      // dragging 标志门控 move,而非 hasPointerCapture —— 长按图标一旦触发原生拖拽会丢失指针捕获,
      // 之后 setPointerCapture 静默失败 → hasPointerCapture 恒 false → 滑动永久失灵(长按后锁死真因)。
      let dragging = false, zx0 = 0, off = 0, cupW = 1, rowW = 1;
      const VISIBLE = 5;
      const EASE_OUT = 'transform 0.28s cubic-bezier(0.22, 1, 0.36, 1)';
      const offFor = (i) => rowW / 2 - (i + 0.5) * cupW;
      const setStrip = (o) => { strip.style.transform = 'translateX(' + o + 'px)'; };
      // 中心杯夸张放大 + 邻杯阶梯(focus/near),点亮态同步
      function setEmphasis(centerIdx) {
        strip.querySelectorAll('.gw-cup').forEach((c, i) => {
          c.classList.toggle('focus', i === centerIdx);
          c.classList.toggle('near', Math.abs(i - centerIdx) === 1);
        });
      }
      function setLit(n) {
        if (n === st.water) return;
        if (n > st.water) justIdx = n - 1;
        st.water = n;
        strip.querySelectorAll('.gw-cup').forEach((c, i) => {
          c.classList.toggle('filled', i < n);
          c.classList.toggle('just', i === justIdx && i < n);
        });
        paintFoot();
      }
      // ★ 相对拖动映射(7.5 三修拍板):按哪都行 — 起点永远 = 当前水量那只杯(点按不改杯数);
      //   拖动是相对位移,整个 0→8 行程压缩在 SPAN(0.75 屏宽)内,不抬手可从头调到尾;
      //   手指位移经 step 齿轮比驱动杯带(视觉仍平移 cupW/杯),两端橡皮阻尼。左滑加。
      let startIdx = 0, step = 1;
      row.addEventListener('pointerdown', (e) => {
        dragging = true;
        try { row.setPointerCapture(e.pointerId); } catch (x) {}
        rowW = row.clientWidth; cupW = rowW / VISIBLE;
        step = (rowW * 0.75) / N;
        startIdx = Math.max(0, st.water - 1);
        block.classList.add('zoom');
        zx0 = e.clientX; off = offFor(startIdx);
        // 进场:strip 平滑滑到位(和长高/放大同拍),0.3s 后交还拖动(拖动期间必须零过渡跟手)
        strip.style.transition = EASE_OUT;
        setStrip(off);
        setTimeout(() => { if (dragging) strip.style.transition = 'none'; }, 300);
        setEmphasis(startIdx);
      });
      row.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        // 连续杯位:起点杯 + 手指位移/齿轮比;越界部分打 0.3 阻尼再收进 [0, N-1]
        let f = startIdx + (zx0 - e.clientX) / step;
        if (f < 0) f = f * 0.3;
        if (f > N - 1) f = (N - 1) + (f - (N - 1)) * 0.3;
        f = Math.max(-0.45, Math.min(N - 0.55, f));
        if (strip.style.transition !== 'none') strip.style.transition = 'none';
        setStrip(offFor(f));
        const center = Math.max(0, Math.min(N - 1, Math.round(f)));
        setLit(center + 1);
        setEmphasis(center);
      });
      const end = () => {
        if (!dragging) return;
        dragging = false;
        block.classList.remove('zoom');
        // 退场:strip 平滑滑回 0,和收窄/缩高同拍;动画完再重渲(避免中途换 DOM 跳帧)
        strip.style.transition = EASE_OUT;
        setStrip(0);
        strip.querySelectorAll('.gw-cup').forEach((c) => c.classList.remove('focus', 'near'));
        setTimeout(() => {
          strip.style.transition = '';
          strip.style.transform = '';
          paint();   // 回缩落定重渲(带 just 脉冲)
          setTimeout(() => { justIdx = -1; paint(); }, 900);
        }, 300);
        GW.bus.emit('pulse');
      };
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
    // ★对照 PC ritual.js taskNode:有图 = 灰度底 + 彩色按 intake/dose 自底填 + 余N + 段刻度 + ✓
    function discHTML(t) {
      const dz = Math.max(1, t.daily_dose || 1);
      const ink = Math.max(0, Math.min(dz, t.today_intake || 0));
      const isDone = ink >= dz;
      if (t.image_url) {
        let segs = '';
        if (dz > 1) for (let k = 1; k < dz; k++) segs += `<span class="gw-task-seg" style="bottom:${(k / dz) * 100}%"></span>`;
        const rem = (typeof t.remaining === 'number')
          ? `<span class="gw-task-remaining${t.remaining <= Math.max(3, dz * 3) ? ' urgent' : ''}">余${t.remaining}</span>` : '';
        return `<span class="gw-task-photo"><img class="gw-task-photo-base" src="${t.image_url}" alt="">`
          + `<span class="gw-task-photo-fill" style="--frac:${ink / dz}"><img src="${t.image_url}" alt=""></span>`
          + `<span class="gw-task-segs">${segs}</span></span>${rem}<span class="gw-task-done-tick">✓</span>`;
      }
      const ring = isDone
        ? `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--umber)" stroke-width="1.4"/></svg>`
        : `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--line-strong)" stroke-width="1.2" stroke-dasharray="2 3"/></svg>`;
      const check = isDone ? `<svg class="gw-task-check" width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3.5 9.5 Q6 12 7.5 14 Q10 8 15 4" stroke="var(--vermilion)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>` : '';
      return `${ring}${check}<span class="gw-task-glyph">${t.glyph}</span>`;
    }
    st.tasks.forEach((t) => {
      const done = t.today_intake >= t.daily_dose;
      const btn = el('button', 'gw-task' + (done ? ' done' : '') + (t.image_url ? ' has-photo' : ''));
      // P2 · snapshot_ui 定位(case daily_tasks__check_* 真 tap 鱼油 等)
      btn.setAttribute('aria-label', `打卡 ${t.name}${done ? ' 已完成' : ` ${t.today_intake || 0}/${t.daily_dose}`}${st.readonly ? ' 只读' : ''}`);
      btn.setAttribute('role', 'button');
      btn.dataset.taskName = t.name;
      btn.dataset.taskDone = done ? '1' : '0';
      btn.dataset.taskReadonly = st.readonly ? '1' : '0';
      // ring/check/glyph/余N/填充 全收进 discHTML(t)
      const dose = t.daily_dose >= 2 ? `${t.today_intake}/${t.daily_dose}` : (done ? '✓' : '\u00a0');
      btn.innerHTML = `<span class="gw-task-disc">${discHTML(t)}</span>
        <span class="gw-task-name">${GW.esc(t.name)}</span><span class="gw-task-dose">${dose}</span>`;
      // tap = 打卡(clamp 0..dose)
      let lpTimer = null, moved = false, downXY = null;
      btn.addEventListener('pointerdown', (e) => { moved = false; downXY = [e.clientX, e.clientY]; lpTimer = setTimeout(() => { lpTimer = null; if (!moved) GW.openTaskSheet(t); }, LP_MS); });
      btn.addEventListener('pointermove', (e) => { if (downXY && (Math.abs(e.clientX - downXY[0]) > 8 || Math.abs(e.clientY - downXY[1]) > 8)) { moved = true; clearTimeout(lpTimer); lpTimer = null; } });
      btn.addEventListener('pointerup', () => {
        if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; if (!moved && !st.readonly) toggle(); }
      });
      btn._toggle = toggle;
      function toggle() {
        if (t.today_intake >= t.daily_dose) t.today_intake = 0; else t.today_intake += 1;
        const nowDone = t.today_intake >= t.daily_dose;
        btn.classList.toggle('done', nowDone);
        if (nowDone) { btn.classList.add('confirm'); setTimeout(() => btn.classList.remove('confirm'), 520); }
        const disc = btn.querySelector('.gw-task-disc');
        if (t.image_url) {
          // 彩色填充层按 intake/dose 自底升(CSS clip-path transition = 灌注动画)
          const fill = disc.querySelector('.gw-task-photo-fill');
          if (fill) fill.style.setProperty('--frac', Math.max(0, Math.min(1, t.today_intake / Math.max(1, t.daily_dose))));
        } else {
          disc.querySelector('.ring').outerHTML = nowDone
            ? `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--umber)" stroke-width="1.4"/></svg>`
            : `<svg class="ring" viewBox="0 0 46 46" fill="none"><circle cx="23" cy="23" r="21.5" stroke="var(--line-strong)" stroke-width="1.2" stroke-dasharray="2 3"/></svg>`;
          let chk = disc.querySelector('.gw-task-check'); if (chk) chk.remove();
          if (nowDone) disc.insertAdjacentHTML('afterbegin', `<svg class="gw-task-check" width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3.5 9.5 Q6 12 7.5 14 Q10 8 15 4" stroke="var(--vermilion)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`);
        }
        btn.querySelector('.gw-task-dose').textContent = t.daily_dose >= 2 ? `${t.today_intake}/${t.daily_dose}` : (nowDone ? '✓' : '\u00a0');
        GW.bus.emit('pulse');
      }
      row.appendChild(btn);
    });
    // ★ parent row delegation handler — 真 hit-test 落到 row 上时(timeline 覆盖 chip 时),
    //   按 clientX 找最近 chip 触发 toggle. cup 同款 pattern.
    if (!st.readonly) {
      row.addEventListener('pointerdown', (e) => {
        if (e.target.closest('.gw-task')) return;  // 真 hit 到具体 chip → 让 chip 自己 handler
        // 落到 row 但不在 chip → 找最近 chip
        const chips = row.querySelectorAll('.gw-task');
        let best = -1, bd = 1e9;
        chips.forEach((c, i) => {
          const r = c.getBoundingClientRect();
          const cx = r.left + r.width / 2;
          const d = Math.abs(e.clientX - cx);
          if (d < bd) { bd = d; best = i; }
        });
        if (best >= 0 && bd < 50) {
          const btn = chips[best];
          if (btn._toggle) btn._toggle();
        }
      });
    }
    host.appendChild(block);
  }

  /* ════ 今日概览════ */
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
