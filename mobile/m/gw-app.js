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

  /* 取一张照片(WKWebView 原生相册/相机,无新依赖)→ 返 dataURL;取消返 null */
  GW.pickPhoto = function (opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = 'image/*';
      if (opts.camera) input.capture = 'environment';
      input.style.cssText = 'position:fixed;left:-9999px;width:1px;height:1px;opacity:0';
      document.body.appendChild(input);
      let settled = false;
      const finish = (v) => { if (settled) return; settled = true; try { document.body.removeChild(input); } catch (e) {} resolve(v); };
      input.addEventListener('change', () => {
        const f = input.files && input.files[0];
        if (!f) return finish(null);
        const r = new FileReader();
        r.onload = () => finish(r.result);
        r.onerror = () => finish(null);
        r.readAsDataURL(f);
      });
      // 用户取消(无 change)→ 窗口重获焦点后兜底 resolve(null)
      const onFocus = () => { window.removeEventListener('focus', onFocus); setTimeout(() => finish(null), 1200); };
      window.addEventListener('focus', onFocus);
      input.click();
    });
  };

  /* 取图入口双选:拍一张(直调相机) / 从相册选。类名对齐 R2 设计稿(gw-attach-pick),
     组装阶段只换皮。mountModal 不在(极早期)则退化为直接开相册。取消返 null。 */
  GW.pickPhotoVia = function () {
    return new Promise((resolve) => {
      if (typeof GW.mountModal !== 'function') { GW.pickPhoto().then(resolve); return; }
      const sheet = document.createElement('div'); sheet.className = 'gw-sheet gw-attach-pick';
      sheet.innerHTML = `<div class="gw-grip"></div>
        <div class="gw-sheet-head">来一张<span class="sub">拍新的,或翻已有的</span></div>
        <button class="gw-sheet-item gw-attach-pick-item" data-src="camera"><span class="glyph">拍</span>拍一张</button>
        <button class="gw-sheet-item gw-attach-pick-item" data-src="album"><span class="glyph">选</span>从相册选</button>`;
      let picked = false;
      const m = GW.mountModal(sheet, { onClose: () => { if (!picked) resolve(null); } });
      sheet.addEventListener('click', (e) => {
        const b = e.target.closest('.gw-attach-pick-item'); if (!b) return;
        picked = true;
        m.close();
        // 等 sheet 收起再拉 input:file picker 与 modal 关闭动画抢焦点会吞 change 事件
        setTimeout(() => { GW.pickPhoto({ camera: b.dataset.src === 'camera' }).then(resolve); }, 480);
      });
    });
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
      days: GW.days(),
      // ★ bug 修:原硬编 '06-25'(mock 日 key)→ 时间线读 GW.journal['06-25']=mock,
      //   而 bridge 把真 md 存在 GW.journal[今天 key]。改成选中今天 → 时间线读真 md。
      dayKey: (GW.days().find(function (d) { return d.state === 'today'; }) || {}).key || '06-25',
      tasks: GW.tasks, water: GW.water, mood: null, noteWritten: GW.noteWritten || false,
      enabled: ['cups', 'tasks', 'pulse', 'mood'], dynWidgets: [],
      thread: GW.thread, readonly: false,
    };
    GW.state = st;

    const gw = document.createElement('div'); gw.className = 'gw'; gw.dataset.theme = st.theme;
    GW.root = gw;
    mountEl.innerHTML = ''; mountEl.appendChild(gw);

    // 外链:WKWebView 里裸 <a href> 点击 = navigate-in-place 被拦(哑火)→ 拦 http(s) 走系统浏览器。
    // 配合 md.js 给外链打的 target=_blank,长按复制则靠 components.css 放开 user-select/touch-callout。
    if (!GW._extLinkBound) {
      GW._extLinkBound = true;
      document.addEventListener('click', function (e) {
        const a = e.target.closest && e.target.closest('a[href]');
        if (!a) return;
        const href = a.getAttribute('href') || '';
        if (!/^https?:\/\//i.test(href)) return;   // 只接管外链;内部锚点/操作不动
        e.preventDefault();
        window.open(href, '_system');              // Capacitor:_system = 交给系统浏览器
      }, true);
    }

    // 键盘弹起时输入框被盖住看不到最新输入(无 @capacitor/keyboard + contentInset:never)。
    // 用 visualViewport 把 app 收到可见区 → chatbar 顶到键盘上方,输入随打随可见。
    if (window.visualViewport && !GW._vvBound) {
      GW._vvBound = true;
      const vv = window.visualViewport;
      const applyVV = function () {
        if (!GW.root) return;
        const kb = window.innerHeight - vv.height;        // 键盘遮住的高度
        GW.root.style.height = kb > 80 ? vv.height + 'px' : '';  // 弹起→收缩;收起→还给 CSS 100%
      };
      vv.addEventListener('resize', applyVV);
      vv.addEventListener('scroll', applyVV);
    }

    function dayState(k) { const d = st.days.find((x) => x.key === k); return d ? d.state : 'today'; }

    function render() {
      // ── 整页左右滑切 tab(左滑→日记,右滑→对话)。绑 gw 根,只绑一次。
      //    让位区:打卡横滑带 / chatbar 输入区 / 弹层;subPage 整页让位。
      //    日期带不让位 — 用户拍板放弃它的横滚翻页,滑动优先切 tab。
      //    entry 左滑删除无冲突:日记页左滑切"日记"= no-op,右滑 entry 行本就不进删除模式。
      if (!gw._swBound) {
        gw._swBound = true;
        let swx = null, swy = null, swLastX = null, swLastY = null;
        gw.addEventListener('touchstart', (e) => {
          const t0 = e.touches[0]; if (!t0) return;
          swx = swLastX = t0.clientX; swy = swLastY = t0.clientY;
          if (st.subPage || e.target.closest('.gw-tasks, .gw-bottom, .gw-sheet, .gw-card, .gw-drawer, .gw-scrim')) swx = null;
        }, { passive: true });
        // {passive:false} + 横向意图确立即 preventDefault — vivo 等 OEM WebView 不抢下
        // 所有权就停发 touchmove、touchend 坐标冻结在起点(Chromium issue 36910235,
        // 真机探针实锤:滑 216ms 结束坐标 == 起点)。touch-action CSS 它们不认,JS 硬抢才认。
        gw.addEventListener('touchmove', (e) => {
          const t0 = e.touches[0]; if (!t0) return;
          swLastX = t0.clientX; swLastY = t0.clientY;
          if (swx != null) {
            const dx = t0.clientX - swx, dy = t0.clientY - swy;
            if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy) * 1.2) e.preventDefault();
          }
        }, { passive: false });
        function swFinish(x, y, why) {
          if (swx == null || x == null) { swx = null; return; }
          const dx = x - swx, dy = y - swy; swx = null;
          if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy) * 1.4) return;
          const want = dx < 0 ? 'chat' : 'journal';  // 左滑→对话(右侧 tab),右滑→日记 — 常规方向
          if (want !== st.tab) { st._slide = want; st.tab = want; render(); }
        }
        gw.addEventListener('touchend', (e) => {
          const t0 = e.changedTouches[0];
          swFinish(t0 ? t0.clientX : swLastX, t0 ? t0.clientY : swLastY, 'end');
        }, { passive: true });
        gw.addEventListener('touchcancel', () => swFinish(swLastX, swLastY, 'cancel'), { passive: true });
      }
      var ds = dayState(st.dayKey);
      st.readonly = (ds === 'past') && !(st.dayCatalog && st.dayCatalog.is_writable);
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
      // 翻页 = 硬切,过渡动画只留标题栏(nav 下划线 gw-ink-spread 每次重建自动重放)
      st._slide = null;
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
          ${st.tab === 'chat' ? `<button class="gw-compact-ring" aria-label="整理对话历史(压成摘要)"></button>` : ''}
          <span class="gw-breath-dot" title="AI 在场"></span>
        </div>
        ${st.tab === 'journal' ? `<div class="gw-dateband"></div>` : ''}`;
      top.querySelector('.gw-burger').addEventListener('click', openDrawer);
      top.querySelectorAll('.gw-nav-item').forEach((b) => b.addEventListener('click', () => { st._slide = b.dataset.tab; st.tab = b.dataset.tab; render(); }));
      const _ring = top.querySelector('.gw-compact-ring');
      if (_ring) { _ring.addEventListener('click', () => runCompact()); setTimeout(updateCompactRing, 0); }
      if (st.tab === 'journal') buildDateband(top.querySelector('.gw-dateband'));
      return top;
    }

    function buildDateband(band) {
      st.days.forEach((d) => {
        const b = document.createElement('button');
        b.className = 'gw-day ' + d.state + (d.key === st.dayKey ? ' sel' : '') + (d.state === 'creatable' ? ' future creatable' : '') + (d.state === 'locked' ? ' future locked' : '') + (d._born ? ' born' : '');
        // P2 · 给 snapshot_ui 可定位(case daily_tasks/journal date-band 用)
        b.setAttribute('aria-label', `日期 ${d.dow} ${d.num}${d.state === 'today' ? ' 今天' : (d.state === 'past' ? ' 过去日只读' : (d.state === 'locked' ? ' 未来日锁定' : ''))}`);
        b.setAttribute('role', 'button');
        b.dataset.dayKey = d.key;
        b.dataset.dayState = d.state;
        b.innerHTML = `${d.state === 'today' ? '<span class="gw-day-seal"></span>' : ''}<span class="gw-day-dow">${d.dow}</span><span class="gw-day-num">${d.num}</span>${d.state === 'creatable' ? '<span class="gw-day-plus">+</span>' : ''}`;
        b.addEventListener('click', () => pickDay(d));
        band.appendChild(b);
      });
      requestAnimationFrame(() => { const t = band.querySelector('.today, .sel'); if (t) band.scrollLeft = t.offsetLeft - band.clientWidth / 2 + t.offsetWidth / 2; });
    }

    function pickDay(d) {
      if (d.state === 'locked') { GW.whisper('最多只能建到明天（+1）'); return; }
      if (d.state === 'creatable') {
        // 先真建 md 再改界面 — 原来只改内存就说「已创建」,盘上没有,之后的写全 404
        const iso = d.iso || (new Date().getFullYear() + '-' + d.key);
        window.fetch('/api/journal/new-day', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ date: iso }) })
          .then((r) => r.json())
          .then((j) => {
            if (!j || j.ok === false) { GW.whisper((j && j.error) || '没建成 · 再点一次'); return; }
            GW.journal[d.key] = []; d.state = 'sel'; d._born = true; st.dayKey = d.key; st.tab = 'journal';
            st.dayCatalog = null;
            GW.whisper('明天已创建 · 落了张空骨架'); render();
            setTimeout(() => { d._born = false; }, 1300);
            window.fetch('/api/daily-tasks?date=' + iso).then((r2) => r2.json()).then((j2) => {
              st.dayCatalog = j2;
              if (Array.isArray(j2.tasks)) st.tasks = j2.tasks;
              if (typeof j2.water_filled === 'number') st.water = j2.water_filled;
              render();
            }).catch(() => {});
          })
          .catch(() => GW.whisper('没建成 · 网络不通'));
        return;
      }
      // FIX D — 同步 render 前清空 dayCatalog,让 readonly 计算回退到 ds==='past' 默认值
      // 防 false-affordance flash(用上一日 catalog 在新日上一帧显示错误可写态)
      st.dayCatalog = null;
      st.dayKey = d.key; st.tab = 'journal';
      // 切到非 creatable 日 → 主动重拉该日 catalog,让 tasks/water/is_writable 是该日真状态
      if (d.state !== 'creatable' && window.fetch) {
        var iso = d.iso;
        window.fetch('/api/daily-tasks?date=' + iso).then(function (r) { return r.json(); }).then(function (j) {
          st.dayCatalog = j;
          if (Array.isArray(j.tasks)) st.tasks = j.tasks;
          if (typeof j.water_filled === 'number') st.water = j.water_filled;
          render();
        }).catch(function () {});
      }
      render();
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
      function autosize() {
        ta.style.height = 'auto';
        var h = Math.min(120, ta.scrollHeight);
        ta.style.height = h + 'px';
        ta.style.overflowY = ta.scrollHeight > h ? 'auto' : 'hidden'; // 封顶后内部滚动
        ta.scrollTop = ta.scrollHeight;                               // 顶到最新行(锁定最下方文字)
      }
      function refresh() {
        send.disabled = !(ta.value.trim() || pending.length);
        // 双通道量高:同步一次(Android 立即生效),下一帧再校正一次
        // (iOS WKWebView 逐字输入时 input 事件里同步读 scrollHeight 是布局前旧值)
        autosize();
        requestAnimationFrame(autosize);
      }
      ta.addEventListener('input', refresh);
      ta.addEventListener('compositionend', refresh);
      // ★vivo(等 OEM)输入法组字期间对 JS 零事件:预览文字直接画进 textarea,
      //   整句上屏才发唯一一个 input(logcat 实锤:len=28 一次跳出,期间无任何事件)。
      //   没有事件可听 → 聚焦期间轻量轮询,只在"内容高于框且未到上限"时校正
      //   (到上限后内部滚动,不再动高度,免得跟用户往回翻的滚动打架)。
      let growT = null;
      ta.addEventListener('focus', () => {
        if (growT) clearInterval(growT);
        growT = setInterval(() => {
          // 组字期零事件:发送键可用态同样只能靠轮询刷(否则打完不删一个字按钮不亮)
          send.disabled = !(ta.value.trim() || pending.length);
          if (ta.clientHeight < 120 && ta.scrollHeight > ta.clientHeight) autosize();
        }, 160);
      });
      ta.addEventListener('blur', () => { if (growT) { clearInterval(growT); growT = null; } });
      ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); fire(); } });
      function renderChips() {
        chips.hidden = !pending.length;
        chips.innerHTML = pending.map((u, i) => `<div class="gw-attach-chip"><img src="${u}"><button class="gw-attach-x" data-i="${i}">×</button></div>`).join('');
        chips.querySelectorAll('.gw-attach-x').forEach((x) => x.addEventListener('click', () => { pending.splice(+x.dataset.i, 1); renderChips(); refresh(); }));
      }
      // ★ 真选图(对照 PC 对话框贴图):chatbar 附件 → 双选(拍一张/从相册选) → dataURL
      bottom.querySelector('.gw-chat-attach').addEventListener('click', async () => {
        const dataUrl = await GW.pickPhotoVia();
        if (!dataUrl) return;
        pending.push(dataUrl);
        renderChips();
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
      else if (st.subPage === 'aggregate') scroll.appendChild(aggregate());
      else { const e = document.createElement('div'); e.className = 'gw-empty'; e.innerHTML = `<b>${meta.label}</b>${meta.desc || ''}。<br>此功能在开发中。`; scroll.appendChild(e); }
    }

    // 聚合页(对照 PC shared/aggregate.js)— GET /api/tag-aggregate → tab/行 + tap-跳 + 注册/刷新
    function aggregate() {
      const wrap = document.createElement('div'); wrap.className = 'gw-agg';
      wrap.innerHTML = `<div class="gw-agg-acts"><button class="gw-agg-act" data-act="register">＋ 注册标签</button><button class="gw-agg-act" data-act="refresh">⟳ 刷新</button></div>
        <div class="gw-agg-tabs"></div><div class="gw-agg-body"><div class="gw-empty">读取中…</div></div>`;
      const tabsEl = wrap.querySelector('.gw-agg-tabs');
      const bodyEl = wrap.querySelector('.gw-agg-body');
      let sections = [], active = 0;
      function jump(iso) {
        st.subPage = null;
        const key = iso.slice(5);  // 2026-05-07 → 05-07(day.key 格式)
        const day = (st.days || []).find((d) => d.key === key);
        if (day) st.dayKey = key;
        st.tab = 'journal'; render();
      }
      function renderActive() {
        const sec = sections[active];
        if (!sec) { bodyEl.innerHTML = '<div class="gw-empty">还没有聚合标签</div>'; return; }
        if (!sec.rows.length) {
          bodyEl.innerHTML = (sec.description ? `<div class="gw-agg-desc">${GW.esc(sec.description)}</div>` : '') +
            `<div class="gw-empty">这个标签还没有条目。点「⟳ 刷新」，或写日记时带上 #${GW.esc(sec.tag)}。</div>`;
          return;
        }
        const rows = sec.rows.slice().reverse();  // 新在上(对照 PC iso_date DESC)
        // ★ 全部动态内容走 GW.esc(标签聚合.md 是 AI/user 写的,可能含 HTML — 防注入,对照 PC aggregate.js escape)
        bodyEl.innerHTML = (sec.description ? `<div class="gw-agg-desc">${GW.esc(sec.description)}</div>` : '') +
          rows.map((r) => `<button class="gw-agg-row${r.iso_date ? '' : ' no-jump'}" data-iso="${GW.esc(r.iso_date || '')}">
            <span class="gw-agg-when">${GW.esc(r.date_short || '')}<i>${GW.esc(r.time || '')}</i></span>
            <span class="gw-agg-text">${GW.esc(r.content || '')}${r.sub_tag ? `<em>${GW.esc(r.sub_tag)}</em>` : ''}</span></button>`).join('');
        bodyEl.querySelectorAll('.gw-agg-row').forEach((b) => {
          if (!b.dataset.iso) return;
          b.addEventListener('click', () => jump(b.dataset.iso));
        });
      }
      function renderTabs() {
        tabsEl.innerHTML = sections.map((s, i) => `<button class="gw-agg-tab${i === active ? ' on' : ''}" data-i="${i}">#${GW.esc(s.tag)}<i>${s.rows.length}</i></button>`).join('');
        tabsEl.querySelectorAll('.gw-agg-tab').forEach((b) => b.addEventListener('click', () => { active = +b.dataset.i; renderTabs(); renderActive(); }));
      }
      function reload(focusTag) {
        return window.fetch('/api/tag-aggregate').then((r) => r.json()).then((d) => {
          sections = (d && d.sections) || [];
          if (!sections.length) { tabsEl.innerHTML = ''; bodyEl.innerHTML = '<div class="gw-empty">还没有聚合标签。点「＋ 注册标签」或在对话中告诉AI。</div>'; return; }
          if (focusTag) { const idx = sections.findIndex((s) => s.tag === focusTag); if (idx >= 0) active = idx; }
          if (active >= sections.length) active = 0;
          renderTabs(); renderActive();
        }).catch(() => { bodyEl.innerHTML = '<div class="gw-empty">聚合页读取失败</div>'; });
      }
      // ⟳ 刷新:扫日记 → 补缺失行(tap-driven 更新)
      wrap.querySelector('[data-act="refresh"]').addEventListener('click', () => {
        GW.whisper('扫描日记中…', false);
        window.fetch('/api/tag-aggregate/refresh', { method: 'POST' }).then((r) => r.json()).then((d) => {
          GW.whisper(d && d.ok ? (d.added ? '新增了 ' + d.added + ' 条' : '没有新条目') : ((d && d.error) || '刷新失败'), false);
          if (d && d.ok && d.added) reload();
        });
      });
      // ＋ 注册标签:WKWebView 安全的内联 input(不用 window.prompt)
      wrap.querySelector('[data-act="register"]').addEventListener('click', () => {
        if (bodyEl.querySelector('.gw-agg-reg')) return;
        const form = document.createElement('div'); form.className = 'gw-agg-reg';
        form.innerHTML = `<input class="gw-agg-reg-in" placeholder="标签名称（如：健身）" maxlength="40"><button class="gw-agg-reg-ok">注册</button><button class="gw-agg-reg-x">×</button>`;
        bodyEl.prepend(form);
        const inp = form.querySelector('.gw-agg-reg-in'); setTimeout(() => inp.focus(), 50);
        form.querySelector('.gw-agg-reg-x').addEventListener('click', () => form.remove());
        const submit = () => {
          const tag = inp.value.trim().replace(/^#/, '');
          if (!tag) return;
          window.fetch('/api/tag-aggregate/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tag: tag }) })
            .then((r) => r.json()).then((d) => {
              if (d && d.ok) { GW.whisper('已添加 #' + d.tag, false); form.remove(); reload(d.tag); }
              else GW.whisper((d && d.error) || '添加失败', false);
            });
        };
        form.querySelector('.gw-agg-reg-ok').addEventListener('click', submit);
        inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
      });
      reload();
      return wrap;
    }

    function settings() {
      const s = document.createElement('div'); s.className = 'gw-set';
      // 静态骨架先渲染(避免空白等 fetch),拿到真 key state 再 hydrate
      s.innerHTML = `
        <div class="gw-set-sec"><div class="gw-set-sec-lab">双钥匙 · 给它声音和眼睛</div>
          <div class="gw-key" data-key="deepseek"><div class="gw-key-head"><span class="gw-key-role">DeepSeek</span><span class="gw-key-tag">· 说话的那个</span></div>
            <div class="gw-key-desc">对话、夹批、21:30 的纸条都从这把钥匙发声。<br><a href="https://platform.deepseek.com" target="_blank" style="color:var(--umber);text-decoration:underline">platform.deepseek.com</a> 注册 → API Keys → 创建 → 复制 sk-… 粘贴下方</div>
            <div class="gw-key-row"><input class="gw-key-in" placeholder="粘贴 DeepSeek API Key (sk-…)" data-field="deepseek"><button class="gw-key-test" data-test="deepseek">测试</button></div>
            <div class="gw-key-status idle">读取中…</div></div>
          <div class="gw-key" data-key="dashscope"><div class="gw-key-head"><span class="gw-key-role">阿里云百炼</span><span class="gw-key-tag">· 看东西的那只眼</span></div>
            <div class="gw-key-desc">看照片、抠图、贴纸都走这把钥匙。可选，填了才长出眼睛。<br><a href="https://bailian.console.aliyun.com" target="_blank" style="color:var(--umber);text-decoration:underline">bailian.console.aliyun.com</a> 新用户 100 万 token 免费 90 天</div>
            <div class="gw-key-row"><input class="gw-key-in" placeholder="粘贴百炼 API Key…" data-field="dashscope"><button class="gw-key-test" data-test="dashscope">测试</button></div>
            <div class="gw-key-status idle">读取中…</div></div>
        </div>
        <div class="gw-set-sec"><div class="gw-set-sec-lab">皮肤</div>
          <div class="gw-row"><div><div class="gw-row-title">私印小报</div><div class="gw-row-desc">深夜台灯 / 日间米黄纸，同一套纸。</div></div>
            <div class="gw-seg" id="skin"><button data-t="day"${st.theme === 'day' ? ' class="on"' : ''}>日间</button><button data-t="night"${st.theme === 'night' ? ' class="on"' : ''}>夜间</button></div></div>
          <div class="gw-row"><div><div class="gw-row-title">呼吸暖光</div><div class="gw-row-desc">页面背后那束慢慢起伏的光。</div></div><div class="gw-toggle on"></div></div>
          <div class="gw-row"><div><div class="gw-row-title">减少动效</div><div class="gw-row-desc">关掉呼吸、墨迹、纸页翻动。</div></div><div class="gw-toggle"></div></div>
        </div>
        <div class="gw-set-sec"><div class="gw-set-sec-lab">能力 · 手机上它能看到什么</div>
          <div class="gw-row"><div><div class="gw-row-title">步数 <span class="gw-cap-status" data-cap="health.steps" style="opacity:.55;font-size:.82em">查询中…</span></div><div class="gw-row-desc">让 AI 看到你今天走了多少步。点「开启」弹系统授权；AI 也可在对话里替你申请。</div></div>
            <button class="gw-key-test gw-cap-btn" data-cap="health.steps">开启</button></div>
        </div>
        <div class="gw-set-sec"><div class="gw-set-sec-lab">告诉我们你想要</div>
          <button class="gw-want">${GW.ICON.nib} 我想要新功能 / 新视觉</button>
          <div class="gw-want-sub">跳进对话告诉 AI，我们一起想。</div>
        </div>`;
      // ── theme + skin + want(原 binding,不动)──
      s.querySelector('#skin').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; st.theme = b.dataset.t; render(); });
      s.querySelectorAll('.gw-toggle').forEach((t) => t.addEventListener('click', () => t.classList.toggle('on')));
      s.querySelector('.gw-want').addEventListener('click', () => { st.subPage = null; st.tab = 'chat'; render(); setTimeout(() => { const ta = gw.querySelector('.gw-chat-input'); if (ta) { ta.value = '我想要'; ta.focus(); ta.dispatchEvent(new Event('input')); } }, 60); });

      // ── 能力注册表:probe → 状态;点「开启」→ 系统授权框(与 AI 的 request_capability 同一入口)──
      const capText = { granted: '已接入', denied: '被拒 · 去系统设置开', undetermined: '未接入', unavailable: '本机不可用' };
      function capRefresh() {
        const P = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Steps;
        const stEl = s.querySelector('.gw-cap-status[data-cap="health.steps"]');
        const btn = s.querySelector('.gw-cap-btn[data-cap="health.steps"]');
        if (!P) { if (stEl) stEl.textContent = capText.unavailable; if (btn) btn.disabled = true; return; }
        P.probe().then((r) => {
          const state = (r && r.state) || 'unavailable';
          if (stEl) stEl.textContent = capText[state] || state;
          if (btn) { btn.disabled = state === 'granted' || state === 'unavailable'; btn.textContent = state === 'granted' ? '已开启' : '开启'; }
        }).catch(() => { if (stEl) stEl.textContent = capText.unavailable; });
      }
      const capBtn = s.querySelector('.gw-cap-btn[data-cap="health.steps"]');
      if (capBtn) capBtn.addEventListener('click', () => {
        const P = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Steps;
        if (!P) return;
        P.request().then((r) => {
          capRefresh();
          GW.whisper((r && r.state) === 'granted' ? '步数已接入' : '没开成 · ' + (capText[r && r.state] || '出了点问题'));
        }).catch(() => GW.whisper('没开成 · 出了点问题'));
      });
      capRefresh();

      // ── key state hydrate + bind(新增)──
      function maskKey(k) { if (!k) return ''; const s = String(k); if (s.length < 8) return '••••'; return s.slice(0, 3) + '••••' + s.slice(-4); }
      function setStatus(role, cls, text) {
        const box = s.querySelector(`.gw-key[data-key="${role}"] .gw-key-status`);
        if (!box) return;
        box.className = 'gw-key-status ' + cls;
        box.textContent = text;
      }

      // 1. 启动时 fetch 当前 key state
      fetch('/api/setup/current').then(r => r.json()).then(cur => {
        const ds = cur && cur.deepseek_key;
        const az = cur && cur.dashscope_key;
        const inDs = s.querySelector('.gw-key-in[data-field="deepseek"]');
        const inAz = s.querySelector('.gw-key-in[data-field="dashscope"]');
        if (inDs) inDs.placeholder = ds ? maskKey(ds) + '(已存,粘新值替换)' : '粘贴 DeepSeek API Key (sk-…)';
        if (inAz) inAz.placeholder = az ? maskKey(az) + '(已存,粘新值替换)' : '粘贴百炼 API Key…';
        setStatus('deepseek', ds ? 'ok' : 'idle', ds ? '已填 · 待测' : '未填 · AI 没声音');
        setStatus('dashscope', az ? 'ok' : 'idle', az ? '已填 · 待测' : '未填 · AI 没眼睛');
      }).catch(() => {
        setStatus('deepseek', 'idle', '未填 · AI 没声音');
        setStatus('dashscope', 'idle', '未填 · AI 没眼睛');
      });

      // 2. input blur 自动保存(用户粘贴 + 离开焦点)
      function saveKey(field, val) {
        if (!val || !val.trim()) return Promise.resolve();
        const body = field === 'deepseek'
          ? { deepseek_api_key: val.trim() }
          : { dashscope_api_key: val.trim() };
        return fetch('/api/setup/save-partial', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }).then(r => r.json()).then(async r => {
          if (r && r.ok) {
            // ★ instant verify:立即读回看真存了
            const cur = await fetch('/api/setup/current').then(rr => rr.json()).catch(() => ({}));
            const stored = field === 'deepseek' ? cur.deepseek_key : cur.dashscope_key;
            if (stored) {
              setStatus(field, 'ok', '✓ 已保存 verify=' + maskKey(stored));
              GW.whisper(field === 'deepseek' ? 'DeepSeek key 已保存' : '百炼 key 已保存', false);
            } else {
              setStatus(field, 'fail', '⚠ 写了但读不回 — Backend 路径 bug · saved=' + JSON.stringify(r).slice(0, 60) + ' · cur=' + JSON.stringify(cur).slice(0, 80));
            }
          } else {
            setStatus(field, 'fail', '保存失败:' + (r && r.error || '未知'));
          }
        }).catch(e => setStatus(field, 'fail', '保存失败:' + e.message));
      }
      s.querySelectorAll('.gw-key-in').forEach(inp => {
        inp.addEventListener('blur', () => saveKey(inp.dataset.field, inp.value));
      });

      // 3. 测试按钮:对齐桌面 shared/setup.js L265-275 contract
      // 传完整四元组 {label, base_url, api_key, model} → 真打 chat.completions
      const PROVIDER_DEFAULT = {
        deepseek: { label: 'DeepSeek 测试', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
        dashscope: { label: '百炼视觉测试', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen3-vl-flash' },
      };
      function friendlyError(reason) {
        const r = String(reason || '');
        if (/401|Unauthorized|invalid.*key|incorrect.*key/i.test(r)) return 'key 不对 — 复制时漏了字符 / 多了空格 / 漏了 sk-?';
        if (/402|403|insufficient.*balance|余额不足|quota.*exceed/i.test(r)) return '余额不足 — 去充值(DeepSeek 起充 10 元 / 百炼新用户免费 100 万 token)';
        if (/timeout|connection|network|网络|超时/i.test(r)) return '网卡了 — 换 WiFi 重试 / 检查代理';
        if (/UnsupportedModel|model.*not.*found|不存在模型/i.test(r)) return 'model 不对 — 平台下线了某模型,换默认';
        if (/429|rate.*limit/i.test(r)) return '限流了 — 等几秒重试';
        return r;
      }
      s.querySelectorAll('.gw-key-test').forEach(btn => {
        btn.addEventListener('click', async () => {
          const field = btn.dataset.test;
          const inp = s.querySelector(`.gw-key-in[data-field="${field}"]`);
          const inputVal = inp && inp.value && inp.value.trim();
          // 拿 key:优先 input 输入,空时 fetch /api/setup/current 拿存的
          let api_key = inputVal;
          if (!api_key) {
            try {
              const cur = await fetch('/api/setup/current').then(r => r.json());
              api_key = field === 'deepseek' ? cur.deepseek_key : cur.dashscope_key;
            } catch (_) {}
          }
          if (!api_key) {
            setStatus(field, 'fail', '✗ 先粘 API Key 再测试');
            return;
          }
          // 先保存新值
          if (inputVal) await saveKey(field, inputVal);
          btn.disabled = true; btn.textContent = '⋯ 测试中';
          setStatus(field, 'idle', '测试中…');
          const cfg = PROVIDER_DEFAULT[field];
          try {
            const r = await fetch('/api/setup/test', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ label: cfg.label, base_url: cfg.base_url, api_key: api_key, model: cfg.model }),
            });
            const j = await r.json();
            if (j && j.ok) {
              setStatus(field, 'ok', '✓ 已连通 · ' + (j.model || cfg.model));
            } else {
              const raw = (j && j.reason) || '未知';
              const dbg = (j && j.debug) ? ' [' + JSON.stringify(j.debug).slice(0, 200) + ']' : '';
              setStatus(field, 'fail', '✗ ' + friendlyError(raw) + ' · raw:' + String(raw).slice(0, 60) + dbg);
            }
          } catch (e) {
            setStatus(field, 'fail', '✗ ' + friendlyError(e.message));
          } finally {
            btn.disabled = false; btn.textContent = '测试';
          }
        });
      });

      return s;
    }

    /* bus 连线 */
    GW.bus.on('reloadDay', () => { if (st.tab === 'journal' && !st.subPage) { const tl = gw.querySelector('.gw-timeline'); const care = gw.querySelector('.gw-care'); if (tl) GW.renderTimeline(tl, st); if (care) GW.renderCare(care, st); } });
    GW.bus.on('reloadCare', () => { if (st.tab === 'journal' && !st.subPage) { const care = gw.querySelector('.gw-care'); if (care) GW.renderCare(care, st); } });
    GW.bus.on('pulse', () => { const care = gw.querySelector('.gw-care'); if (care) GW.renderPulseInPlace(care, st); });
    GW.bus.on('point', (entry) => { st.thread.push({ kind: 'ref', who: 'me', refKind: '日记 · ' + entry.time, refText: entry.title || (entry.body || '').slice(0, 22) }); st.tab = 'chat'; render(); GW.whisper('已拉进对话 ✦ 指给 AI 看', true); });
    GW.bus.on('wantNewTask', () => { st.tab = 'chat'; render(); setTimeout(() => { const ta = gw.querySelector('.gw-chat-input'); if (ta) { ta.value = '我想要新打卡项：'; ta.focus(); ta.dispatchEvent(new Event('input')); } }, 60); });

    /* ── compact:对话历史压缩 + 上下文管理(对照 PC compact-ring.js;移动跳过 3 份 PULSE 自演化,
          因移动无 PULSE 文件、系统提示不注入 PULSE,只做 summary + history reset 控上下文长度)── */
    const COMPACT_THRESHOLD = 150000;  // ~75K tokens,跟桌面一致
    let compactRunning = false, lastAutoFireAt = 0;
    function threadChars() {
      let sum = 0;
      for (const m of (st.thread || [])) {
        sum += (m.text || m.content || m.body || '').length;
        if (m.refText) sum += m.refText.length;
      }
      return sum;
    }
    function isStreamingNow() { return (st.thread || []).some((m) => m.streaming); }
    function updateCompactRing() {
      const ring = gw.querySelector('.gw-compact-ring');
      if (!ring) return;
      const chars = threadChars();
      const pct = Math.min(150, Math.round((chars / COMPACT_THRESHOLD) * 100));
      ring.style.setProperty('--pct', Math.min(100, pct));
      ring.classList.toggle('over', pct >= 100);
      ring.classList.toggle('warn', pct >= 80 && pct < 100);
      ring.title = `对话 ${(chars / 1000).toFixed(1)}K / 150K · ${pct}% · 点一下整理`;
      const autoOn = (st.compactAuto !== false);
      if (autoOn && pct >= 100 && !compactRunning && !isStreamingNow()) {
        const fails = st.compactFails || 0;
        const cooldown = fails >= 2 ? 3600000 : 600000;
        if (Date.now() - lastAutoFireAt >= cooldown) { lastAutoFireAt = Date.now(); runCompact({ skipConfirm: true, auto: true }); }
      }
    }
    async function runCompact(opts) {
      opts = opts || {};
      if (compactRunning) return;
      if (isStreamingNow()) { GW.whisper('AI 还在回复,等它写完再整理', false); return; }
      const chars = threadChars();
      if (chars === 0) { GW.whisper('对话还空,先聊点东西再整理', false); return; }
      const snapshot = (st.thread || []).slice();
      const cutoffIndex = snapshot.length;  // LLM 跑期间用户发的新消息只在 cutoff 之后,reset 不吃
      let conversation = snapshot.map((m) => {
        const role = (m.who === 'ai' || m.role === 'assistant') ? 'AI' : '用户';
        const t = m.text || m.content || m.body || (m.refText ? '[引用] ' + m.refText : '');
        return t ? `[${role}] ${t}` : '';
      }).filter(Boolean).join('\n\n');
      if (conversation.length > 80000) conversation = '[... 早期对话已省略 ...]\n\n' + conversation.slice(-80000);
      if (!opts.skipConfirm) {
        const ok = await GW.gatewayConfirm(`整理对话历史(${(chars / 1000).toFixed(1)}K 字符)?\n\n旧对话压成一段摘要,保留最近 5 轮 + 整理后发的新消息。AI 不会失忆。`);
        if (!ok) return;
      }
      compactRunning = true; updateCompactRing();
      GW.whisper(opts.auto ? '对话超长,自动整理中…' : '整理中…压一段摘要', false);
      let summary = '';
      try {
        const r = await window.fetch('/api/pulse/compact-summary', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conversation }) });
        if (r.ok) { const j = await r.json(); summary = (j.summary || '').trim(); }
      } catch (e) {}
      compactRunning = false;
      if (!summary) {  // 摘要失败:不动历史(防失忆),auto 计失败 2 次自关
        if (opts.auto) { st.compactFails = (st.compactFails || 0) + 1; if (st.compactFails >= 2) st.compactAuto = false; }
        GW.whisper('整理没成(摘要失败),历史没动。' + (opts.auto && st.compactAuto === false ? ' 自动压缩已禁用，可手动操作。' : ''), false);
        updateCompactRing(); return;
      }
      st.compactFails = 0;
      const newAfterCutoff = (st.thread || []).slice(cutoffIndex);
      const lastOld = snapshot.slice(Math.max(0, cutoffIndex - 5));
      const composed = [{ kind: 'note', who: 'ai', time: '✦ 整理摘要', body: summary, sig: '旧对话已压缩', id: 'compact-' + Date.now(), _isCompactSummary: true }];
      composed.push(...lastOld, ...newAfterCutoff);
      // ★ 原地替换(不 reassign):st.thread === GW.thread 同一引用,reassign 会断链 → bridge 重载用旧 GW.thread 覆盖
      st.thread.length = 0;
      Array.prototype.push.apply(st.thread, composed);
      render();
      try { window.fetch('/api/thread/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ history: st.thread }) }); } catch (e) {}
      GW.whisper('整理完成 — 旧对话压成摘要,保留最近 5 轮', false);
    }
    GW.runCompact = runCompact;
    // WKWebView 安全 confirm(window.confirm 在 WKWebView 默默返 false — 6.17 compact 那个坑)
    GW.gatewayConfirm = function (msg) {
      return new Promise((resolve) => {
        const scrim = document.createElement('div'); scrim.className = 'gw-confirm-scrim';
        scrim.innerHTML = `<div class="gw-confirm"><div class="gw-confirm-msg">${GW.esc(msg || '').replace(/\n/g, '<br>')}</div><div class="gw-confirm-acts"><button class="gw-confirm-no">取消</button><button class="gw-confirm-yes">整理</button></div></div>`;
        GW.root.appendChild(scrim); void scrim.offsetHeight; scrim.classList.add('on');
        let done = false;
        const fin = (v) => { if (done) return; done = true; scrim.classList.remove('on'); setTimeout(() => scrim.remove(), 250); resolve(v); };
        scrim.addEventListener('click', (e) => { if (e.target === scrim) fin(false); });
        scrim.querySelector('.gw-confirm-no').addEventListener('click', () => fin(false));
        scrim.querySelector('.gw-confirm-yes').addEventListener('click', () => fin(true));
      });
    };

    render();
    updateCompactRing();
    setInterval(updateCompactRing, 3000);  // 对话长度轮询 + auto-compact 触发(对照 PC POLL_MS=3000)
    return { setTheme: (t) => { st.theme = t; render(); }, state: st };
  };
})();
