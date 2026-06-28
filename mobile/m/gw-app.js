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

    function dayState(k) { const d = st.days.find((x) => x.key === k); return d ? d.state : 'today'; }

    function render() {
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
        GW.journal[d.key] = []; d.state = 'sel'; d._born = true; st.dayKey = d.key; st.tab = 'journal';
        GW.whisper('明天已创建 · 落了张空骨架'); render();
        setTimeout(() => { d._born = false; }, 1300);
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
        <div class="gw-set-sec"><div class="gw-set-sec-lab">告诉我们你想要</div>
          <button class="gw-want">${GW.ICON.nib} 我想要新功能 / 新视觉</button>
          <div class="gw-want-sub">跳进对话告诉 AI，我们一起想。</div>
        </div>`;
      // ── theme + skin + want(原 binding,不动)──
      s.querySelector('#skin').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; st.theme = b.dataset.t; render(); });
      s.querySelectorAll('.gw-toggle').forEach((t) => t.addEventListener('click', () => t.classList.toggle('on')));
      s.querySelector('.gw-want').addEventListener('click', () => { st.subPage = null; st.tab = 'chat'; render(); setTimeout(() => { const ta = gw.querySelector('.gw-chat-input'); if (ta) { ta.value = '我想要'; ta.focus(); ta.dispatchEvent(new Event('input')); } }, 60); });

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

    render();
    return { setTheme: (t) => { st.theme = t; render(); }, state: st };
  };
})();
