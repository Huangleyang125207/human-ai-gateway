// gw-real-bridge.js — 接通 cd 5 件套 mock → mobile-api.js shim 22 tool 真后端
//
// load 时机:在 gw-mock.js 之后(继承 GW.MOODS/ICON/toolLabel/SUGGEST_TAGS 等常量),
//          在 gw-widgets/journal/chat/app.js 之前(让它们读到 patched 后的 GW.*)。
// 由 index.html await GW.bridgePrefetch() 后再 GW.mount() — async 数据 prefetch
// 同步进 GW.tasks/water/journal/thread/days,cd 那 4 个 js sync 读不到 stale mock。
//
// Patch 面(8 个 P0):
//   GW.gatewayMd       → window.gatewayMd(marked + DOMPurify)
//   GW.scanIntent      → window.scanUserIntent(真 SIGNAL_SINK_URL)
//   GW.days/tasks/water/journal/thread — async prefetch 进真数据
//   GW.sendChat        → /api/chat SSE 真流式 + tool chip 三态
//   bus.on('pulse')    → POST /api/daily-tasks/{water,check}(滑/打)
//   bus.on('reloadDay') → diff snapshot → POST /api/journal/{insert-block,patch,delete-block}
//
// 红线:cd 5 件套字节不改,bridge 是 monkey-patch + 监听层。

(function () {
  'use strict';
  var GW = window.GW;
  if (!GW) { console.warn('[gw-real-bridge] GW 不存在,跳过'); return; }

  // ──────────── 工具 ────────────
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }
  function isoToKey(iso) { return iso.slice(5); }  // '2026-06-25' → '06-25'
  function dowOf(iso) {
    var dt = new Date(iso + 'T00:00:00');
    return ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'][dt.getDay()];
  }
  function safeJson(url, opts) {
    return fetch(url, opts || {}).then(function (r) {
      if (!r.ok) throw new Error(url + ' ' + r.status);
      return r.json();
    });
  }
  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).catch(function () { /* fire-and-forget */ });
  }

  // ──────────── 1. 真 markdown(替 cd stub)────────────
  if (typeof window.gatewayMd === 'function') {
    GW.gatewayMd = function (s) { return window.gatewayMd(s || ''); };
  }

  // ──────────── 2. 真信号采集(替 cd stub)────────────
  if (typeof window.scanUserIntent === 'function') {
    GW.scanIntent = function (text) {
      try { window.scanUserIntent(text); } catch (e) {}
    };
  }

  // ──────────── 3. async prefetch:真后端数据进 GW.* ────────────
  // entry id 规则:'r' + time(无:) + idx — bridge 与 backend 唯一锚点
  function entryId(e, i) { return 'r' + (e.time || '00:00').replace(':', '') + '_' + i; }

  GW.bridgePrefetch = async function () {
    var iso = todayIso();
    var dayKey = isoToKey(iso);

    // 3a. days list — 最近 10 天的可读区
    try {
      var daysData = await safeJson('/api/journal/days?n=10');
      var realDays = (daysData.days || []).map(function (d) {
        var diso = d.iso || d.date || iso;
        return {
          key: isoToKey(diso),
          iso: diso,
          dow: dowOf(diso),
          num: parseInt(diso.split('-')[2], 10),
          state: diso === iso ? 'today' : 'past'
        };
      });
      if (!realDays.find(function (x) { return x.iso === iso; })) {
        realDays.push({ key: dayKey, iso: iso, dow: dowOf(iso), num: parseInt(iso.split('-')[2], 10), state: 'today' });
      }
      // 排序:从早到晚
      realDays.sort(function (a, b) { return a.iso < b.iso ? -1 : a.iso > b.iso ? 1 : 0; });
      GW.days = function () { return realDays; };
    } catch (e) { console.warn('[bridge] /api/journal/days 失败,沿用 mock', e); }

    // 3b. tasks + water(同一 endpoint 返)
    try {
      var catalog = await safeJson('/api/daily-tasks?date=' + iso);
      GW.water = (catalog.water_filled | 0);
      GW.tasks = (catalog.tasks || []).map(function (t) {
        var dose = Math.max(1, (t.daily_dose | 0) || 1);
        return {
          name: t.name,
          glyph: t.image_url ? '' : (t.name || '·').charAt(0),
          today_intake: t.today_intake | 0,
          daily_dose: dose,
          days_left: typeof t.days_left === 'number' ? t.days_left : undefined,
          image_url: t.image_url || null
        };
      });
    } catch (e) { console.warn('[bridge] /api/daily-tasks 失败,沿用 mock', e); }

    // 3c. today 日记 entries
    try {
      var todayData = await safeJson('/api/journal/today?date=' + iso);
      GW.journal = GW.journal || {};
      GW.journal[dayKey] = (todayData.entries || []).map(function (e, i) {
        return {
          id: entryId(e, i),
          time: e.time || '00:00',
          tags: e.tags || [],
          author: e.author === 'ai' ? '@ai' : '@我',
          title: e.title || '',
          body: e.body || '',
          commits: (e.commits || []).map(function (c) {
            return { who: c.author === 'ai' ? 'ai' : 'me', text: c.text || '' };
          }),
          isNote: /21\s*[:：]\s*30/.test(e.time || '')  // 21:30 纸条
        };
      });
    } catch (e) { console.warn('[bridge] /api/journal/today 失败,沿用 mock', e); }

    // 3d. thread history
    try {
      var threadData = await safeJson('/api/thread/history');
      var hist = threadData.history || threadData.messages || [];
      if (threadData.status === 'corrupt') {
        console.warn('[bridge] thread corrupt,modal 兜底由 cd 自处理');
        hist = [];
      }
      GW.thread = hist.map(function (m, i) {
        return {
          kind: 'msg',
          who: m.role === 'assistant' || m.who === 'ai' ? 'ai' : 'me',
          text: m.content || m.text || '',
          id: 't' + (m.ts || (Date.now() + i))
        };
      });
    } catch (e) { console.warn('[bridge] /api/thread/history 失败,沿用 mock', e); }

    // 3e. bind 写操作 bus hook(必须在 prefetch 完才挂,免得 mount 早期误触)
    bindWriteHooks();
  };

  // ──────────── 4. 写操作 bus hook ────────────
  // 4a. 喝水 / 打卡 — emit('pulse') 触发 sync(去重避免一秒多次 POST)
  var _pulseQ = null;
  function bindWriteHooks() {
    if (!GW.bus) return;

    GW.bus.on('pulse', function () {
      // 防抖 250ms — 滑动八杯水会快速触发,合并成最后一次
      clearTimeout(_pulseQ);
      _pulseQ = setTimeout(syncPulseState, 250);
    });

    GW.bus.on('reloadDay', function () {
      // 同步当天 journal entry 变更 → 真 vault md
      syncJournalDiff();
    });
  }

  function syncPulseState() {
    var st = GW.state; if (!st) return;
    var iso = todayIso();
    // water
    postJson('/api/daily-tasks/water', { date: iso, filled: st.water | 0 });
    // tasks — 整批同步当前 intake(check endpoint clamp 后端处理)
    (st.tasks || []).forEach(function (t) {
      postJson('/api/daily-tasks/check', {
        date: iso,
        task_name: t.name,
        intake: t.today_intake | 0
      });
    });
  }

  // 4b. journal diff snapshot — 增 / 删 / 改 三路 POST
  var _journalSnap = {};  // dayKey → [{id, time, body, title, tags}]
  function snapshotEntries(entries) {
    return (entries || []).map(function (e) {
      return {
        id: e.id, time: e.time, body: e.body || '',
        title: e.title || '', tags: (e.tags || []).slice()
      };
    });
  }
  function syncJournalDiff() {
    var st = GW.state; if (!st) return;
    var dayKey = st.dayKey;
    var dayObj = (typeof GW.days === 'function' ? GW.days() : []).find(function (x) { return x.key === dayKey; });
    var iso = dayObj ? dayObj.iso : todayIso();
    var nowEntries = GW.journal[dayKey] || [];
    var snap = _journalSnap[dayKey] || [];
    var snapById = {}; snap.forEach(function (e) { snapById[e.id] = e; });
    var nowById = {}; nowEntries.forEach(function (e) { nowById[e.id] = e; });

    // 新增(在 now 不在 snap)
    nowEntries.forEach(function (e) {
      if (!snapById[e.id]) {
        postJson('/api/journal/insert-block', {
          date: iso, time: e.time,
          tag: (e.tags && e.tags[0]) || '#杂',
          title: e.title || '',
          body: e.body || ''
        });
      }
    });
    // 删除(在 snap 不在 now)
    snap.forEach(function (e) {
      if (!nowById[e.id]) {
        postJson('/api/journal/delete-block', { date: iso, time: e.time });
      }
    });
    // 修改(同 id,body/title/tags 任一不同)
    nowEntries.forEach(function (e) {
      var old = snapById[e.id]; if (!old) return;
      var changed = old.body !== (e.body || '') ||
                    old.title !== (e.title || '') ||
                    JSON.stringify(old.tags || []) !== JSON.stringify(e.tags || []);
      if (changed) {
        // patch 必须拼回 commits(6.16 教训:patch 末尾不补 commits 会丢 @ai 批注)
        postJson('/api/journal/patch', {
          date: iso, time: e.time,
          new_md: composeEntryMd(e),
          author: 'user'
        });
      }
    });
    _journalSnap[dayKey] = snapshotEntries(nowEntries);
  }
  function composeEntryMd(e) {
    var tagLine = (e.tags || []).join(' ');
    var header = e.time + (tagLine ? ' ' + tagLine : '') + (e.author === '@ai' ? ' @ai' : ' @user');
    var titleLine = e.title ? '### ' + e.title + '\n' : '';
    var body = e.body || '';
    var commitBlock = (e.commits && e.commits.length)
      ? '\n\n<commit>\n' + e.commits.map(function (c) {
          return '@' + (c.who === 'ai' ? 'ai' : 'user') + ' ' + c.text;
        }).join('\n') + '\n</commit>'
      : '';
    return '## ' + header + '\n' + titleLine + body + commitBlock;
  }

  // ──────────── 5. sendChat 真 SSE 流式 ────────────
  // 替 cd gw-chat.js 内 streamAI(setTimeout 模拟)→ 真 fetch /api/chat 流
  GW.sendChat = function (container, st, text, imgs) {
    if (!text && (!imgs || !imgs.length)) return;

    // user message 立刻进 thread
    var userId = 'u' + Date.now();
    var userMsg = {
      kind: 'msg', who: 'me', text: text || '', id: userId
    };
    if (imgs && imgs.length) {
      userMsg.attachments = imgs.map(function (u) { return { dataUrl: u, url: u }; });
    }
    st.thread.push(userMsg);
    GW.renderThread(container, st);

    // 信号采集(真 sink)
    GW.scanIntent(text);

    // 磨墨墨石(等首个 delta 到才换 AI msg)
    var grindEl = document.createElement('div');
    grindEl.className = 'gw-grind';
    grindEl.innerHTML = '<span class="gw-grind-stone"></span><span class="gw-grind-text">磨墨中…</span>';
    container.appendChild(grindEl);
    var sc = container.closest('.gw-scroll') || container;
    sc.scrollTop = sc.scrollHeight;

    // SSE 真流式
    var aiId = 'a' + Date.now();
    var aiText = '';
    var firstChunkSeen = false;

    var messages = st.thread
      .filter(function (m) { return m.kind === 'msg'; })
      .map(function (m) {
        return { role: m.who === 'ai' ? 'assistant' : 'user', content: m.text || '' };
      });

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: messages })
    }).then(function (resp) {
      if (!resp.ok) throw new Error('chat ' + resp.status);
      var reader = resp.body.getReader();
      var decoder = new TextDecoder('utf-8');
      var buffer = '';
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) {
            if (firstChunkSeen) {
              var msg = st.thread.find(function (x) { return x.id === aiId; });
              if (msg) msg.streaming = false;
              var mn = container.querySelector('.gw-msg[data-id="' + aiId + '"]');
              if (mn) mn.classList.remove('streaming');
            } else {
              grindEl.remove();
            }
            // 保存 thread 到后端(append-only 持久化)
            postJson('/api/thread/save', {
              history: st.thread.filter(function (m) { return m.kind === 'msg'; }).map(function (m) {
                return { role: m.who === 'ai' ? 'assistant' : 'user', content: m.text, ts: Date.now() };
              })
            });
            return;
          }
          buffer += decoder.decode(r.value, { stream: true });
          var lines = buffer.split('\n');
          buffer = lines.pop() || '';
          lines.forEach(function (line) {
            if (!line.startsWith('data: ')) return;
            var payload = line.slice(6).trim();
            if (!payload || payload === '[DONE]') return;
            var ev;
            try { ev = JSON.parse(payload); } catch (e) { return; }

            if (ev.type === 'delta' && ev.text) {
              if (!firstChunkSeen) {
                firstChunkSeen = true;
                grindEl.remove();
                st.thread.push({ kind: 'msg', who: 'ai', text: '', streaming: true, id: aiId });
                GW.renderThread(container, st);
              }
              aiText += ev.text;
              var m = st.thread.find(function (x) { return x.id === aiId; });
              if (m) m.text = aiText;
              var node = container.querySelector('.gw-msg[data-id="' + aiId + '"] .gw-msg-text');
              if (node) node.textContent = aiText;
              sc.scrollTop = sc.scrollHeight;
            } else if (ev.type === 'tool_call' && ev.name) {
              // cd .gw-chip-tool 三态:doing → ok / fail
              var tcId = ev.id || ('tc' + Date.now());
              st.thread.push({
                kind: 'tool', name: ev.name, args: ev.args || {},
                state: 'doing', id: tcId
              });
              GW.renderThread(container, st);
            } else if (ev.type === 'tool_result' && ev.id) {
              var tc = st.thread.find(function (x) { return x.kind === 'tool' && x.id === ev.id; });
              if (tc) {
                tc.state = ev.ok === false ? 'fail' : 'ok';
                tc.result = ev.result;
              }
              GW.renderThread(container, st);
            } else if (ev.type === 'done') {
              // server emit done — pump 自然 r.done 也会到,这里早 break 让 finally 清理
              if (firstChunkSeen) {
                var dm = st.thread.find(function (x) { return x.id === aiId; });
                if (dm) dm.streaming = false;
              }
            }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (e) {
      if (grindEl.parentNode) grindEl.remove();
      st.thread.push({
        kind: 'msg', who: 'ai',
        text: '(chat 出错:' + (e && e.message || '未知') + ')',
        id: aiId
      });
      GW.renderThread(container, st);
    });
  };

  console.log('[gw-real-bridge] 接通 mobile-api shim:gatewayMd/scanIntent/sendChat + bridgePrefetch + pulse/reloadDay hooks');
})();
