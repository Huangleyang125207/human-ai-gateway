// mobile-api.js — 移动端本地"假后端"。
//
// 手法:最先加载,劫持 window.fetch。命中 MVP 名单的 /api/… 用手机本地存储
// 服务掉;其余 /api/… 返回良性占位;非 /api/… 透传给真 fetch(静态资源)。
//
// 守卫:只在「移动语境」启用 —— window.Capacitor 存在(真机) / URL 带 ?mobile=1
// (浏览器自测) / localStorage['__gateway_mobile__']==='1'。桌面真 server 下完全惰性。
//
// 存储后端:浏览器=localStorage(自测用);真机=@capacitor/filesystem(P1 后期换)。
// server.py 一行不改;本文件是拦截层,只重写约 10 个端点。
(function () {
  "use strict";

  // ── 守卫:是否启用拦截 ───────────────────────────────
  var ENABLED =
    (typeof window !== "undefined" && window.__GATEWAY_MOBILE__ === true) ||
    (typeof window !== "undefined" && window.Capacitor !== undefined) ||
    /[?&]mobile=1\b/.test(location.search) ||
    (function () { try { return localStorage.getItem("__gateway_mobile__") === "1"; } catch (e) { return false; } })();

  if (!ENABLED) return; // 桌面:惰性,真 fetch 照常走 server.py

  console.log("[mobile-api] 拦截层启用 — /api/* 走本地存储");

  // ── 存储抽象:浏览器(localStorage) / 真机(Capacitor Filesystem+Preferences)──
  // 同一套 getText/setText/keys 接口,按运行环境自动选后端,handlers 无感知。
  var NS = "gateway.mobile.";
  var LocalBackend = {
    getText: function (k) { try { return Promise.resolve(localStorage.getItem(NS + k)); } catch (e) { return Promise.resolve(null); } },
    setText: function (k, v) { try { localStorage.setItem(NS + k, v); } catch (e) {} return Promise.resolve(); },
    remove: function (k) { try { localStorage.removeItem(NS + k); } catch (e) {} return Promise.resolve(); },
    keys: function (prefix) {
      var out = [];
      try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k && k.indexOf(NS + prefix) === 0) out.push(k.slice(NS.length)); } } catch (e) {}
      return Promise.resolve(out);
    },
  };

  // 真机:日记/打卡/对话落文件(Directory.Data 应用私有区);设置/key 走 Preferences。
  var _cap = (typeof window !== "undefined" && window.Capacitor && window.Capacitor.Plugins) || null;
  var _fs = _cap && _cap.Filesystem, _prefs = _cap && _cap.Preferences;
  var DIR = "DATA";
  function capPath(k) {
    if (k.indexOf("journal/") === 0) return "gw/journal/" + isoToStem(k.slice(8)) + ".md";
    if (k === "daily-tasks") return "gw/daily-tasks.md";
    if (k === "thread") return "gw/thread.json";
    return "gw/kv/" + k.replace(/[^\w.-]/g, "_") + ".txt";
  }
  var CapacitorBackend = {
    getText: function (k) {
      if (k.indexOf("setting/") === 0 && _prefs) return _prefs.get({ key: k.slice(8) }).then(function (r) { return r && r.value != null ? r.value : null; }).catch(function () { return null; });
      return _fs.readFile({ path: capPath(k), directory: DIR, encoding: "utf8" }).then(function (r) { return r.data; }).catch(function () { return null; });
    },
    setText: function (k, v) {
      if (k.indexOf("setting/") === 0 && _prefs) return _prefs.set({ key: k.slice(8), value: v }).catch(function () {});
      return _fs.writeFile({ path: capPath(k), data: v, directory: DIR, encoding: "utf8", recursive: true }).catch(function (e) { console.error("[mobile-api] fs write 失败", k, e); });
    },
    remove: function (k) {
      if (k.indexOf("setting/") === 0 && _prefs) return _prefs.remove({ key: k.slice(8) }).catch(function () {});
      return _fs.deleteFile({ path: capPath(k), directory: DIR }).catch(function () {});
    },
    keys: function (prefix) {
      if (prefix.indexOf("journal/") === 0) {
        return _fs.readdir({ path: "gw/journal", directory: DIR }).then(function (r) {
          var files = (r && r.files) || [];
          return files.map(function (f) { var n = typeof f === "string" ? f : f.name; return "journal/" + stemToIso(n.replace(/\.md$/, "")); });
        }).catch(function () { return []; });
      }
      return Promise.resolve([]);
    },
  };

  var Backend = _fs ? CapacitorBackend : LocalBackend;
  console.log("[mobile-api] 存储后端 =", _fs ? "Capacitor Filesystem" : "localStorage(浏览器)");

  var Store = {
    readJournalMd: function (date) { return Backend.getText("journal/" + date); },
    writeJournalMd: function (date, md) { return Backend.setText("journal/" + date, md); },
    listJournalDates: function () {
      return Backend.keys("journal/").then(function (ks) {
        return ks.map(function (k) { return k.slice("journal/".length); }).sort();
      });
    },
    readDailyTasksMd: function () { return Backend.getText("daily-tasks"); },
    writeDailyTasksMd: function (md) { return Backend.setText("daily-tasks", md); },
    // 5.17 教训:损坏返 sentinel,绝不空 [] 当真覆盖(test_thread_routes corrupt 锁)
    readThread: function () {
      return Backend.getText("thread").then(function (t) {
        if (!t) return { ok: true, history: [] };
        try { return { ok: true, history: JSON.parse(t) }; }
        catch (e) { return { ok: false, corrupt: true, raw_bytes: t.length }; }
      });
    },
    writeThread: function (arr) {
      // 写前 rotate 5 份 bak(复刻桌面 _safe_write_text rotate=True);
      // 再落新 thread + 推进 mtime(CAS 用)。复刻 test_restore_from_bak_roundtrip 真值线。
      var mt = Date.now();
      return Store.rotateThreadBaks().then(function () {
        return Promise.all([
          Backend.setText("thread", JSON.stringify(arr || [])),
          Backend.setText("setting/thread_mtime", String(mt)),
        ]);
      }).then(function () { return mt; });
    },
    readThreadMtime: function () {
      return Backend.getText("setting/thread_mtime").then(function (s) {
        var v = parseInt(s, 10); return isNaN(v) ? 0 : v;  // 0 = 文件尚不存在,首次写放行
      });
    },
    // bak.5 删 → bak.4→bak.5 → ... → 当前→bak.1。无当前 thread 时 noop。
    rotateThreadBaks: function () {
      return Backend.getText("thread").then(function (cur) {
        if (cur == null) return;
        // 从 4→5, 3→4, 2→3, 1→2, current→1。bak.5 旧值丢弃。
        return Backend.getText("setting/thread_bak/4").then(function (b4) {
          return (b4 == null ? Promise.resolve() : Backend.setText("setting/thread_bak/5", b4));
        }).then(function () { return Backend.getText("setting/thread_bak/3"); }).then(function (b3) {
          return (b3 == null ? Promise.resolve() : Backend.setText("setting/thread_bak/4", b3));
        }).then(function () { return Backend.getText("setting/thread_bak/2"); }).then(function (b2) {
          return (b2 == null ? Promise.resolve() : Backend.setText("setting/thread_bak/3", b2));
        }).then(function () { return Backend.getText("setting/thread_bak/1"); }).then(function (b1) {
          return (b1 == null ? Promise.resolve() : Backend.setText("setting/thread_bak/2", b1));
        }).then(function () { return Backend.setText("setting/thread_bak/1", cur); });
      });
    },
    listThreadBaks: function () {
      // 扫 1..5,有则进列表(mobile 无 readdir,逐个尝试)
      var ps = [1, 2, 3, 4, 5].map(function (i) {
        return Backend.getText("setting/thread_bak/" + i).then(function (s) {
          return s == null ? null : { index: i, bytes: s.length };
        });
      });
      return Promise.all(ps).then(function (rs) { return rs.filter(Boolean); });
    },
    readThreadBakAt: function (idx) { return Backend.getText("setting/thread_bak/" + idx); },
    // 原损坏内容存 setting/thread_corrupted/<ts>(对齐桌面.corrupted.<ts> 备份策略)
    archiveCorruptedThread: function (raw) {
      var ts = Date.now();
      return Backend.setText("setting/thread_corrupted/" + ts, raw).then(function () { return ts; });
    },
    getSetting: function (k) { return Backend.getText("setting/" + k); },
    setSetting: function (k, v) { return Backend.setText("setting/" + k, v); },
    removeSetting: function (k) { return Backend.remove("setting/" + k); },
  };

  // ── 信号采集:⑤ E 极简观察 + ⑥ F user_intent,共享一个云端 sink ──
  // 设计契约:
  //  1) fire-and-forget — 失败静默不阻塞 UI(永远不 throw)
  //  2) 无持久化 — 仅 sessionStorage 临时 anon_sid,避免 iOS ATT 弹窗
  //  3) 无 PII — 对话原文不上报,只上报 kind + 200 字命中片段
  //  4) sink 失败容错 — server 未部署时 fetch fail 静默(行业 telemetry 标准做法)
  var SIGNAL_SINK_URL = "https://feedback.yanpaidb.cn/signal";
  function _anonSid() {
    try {
      var s = sessionStorage.getItem("gw.sid");
      if (!s) {
        s = "s-" + Math.random().toString(36).slice(2, 10);
        sessionStorage.setItem("gw.sid", s);
      }
      return s;
    } catch (e) { return "s-nostorage"; }
  }
  function emitSignal(kind, payload) {
    try {
      var body = JSON.stringify({
        kind: kind, payload: payload || {},
        platform: "mobile-ios", ts: Date.now(),
        anon_sid: _anonSid(),
      });
      // realFetch 是 shim hijack 前 cache 的原 fetch(避免被 mobile-api.js 自身的 /api/* 路由拦)
      if (typeof realFetch === "function") {
        realFetch(SIGNAL_SINK_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: body }).catch(function () {});
      }
    } catch (e) {}
  }
  // ⑥ F 隐式信号:sendChat 前扫词,命中关键词 emit user_intent
  function scanUserIntent(text) {
    if (!text || typeof text !== "string") return;
    var KW = {
      want_widget: /想加|想要 ?widget|搞个面板|加打卡|加 ?widget/,
      want_paper: /界面太普通|太简洁|想要纸感|有质感|想要纸/,
      want_desktop_parity: /像桌面那样|跟桌面一样|桌面有手机没有/,
    };
    for (var k in KW) {
      try { if (KW[k].test(text)) emitSignal(k, { excerpt: text.slice(0, 200) }); } catch (e) {}
    }
  }
  // expose 给 mobile.js 调用(IIFE 外的 UI 代码 emit 显式信号)
  if (typeof window !== "undefined") {
    window.emitSignal = emitSignal;
    window.scanUserIntent = scanUserIntent;
  }
  // ⑤ E 全局错误捕获:onerror + unhandledrejection 双轨,只盖硬错误
  if (typeof window !== "undefined" && !window.__GW_SIGNAL_BOUND__) {
    window.__GW_SIGNAL_BOUND__ = true;
    window.addEventListener("error", function (e) {
      try { emitSignal("error.runtime", { msg: (e && e.message || "").slice(0, 200), src: (e && e.filename || "").slice(0, 100) }); } catch (_) {}
    });
    window.addEventListener("unhandledrejection", function (e) {
      try {
        var r = e && e.reason;
        var msg = r && (r.message || String(r)) || "";
        emitSignal("error.promise", { msg: msg.slice(0, 200) });
      } catch (_) {}
    });
  }

  // ── ③ C lazy 纸条:past_boards 提取 + DeepSeek prompt ──
  // 从某天 md 里抽 # 21：30 H2 块的 body(占位 ## 视为无纸条返 null)
  function _extractNoteBody(md) {
    if (!md) return null;
    var lines = md.split(/\r?\n/);
    var h1Idx = -1;
    for (var i = 0; i < lines.length; i++) {
      if (/^#\s*21[：:]30\s*$/.test(lines[i])) { h1Idx = i; break; }
    }
    if (h1Idx === -1) return null;
    var endIdx = lines.length;
    for (var j = h1Idx + 1; j < lines.length; j++) {
      if (/^#\s*\d{1,2}[：:]\d{2}\s*$/.test(lines[j]) || lines[j].trim() === "---") { endIdx = j; break; }
    }
    var bodyLines = [];
    var sawH2 = false;
    for (var k = h1Idx + 1; k < endIdx; k++) {
      var t = lines[k].trim();
      if (t === "##") return null;  // 占位 = 无纸条
      if (t.indexOf("## ") === 0) { sawH2 = true; continue; }  // 跳过 H2 标题行
      if (sawH2) bodyLines.push(lines[k]);
    }
    var body = bodyLines.join("\n").trim();
    return body || null;
  }
  // 调 DeepSeek 出纸条:简化版桌面 _eval_build_messages — past_boards 跨夜连贯 +
  // 今日 md。不复刻 PULSE/CLAUDE.md 注入(mobile 没那些);prompt 思路对齐 PC 端 21:30 仪式
  function _evalLazyNote(todayMd, pastBoards, key) {
    var sys = "你是用户的日记 AI 协作者。每晚 21:30 给他留一段纸条 — 这是仪式。\n\n" +
      "规则:\n① 看见今天他写了什么,具体说几个细节(不空泛、不套话)\n② 给一两句真实感受 — 鼓励、提醒、或一个轻的回应,不要长篇大论\n③ 不超过 120 字\n④ 语气像睡前关灯前那段话,温柔、私人、不像 AI\n\n" +
      (pastBoards ? "过去几晚你给他的纸条:\n\n" + pastBoards + "\n\n---\n\n" : "") +
      "今天他写了:\n\n" + (todayMd || "(今天还没写)");
    var payload = { model: "deepseek-chat", messages: [
      { role: "system", content: sys },
      { role: "user", content: "现在写今晚的纸条。" }
    ], stream: false };
    var url = "https://api.deepseek.com/v1/chat/completions";
    var headers = { "Content-Type": "application/json", Authorization: "Bearer " + key };
    var CapHttp = _cap && _cap.CapacitorHttp;
    if (CapHttp) {
      return CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 90, readTimeout: 90 })
        .then(function (r) { return (r && r.data && r.data.choices && r.data.choices[0] && r.data.choices[0].message && r.data.choices[0].message.content) || ""; });
    }
    return realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload) })
      .then(function (r) { return r.json(); })
      .then(function (d) { return (d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content) || ""; })
      .catch(function () { return ""; });
  }

  // ── 工具:日期 ───────────────────────────────────────
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function todayIso() { var d = new Date(); return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()); }
  // 复刻桌面 _writable_dates_set:闭集 {today, yesterday-if-hour<12}。
  // 6.24 抽 daily_tasks_routes 时抓出 mobile L454 是 date>=today 正好反向(放未来/拒昨天)。
  // 是 daily-tasks 的 Cannot-break 契约,由 test_check_rejects_future_and_catalog_is_writable_window 锁。
  function isWritableDate(date) {
    var now = new Date();
    var t = now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" + pad2(now.getDate());
    if (date === t) return true;
    var y = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    var yIso = y.getFullYear() + "-" + pad2(y.getMonth() + 1) + "-" + pad2(y.getDate());
    return date === yIso && now.getHours() < 12;
  }
  // 复刻桌面 _thread_save_is_stale(test_thread_cas 8 条 assert):
  // base 空 / current 0(首次写)/ base 垃圾值 / base/current 异类型 → 不 stale(不误拒);
  // base != current → stale(防 5.26 陈旧标签页覆盖)。
  function threadSaveIsStale(base, current) {
    if (base === null || base === undefined) return false;        // T1
    if (current === 0) return false;                                 // T2
    var b = parseInt(base, 10), c = parseInt(current, 10);
    if (isNaN(b) || isNaN(c)) return false;                          // T5 垃圾值/异类型不误拒
    return b !== c;                                                  // T3/T4/T6: 严格不等 = stale
  }
  // 第N天:距 2026-05-03(第1天)的日历天数,与桌面 vault 命名同源(实测对齐 6.12=41/6.13=42/6.15=44)。
  // 按日历天算,跳过的天也占号(6.14 缺也让 6.15=44),与 file-count 无关。
  function dayNum(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso); if (!m) return null;
    var anchor = Date.UTC(2026, 4, 3); // 5.3 = 第1天
    return Math.round((Date.UTC(+m[1], +m[2] - 1, +m[3]) - anchor) / 86400000) + 1;
  }
  // 2026-06-15 → 26.6.15(第44天)(桌面 canonical 文件名,字节一致)
  function isoToStem(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return iso;
    var n = dayNum(iso);
    return m[1].slice(2) + "." + parseInt(m[2], 10) + "." + parseInt(m[3], 10) + (n != null ? "(第" + n + "天)" : "");
  }
  // 26.6.15(第44天) 或 26.6.15 → 2026-06-15(读盘 stem 反解回内部 iso 键)
  function stemToIso(stem) {
    var m = /^(\d{2})\.(\d{1,2})\.(\d{1,2})/.exec(stem);
    if (!m) return stem;
    return "20" + m[1] + "-" + pad2(+m[2]) + "-" + pad2(+m[3]);
  }

  // ── 忠实复刻 server.py parse_journal ────────────────
  var TIME_H1_RE = /^#\s*(\d{1,2})[：:](\d{2})\s*$/;
  // 复刻 _check_author + _strip_author 给 patch 的 authorship boundary + H2 guard 用
  // (test_authorship.test_patch_block_ai_refuses_user_block + test_patch_h2_rename 锁)
  var AUTHOR_RE = /@(\w+)\s*$/;
  function checkAuthor(h2) {
    var m = AUTHOR_RE.exec(h2 || ""); return m ? m[1] : "user";  // 失败安全默认 user
  }
  function stripAuthorMarker(h2) { return (h2 || "").replace(/\s*@\S+\s*$/, "").trim(); }
  function parseJournal(text) {
    var lines = (text || "").split(/\r?\n/);
    var blocks = [], cur = null, i;
    for (i = 0; i < lines.length; i++) {
      var line = lines[i];
      var m = TIME_H1_RE.exec(line);
      if (m) {
        if (cur) blocks.push(cur);
        cur = { time: pad2(parseInt(m[1], 10)) + ":" + m[2], h1_raw: parseInt(m[1], 10) + "：" + m[2], raw: [] };
        continue;
      }
      if (cur === null) continue;
      cur.raw.push(line);
    }
    if (cur) blocks.push(cur);

    for (var b = 0; b < blocks.length; b++) {
      var blk = blocks[b], h2s = [], ch = null, j;
      for (j = 0; j < blk.raw.length; j++) {
        var ln = blk.raw[j];
        if (ln.indexOf("## ") === 0) {
          if (ch) h2s.push(ch);
          var content = ln.slice(3).trim();
          var tags = [], tm, tagRe = /#(\S+)/g;
          while ((tm = tagRe.exec(content))) tags.push(tm[1]);
          var title = content.replace(/#\S+\s*/g, "").trim();
          ch = { tags: tags, title: title, body_lines: [], commits: [] };
          continue;
        }
        if (ch === null) continue;
        if (ln.trim() === "---") continue;
        if (/^\s*-\s*#commit/.test(ln) || ln.slice(0, 30).indexOf("#commit") !== -1) {
          ch.commits.push(ln.trim());
        } else {
          ch.body_lines.push(ln);
        }
      }
      if (ch) h2s.push(ch);
      for (var h = 0; h < h2s.length; h++) {
        h2s[h].body = h2s[h].body_lines.join("\n").trim();
        delete h2s[h].body_lines;
      }
      blk.h2 = h2s;
      delete blk.raw;
    }
    blocks = blocks.filter(function (blk) {
      return blk.h2.length && blk.h2.some(function (h) {
        return h.tags.length || h.title || h.body || h.commits.length;
      });
    });
    blocks.sort(function (a, b) { return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });
    return blocks;
  }

  // ── daily-tasks: 解析 / 写回 checkbox 清单 ───────────
  function parseDailyTasks(md) {
    var lines = (md || "").split(/\r?\n/), tasks = [];
    for (var i = 0; i < lines.length; i++) {
      var m = /^\s*-\s*\[([ xX])\]\s*(.+?)\s*$/.exec(lines[i]);
      if (m) {
        var checked = m[1].toLowerCase() === "x";
        tasks.push({
          name: m[2], checked: checked, image_url: null,
          total_pills: null, daily_dose: 1, today_intake: checked ? 1 : 0, remaining: null,
        });
      }
    }
    return tasks;
  }
  function setDailyTaskChecked(md, name, checked) {
    var lines = (md || "").split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var m = /^(\s*-\s*\[)([ xX])(\]\s*)(.+?)(\s*)$/.exec(lines[i]);
      if (m && m[4] === name) { lines[i] = m[1] + (checked ? "x" : " ") + m[3] + m[4]; }
    }
    return lines.join("\n");
  }

  // ── 补剂打卡 + 八杯水:内嵌在当天 md 顶部(# 每日补剂打卡 段,首个时间块前),与桌面 vault 同构 ──
  // 桌面真源:喝水(8 子杯) + 补剂若干,顶层 - [ ] 名、多粒项带缩进子项。喝水归"八杯水"widget,不进打卡行。
  var SUPP_TOP = /^(- \[)([ xX])(\]\s+)(.+?)(\s*)$/;    // 顶层项 - [ ] 名
  var SUPP_SUB = /^(\s+- \[)([ xX])(\]\s+)(.+?)(\s*)$/; // 缩进子项 - [ ] N
  function suppRegionEnd(lines) { // 补剂段下界 = 首个时间块行号
    for (var i = 0; i < lines.length; i++) if (TIME_H1_RE.test(lines[i])) return i;
    return lines.length;
  }
  function suppTemplate() { // 与桌面 SCHEDULE_TEMPLATE 同源(本 vault 定制)
    return [
      "# 每日补剂打卡", "",
      "- [ ] 喝水",
      "  - [ ] 1", "  - [ ] 2", "  - [ ] 3", "  - [ ] 4", "  - [ ] 5", "  - [ ] 6", "  - [ ] 7", "  - [ ] 8",
      "- [ ] 鱼油（Swisse）", "  - [ ] 1", "  - [ ] 2",
      "- [ ] 肌酸",
      "- [ ] 苏糖酸镁",
      "- [ ] 维生素 D3+K2（gloryfeel）",
      "- [ ] 南非醉茄 KSM-66（Nature Love，90粒新版）",
      "", "---", "", "",
    ].join("\n");
  }
  function parseSupplements(dayMd) { // 顶层补剂项(排除"喝水")→ 打卡行
    var lines = (dayMd || "").split(/\r?\n/), end = suppRegionEnd(lines), tasks = [];
    for (var i = 0; i < end; i++) {
      if (SUPP_SUB.test(lines[i])) continue; // 跳子项
      var m = SUPP_TOP.exec(lines[i]);
      if (m && m[4] !== "喝水") {
        var on = m[2].toLowerCase() === "x";
        tasks.push({ name: m[4], checked: on, image_url: null, total_pills: null, daily_dose: 1, today_intake: on ? 1 : 0, remaining: null });
      }
    }
    return tasks;
  }
  function parseWaterFilled(dayMd) { // 喝水下勾选的子杯数 → 八杯水
    var lines = (dayMd || "").split(/\r?\n/), end = suppRegionEnd(lines), inWater = false, n = 0;
    for (var i = 0; i < end; i++) {
      var top = SUPP_TOP.exec(lines[i]);
      if (top && !SUPP_SUB.test(lines[i])) { inWater = (top[4] === "喝水"); continue; }
      if (inWater) { var s = SUPP_SUB.exec(lines[i]); if (s && s[2].toLowerCase() === "x") n++; }
    }
    return n;
  }
  function setSupplementChecked(dayMd, name, checked) {
    var lines = (dayMd || "").split(/\r?\n/), end = suppRegionEnd(lines);
    for (var i = 0; i < end; i++) {
      if (SUPP_SUB.test(lines[i])) continue;
      var m = SUPP_TOP.exec(lines[i]);
      if (m && m[4] === name) { lines[i] = m[1] + (checked ? "x" : " ") + m[3] + m[4]; break; }
    }
    return lines.join("\n");
  }
  // 复刻桌面 _ensure_md_progress_children:dose>=2 的 task 在父行下挂 N 个子 box,
  // 前 intake 个 [x] 其余 [ ];父行 intake>=dose 才 [x]。dose<2 直接返(单行够,展开碍眼)。
  // 幂等:已 in sync → 字节级不动。
  function setSupplementProgress(dayMd, name, dose, intake) {
    if ((dose | 0) < 2) return dayMd;
    var lines = (dayMd || "").split(/\r?\n/);
    var end = suppRegionEnd(lines);
    var parentIdx = -1, parentM = null;
    for (var i = 0; i < end; i++) {
      if (SUPP_SUB.test(lines[i])) continue;
      var m = SUPP_TOP.exec(lines[i]);
      if (m && m[4] === name) { parentIdx = i; parentM = m; break; }
    }
    if (parentIdx === -1) return dayMd;
    var childEnd = parentIdx + 1;
    while (childEnd < end && /^\s+-\s*\[[ xX]\]/.test(lines[childEnd])) childEnd++;
    var clamp = Math.max(0, Math.min(intake | 0, dose | 0));
    var desired = [];
    for (var k = 1; k <= dose; k++) {
      desired.push("  - [" + (k <= clamp ? "x" : " ") + "] " + k);
    }
    var parentBox = clamp >= dose ? "x" : " ";
    var newParent = parentM[1] + parentBox + parentM[3] + parentM[4] + (parentM[5] || "");
    var existingChildren = lines.slice(parentIdx + 1, childEnd);
    if (lines[parentIdx] === newParent && existingChildren.length === desired.length) {
      var match = true;
      for (var j = 0; j < desired.length; j++) {
        if (existingChildren[j] !== desired[j]) { match = false; break; }
      }
      if (match) return dayMd;
    }
    return lines.slice(0, parentIdx)
      .concat([newParent], desired, lines.slice(childEnd))
      .join("\n");
  }
  // 删 task:删顶层项行 + 其下所有缩进子项(对齐 PC 端从补剂段彻底清掉)
  function removeSupplement(dayMd, name) {
    var lines = (dayMd || "").split(/\r?\n/), end = suppRegionEnd(lines), out = [], skipChildren = false;
    for (var i = 0; i < lines.length; i++) {
      if (i >= end) { out.push(lines[i]); continue; }
      if (skipChildren) { if (SUPP_SUB.test(lines[i])) continue; skipChildren = false; }
      var m = SUPP_SUB.test(lines[i]) ? null : SUPP_TOP.exec(lines[i]);
      if (m && m[4] === name) { skipChildren = true; continue; }   // 删本行 + 触发跳子项
      out.push(lines[i]);
    }
    return out.join("\n");
  }
  function setWaterFilled(dayMd, filled) { // 喝水子杯 1..8:序号<=filled 勾上;父项 filled>=8 勾上
    var lines = (dayMd || "").split(/\r?\n/), end = suppRegionEnd(lines), inWater = false, idx = 0;
    for (var i = 0; i < end; i++) {
      var top = SUPP_SUB.test(lines[i]) ? null : SUPP_TOP.exec(lines[i]);
      if (top) {
        inWater = (top[4] === "喝水");
        if (inWater) { idx = 0; lines[i] = top[1] + (filled >= 8 ? "x" : " ") + top[3] + top[4]; }
        continue;
      }
      if (inWater) { var s = SUPP_SUB.exec(lines[i]); if (s) { idx++; lines[i] = s[1] + (idx <= filled ? "x" : " ") + s[3] + s[4]; } }
    }
    return lines.join("\n");
  }

  // ── 空白一天模板(补剂段 + 半小时格) ───────────────────
  function emptyDayMd() {
    var out = [], h, mm, mins = ["00", "30"];
    for (h = 7; h <= 23; h++) {
      for (var k = 0; k < mins.length; k++) {
        mm = mins[k];
        if (h === 23 && mm === "30") continue;
        out.push("# " + h + "：" + mm, "", "##", "", "---", "");
      }
    }
    return suppTemplate() + out.join("\n");
  }

  // ── 首次启动:seed 示例数据(合成,非真日记) ───────────
  function seedIfEmpty() {
    return Store.listJournalDates().then(function (dates) {
      if (dates.length) return;
      var today = todayIso();
      var sample = suppTemplate() + [
        "# 9：00", "", "## #ESP32 桌宠固件烧录", "",
        "折腾了一上午终于把固件刷进去了。**意义**:硬件这条线终于能自测了。", "", "---", "",
        "# 13：00", "", "## #配置系统/ctrl-c-v 跑通移动端 shim 雏形", "",
        "gateway 前端在本地 JS 假后端下第一次跑起来了 —— 不用 Python,纯浏览器。", "", "---", "",
        "# 21：30", "", "## 纸条", "",
        "（晚间 AI 纸条会落在这里。移动版对话接通后由 AI 写。）", "", "---", "",
      ].join("\n");
      return Store.writeJournalMd(today, sample);
    });
  }

  // ── 响应构造 ─────────────────────────────────────────
  function jsonResp(obj, status) {
    return new Response(JSON.stringify(obj), {
      status: status || 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  // SSE 流式响应(chat 用)
  function sseResp(events) {
    var stream = new ReadableStream({
      start: function (controller) {
        var enc = new TextEncoder(), idx = 0;
        function push() {
          if (idx >= events.length) { controller.close(); return; }
          controller.enqueue(enc.encode("data: " + JSON.stringify(events[idx]) + "\n\n"));
          idx++;
          setTimeout(push, 40);
        }
        push();
      },
    });
    return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  }

  // ── DeepSeek 直连(真机走原生 HTTP 桥绕 CORS;浏览器尝试直连,被 CORS 拦则提示)──
  function histToMsgs(body) {
    var hist = (body && body.history) || [], out = [];
    for (var i = 0; i < hist.length; i++) {
      var h = hist[i]; if (!h) continue;
      // ref(用户拉日记 entry 进对话)→ 当 user 上下文,让 AI 知道用户在指什么
      if (h.kind === "ref") {
        var label = "[" + (h.refKind || "引用") + "] " + (h.refText || "");
        out.push({ role: "user", content: label });
        continue;
      }
      // note(21:30 AI 纸条 / 之前留的便签)→ 当 AI 之前发的 assistant 消息
      if (h.kind === "note") {
        var nb = (h.body || "").trim();
        if (nb) out.push({ role: "assistant", content: nb });
        continue;
      }
      // 普通 msg(无 kind 或 kind:'msg')
      var role = (h.role === "ai" || h.role === "assistant" || h.who === "ai") ? "assistant" : "user";
      var content = typeof h.content === "string" ? h.content : (h.text || "");
      if (content) out.push({ role: role, content: content });
    }
    return out;
  }
  // ── Tool calling — Group A 7 个 mobile 本机 endpoint 对应 tool ──
  // OpenAI-compatible function calling spec(DeepSeek 同协议)
  var TOOL_SPECS = [
    { type: "function", function: { name: "patch_journal_block", description: "改某个时间块的内容,替换 H2 + body 一段。改标题时传 allow_h2_rename:true",
      parameters: { type: "object", properties: {
        date: { type: "string", description: "yyyy-mm-dd,不传默认今天" },
        time: { type: "string", description: "时间块,如 '14:00'" },
        new_md: { type: "string", description: "新内容,从 ## H2 行开始" },
        allow_h2_rename: { type: "boolean", description: "改 H2 标题时传 true,否则会被 guard 拒" },
      }, required: ["time", "new_md"] }}},
    { type: "function", function: { name: "insert_journal_block", description: "在指定时间块**插入新条目**(写在空 H2 占位上)。已有 entry 用 patch",
      parameters: { type: "object", properties: {
        date: { type: "string" }, time: { type: "string" }, tag: { type: "string" }, title: { type: "string" }, body: { type: "string" },
      }, required: ["time"] }}},
    { type: "function", function: { name: "check_daily_task", description: "打卡(吃药/补剂)。优先级 intake > increment > checked > toggle",
      parameters: { type: "object", properties: {
        task_name: { type: "string" }, date: { type: "string" },
        intake: { type: "integer", description: "今天吃了几粒(优先级最高)" },
        increment: { type: "integer", description: "增量,如 +1" },
        checked: { type: "boolean", description: "直接勾/取消" },
      }, required: ["task_name"] }}},
    { type: "function", function: { name: "set_daily_task_meta", description: "改打卡 meta(每天 N 粒/瓶装颗数)",
      parameters: { type: "object", properties: {
        task_name: { type: "string" }, daily_dose: { type: "integer" }, total_pills: { type: "integer" },
      }, required: ["task_name"] }}},
    { type: "function", function: { name: "read_today_schedule", description: "读今天的 schedule md 原文",
      parameters: { type: "object", properties: { date: { type: "string" } }}}},
    { type: "function", function: { name: "list_recent_days", description: "列最近几天的 schedule 文件名",
      parameters: { type: "object", properties: { n: { type: "integer", description: "几天,默认 7" } }}}},
    { type: "function", function: { name: "set_water_cup_image", description: "换喝水图标",
      parameters: { type: "object", properties: { image: { type: "string", description: "png base64 dataURL" } }, required: ["image"] }}},
    // Group B 新增
    { type: "function", function: { name: "append_journal_comment", description: "给某个时间块加 AI 评论(authorship 合法旁路,改不了 @user 块时用这个)",
      parameters: { type: "object", properties: {
        date: { type: "string" }, time: { type: "string" }, comment: { type: "string" },
      }, required: ["time", "comment"] }}},
    { type: "function", function: { name: "manage_daily_task", description: "加新打卡 task 到补剂段(每天追踪一项)",
      parameters: { type: "object", properties: {
        action: { type: "string", enum: ["add", "delete"], description: "默认 add" },
        task_name: { type: "string" },
      }, required: ["task_name"] }}},
    // Group C
    { type: "function", function: { name: "search_journal", description: "在本机 vault 全部日记里搜关键词,返匹配的日期 + 时间块 + 片段",
      parameters: { type: "object", properties: {
        query: { type: "string", description: "搜索关键词" },
        days: { type: "integer", description: "回看多少天,默认 30,最大 365" },
      }, required: ["query"] }}},
  ];
  // tool_name → mobile-api endpoint dispatch
  // 注意:用 window.fetch(shim-hijacked)而不是 realFetch — /api/* 路径要走 shim
  // 路由到本机 handler,realFetch 是绕开 shim 调外部 URL 用的(DeepSeek 等)
  function dispatchTool(name, args) {
    args = args || {};
    var fch = (typeof window !== "undefined") ? window.fetch : realFetch;
    var H = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args) };
    switch (name) {
      case "patch_journal_block": return fch("/api/journal/patch", H).then(function (r) { return r.json(); });
      case "insert_journal_block": return fch("/api/journal/insert-block", H).then(function (r) { return r.json(); });
      case "check_daily_task": return fch("/api/daily-tasks/check", H).then(function (r) { return r.json(); });
      case "set_daily_task_meta": return fch("/api/daily-tasks/meta", H).then(function (r) { return r.json(); });
      case "read_today_schedule": return fch("/api/journal/today" + (args.date ? "?date=" + encodeURIComponent(args.date) : "")).then(function (r) { return r.json(); });
      case "list_recent_days": return fch("/api/journal/days?n=" + (args.n || 7)).then(function (r) { return r.json(); });
      case "set_water_cup_image": return fch("/api/water-cup", H).then(function (r) { return r.json(); });
      // Group B
      case "append_journal_comment": return fch("/api/journal/append-comment", H).then(function (r) { return r.json(); });
      case "manage_daily_task":
        var act = (args.action || "add");
        return fch("/api/daily-tasks/" + (act === "delete" ? "delete" : "add"), H).then(function (r) { return r.json(); });
      case "search_journal":
        return fch("/api/journal/search?query=" + encodeURIComponent(args.query || "") + "&days=" + (args.days || 30))
          .then(function (r) { return r.json(); });
      default: return Promise.resolve({ error: "unknown tool: " + name });
    }
  }
  // expose for tests + future overrides
  if (typeof window !== "undefined") { window.__gwTool = { specs: TOOL_SPECS, dispatch: dispatchTool }; }

  function pickReply(d) { return d && d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content; }
  // 多轮 tool 调用 loop:DeepSeek 返 tool_calls → dispatch → result push 回 → 再调,
  // 直到无 tool_calls 或达 maxRounds 上限(防 infinite loop)。
  // 最后一轮 force-no-tool(不传 tools)防 AI 永远在调用 tool 不出回应。
  function chatViaDeepseek(body, key, model) {
    return Store.readJournalMd(todayIso()).then(function (todayMd) {
      var sys = "你是用户的日记协作 AI,语气温和、像深夜台灯下说话。\n\n" +
        "这是今天的日记:\n\n" + (todayMd || "(今天还没写)") +
        "\n\n你有以下工具可用 — 改日记/打卡/换图标时调对应 tool;只聊天回应不调 tool。";
      var messages = [{ role: "system", content: sys }].concat(histToMsgs(body), [{ role: "user", content: (body && body.message) || "" }]);
      var events = [];
      var maxRounds = 5;
      var url = "https://api.deepseek.com/v1/chat/completions";
      var headers = { "Content-Type": "application/json", Authorization: "Bearer " + key };
      var CapHttp = _cap && _cap.CapacitorHttp;

      function callRound(round) {
        if (round >= maxRounds) {
          events.push({ type: "error", text: "已达最大工具调用轮数 (" + maxRounds + "),停止" });
          events.push({ type: "done", actions: [], model_id: model || "deepseek" });
          return Promise.resolve(events);
        }
        var lastRound = round === maxRounds - 1;
        var payload = { model: model || "deepseek-chat", messages: messages, stream: false };
        if (!lastRound) { payload.tools = TOOL_SPECS; payload.tool_choice = "auto"; }
        var fetchPromise;
        if (CapHttp) {
          fetchPromise = CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 90, readTimeout: 90 })
            .then(function (res) { return res && res.data; });
        } else {
          var abortCtrl = (typeof AbortController === "function") ? new AbortController() : null;
          var timer = abortCtrl ? setTimeout(function () { abortCtrl.abort(); }, 90000) : null;
          fetchPromise = realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload), signal: abortCtrl && abortCtrl.signal })
            .then(function (r) { if (timer) clearTimeout(timer); return r.json(); });
        }
        return fetchPromise.then(function (d) {
          var msg = d && d.choices && d.choices[0] && d.choices[0].message;
          if (!msg) {
            events.push({ type: "error", text: "DeepSeek 返空" });
            events.push({ type: "done", actions: [], model_id: model || "deepseek" });
            return events;
          }
          var toolCalls = msg.tool_calls;
          if (toolCalls && toolCalls.length) {
            messages.push(msg);  // assistant + tool_calls,下一轮必须保留
            var ps = toolCalls.map(function (tc) {
              var name = tc.function && tc.function.name;
              var args = {};
              try { args = JSON.parse(tc.function.arguments || "{}"); } catch (e) {}
              events.push({ type: "tool_call", id: tc.id, name: name, args: args });
              return dispatchTool(name, args).then(function (result) {
                events.push({ type: "tool_result", id: tc.id, name: name, ok: !(result && result.error), result: result });
                messages.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify(result || {}) });
              }).catch(function (err) {
                var e = String(err && err.message || err);
                events.push({ type: "tool_result", id: tc.id, name: name, ok: false, error: e });
                messages.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify({ error: e }) });
              });
            });
            return Promise.all(ps).then(function () { return callRound(round + 1); });
          }
          // 无 tool_calls = 终态
          events.push({ type: "delta", text: msg.content || "(空回复)" });
          events.push({ type: "done", actions: [], model_id: model || "deepseek" });
          return events;
        }).catch(function (err) {
          var emsg = String(err && err.message || err);
          if (emsg.indexOf("Failed to fetch") >= 0 || emsg.indexOf("CORS") >= 0) {
            events.push({ type: "delta", text: "（浏览器直连 DeepSeek 受 CORS 限制 —— 真机经原生 HTTP 桥即可正常聊。）" });
          } else if (emsg.indexOf("abort") >= 0 || emsg.indexOf("timeout") >= 0) {
            events.push({ type: "error", text: "DeepSeek 超时(>90s),请重试" });
          } else {
            events.push({ type: "error", text: "DeepSeek 调用失败:" + emsg });
          }
          events.push({ type: "done", actions: [], model_id: model || "deepseek" });
          return events;
        });
      }
      return callRound(0).then(function (all) { return sseResp(all); });
    });
  }

  // ── 端点处理 ─────────────────────────────────────────
  function qsDate(u) { return new URL(u, location.origin).searchParams.get("date") || ""; }

  var handlers = {
    "GET /api/init-status": function () {
      return jsonResp({ ready: true, phase: "ready", detail: "", started_at: null, finished_at: null, error: null });
    },
    "GET /api/health": function () {
      return jsonResp({ ok: true, ts: new Date().toISOString().slice(0, 19), version: "mobile-mvp" });
    },
    "GET /api/config-status": function () {
      return Store.getSetting("deepseek_key").then(function (k) {
        return k ? jsonResp({ ok: true, model: "deepseek-v4-pro", provider: "deepseek" })
                 : jsonResp({ ok: false, reason: "尚未填写 DeepSeek key(设置里填)" });
      });
    },
    // 关键:必须 configured:true,否则被锁在无法关闭的设置弹窗后面
    "GET /api/setup-status": function () { return jsonResp({ configured: true, profile_count: 1 }); },
    "GET /api/setup/current": function () {
      return Store.getSetting("deepseek_key").then(function (k) {
        return jsonResp({
          models: [{ id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", api_key: k || "", base_url: "https://api.deepseek.com/v1" }],
          default_model_id: "deepseek-v4-pro",
          dashscope_api_key: "", dashscope_base_url: "", dashscope_vision_model: "",
          baidu_cutout_api_key: "", baidu_cutout_secret_key: "",
        });
      });
    },
    "GET /api/models": function () {
      return jsonResp({ models: [{ id: "deepseek-v4-pro", name: "DeepSeek V4 Pro" }], default_model_id: "deepseek-v4-pro" });
    },
    "GET /api/telemetry/consent": function () {
      return jsonResp({ needs_consent: false, failures: false, heartbeat: false, consented_at: null, client_id: "mobile", silent_failures_local: 0 });
    },
    "GET /api/user-widgets": function () { return jsonResp({ active: [] }); },
    "GET /api/water-cup": function () {
      return Store.getSetting("water_cup_img").then(function (img) { return jsonResp({ image_url: img || null }); });
    },
    // 同 daily-tasks/set-image:存 base64 dataUrl 到 Preferences,客户端已端侧抠图过
    "POST /api/water-cup": function (req, u, body) {
      return Store.setSetting("water_cup_img", (body && body.image) || "").then(function () { return jsonResp({ ok: true }); });
    },
    "GET /api/journal/tag-stats": function () { return jsonResp({ tags: [] }); },
    // 移动端无 vault 文件漂移概念;返 0 漂移,vault-audit.js 据此不弹横幅
    "GET /api/vault/audit": function () { return jsonResp({ total_drift: 0, image_recoverable: [], image_orphans: [], meta_orphans: [], aggregate_broken_links: [] }); },

    "GET /api/journal/days": function () {
      return Store.listJournalDates().then(function (dates) {
        return jsonResp({
          days: dates.map(function (d) { return { date: d, stem: isoToStem(d), file: "vault/半小时复盘/" + isoToStem(d) + ".md" }; }),
        });
      });
    },
    "GET /api/journal/today": function (req, u) {
      var date = qsDate(u) || todayIso();
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ error: "no journal file for " + date });
        return jsonResp({ file: "vault/半小时复盘/" + isoToStem(date) + ".md", date: date, blocks: parseJournal(md) });
      });
    },
    "POST /api/journal/new-day": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      var nd = new Date(); var tm = new Date(nd.getFullYear(), nd.getMonth(), nd.getDate() + 1);
      var tmw = tm.getFullYear() + "-" + pad2(tm.getMonth() + 1) + "-" + pad2(tm.getDate());
      // 跟 PC 一致:最多建到明天(+1),再远拒
      if (date > tmw) return jsonResp({ ok: false, error: "最多创建到明天" });
      return Store.readJournalMd(date).then(function (md) {
        if (md !== null) return jsonResp({ ok: true, created: false, file: isoToStem(date) + ".md", message: "已存在" });
        return Store.writeJournalMd(date, emptyDayMd()).then(function () {
          return jsonResp({ ok: true, created: true, file: isoToStem(date) + ".md", message: "已创建" });
        });
      });
    },
    "GET /api/daily-tasks": function (req, u) {
      var date = qsDate(u) || todayIso();
      return Store.readJournalMd(date).then(function (md) {
        var tasks = parseSupplements(md), water = parseWaterFilled(md);
        // 并发拉 image + meta + intake_log(对齐 PC catalog 的真值线:
        // tasks[].today_intake 从 intake_log 算,不是用 md 行勾态硬编 1)
        return Promise.all(tasks.map(function (t) {
          return Promise.all([
            Store.getSetting("taskimg/" + t.name),
            Store.getSetting("taskmeta/" + t.name),
            Store.getSetting("taskintake/" + t.name),
          ]).then(function (rs) {
            t.image_url = rs[0] || null;
            try {
              var meta = rs[1] ? JSON.parse(rs[1]) : {};
              if (meta.total_pills) t.total_pills = meta.total_pills;
              if (meta.daily_dose) t.daily_dose = meta.daily_dose;
              // 余量徽标:days_left = floor(total/dose),≤3 在前端贴 .urgent 红徽
              if (meta.total_pills && meta.daily_dose) {
                t.days_left = Math.floor(meta.total_pills / Math.max(1, meta.daily_dose));
              }
            } catch (e) {}
            try {
              var log = rs[2] ? JSON.parse(rs[2]) : {};
              t.today_intake = log[date] | 0;
            } catch (e) {}
            return t;
          });
        })).then(function (ts) {
          // is_writable:复刻桌面 _writable_dates_set,不是 date>=today(L454 旧错值)
          return jsonResp({ tasks: ts, water_filled: water, date: date, is_today: date === todayIso(), is_writable: isWritableDate(date) });
        });
      });
    },
    // 打卡图标:存抠好的 PNG(端侧抠图后由前端传来),按 task 名持久化
    "POST /api/daily-tasks/set-image": function (req, u, body) {
      if (!(body && body.task_name)) return jsonResp({ ok: false, error: "缺 task_name" });
      return Store.setSetting("taskimg/" + body.task_name, body.image || "").then(function () { return jsonResp({ ok: true }); });
    },
    // 改 meta:total_pills(瓶装颗数)/ daily_dose(每天 N 粒),对齐 PC 端 /meta
    "POST /api/daily-tasks/meta": function (req, u, body) {
      var name = (body && body.task_name) || "";
      if (!name) return jsonResp({ ok: false, error: "缺 task_name" }, 400);
      return Store.getSetting("taskmeta/" + name).then(function (raw) {
        var meta = {}; try { meta = raw ? JSON.parse(raw) : {}; } catch (e) {}
        if ("total_pills" in body) {
          var v = body.total_pills;
          if (v === null || v === "" || v === 0) delete meta.total_pills;
          else meta.total_pills = Math.max(1, parseInt(v, 10) || 0);
        }
        if ("daily_dose" in body) meta.daily_dose = Math.max(1, parseInt(body.daily_dose, 10) || 1);
        return Store.setSetting("taskmeta/" + name, JSON.stringify(meta)).then(function () {
          return jsonResp({ ok: true, task_name: name, total_pills: meta.total_pills || null, daily_dose: meta.daily_dose || 1 });
        });
      });
    },
    // 删 task:当天 md 补剂段删行 + 清 image + 清 meta(对齐 PC 端 /delete 三清)
    // Group B:加新 task(写补剂段 - [ ] 名字)— AI 在 mobile session 用嘴加 task
    "POST /api/daily-tasks/add": function (req, u, body) {
      var name = body && body.task_name;
      if (!name) return jsonResp({ ok: false, error: "缺 task_name" }, 400);
      var today = todayIso();
      return Store.readJournalMd(today).then(function (md) {
        var lines = (md || "").split(/\r?\n/);
        var end = suppRegionEnd(lines);
        // 检查重名 — 已有则 ok no-op
        for (var i = 0; i < end; i++) {
          if (SUPP_SUB.test(lines[i])) continue;
          var m = SUPP_TOP.exec(lines[i]);
          if (m && m[4] === name) return jsonResp({ ok: true, task_name: name, existed: true });
        }
        // 插到补剂段末尾(end 之前)
        var newLine = "- [ ] " + name;
        var newLines = lines.slice(0, end).concat([newLine], lines.slice(end));
        return Store.writeJournalMd(today, newLines.join("\n")).then(function () {
          return jsonResp({ ok: true, task_name: name, added: true });
        });
      });
    },
    "POST /api/daily-tasks/delete": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      var name = (body && body.task_name) || "";
      if (!name) return jsonResp({ ok: false, error: "缺 task_name" }, 400);
      return Store.readJournalMd(date).then(function (md) {
        var p = [];
        if (md !== null) p.push(Store.writeJournalMd(date, removeSupplement(md, name)));
        p.push(Store.removeSetting("taskimg/" + name));
        p.push(Store.removeSetting("taskmeta/" + name));
        return Promise.all(p).then(function () { return jsonResp({ ok: true, task_name: name }); });
      });
    },
    // 历史:近 N 天每天是否打勾,对齐 PC 端 /history(query: name + days)
    "GET /api/daily-tasks/history": function (req, u) {
      var url = new URL(u, "http://x");
      var name = url.searchParams.get("name") || "";
      var days = Math.max(1, Math.min(parseInt(url.searchParams.get("days") || "14", 10), 60));
      if (!name) return jsonResp({ ok: false, error: "需 name query" }, 400);
      var today = new Date();
      var dates = [];
      for (var i = 0; i < days; i++) {
        var d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
        dates.push(d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()));
      }
      return Promise.all(dates.map(function (dt) {
        return Store.readJournalMd(dt).then(function (md) {
          if (md === null) return { date: dt, checked: null };  // 没文件 = 未记录
          var tasks = parseSupplements(md);
          var found = tasks.filter(function (t) { return t.name === name; })[0];
          return { date: dt, checked: found ? found.checked : null };
        });
      })).then(function (history) {
        var checked_days = history.filter(function (h) { return h.checked === true; }).length;
        var recorded_days = history.filter(function (h) { return h.checked !== null; }).length;
        return jsonResp({ ok: true, name: name, days: days, history: history, checked_days: checked_days, recorded_days: recorded_days });
      });
    },
    "POST /api/daily-tasks/check": function (req, u, body) {
      // 复刻桌面 _bump_intake 数学(由 test_check_intake_increment_clamp_and_md_box 锁):
      //  · intake/increment/checked 三入口,优先级 intake > increment > checked > toggle
      //  · clamp [0, daily_dose];intake>=dose → md [x],否则 [ ]
      //  · intake_log:{date: intake} 存独立 setting key;0 → pop 当日 key
      //  · 窗口外日期 400(test_check_rejects_future_and_catalog_is_writable_window);非整 500
      var date = (body && body.date) || todayIso();
      if (!isWritableDate(date)) return jsonResp({ ok: false, error: "date 不在可写窗口(只能补昨天 hour<12,不能写未来)" }, 400);
      var name = body && body.task_name;
      return Promise.all([
        Store.readJournalMd(date),
        Store.getSetting("taskmeta/" + name),
        Store.getSetting("taskintake/" + name),
      ]).then(function (rs) {
        var md = rs[0];
        if (md === null) return jsonResp({ ok: false, error: "no file" }, 404);
        var meta = {}; try { meta = rs[1] ? JSON.parse(rs[1]) : {}; } catch (e) {}
        var log = {}; try { log = rs[2] ? JSON.parse(rs[2]) : {}; } catch (e) {}
        var dose = Math.max(1, parseInt(meta.daily_dose, 10) || 1);
        var cur = log[date] | 0;
        var next;
        if ("intake" in body) {
          var iv = parseInt(body.intake, 10);
          if (isNaN(iv)) return jsonResp({ ok: false, error: "intake 必须是整数" }, 500);
          next = Math.max(0, Math.min(dose, iv));
        } else if ("increment" in body) {
          var inc = parseInt(body.increment, 10) | 0;
          next = Math.max(0, Math.min(dose, cur + inc));
        } else if (body && typeof body.checked === "boolean") {
          next = body.checked ? dose : 0;
        } else {
          next = (cur >= dose) ? 0 : dose;  // toggle
        }
        var checked = next >= dose;
        if (next === 0) delete log[date]; else log[date] = next;
        // dose>=2 走 setSupplementProgress 同步父行 + 子 box(桌面 _ensure_md_progress_children
        // 真值);dose<2 走 setSupplementChecked 只改顶层(单行够,展开碍眼)
        var newMd = (dose >= 2)
          ? setSupplementProgress(md, name, dose, next)
          : setSupplementChecked(md, name, checked);
        var p = [Store.writeJournalMd(date, newMd)];
        if (Object.keys(log).length === 0) p.push(Store.removeSetting("taskintake/" + name));
        else p.push(Store.setSetting("taskintake/" + name, JSON.stringify(log)));
        return Promise.all(p).then(function () {
          return jsonResp({
            ok: true, task_name: name, checked: checked,
            total_pills: meta.total_pills || null, daily_dose: dose, today_intake: next,
            remaining: null,
          });
        });
      });
    },
    // 八杯水:落进当天 md 的"喝水"子杯勾选(序号<=filled 勾上),持久化八杯水进度
    "POST /api/daily-tasks/water": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      var filled = Math.max(0, Math.min(8, (body && body.filled) | 0));
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ ok: false, error: "no file" }, 404);
        return Store.writeJournalMd(date, setWaterFilled(md, filled)).then(function () {
          return jsonResp({ ok: true, filled: filled });
        });
      });
    },
    // 复刻桌面 thread_routes.py:
    //   GET 损坏 → status='corrupt' + baks(5.17:绝不空 [] 当真覆盖);健康返 mtime 给 client 做 CAS
    //   POST 带 base_mtime,跟当前不符 → 409 + 文件原样(5.26:防陈旧标签页覆盖)
    "GET /api/thread/history": function () {
      return Promise.all([Store.readThread(), Store.readThreadMtime()]).then(function (rs) {
        var r = rs[0], mt = rs[1];
        if (!r.ok && r.corrupt) {
          // 复刻桌面 test_history_corrupt_returns_modal_payload_and_rings:扫 bak.1..5 给前端 modal
          return Store.listThreadBaks().then(function (baks) {
            return jsonResp({
              status: "corrupt", history: [], mtime: 0,
              baks: baks, raw_bytes: r.raw_bytes,
              message: "thread-history 解析失败,选 bak.N 恢复或从空开始",
            });
          });
        }
        return jsonResp({ history: r.history || [], mtime: mt });
      });
    },
    // 复刻桌面 /api/thread/restore-from-bak(test_restore_from_bak_roundtrip + bad_index 400 + missing 404)
    "POST /api/thread/restore-from-bak": function (req, u, body) {
      var idx = parseInt(body && body.bak_index, 10);
      if (isNaN(idx) || idx < 1 || idx > 5) return jsonResp({ ok: false, error: "bak_index 必须 1..5" }, 400);
      return Store.readThreadBakAt(idx).then(function (raw) {
        if (raw == null) return jsonResp({ ok: false, error: "bak." + idx + " 不存在" }, 404);
        var hist;
        try { hist = JSON.parse(raw); }
        catch (e) { return jsonResp({ ok: false, error: "bak." + idx + " 内容也损坏了" }, 500); }
        // 先把原损坏内容存档(若有),再写回
        return Backend.getText("thread").then(function (cur) {
          var archive = cur ? Store.archiveCorruptedThread(cur) : Promise.resolve(null);
          return archive.then(function () {
            var mt = Date.now();
            return Promise.all([
              Backend.setText("thread", JSON.stringify(hist)),
              Backend.setText("setting/thread_mtime", String(mt)),
            ]).then(function () {
              return jsonResp({ ok: true, restored_from: "bak." + idx, count: Array.isArray(hist) ? hist.length : 0, mtime: mt });
            });
          });
        });
      });
    },
    "POST /api/thread/save": function (req, u, body) {
      var hist = (body && body.history);
      if (!Array.isArray(hist)) return jsonResp({ ok: false, error: "history must be a list" }, 400);
      var base = body && body.base_mtime;
      return Store.readThreadMtime().then(function (current) {
        if (threadSaveIsStale(base, current)) {
          return jsonResp({
            conflict: true, current_mtime: current,
            message: "stale base_mtime — reload server history before saving",
          }, 409);
        }
        return Store.writeThread(hist).then(function (mt) {
          return jsonResp({ ok: true, mtime: mt, count: hist.length });
        });
      });
    },

    // 写日记:行内编辑/插入/删除 —— MVP 简化,人写自己的块,不跑 authorship 守卫
    "POST /api/journal/insert-block": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) md = "";
        var time = body.time, h = parseInt((time || "0:0").split(":")[0], 10), mm = (time || "0:00").split(":")[1];
        var h2 = "## " + (body.tag ? "#" + body.tag + " " : "") + (body.title || "");
        var blockMd = "# " + h + "：" + mm + "\n\n" + h2 + "\n" + (body.body || "") + "\n\n---\n";
        Store.writeJournalMd(date, (md ? md.replace(/\s*$/, "\n\n") : "") + blockMd);
        return jsonResp({ ok: true, inserted: "# " + h + "：" + mm, file: isoToStem(date) + ".md" });
      });
    },
    // ③ C 简化版 lazy 纸条 — 用户打开 app 时如果当天 # 21：30 H2 块是占位 ##,
    // 调 DeepSeek 用桌面 prompt 同源写一段,写进 21:30 H2 块。
    // 不绑定时间(早晚都触发),time 戳走 PC 端原位 21:30 H2(user 拍板"保持 PC 端原位")。
    "POST /api/note/check-lazy": function () {
      var today = todayIso();
      return Store.readJournalMd(today).then(function (md) {
        if (md === null) return jsonResp({ skip: "no file" });
        var lines = (md || "").split(/\r?\n/);
        var h1Idx = -1;
        for (var i = 0; i < lines.length; i++) {
          if (/^#\s*21[：:]30\s*$/.test(lines[i])) { h1Idx = i; break; }
        }
        if (h1Idx === -1) return jsonResp({ skip: "no 21:30 block" });
        var endIdx = lines.length;
        for (var j = h1Idx + 1; j < lines.length; j++) {
          if (TIME_H1_RE.test(lines[j]) || lines[j].trim() === "---") { endIdx = j; break; }
        }
        var firstH2 = null;
        for (var k = h1Idx + 1; k < endIdx; k++) {
          var t = lines[k].trim();
          if (t === "##" || lines[k].indexOf("## ") === 0) { firstH2 = lines[k]; break; }
        }
        if (!firstH2 || firstH2.trim() !== "##") return jsonResp({ skip: "already has note" });
        return Store.getSetting("deepseek_key").then(function (key) {
          if (!key) return jsonResp({ skip: "no key" });
          // past_boards 跨夜连贯:扫过去 7 天 vault 提取 21:30 H2 块 body
          return Store.listJournalDates().then(function (dates) {
            var past = (dates || []).filter(function (d) { return d < today; }).sort().reverse().slice(0, 7);
            return Promise.all(past.map(function (d) {
              return Store.readJournalMd(d).then(function (m) {
                var body = _extractNoteBody(m);
                return body ? "## " + d + "\n\n" + body : null;
              });
            })).then(function (boards) {
              var pastBoards = boards.filter(Boolean).join("\n\n---\n\n");
              return _evalLazyNote(md, pastBoards, key).then(function (noteText) {
                if (!noteText) return jsonResp({ skip: "empty eval" });
                // 写入 21:30 H2 占位 → "## 纸条 @ai\n\n{noteText}" — 走 patch 路径,
                // 占位 H2 不卡 H2-guard,且 Sprint 1 #1 authorship boundary 已加占位排除。
                // 用 window.fetch 走 shim 自调 routing → patch handler(realFetch 绕开 shim 给外部用)
                var newMd = "## 纸条 @ai\n\n" + noteText;
                return window.fetch("/api/journal/patch", { method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ date: today, time: "21:30", new_md: newMd, author: "ai" }) })
                  .then(function (r) { return r.json(); })
                  .then(function (j) { return jsonResp({ wrote: !j.error, detail: j }); });
              });
            });
          }).catch(function (e) { return jsonResp({ skip: "error", err: String(e) }); });
        });
      });
    },
    // Group B:append_journal_comment — 给某块加 AI 评论(authorship 合法旁路,
    // AI 不能改 @user 块但可以在 body 末尾加 *AI:* 评论)
    // Group C:search_journal — 扫 mobile 本机 vault md,关键词匹配返结果列表
    "GET /api/journal/search": function (req, u) {
      var url = new URL(u, "http://x");
      var q = (url.searchParams.get("query") || "").trim();
      var days = Math.max(1, Math.min(parseInt(url.searchParams.get("days") || "30", 10), 365));
      if (!q) return jsonResp({ ok: false, error: "缺 query" }, 400);
      var qLc = q.toLowerCase();
      return Store.listJournalDates().then(function (dates) {
        var sorted = (dates || []).sort().reverse().slice(0, days);
        return Promise.all(sorted.map(function (date) {
          return Store.readJournalMd(date).then(function (md) {
            if (!md) return null;
            var matches = [];
            var lines = md.split(/\r?\n/);
            var curTime = null;
            for (var i = 0; i < lines.length; i++) {
              var tm = TIME_H1_RE.exec(lines[i]);
              if (tm) { curTime = pad2(parseInt(tm[1], 10)) + ":" + tm[2]; continue; }
              if (lines[i].toLowerCase().indexOf(qLc) >= 0 && curTime) {
                matches.push({ time: curTime, snippet: lines[i].trim().slice(0, 200) });
              }
            }
            return matches.length ? { date: date, matches: matches } : null;
          });
        })).then(function (rs) {
          var hits = rs.filter(Boolean);
          var total = hits.reduce(function (a, h) { return a + h.matches.length; }, 0);
          return jsonResp({ ok: true, query: q, days: days, total: total, hits: hits.slice(0, 30) });
        });
      });
    },
    "POST /api/journal/append-comment": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      var time = body && body.time;
      var comment = body && body.comment;
      var author = (body && body.author) || "ai";
      if (!time || !comment) return jsonResp({ error: "缺 time 或 comment" }, 400);
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ error: "no file" }, 404);
        var lines = md.split(/\r?\n/);
        var pad = pad2(parseInt(time.split(":")[0], 10)) + ":" + time.split(":")[1];
        var start = -1;
        for (var i = 0; i < lines.length; i++) {
          var tm = TIME_H1_RE.exec(lines[i]);
          if (tm && (pad2(parseInt(tm[1], 10)) + ":" + tm[2]) === pad) { start = i; break; }
        }
        if (start === -1) return jsonResp({ error: "time block " + time + " not found" }, 404);
        var end = lines.length;
        for (var j = start + 1; j < lines.length; j++) {
          if (TIME_H1_RE.test(lines[j]) || lines[j].trim() === "---") { end = j; break; }
        }
        // append 在 body 末尾(end 之前,去掉末尾空行)
        var insertAt = end;
        while (insertAt > start + 1 && lines[insertAt - 1].trim() === "") insertAt--;
        var prefix = author === "ai" ? "*AI:* " : "";
        var newLines = lines.slice(0, insertAt).concat(["", prefix + comment], lines.slice(insertAt));
        return Store.writeJournalMd(date, newLines.join("\n")).then(function () {
          return jsonResp({ ok: true, appended: time, file: isoToStem(date) + ".md" });
        });
      });
    },
    "POST /api/journal/patch": function (req, u, body) {
      // 复刻桌面 _patch_block 完整契约:
      //  · authorship boundary:author='ai' + 块内 H2 标 @user → 拒(test_authorship)
      //  · H2-rename guard:author='ai' + existing H2 strip 不等 new H2 strip + !allow_h2_rename → 拒
      //    (test_patch_h2_rename;5.29 联想 entry 被 patch 吃掉事故的反向防御)
      //  · author 字段未传默认 'ai' 失败安全(test_patch_block_default_caller_is_ai)
      var date = (body && body.date) || todayIso();
      var time = body && body.time;
      var newMd = (body && body.new_md) || "";
      var author = (body && body.author) || "ai";
      var allowRename = !!(body && body.allow_h2_rename);
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ error: "no file" }, 404);
        var pad = pad2(parseInt((time || "0:0").split(":")[0], 10)) + ":" + (time || "0:00").split(":")[1];
        var lines = md.split(/\r?\n/);
        // 1. 找 block 边界(start = H1 行,end = 下个 H1 或 ---)
        var start = -1;
        for (var i = 0; i < lines.length; i++) {
          var tm = TIME_H1_RE.exec(lines[i]);
          if (tm && (pad2(parseInt(tm[1], 10)) + ":" + tm[2]) === pad) { start = i; break; }
        }
        if (start === -1) return jsonResp({ error: "time block # " + time + " not found" }, 404);
        var end = lines.length;
        for (var j = start + 1; j < lines.length; j++) {
          if (TIME_H1_RE.test(lines[j]) || lines[j].trim() === "---") { end = j; break; }
        }
        // 2. existing 首条 H2
        var existingH2 = null;
        for (var k = start + 1; k < end; k++) {
          if (lines[k].indexOf("## ") === 0) { existingH2 = lines[k]; break; }
        }
        // 3. authorship boundary:AI 不能 patch @user 块(test_patch_block_ai_refuses_user_block)
        //    占位 H2 "##" 不算任何人所有,AI 可以填入(③ C lazy 纸条写入 21:30 占位块用)
        if (author !== "user" && existingH2 && existingH2.trim() !== "##" && checkAuthor(existingH2) === "user") {
          return jsonResp({ error: "block @ " + time + " 是 @user 所有,AI 不能 patch。想加评论用 append_journal_comment;想新加 entry 用 insert_journal_block。" }, 403);
        }
        // 4. H2 mismatch guard(test_patch_rejects_h2_mismatch_by_default + test_patch_allows_h2_rename_with_flag)
        var newH2 = null;
        var newLines = newMd.split(/\r?\n/);
        for (var n = 0; n < newLines.length; n++) {
          if (newLines[n].indexOf("## ") === 0) { newH2 = newLines[n]; break; }
        }
        if (author !== "user" && existingH2 && newH2 &&
            existingH2.trim() !== "##" &&
            stripAuthorMarker(existingH2) !== stripAuthorMarker(newH2) &&
            !allowRename) {
          return jsonResp({
            error: "block @ " + time + " 已有 H2:`" + existingH2.trim() + "`。new_md 第一个 H2 是:`" + newH2.trim() + "` — 不一样。patch 会整段替换,原 H2 会被吃掉。想加新 H2 用 insert;改标题重传 allow_h2_rename=true。",
            conflict: true,
          }, 409);
        }
        // 5. splice:保留 H1 行,替换 H1+1..end 之间的 body
        var trimmedNewMd = newMd.replace(/\s+$/, "");
        var out = lines.slice(0, start + 1).concat([""], trimmedNewMd.split(/\r?\n/), [""], lines.slice(end));
        return Store.writeJournalMd(date, out.join("\n")).then(function () {
          return jsonResp({ patched: time, file: isoToStem(date) + ".md" });
        });
      });
    },
    "POST /api/journal/delete-block": function (req, u, body) {
      var date = (body && body.date) || todayIso(), time = body && body.time;
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ error: "no file" }, 404);
        var pad = pad2(parseInt((time || "0:0").split(":")[0], 10)) + ":" + (time || "0:00").split(":")[1];
        var lines = md.split(/\r?\n/), out = [], skip = false, found = false;
        for (var i = 0; i < lines.length; i++) {
          var tm = TIME_H1_RE.exec(lines[i]);
          if (tm) {
            var t = pad2(parseInt(tm[1], 10)) + ":" + tm[2];
            if (t === pad) { skip = true; found = true; out.push(lines[i], "", "##", ""); continue; }
            skip = false;
          }
          if (skip) { if (lines[i].trim() === "---") { skip = false; out.push("---"); } continue; }
          out.push(lines[i]);
        }
        if (!found) return jsonResp({ error: "not found" }, 404);
        return Store.writeJournalMd(date, out.join("\n")).then(function () {
          return jsonResp({ ok: true, cleared: time, file: isoToStem(date) + ".md" });
        });
      });
    },

    // 对话:有 key 就真连 DeepSeek(读今天日记当 context);没 key 提示去设置填
    "POST /api/chat": function (req, u, body) {
      return Store.getSetting("deepseek_key").then(function (key) {
        if (!key) return sseResp([{ type: "delta", text: "（还没填 DeepSeek key —— 点报头 ⚙ 进设置填了,AI 就能读今天的日记跟你聊。）" }, { type: "done", actions: [], model_id: "deepseek" }]);
        return Store.getSetting("deepseek_model").then(function (m) { return chatViaDeepseek(body, key, m || "deepseek-chat"); });
      });
    },
    // 设置保存:容错抽取 DeepSeek key/model 落本地(让现有设置 UI 能填 key)
    "POST /api/setup/save": function (req, u, body) {
      var key = "", model = "";
      if (body) {
        if (Array.isArray(body.models) && body.models[0]) { key = body.models[0].api_key || body.models[0].apiKey || ""; model = body.models[0].id || body.models[0].model || ""; }
        key = key || body.deepseek_api_key || body.api_key || "";
        model = model || body.default_model_id || body.model || "";
      }
      var p = [];
      if (key) p.push(Store.setSetting("deepseek_key", key));
      if (model) p.push(Store.setSetting("deepseek_model", model));
      if (body && body.dashscope_api_key) p.push(Store.setSetting("dashscope_key", body.dashscope_api_key));
      return Promise.all(p).then(function () { return jsonResp({ ok: true }); });
    },
    // 复刻 test_save_partial_updates_and_clears 契约:body 字段路由到对应 setting,
    // 空字符串值 → pop 整 key(不是存空串)。允许逐字段改而不带全套 models。
    "POST /api/setup/save-partial": function (req, u, body) {
      if (!body) return jsonResp({ ok: true });
      var p = [];
      if (Array.isArray(body.models) && body.models[0]) {
        var k = body.models[0].api_key || body.models[0].apiKey || "";
        var m = body.models[0].id || body.models[0].model || "";
        if (k) p.push(Store.setSetting("deepseek_key", k));
        if (m) p.push(Store.setSetting("deepseek_model", m));
      }
      // 单字段:有值 set,空字符串 pop(对齐 test_save_partial)
      var SINGLES = [
        ["dashscope_api_key", "dashscope_key"],
        ["dashscope_base_url", "dashscope_base_url"],
        ["dashscope_vision_model", "dashscope_vision_model"],
        ["deepseek_api_key", "deepseek_key"],
        ["deepseek_base_url", "deepseek_base_url"],
        ["deepseek_default_model", "deepseek_model"],
        ["baidu_cutout_api_key", "baidu_cutout_api_key"],
        ["baidu_cutout_secret_key", "baidu_cutout_secret_key"],
      ];
      SINGLES.forEach(function (pair) {
        var field = pair[0], slot = pair[1];
        if (field in body) {
          p.push(body[field] ? Store.setSetting(slot, body[field]) : Store.removeSetting(slot));
        }
      });
      return Promise.all(p).then(function () { return jsonResp({ ok: true }); });
    },
    // 真机无法在 webview 里 CORS 自测 key,乐观返 ok;真验证发生在第一次聊天
    "POST /api/setup/test": function () { return jsonResp({ ok: true, model: "deepseek-chat" }); },
  };

  // ── EventSource 劫持 ─────────────────────────────────
  // /api/* 的 SSE(如 update-banner 的 migration/stream)在移动端无意义。
  // 返回一个惰性 EventSource(从不连、从不报错),避免 404 噪音 + 让 banner 静默。
  var RealES = window.EventSource;
  if (RealES) {
    function InertES(url) { this.url = url; this.readyState = 2 /* CLOSED */; this.onmessage = null; this.onerror = null; this.onopen = null; }
    InertES.CONNECTING = 0; InertES.OPEN = 1; InertES.CLOSED = 2;
    InertES.prototype.close = function () { this.readyState = 2; };
    InertES.prototype.addEventListener = function () {};
    InertES.prototype.removeEventListener = function () {};
    window.EventSource = function (url, cfg) {
      try { if (String(url).indexOf("/api/") !== -1) return new InertES(url); } catch (e) {}
      return new RealES(url, cfg);
    };
    window.EventSource.CONNECTING = 0; window.EventSource.OPEN = 1; window.EventSource.CLOSED = 2;
  }

  // ── fetch 劫持 ───────────────────────────────────────
  // realFetch = 启动时 cache 的原 window.fetch,绕开 shim 自身 /api/* 路由
  // 加一层 wrapper 允许测试时 window.__gwFetchOverride hijack(生产无影响)
  var _origFetch = window.fetch.bind(window);
  function realFetch(input, init) {
    if (typeof window !== "undefined" && typeof window.__gwFetchOverride === "function") {
      return window.__gwFetchOverride(input, init);
    }
    return _origFetch(input, init);
  }

  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    var path;
    try { path = new URL(url, location.origin).pathname; } catch (e) { path = url; }

    if (path.indexOf("/api/") !== 0) return realFetch(input, init); // 静态资源透传

    var key = method + " " + path;
    var fn = handlers[key];
    if (!fn) {
      // 未实现的端点:良性占位,不让脚本崩
      return Promise.resolve(jsonResp({ ok: false, mobile_stub: true, error: "桌面版功能,移动 MVP 未实现" }));
    }
    // 解析 body(POST JSON)
    var bodyP = Promise.resolve(null);
    if (init && init.body && typeof init.body === "string") {
      bodyP = Promise.resolve().then(function () { try { return JSON.parse(init.body); } catch (e) { return null; } });
    }
    return bodyP.then(function (body) {
      try { return fn(init || {}, url, body); }
      catch (e) { console.error("[mobile-api] handler error", key, e); return jsonResp({ error: String(e) }, 500); }
    });
  };

  // ── 启动:seed 后放行(其它脚本 defer,会在 seed 完成后才真正 fetch?
  //    不保证 —— 故 seed 同步触发,fetch 处理是 async 的,首个 today 请求
  //    会 await seed) ──────────────────────────────────
  var seedPromise = seedIfEmpty();
  // 让 journal/today 等到 seed 完成
  var _origToday = handlers["GET /api/journal/today"];
  handlers["GET /api/journal/today"] = function (req, u) { return seedPromise.then(function () { return _origToday(req, u); }); };
  var _origDays = handlers["GET /api/journal/days"];
  handlers["GET /api/journal/days"] = function (req, u) { return seedPromise.then(function () { return _origDays(req, u); }); };
  var _origTasks = handlers["GET /api/daily-tasks"];
  handlers["GET /api/daily-tasks"] = function (req, u) { return seedPromise.then(function () { return _origTasks(req, u); }); };
})();
