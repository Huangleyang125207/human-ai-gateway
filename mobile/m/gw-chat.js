// gw-chat.js — 对话流 4 类消息(msg/ref/note/tool chip)+ 磨墨等待 + 流式
// chip 三态 doing/ok/fail 用 GW.toolLabel 翻自然句;永久留存,不可点开成面板(fail 可展开一行)
(function () {
  'use strict';
  const GW = window.GW;

  GW.renderThread = function (container, st) {
    container.innerHTML = '';
    st.thread.forEach((m) => container.appendChild(buildMsg(m)));
    scrollEnd(container);
  };

  function buildMsg(m) {
    if (m.kind === 'ref') {
      const n = div('gw-ref');
      n.innerHTML = `<div class="rk">${GW.esc(m.refKind)}</div><div class="rt">${GW.esc(m.refText)}</div>`;
      return n;
    }
    if (m.kind === 'note') {
      const n = div('gw-note' + (m._new ? ' unfold' : ''));
      n.innerHTML = `<div class="gw-note-time">${GW.esc(m.time)}</div>
        <div class="gw-note-body">${GW.gatewayMd(m.body)}</div>
        <div class="gw-note-sig">${GW.esc(m.sig || '')}</div>`;
      return n;
    }
    if (m.kind === 'tool') return buildChip(m);
    // msg
    const n = div('gw-msg ' + (m.who === 'me' ? 'me' : 'ai') + (m.streaming ? ' streaming' : '') + (m.err ? ' err' : ''));
    const who = m.who === 'me' ? '我' : 'Gateway';
    const text = m.who === 'ai' ? GW.gatewayMd(m.text) : `<div class="gw-msg-text">${GW.esc(m.text)}</div>`;
    n.innerHTML = `<span class="who">${who}</span>` +
      (m.who === 'ai' ? `<div class="gw-msg-text">${m.streaming ? GW.esc(m.text) : GW.gatewayMd(m.text)}</div>` : `<div class="gw-msg-text">${GW.esc(m.text)}</div>`) +
      (m.imgs ? `<div class="gw-msg-imgs">${m.imgs.map((u) => `<img src="${GW.esc(u)}" alt="">`).join('')}</div>` : '') +
      (m.err ? `<div class="gw-msg-err-note">没发出去 · 点一下重试</div>` : '');
    n.dataset.id = m.id || '';
    return n;
  }

  /* ── tool chip 三态 ── */
  function buildChip(m) {
    const icon = GW.ICON[GW.toolGroupIcon(m.name)] || GW.ICON.dot;
    const label = GW.toolLabel(m.name, m.args);
    const chip = div('gw-chip-tool ' + m.state);
    chip.dataset.id = m.id;
    let inner = `<span class="glyph">${icon}</span><span class="label">${label}</span>`;
    if (m.state === 'doing') inner += `<span class="ink-pulse"></span>`;
    else if (m.state === 'ok') inner += `<span class="seal-dot"></span>`;
    chip.innerHTML = inner;
    if (m.state === 'fail') {
      chip.addEventListener('click', () => {
        let r = chip.parentElement.querySelector('.gw-chip-fail-reason[data-for="' + m.id + '"]');
        if (r) { r.remove(); return; }
        r = div('gw-chip-fail-reason'); r.dataset.for = m.id; r.textContent = m.error || '出问题了';
        chip.after(r);
      });
    }
    return chip;
  }

  /* ── 发消息:用户 → 磨墨 → AI 流式(可带 tool chip)── */
  GW.sendChat = function (container, st, text, imgs) {
    if (!text && (!imgs || !imgs.length)) return;
    GW.scanIntent(text); // ⑥ 隐式意图信号(fire-and-forget)
    st.thread.push({ kind: 'msg', who: 'me', text: text, imgs: imgs });
    GW.renderThread(container, st);
    grind(container, st, function () {
      // 简单脚本化回应:含"改"→ 演示 chip 三态
      const wantPatch = /改|把.*那条|14:00|9:00/.test(text);
      if (imgs && imgs.length) pushChip(container, st, 'vision_classify', { attachment_url: 'cap_x.jpg' });
      if (wantPatch) pushChip(container, st, 'patch_journal_block', { time: '9:00' });
      const reply = wantPatch ? '改好了。9:00 那条标题已经更新，你滑回日记页能看到。'
        : (imgs && imgs.length) ? '是只橘猫，毛色偏深。要我把它做成贴纸贴到今天那条吗？'
        : '记下了。需要我夹批哪条，长按它拉给我就行。';
      streamAI(container, st, reply);
    });
  };

  function pushChip(container, st, name, args) {
    const id = 'tc' + Date.now() + Math.random().toString(36).slice(2, 5);
    st.thread.push({ kind: 'tool', id: id, name: name, args: args, state: 'doing' });
    GW.renderThread(container, st);
    setTimeout(() => {
      const m = st.thread.find((x) => x.id === id); if (m) m.state = 'ok';
      const chip = container.querySelector('.gw-chip-tool[data-id="' + id + '"]');
      if (chip) { chip.className = 'gw-chip-tool ok'; chip.querySelector('.ink-pulse')?.replaceWith(seal()); }
    }, 1100);
  }
  function seal() { const s = document.createElement('span'); s.className = 'seal-dot'; return s; }

  function grind(container, st, done) {
    const g = div('gw-grind'); g.innerHTML = `<span class="gw-grind-stone"></span><span class="gw-grind-text">磨墨中…</span>`;
    container.appendChild(g); scrollEnd(container);
    setTimeout(() => { g.remove(); done(); }, 1050);
  }

  function streamAI(container, st, full) {
    const id = 'a' + Date.now();
    st.thread.push({ kind: 'msg', who: 'ai', text: '', streaming: true, id: id });
    GW.renderThread(container, st);
    let i = 0;
    const iv = setInterval(() => {
      i++; const m = st.thread.find((x) => x.id === id); if (!m) { clearInterval(iv); return; }
      m.text = full.slice(0, i);
      const node = container.querySelector('.gw-msg[data-id="' + id + '"] .gw-msg-text');
      if (node) node.textContent = m.text;
      scrollEnd(container);
      if (i >= full.length) { clearInterval(iv); m.streaming = false; const mn = container.querySelector('.gw-msg[data-id="' + id + '"]'); if (mn) mn.classList.remove('streaming'); }
    }, 34);
  }

  function scrollEnd(container) { const sc = container.closest('.gw-scroll') || container; sc.scrollTop = sc.scrollHeight; }
  function div(cls) { const d = document.createElement('div'); d.className = cls; return d; }
})();
