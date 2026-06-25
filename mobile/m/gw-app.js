// gw-app.js — 壳:tab 切换 · 日期带(建明天)· 顶栏下滑收起 · 抽屉 · 设置 · 主题 · 连线
// 加载顺序最后。先定义 bus / root / whisper / scanIntent,再 mount。
(function () {
  'use strict';
  const GW = window.GW;

  /* 事件总线 */
  GW.bus = (function () { const map = {}; return {
    on: (k, fn) => { (map[k] = map[k] || []).push(fn); },
    emit: (k, p) => { (map[k] || []).forEach((fn) => fn(p)); },
  }; })();

  /* whisper(AI 低语 / 提示,2.2s)*/
  let whisperTimer = null;
  GW.whisper = function (text, ai) {
    let n = GW.root.querySelector('.gw-whisper');
    if (!n) { n = document.createElement('div'); n.className = 'gw-whisper'; GW.root.appendChild(n); }
    n.className = 'gw-whisper' + (ai ? ' ai' : ''); n.textContent = text;
    void n.offsetHeight; n.classList.add('on');
    clearTimeout(whisperTimer); whisperTimer = setTimeout(() => n.classList.remove('on'), 2200);
  };

  /* ⑥ 隐式意图扫词(fire-and-forget,用户无感;真机 POST feedback sink)*/
  GW.scanIntent = function (text) {
    if (!text) return;
    try {
      const hits = [];
      if (/想加|想要 ?widget|搞个面板|加打卡|加 ?widget/.test(text)) hits.push('want_widget');
      if (/界面太普通|太简洁|想要纸感|有质感|想要纸/.test(text)) hits.push('want_paper');
      if (/像桌面那样|跟桌面一样|桌面有手机没有/.test(text)) hits.push('want_desktop_parity');
      // 真机:hits.forEach(k => realFetch(SINK, {kind:k, excerpt:text.slice(0,200)}))
    } catch (e) { /* 永不 throw */ }
  };

  const MENU = [
    { id: 'settings', glyph: 'settings', label: '设置', desc: '钥匙 · 模型 · 皮肤' },
    { id: 'aggregate', glyph: 'layers', label: '聚合页', desc: '按 #标签 横切' },
    { id: 'widget', glyph: 'grid', label: '小组件', desc: '打卡 · 八杯水 · 脉搏' },
    { id: 'about', glyph: 'dot', label: '关于', desc: 'Gateway · 私印小报' },
  ];

  /* ════ mount ════ */
  GW.mount = function (mountEl, opts) {
    opts = opts || {};
    const st = {
      theme: opts.theme || 'day',
      tab: 'journal', subPage: null,
      days: GW.days(), dayKey: '06-25',
      tasks: GW.tasks, water: GW.water, mood: null, noteWritten: false,
      enabled: ['cups', 'tasks', 'pulse', 'mood'], dynWidgets: [],
      thread: GW.thread, readonly: false,
    };
    GW.state = st;

    const gw = document.createElement('div'); gw.className = 'gw'; gw.dataset.theme = st.theme;
    GW.root = gw;
    mountEl.innerHTML = ''; mountEl.appendChild(gw);

    function dayState(k) { const d = st.days.find((x) => x.key === k); return d ? d.state : 'today'; }

    function render() {
      st.readonly = dayState(st.dayKey) === 'past';
      gw.dataset.theme = st.theme;
      // iOS 真状态栏在 webview 上方,删 cd 原型画的 9:41 + 假电池(避免重复)
      gw.innerHTML = `<div class="gw-grain"></div><div class="gw-glow"></div>
        <div class="gw-scroll"></div>`;
      const scroll = gw.querySelector('.gw-scroll');
      if (st.subPage) { renderSub(scroll); return; }
      scroll.appendChild(topbar());
      if (st.tab === 'journal') {
        const care = document.createElement('section'); care.className = 'gw-care'; care.id = 'care';
        const tl = document.createElement('div'); tl.className = 'gw-timeline';
        scroll.appendChild(care); scroll.appendChild(tl);
        GW.renderCare(care, st); GW.renderTimeline(tl, st);
        gw.appendChild(nib());
        wireHideOnScroll(scroll);
      } else {
        const th = document.createElement('div'); th.className = 'gw-thread';
        scroll.appendChild(th); GW.renderThread(th, st);
        gw.appendChild(chatbar(th));
      }
    }

    function topbar() {
      const top = document.createElement('header'); top.className = 'gw-top';
      top.innerHTML = `<div class="gw-top-row">
          <button class="gw-burger">${GW.ICON.burger}</button>
          <nav class="gw-nav">
            <button class="gw-nav-item${st.tab === 'journal' ? ' on' : ''}" data-tab="journal">日记</button>
            <button class="gw-nav-item${st.tab === 'chat' ? ' on' : ''}" data-tab="chat">对话</button>
          </nav>
          <span class="gw-top-spacer"></span>
          <span class="gw-breath-dot" title="AI 在场"></span>
        </div>
        ${st.tab === 'journal' ? `<div class="gw-dateband"></div>` : ''}`;
      top.querySelector('.gw-burger').addEventListener('click', openDrawer);
      top.querySelectorAll('.gw-nav-item').forEach((b) => b.addEventListener('click', () => { st.tab = b.dataset.tab; render(); }));
      if (st.tab === 'journal') buildDateband(top.querySelector('.gw-dateband'));
      return top;
    }

    function buildDateband(band) {
      st.days.forEach((d) => {
        const b = document.createElement('button');
        b.className = 'gw-day ' + d.state + (d.key === st.dayKey ? ' sel' : '') + (d.state === 'creatable' ? ' future creatable' : '') + (d.state === 'locked' ? ' future locked' : '') + (d._born ? ' born' : '');
        b.innerHTML = `${d.state === 'today' ? '<span class="gw-day-seal"></span>' : ''}<span class="gw-day-dow">${d.dow}</span><span class="gw-day-num">${d.num}</span>${d.state === 'creatable' ? '<span class="gw-day-plus">+</span>' : ''}`;
        b.addEventListener('click', () => pickDay(d));
        band.appendChild(b);
      });
      requestAnimationFrame(() => { const t = band.querySelector('.today, .sel'); if (t) band.scrollLeft = t.offsetLeft - band.clientWidth / 2 + t.offsetWidth / 2; });
    }

    function pickDay(d) {
      if (d.state === 'locked') { GW.whisper('最多只能建到明天（+1）'); return; }
      if (d.state === 'creatable') {
        GW.journal[d.key] = []; d.state = 'sel'; d._born = true; st.dayKey = d.key; st.tab = 'journal';
        GW.whisper('明天已创建 · 落了张空骨架'); render();
        setTimeout(() => { d._born = false; }, 1300);
        return;
      }
      st.dayKey = d.key; st.tab = 'journal'; render();
    }

    function wireHideOnScroll(scroll) {
      let last = 0; const top = gw.querySelector('.gw-top');
      scroll.addEventListener('scroll', () => {
        const t = scroll.scrollTop;
        if (t > last + 6 && t > 64) top.classList.add('hidden');
        else if (t < last - 6) top.classList.remove('hidden');
        last = t;
      });
    }

    function nib() {
      const n = document.createElement('button'); n.className = 'gw-nib'; n.setAttribute('aria-label', '提笔写一段'); n.innerHTML = GW.ICON.nib;
      n.addEventListener('click', () => GW.openCard({ st: st }));
      return n;
    }

    function chatbar(thread) {
      const bottom = document.createElement('div'); bottom.className = 'gw-bottom';
      bottom.innerHTML = `<div class="gw-attach-chips" hidden></div>
        <div class="gw-chatbar">
          <button class="gw-chat-attach">${GW.ICON.attach}</button>
          <textarea class="gw-chat-input" rows="1" placeholder="跟 Gateway 说点什么…"></textarea>
          <button class="gw-chat-send" disabled>${GW.ICON.send}</button>
        </div>`;
      const ta = bottom.querySelector('.gw-chat-input');
      const send = bottom.querySelector('.gw-chat-send');
      const chips = bottom.querySelector('.gw-attach-chips');
      let pending = [];
      function refresh() { send.disabled = !(ta.value.trim() || pending.length); ta.style.height = 'auto'; ta.style.height = Math.min(96, ta.scrollHeight) + 'px'; }
      ta.addEventListener('input', refresh);
      ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); fire(); } });
      bottom.querySelector('.gw-chat-attach').addEventListener('click', () => {
        // demo:贴一张占位图(真机走 Capacitor Camera)
        pending.push('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2280%22 height=%2280%22%3E%3Crect width=%2280%22 height=%2280%22 fill=%22%23cdbfa6%22/%3E%3C/svg%3E');
        chips.hidden = false; chips.innerHTML = pending.map((u, i) => `<div class="gw-attach-chip"><img src="${u}"><button class="gw-attach-x" data-i="${i}">×</button></div>`).join('');
        chips.querySelectorAll('.gw-attach-x').forEach((x) => x.addEventListener('click', () => { pending.splice(+x.dataset.i, 1); chips.hidden = !pending.length; chips.innerHTML = pending.map((u, i) => `<div class="gw-attach-chip"><img src="${u}"><button class="gw-attach-x" data-i="${i}">×</button></div>`).join(''); refresh(); }));
        refresh();
      });
      function fire() { const t = ta.value.trim(); if (!t && !pending.length) return; const imgs = pending.slice(); ta.value = ''; pending = []; chips.hidden = true; chips.innerHTML = ''; refresh(); GW.sendChat(thread, st, t, imgs); }
      send.addEventListener('click', fire);
      return bottom;
    }

    /* 抽屉 */
    function openDrawer() {
      const d = document.createElement('div'); d.className = 'gw-drawer';
      d.innerHTML = `<div class="gw-grip"></div>
        <div class="gw-drawer-head"><span class="gw-drawer-brand">Gateway</span><span class="gw-drawer-sub">人和 AI 共写的一本日记</span></div>
        ${MENU.map((m) => `<button class="gw-menu-item" data-id="${m.id}"><span class="gw-menu-glyph">${GW.ICON[m.glyph] || GW.ICON.dot}</span><span class="gw-menu-label">${m.label}</span><span class="gw-menu-desc">${m.desc}</span></button>`).join('')}`;
      const m = GW.mountModal(d);
      d.addEventListener('click', (e) => { const b = e.target.closest('.gw-menu-item'); if (!b) return; m.close(); setTimeout(() => { st.subPage = b.dataset.id; render(); }, 320); });
    }

    /* 子页(设置 / 其余占位)*/
    function renderSub(scroll) {
      const meta = MENU.find((m) => m.id === st.subPage) || { label: '' };
      const top = document.createElement('header'); top.className = 'gw-top';
      top.innerHTML = `<div class="gw-top-row"><button class="gw-burger">${GW.ICON.back}</button><nav class="gw-nav"><span class="gw-nav-item on">${meta.label}</span></nav><span class="gw-top-spacer"></span><span class="gw-breath-dot"></span></div>`;
      top.querySelector('.gw-burger').addEventListener('click', () => { st.subPage = null; render(); });
      scroll.appendChild(top);
      if (st.subPage === 'settings') scroll.appendChild(settings());
      else { const e = document.createElement('div'); e.className = 'gw-empty'; e.innerHTML = `<b>${meta.label}</b>${meta.desc || ''}。<br>桌面已有，移动端按路线图往上加。`; scroll.appendChild(e); }
    }

    function settings() {
      const s = document.createElement('div'); s.className = 'gw-set';
      s.innerHTML = `
        <div class="gw-set-sec"><div class="gw-set-sec-lab">双钥匙 · 给它声音和眼睛</div>
          <div class="gw-key ok"><div class="gw-key-head"><span class="gw-key-role">DeepSeek</span><span class="gw-key-tag">· 说话的那个</span></div>
            <div class="gw-key-desc">对话、夹批、21:30 的纸条都从这把钥匙发声。</div>
            <div class="gw-key-row"><input class="gw-key-in" value="sk-••••••••3f9a"><button class="gw-key-test">测试</button></div>
            <div class="gw-key-status ok">已连通 · deepseek-chat</div></div>
          <div class="gw-key"><div class="gw-key-head"><span class="gw-key-role">阿里云百炼</span><span class="gw-key-tag">· 看东西的那只眼</span></div>
            <div class="gw-key-desc">看照片、抠图、贴纸都走这把钥匙。可选，填了才长出眼睛。</div>
            <div class="gw-key-row"><input class="gw-key-in" placeholder="粘贴百炼 API Key…"><button class="gw-key-test">测试</button></div>
            <div class="gw-key-status idle">未填 · 暂无视觉</div></div>
        </div>
        <div class="gw-set-sec"><div class="gw-set-sec-lab">皮肤</div>
          <div class="gw-row"><div><div class="gw-row-title">私印小报</div><div class="gw-row-desc">深夜台灯 / 日间米黄纸，同一套纸。</div></div>
            <div class="gw-seg" id="skin"><button data-t="day"${st.theme === 'day' ? ' class="on"' : ''}>日间</button><button data-t="night"${st.theme === 'night' ? ' class="on"' : ''}>夜间</button></div></div>
          <div class="gw-row"><div><div class="gw-row-title">呼吸暖光</div><div class="gw-row-desc">页面背后那束慢慢起伏的光。</div></div><div class="gw-toggle on"></div></div>
          <div class="gw-row"><div><div class="gw-row-title">减少动效</div><div class="gw-row-desc">关掉呼吸、墨迹、纸页翻动。</div></div><div class="gw-toggle"></div></div>
        </div>
        <div class="gw-set-sec"><div class="gw-set-sec-lab">告诉我们你想要</div>
          <button class="gw-want">${GW.ICON.nib} 我想要新功能 / 新视觉</button>
          <div class="gw-want-sub">跳进对话告诉 AI，我们一起想。</div>
        </div>`;
      s.querySelector('#skin').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; st.theme = b.dataset.t; render(); });
      s.querySelectorAll('.gw-toggle').forEach((t) => t.addEventListener('click', () => t.classList.toggle('on')));
      s.querySelector('.gw-want').addEventListener('click', () => { st.subPage = null; st.tab = 'chat'; render(); setTimeout(() => { const ta = gw.querySelector('.gw-chat-input'); if (ta) { ta.value = '我想要'; ta.focus(); ta.dispatchEvent(new Event('input')); } }, 60); });
      return s;
    }

    /* bus 连线 */
    GW.bus.on('reloadDay', () => { if (st.tab === 'journal' && !st.subPage) { const tl = gw.querySelector('.gw-timeline'); const care = gw.querySelector('.gw-care'); if (tl) GW.renderTimeline(tl, st); if (care) GW.renderCare(care, st); } });
    GW.bus.on('pulse', () => { const care = gw.querySelector('.gw-care'); if (care) GW.renderPulseInPlace(care, st); });
    GW.bus.on('point', (entry) => { st.thread.push({ kind: 'ref', who: 'me', refKind: '日记 · ' + entry.time, refText: entry.title || (entry.body || '').slice(0, 22) }); st.tab = 'chat'; render(); GW.whisper('已拉进对话 ✦ 指给 AI 看', true); });
    GW.bus.on('wantNewTask', () => { st.tab = 'chat'; render(); setTimeout(() => { const ta = gw.querySelector('.gw-chat-input'); if (ta) { ta.value = '我想要新打卡项：'; ta.focus(); ta.dispatchEvent(new Event('input')); } }, 60); });

    render();
    return { setTheme: (t) => { st.theme = t; render(); }, state: st };
  };
})();
