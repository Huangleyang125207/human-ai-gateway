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
//   bus.on('reloadDay') → diff snapshot → POST insert-block / patch / delete-block
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
    // 失败必须可见:静默吞错让「界面显示写上了、盘上没有」成为可能(C1 教训)
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      if (r && !r.ok) {
        console.warn('[bridge] 写失败', url, r.status);
        try { GW.whisper('刚才没写进去 · 再试一次'); } catch (e) {}
      }
      return r;
    }).catch(function (e) {
      console.warn('[bridge] 写失败(网络)', url, e);
      try { GW.whisper('刚才没写进去 · 再试一次'); } catch (e2) {}
    });
  }

  // ──────────── 0+. thread 持久层守护:损坏 modal + CAS(桌面 5.17/5.26 两条铁律的移动镜像)────────────
  var threadMtime = null;      // CAS 基线:GET/save 返回的 mtime
  var threadCorrupt = null;    // 损坏未处理 = {baks};期间禁止 save 覆盖

  function mapThreadMsg(m, i) {
    // cd 原 schema 带 kind(msg/ref/note/tool)→ 原样保留。
    // ★不能要求 who:tool/ref/note 没有 who 字段,老条件把工具 chip 重载时碾成空 me 消息
    if (m && m.kind) return m;
    return {
      kind: 'msg',
      who: (m.role === 'assistant' || m.who === 'ai') ? 'ai' : 'me',
      text: m.content || m.text || '',
      id: m.id || ('t' + (m.ts || (Date.now() + i)))
    };
  }
  function applyThreadHistory(hist) {
    // 原地替换:st.thread === GW.thread 同一引用,reassign 会断链(gw-app 教训)
    var arr = (GW.state && GW.state.thread) || GW.thread || [];
    arr.length = 0;
    Array.prototype.push.apply(arr, (hist || []).map(mapThreadMsg));
    GW.thread = arr;
    return arr;
  }
  function reloadThreadFromStore() {
    return window.fetch('/api/thread/history').then(function (r) { return r.json(); }).then(function (h) {
      if (h && h.status === 'corrupt') {
        if (!threadCorrupt) { threadCorrupt = { baks: h.baks || [] }; showThreadCorruptSheet(); }
        return null;
      }
      if (h && h.mtime != null) threadMtime = h.mtime;
      return applyThreadHistory((h && h.history) || []);
    });
  }
  function saveThread(st, container) {
    if (threadCorrupt) { try { GW.whisper('对话记录损坏还没处理 · 先不写入'); } catch (e) {} return Promise.resolve(); }
    return window.fetch('/api/thread/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ history: st.thread, base_mtime: threadMtime })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.status === 409) {
          // 陈旧基线 → 放弃本地覆盖,改拉 server(对齐桌面 CAS 行为)
          console.warn('[bridge] thread save 409 — 放弃覆盖,拉 server 最新');
          return reloadThreadFromStore().then(function (arr) {
            if (arr && container && GW.state) { try { GW.renderThread(container, GW.state); } catch (e) {} }
            try { GW.whisper('对话在别处更新过 · 已同步最新'); } catch (e2) {}
          });
        }
        if (!r.ok) {
          console.warn('[bridge] thread save 失败', r.status, d);
          try { GW.whisper('对话没存上 · 稍后再试'); } catch (e) {}
          return;
        }
        if (d && d.mtime != null) threadMtime = d.mtime;
      });
    }).catch(function (e) {
      console.warn('[bridge] thread save 网络失败', e);
      try { GW.whisper('对话没存上 · 稍后再试'); } catch (e2) {}
    });
  }
  // ★ 聊天照片气泡渲染:thread 只存 /attachments/ 短路径,<img> 不走 shim fetch 拦截,
  //   渲染前查内存 cache → miss 再走 /api/attachment-data 解析成 dataURL(同 scrapbook 手法)
  GW.resolveImg = function (path) {
    GW._imgCache = GW._imgCache || {};
    if (GW._imgCache[path]) return Promise.resolve(GW._imgCache[path]);
    return window.fetch('/api/attachment-data?url=' + encodeURIComponent(path))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.dataUrl) { GW._imgCache[path] = d.dataUrl; return d.dataUrl; }
        return null;
      }).catch(function () { return null; });
  };

  function showThreadCorruptSheet() {
    if (!GW.root) { setTimeout(showThreadCorruptSheet, 600); return; }  // boot 早于 mount 时等挂载
    if (typeof GW.mountModal !== 'function') { try { GW.whisper('对话记录损坏 · 已暂停写入保护现场'); } catch (e) {} return; }
    var baks = (threadCorrupt && threadCorrupt.baks) || [];
    var sheet = document.createElement('div'); sheet.className = 'gw-sheet';
    sheet.innerHTML = '<div class="gw-grip"></div>' +
      '<div class="gw-sheet-head">对话记录文件损坏了<span class="sub">选个处理方式 · 处理前不会写入覆盖</span></div>' +
      (baks.length ? '<button class="gw-sheet-item" data-act="restore">从最近的备份恢复</button>' : '') +
      '<button class="gw-sheet-item" data-act="fresh">不要旧记录 · 空白重来</button>';
    var m = GW.mountModal(sheet);
    sheet.addEventListener('click', function (e) {
      var b = e.target.closest('.gw-sheet-item'); if (!b) return;
      if (b.dataset.act === 'restore') {
        var idx = (baks[0] && baks[0].index) || 1;
        window.fetch('/api/thread/restore-from-bak', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bak_index: idx })
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (!j || !j.ok) { try { GW.whisper((j && j.error) || '恢复失败 · 试试空白重来'); } catch (e2) {} return; }
          threadCorrupt = null;
          if (j.mtime != null) threadMtime = j.mtime;
          return reloadThreadFromStore().then(function () {
            try { GW.whisper('已从备份恢复对话'); } catch (e3) {}
            m.close();
          });
        }).catch(function () { try { GW.whisper('恢复失败 · 存储出问题了'); } catch (e4) {} });
      } else if (b.dataset.act === 'fresh') {
        threadCorrupt = null;
        applyThreadHistory([]);
        // base_mtime=null 首写放行 → 覆盖损坏文件,重建 CAS 基线
        window.fetch('/api/thread/save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ history: [], base_mtime: null })
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (j && j.mtime != null) threadMtime = j.mtime;
        }).catch(function () {});
        m.close();
      }
    });
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

  GW.bridgePrefetch = async function (targetIso) {
    // FIX C — 接受 targetIso(补昨天/历史日 chat 后应刷新对应日);默认 today
    targetIso = targetIso || todayIso();
    var iso = targetIso;
    var dayKey = isoToKey(iso);

    // 3a. days list — 最近 10 天的可读区
    // FIX C 注:days endpoint 不用 targetIso,'today' state 永远锚在真今天(墙上日历)
    try {
      var realToday = todayIso();
      var daysData = await safeJson('/api/journal/days?n=10');
      var realDays = (daysData.days || []).map(function (d) {
        var diso = d.iso || d.date || realToday;
        return {
          key: isoToKey(diso),
          iso: diso,
          dow: dowOf(diso),
          num: parseInt(diso.split('-')[2], 10),
          state: diso === realToday ? 'today' : 'past'
        };
      });
      if (!realDays.find(function (x) { return x.iso === realToday; })) {
        realDays.push({ key: isoToKey(realToday), iso: realToday, dow: dowOf(realToday), num: parseInt(realToday.split('-')[2], 10), state: 'today' });
      }
      // 明天的"+"位:真日期带原本从不产出 creatable(只有 mock 有),pickDay 的创建交互
      // 在真机永远不可达 — 补上,与 new-day 的「最多建到明天」上限同权
      var tmD = new Date(); tmD.setDate(tmD.getDate() + 1);
      var tmIso = tmD.getFullYear() + '-' + pad2(tmD.getMonth() + 1) + '-' + pad2(tmD.getDate());
      if (!realDays.find(function (x) { return x.iso === tmIso; })) {
        realDays.push({ key: isoToKey(tmIso), iso: tmIso, dow: dowOf(tmIso), num: parseInt(tmIso.split('-')[2], 10), state: 'creatable' });
      }
      // 排序:从早到晚
      realDays.sort(function (a, b) { return a.iso < b.iso ? -1 : a.iso > b.iso ? 1 : 0; });
      GW.days = function () { return realDays; };
    } catch (e) { console.warn('[bridge] /api/journal/days 失败,沿用 mock', e); }

    // 3a+. 当天骨架幂等确保:seed 只在首装跑一次,种子日之后没人建当天 md,
    //      写操作(落笔/打卡/喝水)会一路 404 且被静默吞掉 → 重启全丢。
    //      开机建一次,已存在就是 no-op(new-day 幂等)。
    try {
      var ndr = await window.fetch('/api/journal/new-day', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: todayIso() })
      }).then(function (r) { return r.json(); });
      if (ndr && ndr.created) console.log('[bridge] 今天的日记骨架已创建');
    } catch (e) { console.warn('[bridge] new-day 确保失败', e); }

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
          remaining: typeof t.remaining === 'number' ? t.remaining : null,
          image_url: t.image_url || null
        };
      });
      // 八杯水图标(用户上传的水杯抠图)— 对齐 PC ritual.js _cupImageUrl
      try {
        var wc = await safeJson('/api/water-cup');
        var cupUrl = (wc && wc.image_url) || null;
        // /attachments/ 短路径 <img> 不走 shim 拦截 → 解析成 dataURL(同聊天照片气泡)
        if (cupUrl && cupUrl.indexOf('/attachments/') === 0 && GW.resolveImg) cupUrl = await GW.resolveImg(cupUrl);
        GW.cupImageUrl = cupUrl;
      } catch (e) { GW.cupImageUrl = null; }
    } catch (e) { console.warn('[bridge] /api/daily-tasks 失败,沿用 mock', e); }

    // ★ 招牌:21:30 lazy 纸条 —— app 打开若当天 21:30 是占位 ##,AI 据 past_boards(过去7晚自己的纸条)
    //   写一段;放在 journal prefetch 之前,这样下面拉 journal 自然带上写好的纸条
    try { await window.fetch('/api/note/check-lazy', { method: 'POST' }).then(function (r) { return r.json(); }); } catch (e) {}

    // 3c. today 日记 entries — mobile-api 真返 schema:
    //  { file, date, blocks: [{ time, h1_raw, h2: [{tags, title, body, commits}] }] }
    // 一个 H1 时间块可含多个 H2 entry,flatten 成 cd entry list
    try {
      var todayData = await safeJson('/api/journal/today?date=' + iso);
      GW.journal = GW.journal || {};
      var flatEntries = [];
      var idx = 0;
      (todayData.blocks || []).forEach(function (b) {
        var t = b.time || '00:00';
        (b.h2 || []).forEach(function (h) {
          // server.py parse_journal 把 @author marker 泄漏进 h.title 末尾、commit 留整行字符串。
          // 抽 marker 给 _authorMark(compose 原样回写,原块无 marker → null → patch 不凭空加);
          // commit 解析成 {who,text,raw},raw 留作 byte 回写。
          var pa = parseH2Author(h.title || '');
          flatEntries.push({
            id: 'r' + t.replace(':', '') + '_' + (idx++),
            time: t,
            tags: (h.tags || []).map(function (tg) { return tg.charAt(0) === '#' ? tg : '#' + tg; }),
            author: pa.mark === 'ai' ? '@ai' : '@我',   // gw-journal 题签显示用
            _authorMark: pa.mark,                        // 'ai' | 'user' | null —— compose 原样回写
            title: pa.title,
            body: h.body || '',
            commits: (h.commits || []).map(parseCommitLine),
            isNote: /21\s*[:：]?\s*30/.test(t) && /纸条/.test(pa.title)
          });
        });
      });
      GW.journal[dayKey] = flatEntries;
      // ★ 招牌:21:30 纸条状态 —— 21:30 块有真 body 即"已写"(喂 gw-app st.noteWritten + 总览状态行)
      GW.noteWritten = flatEntries.some(function (e) { return /21\s*[:：]\s*30/.test(e.time) && (e.body || '').trim(); });
      // FIX A(a) — seed snapshot 防 first reloadDay 把 prefetch 来的 entries 当用户新增 POST insert-block(造成服务端 H2 重复)
      _journalSnap[dayKey] = snapshotEntries(flatEntries);
    } catch (e) { console.warn('[bridge] /api/journal/today 失败,沿用 mock', e); }

    // ★ scrapbook 贴纸 —— 读 /api/scrapbook 进 GW.scrapbook(buildEntry 按 anchor_time 浮进对应块)
    try { var sb = await safeJson('/api/scrapbook?date=' + iso); GW.scrapbook = (sb && sb.items) || []; } catch (e) { GW.scrapbook = []; }
    GW.scrapbookDate = iso;  // Phase3 贴纸编辑(拖拽/缩放/删除)持久化到这天

    // 3d. thread history
    // mobile-api 直接 JSON.stringify 存读 thread array,save 啥 read 啥。
    // 所以保留 cd 原 schema({kind,who,text,id,attachments?})— 不双向 transform。
    // 旧版本可能存的是 {role, content} 老格式,做 backward compat。
    try {
      var threadData = await safeJson('/api/thread/history');
      if (threadData.status === 'corrupt') {
        // 5.17 铁律的移动镜像:损坏绝不能静默当空(原来 hist=[] 无 modal,下一条消息就覆盖全部旧对话)
        console.warn('[bridge] thread corrupt — 弹恢复选择,期间禁写');
        if (!threadCorrupt) {
          threadCorrupt = { baks: threadData.baks || [] };
          if (!GW.state) GW.thread = [];   // boot:别把 mock 样例当历史;运行中:内存对话保留不动
          showThreadCorruptSheet();
        }
      } else {
        threadCorrupt = null;
        if (threadData.mtime != null) threadMtime = threadData.mtime;
        GW.thread = (threadData.history || []).map(mapThreadMsg);
      }
    } catch (e) { console.warn('[bridge] /api/thread/history 失败,沿用 mock', e); }

    // 3e. bind 写操作 bus hook(必须在 prefetch 完才挂,免得 mount 早期误触)
    bindWriteHooks();
  };

  // ──────────── 4. 写操作 bus hook ────────────
  // 4a. 喝水 / 打卡 — emit('pulse') 触发 sync(去重避免一秒多次 POST)
  var _pulseQ = null;
  function bindWriteHooks() {
    if (!GW.bus) return;
    // FIX G — idempotent guard:bridgePrefetch 可被 done 分支多次调,避免重复注册 listener leak
    if (GW._hooksBound) return;
    GW._hooksBound = true;

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
    var dayObj = (typeof GW.days === 'function' ? GW.days() : []).find(function (x) { return x.key === st.dayKey; });
    var iso = dayObj ? dayObj.iso : todayIso();
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
  // ── parse_journal 的逆运算(byte 对齐桌面 server.py,跨端 git-sync 字节兼容)──
  // server.py parse_journal 不剥 @author marker,它泄漏进 title 末尾。抽出来:
  // 返 {mark:'ai'|'user'|null, title:去 marker 后的纯标题}。末尾锚 → 不碰标题内部字节;
  // marker 若在中间(罕见/手写畸形)则留在 title 里照样原样回写,仍 byte-identical。
  function parseH2Author(rawTitle) {
    rawTitle = rawTitle || '';
    var m = /\s*@(user|ai)\b\s*$/.exec(rawTitle);
    if (!m) return { mark: null, title: rawTitle.trim() };
    return { mark: m[1], title: rawTitle.slice(0, m.index).trim() };
  }

  // 一条 #commit 行 → {who,text,raw}。raw 整行原样留作 byte 回写(全角/半角变体不归一,
  // 免 git 伪 diff);who/text 仅供 gw-journal 夹批题签(批/我)显示,错了不污染字节。
  // 兼容:`- #commit（claude-opus-4.8）： text` / `#commit (claude-opus-4.7): text`
  function parseCommitLine(raw) {
    raw = String(raw == null ? '' : raw);
    var m = /#commit\s*[（(]\s*([^）)]*?)\s*[）)]\s*[:：]\s*([\s\S]*)$/.exec(raw);
    var who = 'me', text = raw.replace(/^[\s-]*#commit\s*/, '').trim();
    if (m) {
      text = m[2].trim();
      // 模型名 → ai;用户手柄 → me(失败安全默认 me)
      if (/claude|gpt|opus|sonnet|deepseek|minimax|gemini|\bai\b/i.test(m[1])) who = 'ai';
    }
    return { who: who, text: text, raw: raw };
  }

  // model → canonical H2 块。形态:`## #tags 内联title [@user|@ai]` + 空行 + body
  //   [+ 空行 + 原样 #commit 行]。铁律(对齐桌面 / 修复跨端 byte 兼容):
  //   ① 时间只在 H1,绝不进 H2  ② title 内联,不写 ### H3  ③ @author 仅当原块本就有
  //   ④ #commit 整行 raw 回写(authorship Cannot-break:@user 块/批注字节不可被改写,6.16 丢批注)
  function composeEntryMd(e) {
    var tagLine = (e.tags || []).join(' ');
    var title = e.title || '';
    var h2 = '## ' + tagLine
      + (title ? (tagLine ? ' ' : '') + title : '')
      + (e._authorMark ? ' @' + e._authorMark : '');
    var out = h2 + '\n\n' + (e.body || '');
    var commitRaws = (e.commits || []).map(function (c) { return c && c.raw; }).filter(Boolean);
    if (commitRaws.length) out += '\n\n' + commitRaws.join('\n');
    return out;
  }

  // ──────────── 5. sendChat 真 SSE 流式 ────────────
  // 替 cd gw-chat.js 内 streamAI(setTimeout 模拟)→ 真 fetch /api/chat 流
  GW.sendChat = async function (container, st, text, imgs) {
    if (!text && (!imgs || !imgs.length)) return;

    // user message 立刻进 thread
    var userId = 'u' + Date.now();
    var userMsg = {
      kind: 'msg', who: 'me', text: text || '', id: userId
    };
    // ★ 7.5 OOM 崩溃根因:thread 里存 dataURL(imgs+attachments 三份拷贝)→ thread.json 13MB
    //   → saveThread 过 Capacitor 桥 JSONTokener 47MB 分配打爆 256MB Java 堆(dropbox 实锤)。
    //   契约改为:先上传拿 /attachments/ 短路径,thread 只存路径;dataURL 只进内存 cache 供即时渲染。
    var refs = [];
    if (imgs && imgs.length) {
      var paths = [];
      for (var ri = 0; ri < imgs.length; ri++) {
        var _it = imgs[ri]; var _du = (_it && _it.u) ? _it.u : _it;
        try {
          var up = await fetch('/api/chat/upload-image', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dataUrl: _du }) }).then(function (r) { return r.json(); });
          if (up && up.url) {
            GW._imgCache = GW._imgCache || {};
            GW._imgCache[up.url] = _du;
            paths.push(up.url);
            refs.push({ url: up.url, cutout: !(_it && _it.cut === false) });
          } else { try { GW.whisper('第 ' + (ri + 1) + ' 张图没存上 · AI 这轮看不到它'); } catch (e2) {} }
        } catch (e) { try { GW.whisper('第 ' + (ri + 1) + ' 张图没存上 · AI 这轮看不到它'); } catch (e2) {} }
      }
      if (paths.length) {
        userMsg.imgs = paths;
        userMsg.attachments = paths.map(function (p) { return { url: p }; });
      }
    }
    st.thread.push(userMsg);
    GW.renderThread(container, st);
    // ★ 早持久化:崩溃/被 OEM 杀(拍照 intent 期间常见)不再吞掉整轮 —— 用户消息先落盘
    saveThread(st, container);

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

    // mobile-api.js chatViaDeepseek 期待:body = { history: [全部历史含 cd 4 kind], message: "最新用户消息" }
    // L988: messages = sys + histToMsgs(body.history) + [{role:user, content:body.message}]
    // histToMsgs 已 cd 4 kind:msg/ref/note/tool — 我传整条 thread(去掉本轮 user)就行
    var historyForApi = st.thread.slice(0, -1);  // 去掉刚 push 的 user msg(它进 body.message)

    // (贴图上传已在 push userMsg 前完成 — refs 供 AI place_scrapbook_image 引用)
    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ history: historyForApi, message: text || '', refs: refs })
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
              // 终稿必须全量重渲:流式期间正文是 textContent 纯文本,
              // 不重渲 = 刚收到的回复里链接/加粗永远不过 gatewayMd,链接点不了
              GW.renderThread(container, st);
            } else {
              grindEl.remove();
            }
            // 保存 thread 到后端 — 带 base_mtime 走 CAS,409 放弃覆盖改拉 server;
            // 损坏未处理时 saveThread 拒写(cd 原 schema 含 tool/ref/note 三个 kind,save 啥 read 啥)
            saveThread(st, container);
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
              // FIX A(b) — 不在 tool_result 重复 reloadDay+bridgePrefetch;done 分支唯一收口
              // (tool chip 状态已在上方 tc.state/result 更新;syncJournalDiff 跑两遍会把 prefetch 来的 entries 当新增 POST insert-block)
            } else if (ev.type === 'error') {
              // mobile-api emit error(CORS / 超时 / DeepSeek 返空 / 工具上限)
              if (!firstChunkSeen) {
                firstChunkSeen = true;
                if (grindEl.parentNode) grindEl.remove();
                st.thread.push({ kind: 'msg', who: 'ai', text: '⚠ ' + (ev.text || '出错了'), id: aiId });
                GW.renderThread(container, st);
              } else {
                aiText += '\n\n⚠ ' + (ev.text || '出错了');
                var em = st.thread.find(function (x) { return x.id === aiId; });
                if (em) em.text = aiText;
                var enode = container.querySelector('.gw-msg[data-id="' + aiId + '"] .gw-msg-text');
                if (enode) enode.textContent = aiText;
              }
            } else if (ev.type === 'done') {
              // server emit done — pump 自然 r.done 也会到,这里早 break 让 finally 清理
              if (firstChunkSeen) {
                var dm = st.thread.find(function (x) { return x.id === aiId; });
                if (dm) dm.streaming = false;
              } else if (!firstChunkSeen) {
                // 走到 done 但一个 delta 都没收 → 退磨墨 + push 占位
                if (grindEl.parentNode) grindEl.remove();
                st.thread.push({ kind: 'msg', who: 'ai', text: '(无回复)', id: aiId });
                GW.renderThread(container, st);
              }
              // AI 换过水杯图 → 重取 + 解析,reloadDay 重渲时打卡区立即见新图
              try {
                if (st.thread.some(function (x) { return x && x.kind === 'tool' && x.name === 'set_water_cup_image' && x.state === 'ok'; })) {
                  window.fetch('/api/water-cup').then(function (r) { return r.json(); }).then(function (wc2) {
                    var u2 = (wc2 && wc2.image_url) || null;
                    if (u2 && u2.indexOf('/attachments/') === 0 && GW.resolveImg) return GW.resolveImg(u2).then(function (du) { GW.cupImageUrl = du; });
                    GW.cupImageUrl = u2;
                  }).then(function () {
                    // reloadDay/reloadCare 有 tab==='journal' 守卫,换图时用户正在对话页会被跳过;
                    // 双页 pager 两页 DOM 常驻 → 直接重画 care,滑回日记即见新图
                    var careEl = document.querySelector('.gw-care');
                    if (careEl && GW.renderCare && GW.state) GW.renderCare(careEl, GW.state);
                  }).catch(function () {});
                }
              } catch (e) {}
              // AI 写完 md 后 → 刷新内存 GW.journal[dayKey] + 时间线重渲(spec case 1 ⑥)
              // FIX C — 用当前 selected day 的 iso(补昨天/历史日时不会错刷今天)
              // FIX A.c — emit('reloadDay') 在 bridgePrefetch resolve 之后:
              //   reloadDay handler 读 GW.journal[dayKey] 重渲 timeline;
              //   prefetch 前 emit 会读到 stale,resolve 后再 emit 才能看到 AI 新写的 entry
              if (GW.bridgePrefetch) {
                var curIso = todayIso();
                try {
                  var curDayKey = (GW.state && GW.state.dayKey) || null;
                  if (curDayKey && typeof GW.days === 'function') {
                    var curDayObj = GW.days().find(function (x) { return x.key === curDayKey; });
                    if (curDayObj && curDayObj.iso) curIso = curDayObj.iso;
                  }
                } catch (e) {}
                GW.bridgePrefetch(curIso).then(function () {
                  GW.bus && GW.bus.emit('reloadDay');
                }).catch(function () {
                  // prefetch 挂了仍 emit,让 timeline 至少触发 renderTimeline(可能读到 stale 但比不刷强)
                  GW.bus && GW.bus.emit('reloadDay');
                });
              } else {
                GW.bus && GW.bus.emit('reloadDay');
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
        text: '(出错了:' + (e && e.message || '未知') + ')',
        id: aiId
      });
      GW.renderThread(container, st);
    });
  };

  console.log('[gw-real-bridge] 接通 mobile-api shim:gatewayMd/scanIntent/sendChat + bridgePrefetch + pulse/reloadDay hooks');
})();
