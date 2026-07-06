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
  // ★ H1:版本单源 = mobile/VERSION。build-web.sh 一致性 gate 守 VERSION==此常量==Android versionName,
  //   任一漂移 build 失败。health 返真版本(替代占位 "mobile-mvp"),feedback-sink/心跳可定位真 build。
  var APP_VERSION = "0.1.39";

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
  // ★ Capacitor plugin lazy resolve — IIFE 启动时 bridge 可能未就绪 (_cap=null),
  //   写代码 cache 会永久 lock LocalBackend → save 假装 ok 但 storage 空。
  //   解法:每次访问都 re-resolve window.Capacitor.Plugins,确保拿到 lazy-loaded plugin。
  function _getCap() { return (typeof window !== "undefined" && window.Capacitor && window.Capacitor.Plugins) || null; }
  function _getFs() { var c = _getCap(); return c && c.Filesystem; }
  function _getPrefs() { var c = _getCap(); return c && c.Preferences; }
  var DIR = "DATA";
  function capPath(k) {
    if (k.indexOf("journal/") === 0) return "gw/journal/" + isoToStem(k.slice(8)) + ".md";
    if (k === "daily-tasks") return "gw/daily-tasks.md";
    if (k === "thread") return "gw/thread.json";
    return "gw/kv/" + k.replace(/[^\w.-]/g, "_") + ".txt";
  }
  // ★ catch 不吞 write 错 — 之前 .catch(()=>{}) 让 setText 在 plugin fail 时假装 success,
  //   导致 saveKey 返 ok:true 但 storage 空。现在 reject 让 caller 看到真错。
  // ── fs 就绪门:启动早期 Filesystem 插件未挂载时,读文件返 null 会被当"文件不存在",
  //    幂等 new-day 会拿骨架盖掉真文件(数据丢失级)。"未就绪"必须等待,不能误判为缺失。──
  function _fsWait() {
    var f = _getFs();
    if (f) return Promise.resolve(f);
    return new Promise(function (res) {
      var n = 0;
      var t = setInterval(function () {
        var fs2 = _getFs();
        if (fs2 || ++n > 50) { clearInterval(t); res(fs2 || null); }
      }, 100);
    });
  }

  // PATTERN: util — 文件名后缀推 mime(attachment 二进制存储读回拼 dataURL 用)
  function _mimeFromStem(stem) {
    var ext = String(stem).split(".").pop().toLowerCase();
    return ({ jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif" })[ext] || "application/octet-stream";
  }
  var CapacitorBackend = {
    // ── 日记文件名迁移守护:文件名内嵌"第N天",dayNum 锚点改变(硬编码→动态)后,
    //    同一 iso 的 canonical 文件名会变 → 旧文件读不到、写入开叉文件(iOS 真机实锤:
    //    26.7.3(第62天).md 与 26.7.3(第1天).md 并存)。读写前按 iso 语义解析,
    //    命中旧名就惰性 rename 到 canonical。 ──
    _findJournalAlt: function (iso) {
      var fs = _getFs(); if (!fs) return Promise.resolve(null);
      return fs.readdir({ path: "gw/journal", directory: DIR }).then(function (r) {
        var files = (r && r.files) || [];
        for (var i = 0; i < files.length; i++) {
          var n = typeof files[i] === "string" ? files[i] : files[i].name;
          if (!/\.md$/.test(n)) continue;
          if (stemToIso(n.replace(/\.md$/, "")) === iso) return "gw/journal/" + n;
        }
        return null;
      }).catch(function () { return null; });
    },
    _canonJournal: function (iso) {
      var fs = _getFs(); var want = capPath("journal/" + iso);
      return fs.stat({ path: want, directory: DIR }).then(function () { return want; }).catch(function () {
        return CapacitorBackend._findJournalAlt(iso).then(function (alt) {
          if (!alt) return want;   // 没有旧命名文件 → canonical 即目标(可能尚不存在)
          return fs.rename({ from: alt, to: want, directory: DIR, toDirectory: DIR })
            .then(function () { return want; })
            .catch(function () { return alt; });  // rename 失败原地用旧名,不丢数据
        });
      });
    },
    getText: function (k) {
      var prefs = _getPrefs();
      if (k.indexOf("setting/") === 0 && prefs) return prefs.get({ key: k.slice(8) }).then(function (r) { return r && r.value != null ? r.value : null; }).catch(function () { return null; });
      return _fsWait().then(function (fs) {
        if (!fs) return null;
        if (k.indexOf("journal/") === 0) {
          return CapacitorBackend._canonJournal(k.slice(8)).then(function (p) {
            return fs.readFile({ path: p, directory: DIR, encoding: "utf8" }).then(function (r) { return r.data; }).catch(function () { return null; });
          });
        }
        return fs.readFile({ path: capPath(k), directory: DIR, encoding: "utf8" }).then(function (r) { return r.data; }).catch(function () { return null; });
      });
    },
    setText: function (k, v) {
      var prefs = _getPrefs();
      if (k.indexOf("setting/") === 0 && prefs) return prefs.set({ key: k.slice(8), value: v });
      return _fsWait().then(function (fs) {
        if (!fs) throw new Error("存储不可用");
        if (k.indexOf("journal/") === 0) {
          // ★ H2:日记本体是 MD-is-truth 根数据 → 原子写 + .bak(对齐 PC _safe_write_text)
          return CapacitorBackend._canonJournal(k.slice(8)).then(function (p) {
            return CapacitorBackend._writeAtomicWithBak(fs, p, v);
          });
        }
        return fs.writeFile({ path: capPath(k), data: v, directory: DIR, encoding: "utf8", recursive: true });
      });
    },
    // ★ H2 原子写 + 单级备份:tmp 全量落 → 现真身备份到 .bak → rename 覆盖。
    //   崩溃/OOM 只可能撕裂 .tmp(丢弃),真身要么旧要么新,永不半截;.bak 留最后一版好数据。
    //   Capacitor rename 覆盖行为跨平台不保证 → 先删真身再 rename(窗口内 JS 单线程 + 写锁
    //   串行,崩在此 ~1ms 窗口只丢真身但 .bak 在,可恢复)。
    _writeAtomicWithBak: function (fs, p, v) {
      var tmp = p + ".tmp";
      return fs.writeFile({ path: tmp, data: v, directory: DIR, encoding: "utf8", recursive: true })
        .then(function () {
          return fs.readFile({ path: p, directory: DIR, encoding: "utf8" }).then(function (cur) {
            return fs.writeFile({ path: p + ".bak", data: cur.data, directory: DIR, encoding: "utf8" }).catch(function () {});
          }, function () { /* 首次无真身,跳过备份 */ });
        })
        .then(function () {
          return fs.deleteFile({ path: p, directory: DIR }).catch(function () {});  // 真身不存在也无妨
        })
        .then(function () {
          return fs.rename({ from: tmp, to: p, directory: DIR, toDirectory: DIR });
        });
    },
    remove: function (k) {
      var prefs = _getPrefs(), fs = _getFs();
      if (k.indexOf("setting/") === 0 && prefs) return prefs.remove({ key: k.slice(8) });
      if (!fs) return Promise.resolve();
      return fs.deleteFile({ path: capPath(k), directory: DIR }).catch(function () {});
    },
    keys: function (prefix) {
      // ★ setting/ 前缀走 Preferences.keys()(7.5 修:此前非 journal 一律返 [],
      //   uploads_index 列举永远为空 → 照片 curator 在真机上失明)
      if (prefix.indexOf("setting/") === 0) {
        var prefs = _getPrefs();
        if (!prefs || !prefs.keys) return Promise.resolve([]);
        var sub = prefix.slice(8);
        return prefs.keys().then(function (r) {
          return ((r && r.keys) || []).filter(function (k) { return k.indexOf(sub) === 0; })
            .map(function (k) { return "setting/" + k; });
        }).catch(function () { return []; });
      }
      return _fsWait().then(function (fs) {
      if (!fs) return [];
      if (prefix.indexOf("journal/") === 0) {
        return fs.readdir({ path: "gw/journal", directory: DIR }).then(function (r) {
          var files = (r && r.files) || [];
          var seen = {}, out = [];
          for (var i = 0; i < files.length; i++) {
            var n = typeof files[i] === "string" ? files[i] : files[i].name;
            if (!/\.md$/.test(n)) continue;                     // 迁移残留/非日记不进列表
            var iso = stemToIso(n.replace(/\.md$/, ""));
            if (seen[iso]) continue;                            // 同 iso 双文件(锚点迁移孤儿)去重
            seen[iso] = true;
            out.push("journal/" + iso);
          }
          return out;
        }).catch(function () { return []; });
      }
      return [];
      });
    },
  };

  // ★ Backend 改 wrapper 对象 — 每次方法调用都 lazy 决定 delegate,而不是 IIFE 启动时锁死。
  //   ★ 新增:node 测试环境 globalThis.__GW_TEST_BACKEND__ 优先(harness 注入 Map-based store)
  function _testBackend() { return (typeof globalThis !== "undefined" && globalThis.__GW_TEST_BACKEND__) || null; }
  var Backend = {
    getText: function (k) { var tb = _testBackend(); if (tb) return tb.getText(k); return (_getFs() ? CapacitorBackend : LocalBackend).getText(k); },
    setText: function (k, v) { var tb = _testBackend(); if (tb) return tb.setText(k, v); return (_getFs() ? CapacitorBackend : LocalBackend).setText(k, v); },
    remove: function (k) { var tb = _testBackend(); if (tb) return tb.remove(k); return (_getFs() ? CapacitorBackend : LocalBackend).remove(k); },
    keys: function (prefix) {
      var tb = _testBackend();
      if (tb) return tb.keys().then(function (ks) { return ks.filter(function (k) { return k.indexOf(prefix) === 0; }); });
      return (_getFs() ? CapacitorBackend : LocalBackend).keys(prefix);
    },
  };

  // 对照 PC server.py:4284 _parse_tag_aggregate — walk lines → [{tag,description,columns,rows}]
  function _parseTagAggregate(text) {
    var sections = [], cur = null;
    var LINK_RE = /\[([^\]]+)\]\(([^)]+)\)/;
    var DATE_RE = /(\d{2})\.(\d{1,2})\.(\d{1,2})/;  // 26.5.7 → 2026-05-07
    (text || "").split(/\r?\n/).forEach(function (raw) {
      var line = raw.replace(/\s+$/, "");
      var hm = line.match(/^##\s+#(\S+)\s*$/);
      if (hm) { if (cur) sections.push(cur); cur = { tag: hm[1], description: "", columns: [], rows: [] }; return; }
      if (!cur) return;
      if (line.indexOf("|") === 0) {
        var cells = line.replace(/^\|/, "").replace(/\|\s*$/, "").split("|").map(function (c) { return c.trim(); });
        if (cells.length && (cells[0] === "日期" || cells[0] === "Date")) { cur.columns = cells; return; }
        if (cells.every(function (c) { return !c || /^[-:\s]+$/.test(c); })) return;  // 分隔行
        if (cells.length >= 4) {
          var linkText = cells[2], linkTarget = "";
          var lm = LINK_RE.exec(cells[2]);
          if (lm) { linkText = lm[1]; linkTarget = lm[2]; }
          var isoDate = null, dm = DATE_RE.exec(linkTarget || cells[0]);
          if (dm) isoDate = "20" + dm[1] + "-" + ("0" + dm[2]).slice(-2) + "-" + ("0" + dm[3]).slice(-2);
          var subTag = cells.length >= 5 ? cells[4] : null;
          cur.rows.push({ date_short: cells[0], iso_date: isoDate, time: cells[1],
            link_text: linkText, link_target: linkTarget, content: cells[3],
            sub_tag: (subTag && subTag !== "—") ? subTag : null });
        }
        return;
      }
      if (line.trim() && line.trim() !== "---" && !cur.description && line.indexOf(">") !== 0) cur.description = line.trim();
    });
    if (cur) sections.push(cur);
    return sections;
  }

  // 对照 PC server.py:4573 _format_row — 单行 md table 行(链接锚点全角冒号)
  function _formatAggRow(row, withSub) {
    var link = "[26." + row.date_short + "#" + row.time + "](" + row.link_target + ")";
    var base = "| " + row.date_short + " | " + row.time + " | " + link + " | " + row.content + " |";
    if (withSub) base += " " + (row.sub_tag || "—") + " |";
    return base;
  }
  // 对照 PC server.py:4454 _scan_schedule_for_project_tags — 扫 journal md 抽 project-tag H2 entry
  //   mds: [{iso, md}];projectTags: [tag, ...] → {tag: [{iso_date,date_short,time,sub_tag,content,link_target}]}
  function _scanJournalForTags(projectTags, mds) {
    var out = {}; projectTags.forEach(function (t) { out[t] = []; });
    mds.forEach(function (e) {
      if (!e.md) return;
      var parts = e.iso.split("-"), mo = parseInt(parts[1], 10), dd = parseInt(parts[2], 10);
      var dateShort = mo + "." + dd, curTime = null;
      e.md.split(/\r?\n/).forEach(function (line) {
        var m1 = line.match(/^#\s+(\d{1,2})[：:](\d{2})\s*$/);
        if (m1) { curTime = m1[1] + "：" + m1[2]; return; }
        var m2 = line.match(/^##\s+(.+)$/);
        if (!m2 || !curTime) return;
        var h2 = m2[1].trim();
        var tags = h2.match(/#([A-Za-z0-9_\-/一-鿿]+)/g);
        if (!tags) return;
        var title = h2.replace(/#([A-Za-z0-9_\-/一-鿿]+)/g, "").trim();
        if (!title) return;
        tags.forEach(function (tagFull) {
          tagFull = tagFull.replace(/^#/, "");
          var parent, sub;
          if (tagFull.indexOf("/") >= 0) { var sp = tagFull.split("/"); parent = sp[0]; sub = "/" + sp.slice(1).join("/"); }
          else { parent = tagFull; sub = null; }
          if (projectTags.indexOf(parent) < 0) return;
          out[parent].push({ iso_date: e.iso, date_short: dateShort, time: curTime, sub_tag: sub,
            content: title, link_target: "半小时复盘/26." + dateShort + ".md#" + curTime });
        });
      });
    });
    return out;
  }
  // 对照 PC server.py:4582 _append_rows_to_aggregate — 每 tag 段尾 table 后按 iso 升序插新行,只 append
  function _appendRowsToAgg(text, newRows) {
    var lines = text.split(/\r?\n/), out = [], curTag = null, pending = [], tableLastIdx = -1;
    function flush() {
      if (pending.length && tableLastIdx >= 0) {
        var withSub = pending.some(function (r) { return r.sub_tag; });
        if ((out[tableLastIdx].split("|").length - 1) >= 6) withSub = true;
        var sorted = pending.slice().sort(function (a, b) { return (a.iso_date + a.time).localeCompare(b.iso_date + b.time); });
        sorted.forEach(function (r, o) { out.splice(tableLastIdx + 1 + o, 0, _formatAggRow(r, withSub)); });
      }
      pending = []; tableLastIdx = -1;
    }
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var m = line.match(/^##\s+#(\S+)\s*$/);
      if (m) { flush(); curTag = m[1]; pending = (newRows[curTag] || []).slice(); out.push(line); continue; }
      if (line.trim() === "---") { flush(); curTag = null; out.push(line); continue; }
      if (line.indexOf("|") === 0 && curTag) { out.push(line); tableLastIdx = out.length - 1; continue; }
      out.push(line);
    }
    flush();
    return out.join("\n");
  }

  var Store = {
    readJournalMd: function (date) { return Backend.getText("journal/" + date); },
    writeJournalMd: function (date, md) { return Backend.setText("journal/" + date, md); },
    // 标签聚合.md — 单文件横切索引(对照 PC TAG_AGGREGATE_PATH),存 Filesystem(ASCII key)
    readTagAggregate: function () { return Backend.getText("tag_aggregate"); },
    writeTagAggregate: function (md) { return Backend.setText("tag_aggregate", md); },
    listJournalDates: function () {
      return Backend.keys("journal/").then(function (ks) {
        return ks.map(function (k) { return k.slice("journal/".length); }).sort();
      });
    },
    // vision/OCR 移植 — attachment 对齐 PC 保存方式(7.5 移植):真二进制文件存
    // gw/attachments/YYYY-MM-DD/<stem>(chat_routes.py ATTACHMENTS_DIR 同布局,
    // 比旧 base64 .txt 省 1/3 体积);对外契约不变:write 收 dataURL / read 返 dataURL。
    // 旧 kv 文本格式读到即懒迁移成二进制并删旧键。浏览器仍走 localStorage dataURL。
    writeAttachment: function (date, stem, dataUrl) {
      if (!_getFs()) return Backend.setText("attachments/" + date + "/" + stem, dataUrl);
      var b64 = String(dataUrl).replace(/^data:[^,]*,/, "");
      return _fsWait().then(function (f) {
        if (!f) throw new Error("存储不可用");
        return f.writeFile({ path: "gw/attachments/" + date + "/" + stem, data: b64, directory: DIR, recursive: true });
      });
    },
    readAttachment: function (date, stem) {
      if (!_getFs()) return Backend.getText("attachments/" + date + "/" + stem);
      return _fsWait().then(function (f) {
        if (!f) return null;
        return f.readFile({ path: "gw/attachments/" + date + "/" + stem, directory: DIR }).then(function (r) {
          return "data:" + _mimeFromStem(stem) + ";base64," + r.data;
        }).catch(function () {
          // 旧 kv dataURL 文本 → 迁移成二进制,删旧键;迁移失败也把旧值返出去(不阻读)
          return Backend.getText("attachments/" + date + "/" + stem).then(function (old) {
            if (!old) return null;
            var b64 = String(old).replace(/^data:[^,]*,/, "");
            return f.writeFile({ path: "gw/attachments/" + date + "/" + stem, data: b64, directory: DIR, recursive: true })
              .then(function () { return Backend.remove("attachments/" + date + "/" + stem); })
              .then(function () { return old; }, function () { return old; });
          });
        });
      });
    },
    listAttachments: function (date) {
      if (!_getFs()) {
        var prefix = "attachments/" + (date ? date + "/" : "");
        return Backend.keys(prefix).then(function (ks) {
          return ks.map(function (k) { return k.slice("attachments/".length); }).sort();
        });
      }
      return _fsWait().then(function (f) {
        if (!f) return [];
        return f.readdir({ path: "gw/attachments/" + (date || ""), directory: DIR }).then(function (r) {
          return ((r && r.files) || []).map(function (x) {
            var n = typeof x === "string" ? x : x.name;
            return date ? date + "/" + n : n;
          }).sort();
        }).catch(function () { return []; });
      });
    },
    // attachment metadata index(对齐 PC _index.json):vision_classify result 缓存 + uploaded_at
    // 走 setting/uploads_index/<date>/<stem> 持久化,跟 attachment 本体并列存
    writeUploadMeta: function (date, stem, meta) { return Backend.setText("setting/uploads_index/" + date + "/" + stem, JSON.stringify(meta)); },
    readUploadMeta: function (date, stem) {
      return Backend.getText("setting/uploads_index/" + date + "/" + stem).then(function (s) {
        try { return s ? JSON.parse(s) : null; } catch (e) { return null; }
      });
    },
    deleteUploadMeta: function (date, stem) { return Backend.remove("setting/uploads_index/" + date + "/" + stem); },
    listAllUploadMetas: function () {
      return Backend.keys("setting/uploads_index/").then(function (ks) {
        return Promise.all(ks.map(function (k) {
          return Backend.getText(k).then(function (s) {
            var m = /^setting\/uploads_index\/([^/]+)\/(.+)$/.exec(k);
            if (!m) return null;
            try { var meta = s ? JSON.parse(s) : {}; meta._date = m[1]; meta._stem = m[2]; meta._url = "/attachments/" + m[1] + "/" + m[2]; return meta; }
            catch (e) { return null; }
          });
        })).then(function (rs) { return rs.filter(Boolean); });
      });
    },
    // ⑥ B Turn 5:AI 动态 widget manifest 持久化 setting/widgets/<id>
    listWidgetManifests: function () {
      return Backend.keys("setting/widgets/").then(function (ks) {
        return Promise.all(ks.map(function (k) {
          return Backend.getText(k).then(function (s) {
            try { return JSON.parse(s); } catch (e) { return null; }
          });
        })).then(function (rs) { return rs.filter(Boolean); });
      });
    },
    readDailyTasksMd: function () { return Backend.getText("daily-tasks"); },
    writeDailyTasksMd: function (md) { return Backend.setText("daily-tasks", md); },
    // ★ Scrapbook MVP — 对齐 PC scrapbook/{date}.json:items[]
    //   item = {id, src, anchor_time, x_pct, y_px, w, h, rotation, auto_y, z}
    //   存储位置:setting/scrapbook/<date> 走 Capacitor Preferences
    readScrapbook: function (date) {
      return Backend.getText("setting/scrapbook/" + date).then(function (s) {
        if (!s) return [];
        try { return JSON.parse(s); } catch (e) { return []; }
      });
    },
    writeScrapbook: function (date, items) {
      return Backend.setText("setting/scrapbook/" + date, JSON.stringify(items || []));
    },
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
    // ★ 7.5 OOM 修:bak 从 Preferences 挪 Filesystem("thread-bak/N" 文件键)。
    //   旧位置(setting/thread_bak/N)曾把多 MB thread 塞 SharedPreferences,整个 XML 常驻内存。
    //   旧 Preferences bak 由 GET /api/thread/history 迁移时删除。
    rotateThreadBaks: function () {
      return Backend.getText("thread").then(function (cur) {
        if (cur == null) return;
        // 从 4→5, 3→4, 2→3, 1→2, current→1。bak.5 旧值丢弃。
        return Backend.getText("thread-bak/4").then(function (b4) {
          return (b4 == null ? Promise.resolve() : Backend.setText("thread-bak/5", b4));
        }).then(function () { return Backend.getText("thread-bak/3"); }).then(function (b3) {
          return (b3 == null ? Promise.resolve() : Backend.setText("thread-bak/4", b3));
        }).then(function () { return Backend.getText("thread-bak/2"); }).then(function (b2) {
          return (b2 == null ? Promise.resolve() : Backend.setText("thread-bak/3", b2));
        }).then(function () { return Backend.getText("thread-bak/1"); }).then(function (b1) {
          return (b1 == null ? Promise.resolve() : Backend.setText("thread-bak/2", b1));
        }).then(function () { return Backend.setText("thread-bak/1", cur); });
      });
    },
    listThreadBaks: function () {
      // 扫 1..5,有则进列表(fs 新位 miss 再看旧 Preferences 位 — corrupt 恢复网跨迁移不空窗)
      var ps = [1, 2, 3, 4, 5].map(function (i) {
        return Backend.getText("thread-bak/" + i).then(function (s) {
          if (s != null) return { index: i, bytes: s.length };
          return Backend.getText("setting/thread_bak/" + i).then(function (old) {
            return old == null ? null : { index: i, bytes: old.length };
          });
        });
      });
      return Promise.all(ps).then(function (rs) { return rs.filter(Boolean); });
    },
    readThreadBakAt: function (idx) {
      return Backend.getText("thread-bak/" + idx).then(function (s) {
        return s != null ? s : Backend.getText("setting/thread_bak/" + idx);
      });
    },
    // 原损坏内容存 thread-corrupted/<ts> 文件(对齐桌面.corrupted.<ts> 备份策略)
    archiveCorruptedThread: function (raw) {
      var ts = Date.now();
      return Backend.setText("thread-corrupted/" + ts, raw).then(function () { return ts; });
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
    // lazy resolve(IIFE 顶部 _cap race fix,同 chatViaDeepseek)
    var CapHttp = _getCapHttp();
    if (CapHttp) {
      return CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 15000, readTimeout: 90000 })
        .then(function (r) { return (r && r.data && r.data.choices && r.data.choices[0] && r.data.choices[0].message && r.data.choices[0].message.content) || ""; });
    }
    return realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload) })
      .then(function (r) { return r.json(); })
      .then(function (d) { return (d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content) || ""; })
      .catch(function () { return ""; });
  }

  // ── web_search 移植:PC 端 web_tools.py 三层降级链(360 → 百炼 → 拒答)
  // critic 校正:① selector 模糊匹配 li[class*='res-list'](精确匹配漏 30-50%)
  // ② entity unescape 用 table(不用 DOMParser 防 inline img prefetch CSP)
  // ③ http→https 自动升级(iOS ATS 拒 cleartext)④ dashscope_key 用正确键名
  var _HTML_ENT_TABLE = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " ", "#10": "\n", "#13": "\r" };
  function _htmlUnescape(s) {
    return String(s == null ? "" : s)
      .replace(/&(#x?[0-9a-fA-F]+|\w+);/g, function (_, k) {
        if (k.charAt(0) === "#") {
          var c = (k.charAt(1) === "x" || k.charAt(1) === "X")
            ? parseInt(k.slice(2), 16) : parseInt(k.slice(1), 10);
          return isNaN(c) ? _ : String.fromCharCode(c);
        }
        return _HTML_ENT_TABLE.hasOwnProperty(k) ? _HTML_ENT_TABLE[k] : _;
      });
  }
  function _htmlStripToText(html) {
    if (!html) return "";
    return _htmlUnescape(
      String(html)
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
        .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
    );
  }
  function _httpsUpgrade(u) {
    // iOS ATS 拒 http://, 自动升 https(失败时 LLM 看到 error 自行 retry)
    if (typeof u !== "string") return u;
    return u.replace(/^http:\/\//i, "https://");
  }
  // lazy resolve CapacitorHttp(IIFE 启动时 cache 的 _cap 拿不到测试时后注入的 mock)
  function _getCapHttp() {
    return (typeof window !== "undefined" && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.CapacitorHttp) || null;
  }
  // ── vision_classify 移植 — 调阿里云百炼 qwen3-vl-flash(OpenAI 兼容)
  // 复刻桌面 server.py:2171 _qwen_classify_image 的 system prompt + JSON mode
  function _qwenClassifyImage(dataUrl, extraQuestion, key) {
    if (!key) return Promise.resolve({ error: "no_dashscope_key", hint: "进设置填 API key 解锁拍照识图" });
    if (!dataUrl) return Promise.resolve({ error: "no_image" });
    var CapHttp = _getCapHttp();
    var url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions";
    var headers = { "Content-Type": "application/json", Authorization: "Bearer " + key };
    var sysPrompt = "你看图,用 JSON 返回:{kind: 'supplement'/'photo'/'screenshot'/'document'/'other', " +
      "description: 一两句具体描述图里有啥(看清楚再写,别空泛), " +
      "ocr_likely: bool 这图里有没有可读文字, " +
      "suggested_action: 给用户一句行动建议(可选), " +
      "brand: 看到的品牌(可选,补剂/产品类才有), " +
      "pill_count: 看到的瓶装颗数(可选,补剂瓶子才有)}";
    var userContent = [
      { type: "text", text: extraQuestion || "请按规则描述这张图。" },
      { type: "image_url", image_url: { url: dataUrl } },
    ];
    var payload = {
      model: "qwen3-vl-flash",
      messages: [{ role: "system", content: sysPrompt }, { role: "user", content: userContent }],
      response_format: { type: "json_object" },
    };
    var p;
    if (CapHttp) {
      p = CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 15000, readTimeout: 60000 })
        .then(function (r) { return (r && r.data) || {}; });
    } else {
      p = realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload) }).then(function (r) { return r.json(); });
    }
    return p.then(function (d) {
      var content = d && d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content;
      if (!content) return { error: "empty_response" };
      // 容错 ```json fence
      var s = String(content).trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
      try { return JSON.parse(s); } catch (e) { return { error: "json_parse_failed", raw: s.slice(0, 200) }; }
    }).catch(function (e) {
      return { error: "vision_failed", detail: String(e && e.message || e) };
    });
  }
  // 简单 sha256 用 SubtleCrypto(浏览器/iOS WKWebView 都支持)
  function _sha256Hex(buf) {
    if (typeof crypto === "undefined" || !crypto.subtle) {
      // dev fallback:返时间戳作 unique stem(不去重但能跑)
      return Promise.resolve("ts" + Date.now() + Math.random().toString(36).slice(2, 8));
    }
    return crypto.subtle.digest("SHA-256", buf).then(function (h) {
      var b = new Uint8Array(h);
      var hex = ""; for (var i = 0; i < b.length; i++) { hex += (b[i] < 16 ? "0" : "") + b[i].toString(16); }
      return hex.slice(0, 16);  // 短 hash 够 mobile vault 用
    });
  }
  function _dataUrlToBuf(dataUrl) {
    var m = /^data:([^;]+);base64,(.+)$/.exec(dataUrl || "");
    if (!m) return null;
    var b64 = m[2];
    try {
      var bin = atob(b64); var u = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
      return { mime: m[1], buf: u.buffer };
    } catch (e) { return null; }
  }
  // PATTERN: util — dataURL 存附件(sha256 去重)
  // USE WHEN: 任何要把 dataURL 落 attachment store 换短路径的地方(upload-image / thread 瘦身)
  function _saveDataUrlAttachment(dataUrl) {
    var parsed = _dataUrlToBuf(dataUrl);
    if (!parsed) return Promise.resolve(null);
    var ext = ({ "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif" })[parsed.mime] || "bin";
    var date = todayIso();
    return _sha256Hex(parsed.buf).then(function (hash) {
      var stem = hash + "." + ext;
      var url = "/attachments/" + date + "/" + stem;
      return Store.readAttachment(date, stem).then(function (existing) {
        if (existing) return { url: url, deduped: true, size: parsed.buf.byteLength };
        return Store.writeAttachment(date, stem, dataUrl).then(function () {
          return Store.writeUploadMeta(date, stem, { uploaded_at: Date.now(), size: parsed.buf.byteLength, mime: parsed.mime }).then(function () {
            _bgOcrIndex(date, stem, dataUrl);  // fire-and-forget,对齐 PC _index_attachment
            return { url: url, deduped: false, size: parsed.buf.byteLength };
          });
        });
      });
    });
  }
  // 上传即后台 OCR(对齐 PC _index_attachment:OCR upload 时跑,vision 留 lazy):
  // 失败静默降级 — 索引没有 ocr_text 只是 curator 检索少一路,不阻上传
  function _bgOcrIndex(date, stem, dataUrl) {
    setTimeout(function () {
      try {
        // ★ H6:后台索引 OCR 走统一入口。但 upload 后台跑不该悄悄触发云端付费 —
        //   只在端侧可用时写 ocr_text;无 GMS 时留空(curator 检索少一路,但不背着用户
        //   烧云端 quota)。用户主动换图标(/api/cutout)那条才允许云端兜底 + 明示。
        var plugin = (typeof window !== "undefined") && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.NativeOcr;
        if (!plugin || !plugin.recognize) return;
        _ocrNativeAvailable(plugin).then(function (ok) {
          if (!ok) return;   // 无端侧 → 后台不烧云端
          return plugin.recognize({ image: dataUrl, languages: ["zh-Hans", "en-US"] }).then(function (r) {
            if (!r || !r.text) return;
            return Store.readUploadMeta(date, stem).then(function (meta) {
              meta = meta || {};
              meta.ocr_text = String(r.text).slice(0, 2000);
              return Store.writeUploadMeta(date, stem, meta);
            });
          });
        }).catch(function () {});
      } catch (e) {}
    }, 0);
  }
  // ★ 7.5 OOM 崩溃根因修:thread 里 msg.imgs/attachments 曾内联 dataURL(单文件 13MB),
  //   saveThread 过 Capacitor 桥 → Java 侧 JSONTokener 47MB 分配打爆 256MB 堆。
  //   这里把 history 里所有 data: 内联图转成附件短路径;落盘前必经此闸(save + 读取迁移双入口)。
  function _slimHistoryImgs(hist) {
    var changed = false;
    var ps = [];
    function isData(s) { return typeof s === "string" && s.indexOf("data:") === 0; }
    (hist || []).forEach(function (m) {
      if (!m) return;
      // imgs:data: 内联 → 存附件换短路径(sha256 去重,同图不重复占空间)
      if (m.imgs && m.imgs.length) {
        m.imgs.forEach(function (u, i) {
          if (!isData(u)) return;
          changed = true;
          ps.push(_saveDataUrlAttachment(u).then(function (r) { m.imgs[i] = r ? r.url : null; }));
        });
      }
      // attachments:老形状每项带 dataUrl+url 双份 dataURL 拷贝 → 只留短路径 url
      if (m.attachments && m.attachments.some(function (a) { return a && (a.dataUrl || isData(a.url)); })) {
        changed = true;
        m.attachments = m.attachments
          .map(function (a) { return (a && a.url && !isData(a.url)) ? { url: a.url } : null; })
          .filter(Boolean);
      }
    });
    return Promise.all(ps).then(function () {
      (hist || []).forEach(function (m) {
        if (!m) return;
        if (m.imgs) { m.imgs = m.imgs.filter(Boolean); if (!m.imgs.length) delete m.imgs; }
        // attachments 被掏空但 imgs 有路径 → 从 imgs 重建(保持两字段契约一致)
        if (m.attachments && !m.attachments.length) {
          if (m.imgs && m.imgs.length) m.attachments = m.imgs.map(function (p) { return { url: p }; });
          else delete m.attachments;
        }
      });
      return { hist: hist, changed: changed };
    });
  }
  // 失败哨兵判定 — 降级链靠它识别"这串不是搜索结果"。
  // 文案可以改,形状不能破:失败返回必须匹配这里(1361deb 把 "[360 …" 前缀改成
  // 产品化文案后,消费方的 indexOf("[360") 判定失明,错误串被当结果喂给 LLM)。
  function _searchFailed(s) {
    return !s || /^\[(?:360 )?搜索(无结果|无响应|失败|出错|异常|返空)/.test(s) || s.indexOf("[未配置") === 0;
  }
  function _mobileWebSearch360(query, max) {
    var CapHttp = _getCapHttp();
    var url = "https://www.so.com/s";
    var headers = {
      "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
      "Accept-Language": "zh-CN,zh;q=0.9",
    };
    var params = { q: query, pn: "1" };
    var p;
    if (CapHttp) {
      p = CapHttp.get({ url: url, params: params, headers: headers, connectTimeout: 15000, readTimeout: 15000 })
        .then(function (r) { return (r && r.data) || ""; });
    } else {
      // 浏览器 dev fallback (CORS 大概率拦,但保留 path 让 dev 看到错误)
      var qs = Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
      p = realFetch(url + "?" + qs, { headers: headers }).then(function (r) { return r.text(); });
    }
    return p.then(function (html) {
      if (!html) return "[搜索无结果]";
      // DOMParser 解析 + 模糊 class 匹配(critic 校正)
      try {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var items = doc.querySelectorAll('li[class*="res-list"]');
        if (!items.length) return "[搜索无结果]";
        var out = [];
        for (var i = 0; i < items.length && out.length < (max || 5); i++) {
          var node = items[i];
          var a = node.querySelector("h3 a") || node.querySelector("a");
          if (!a) continue;
          var href = a.getAttribute("data-mdurl") || a.getAttribute("href") || "";
          var title = (a.textContent || "").trim();
          var desc = node.querySelector("p.res-desc, .res-desc, p");
          var dt = desc ? (desc.textContent || "").trim() : "";
          if (title) out.push("【" + title + "】 " + (href ? href + " — " : "") + dt);
        }
        return out.length ? out.join("\n\n") : "[搜索无结果]";
      } catch (e) { return "[搜索出错:" + (e.message || "") + "]"; }
    }).catch(function (e) { return "[搜索异常:" + (e && e.message || e) + "]"; });
  }
  function _mobileWebSearchBailian(query, key) {
    if (!key) return Promise.resolve("[未配置搜索 API — 进设置填写以解锁联网搜索]");
    var CapHttp = _getCapHttp();
    var url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions";
    var headers = { "Content-Type": "application/json", Authorization: "Bearer " + key };
    var payload = {
      model: "qwen-flash",
      messages: [{ role: "user", content: "联网搜索并回答下面的查询。列关键事实要点,能附来源链接就附。简洁,别废话。\n\n" + query }],
      enable_search: true,
      search_options: { search_strategy: "turbo", enable_source: true },
    };
    var p;
    if (CapHttp) {
      p = CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 15000, readTimeout: 30000 })
        .then(function (r) { return (r && r.data) || {}; });
    } else {
      p = realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload) }).then(function (r) { return r.json(); });
    }
    return p.then(function (d) {
      var c = d && d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content;
      return c || "[搜索无响应]";
    }).catch(function (e) { return "[搜索异常:" + (e && e.message || e) + "]"; });
  }

  // ── 工具:日期 ───────────────────────────────────────
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  // 全角冒号归一:H1 canonical 是全角(# 21：30),AI 工具/UI 常把读到的时间原样回传,
  // 半角 split(":") 会得到 undefined → 查找 404 / 写入损坏。所有 time 入参先过这里。
  function normTime(t) { return String(t == null ? "" : t).trim().replace(/：/g, ":"); }
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
  // 第N天:对齐桌面 _get_day_one 语义 — 显式设置 vault_day_one > 最早日记日 > 今天(装机日=第1天)。
  // 旧实现硬编码 2026-05-03(开发者 vault 起始日):同步过桌面 vault 的设备结果不变(最早文件就是 5.3),
  // 但全新用户首日会直接"第61天",与桌面同日不同文件名,双端 git 同步必然分叉。
  // 按日历天算,跳过的天也占号(6.14 缺也让 6.15=44),与 file-count 无关。
  var _dayOneIso = null;   // boot 时(seedPromise 链上)算好缓存;seed 之后算 → 新装用户 = 今天
  function _initDayOne() {
    return Store.getSetting("vault_day_one").then(function (explicit) {
      if (explicit && /^\d{4}-\d{2}-\d{2}$/.test(String(explicit).trim())) { _dayOneIso = String(explicit).trim(); return; }
      return Store.listJournalDates().then(function (dates) {
        var ds = (dates || []).filter(function (d) { return /^\d{4}-\d{2}-\d{2}$/.test(d); }).sort();
        _dayOneIso = ds.length ? ds[0] : todayIso();
      });
    }).catch(function () { _dayOneIso = todayIso(); });
  }
  function dayNum(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso); if (!m) return null;
    var a = /^(\d{4})-(\d{2})-(\d{2})$/.exec(_dayOneIso || todayIso());
    var anchor = Date.UTC(+a[1], +a[2] - 1, +a[3]);
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

  // ── 每日打卡 + 八杯水:内嵌在当天 md 顶部(首个时间块前),与桌面 vault 同构 ──
  // 桌面真源:喝水(8 子杯) + 打卡项若干,顶层 - [ ] 名、多粒项带缩进子项。喝水归"八杯水"widget,不进打卡行。
  var SUPP_TOP = /^(- \[)([ xX])(\]\s+)(.+?)(\s*)$/;    // 顶层项 - [ ] 名
  var SUPP_SUB = /^(\s+- \[)([ xX])(\]\s+)(.+?)(\s*)$/; // 缩进子项 - [ ] N
  function suppRegionEnd(lines) { // 补剂段下界 = 首个时间块行号
    for (var i = 0; i < lines.length; i++) if (TIME_H1_RE.test(lines[i])) return i;
    return lines.length;
  }
  function suppTemplate() {
    // 与桌面 server.py _new_day_create 的 fallback top_section 字节同源 —
    // 两端全新安装长出同一份初始 md(改一边必须同步另一边)。
    // 注意:不带尾部 ---/换行,分隔符由 emptyDayMd/seed 按桌面 join 语义补。
    return [
      "# 每日打卡", "",
      "<!-- 想加打卡项(运动 / 阅读 / 冥想 / 补剂...)?跟 AI 说一声就行 -->", "",
      "- [ ] 喝水",
      "  - [ ] 1", "  - [ ] 2", "  - [ ] 3", "  - [ ] 4", "  - [ ] 5", "  - [ ] 6", "  - [ ] 7", "  - [ ] 8",
      "- [ ] (添加你的第一个打卡项)",
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

  // ── 端侧 OCR 后抽颗数(N2 parity)──────────────────────
  // 桌面 oracle 期望:"鱼油 60 粒" → ocr_pill_count = 60
  // 中文/英文/补剂瓶常见 packaging 字串都 cover
  function extractPillCount(ocrText) {
    if (!ocrText) return 0;
    var t = String(ocrText);
    // 优先:数字 + (粒|片|颗|丸|capsules|tablets|softgels|ct|count)
    var m = t.match(/(\d+)\s*(?:粒|片|颗|丸|softgels?|capsules?|tablets?|ct\b|count\b)/i);
    if (m) return parseInt(m[1], 10);
    // 次选:NET / 净含量 / 装量 / Net Content N
    m = t.match(/(?:net\s*(?:content)?|净含量|装量)[\s:：]*(\d+)/i);
    if (m) return parseInt(m[1], 10);
    // 退一步:孤立 token 数字(避开 SAM-e / B-12 这种品牌名连字符内数字)
    // 严格:前后必须是行首/尾或空白/标点,排除 mg/iu/mcg/g/ml 剂量
    var rest = t.replace(/\d+\s*(?:mg|mcg|μg|iu|g|ml|fl\s*oz)/gi, "");
    var standalone = rest.match(/(?:^|[\s,，。;；:：])(\d+)(?=$|[\s,，。;；:：])/g) || [];
    for (var i = 0; i < standalone.length; i++) {
      var n = parseInt(standalone[i].replace(/\D/g, ""), 10);
      if (n >= 10 && n <= 500) return n;
    }
    return 0;
  }

  // 无 native OCR(无 iOS Vision / 无 GMS)时云端兜底:走百炼 vision endpoint
  function _ocrViaCloud(attachmentUrl, dataUrl) {
    var url = attachmentUrl ||
      "/attachments/" + todayIso() + "/inline-ocr-tmp." + Date.now() + ".jpg";
    return fetch("/api/vision/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attachment_url: url, extra_question: "把图里所有文字 OCR 出来,只返文字本身,不要解释。" }),
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.result && j.result.description) return j.result.description;
      if (j && j.description) return j.description;
      return "";
    }).catch(function () { return ""; });
  }

  // ★ H6:统一 OCR 入口 —— 显式探测端侧可用性(不再靠 recognize() 抛异常隐蔽兜),
  //   无 GMS(ML Kit 不可用)→ 发遥测信号 + 置一次性提示标志(杀掉「静默转云端付费」的"静默"),
  //   再走云端。端侧可用则直接用。返 { text, engine, degraded }。
  //   真离线端侧模型(PP-OCR onnx / Tesseract)是 degraded 路径的目标替代,见 native-ocr 插件 TODO。
  var _ocrProbe = null;               // null=未探测, true/false=端侧可用性缓存
  function _ocrNativeAvailable(plugin) {
    if (_ocrProbe !== null) return Promise.resolve(_ocrProbe);
    if (!plugin || !plugin.available) { _ocrProbe = !!(plugin && plugin.recognize); return Promise.resolve(_ocrProbe); }
    return plugin.available().then(function (r) { _ocrProbe = !!(r && r.available); return _ocrProbe; })
      .catch(function () { _ocrProbe = false; return false; });
  }
  function _runOcr(dataUrl, urlForCloud) {
    var plugin = (typeof window !== "undefined") && window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.NativeOcr;
    if (!plugin || !plugin.recognize) {
      // 浏览器 stub / 无插件:不阻断视觉层
      return Promise.resolve({ text: "", engine: "BrowserStub", degraded: false });
    }
    return _ocrNativeAvailable(plugin).then(function (ok) {
      if (ok) {
        return plugin.recognize({ image: dataUrl, languages: ["zh-Hans", "en-US"] })
          .then(function (r) { return { text: (r && r.text) || "", engine: (r && r.engine) || "native", degraded: false }; })
          .catch(function () {
            // 端侧本应可用却抛错 → 兜云端 + 记信号(区别于无 GMS)
            _ocrDegradedNotice("native-error");
            return _ocrViaCloud(urlForCloud || null, dataUrl).then(function (t) { return { text: t || "", engine: "CloudVision_fallback", degraded: true }; });
          });
      }
      // 无 GMS:端侧不可用 → 显式走云端 + 可观测(信号 + 一次性 UI 提示)
      _ocrDegradedNotice("no-gms");
      return _ocrViaCloud(urlForCloud || null, dataUrl).then(function (t) { return { text: t || "", engine: "CloudVision_fallback", degraded: true }; });
    });
  }
  var _ocrNoticeShown = false;
  function _ocrDegradedNotice(reason) {
    try { if (typeof window !== "undefined" && window.emitSignal) window.emitSignal("ocr.cloud_fallback", { reason: reason }); } catch (e) {}
    if (_ocrNoticeShown) return;        // 一次性,不每张图都打扰
    _ocrNoticeShown = true;
    try {
      if (typeof window !== "undefined" && window.GW && window.GW.whisper) {
        window.GW.whisper(reason === "no-gms" ? "这台设备没有端侧文字识别,这次用了云端(会走一次云调用)" : "端侧识别没成,这次用了云端", false);
      }
    } catch (e) {}
  }

  // ── 空白一天模板(打卡段 + 半小时格)— 复刻桌面 _new_day_create 生成算法,输出字节一致 ──
  function emptyDayMd() {
    var parts = [suppTemplate(), "\n---"];
    for (var h = 7; h <= 22; h++) {
      for (var k = 0; k < 2; k++) {
        var mm = k === 0 ? "00" : "30";
        if (h === 7 && mm === "00") continue;   // 桌面同源:7:00 没有,7:30 起
        parts.push("\n# " + h + "：" + mm + "\n\n##\n\n---");
      }
    }
    parts.push("\n# 23：00\n\n##\n");
    return parts.join("\n");
  }

  // ── 首次启动:seed 示例数据(合成,非真日记) ───────────
  function seedIfEmpty() {
    return Store.listJournalDates().then(function (dates) {
      if (dates.length) return;
      var today = todayIso();
      var sample = suppTemplate() + "\n\n---\n\n" + [
        "# 9：00", "", "## #生活 记录今天的一件小事", "",
        "今早做了件让自己满意的事。**意义**:把想法落到了行动上。", "", "---", "",
        "# 13：00", "", "## #工作 完成一项任务", "",
        "花了点时间把一件事推进到一个节点，感觉踏实。", "", "---", "",
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
      // ★ 历史图片路径透出:不透出 AI 下一轮就"看不到用户发过的照片",
      //   对"用刚才那张图换水杯/贴日记"这类跨轮引用直接失明(7.5 真机实锤)
      if (h.imgs && h.imgs.length) {
        var urls = h.imgs.filter(function (u) { return typeof u === "string" && u.indexOf("/attachments/") === 0; });
        // 指令式标记:弱标记("[已上传图片: x]")会被模型自己此前"照片没存下来"的
        // 发言带偏而无视(7.5 真机实锤);必须明说"图还在、URL 直接可用"
        if (urls.length) content += (content ? "\n" : "") + "[系统:本条消息附带的图片已永久保存,附件 URL: " + urls.join(" , ") + " — 后续任何时候需要用这张图(换水杯图标/贴日记等),直接把此 URL 作为 attachment_url 传给对应工具即可,图片不会丢失]";
      }
      if (content) out.push({ role: role, content: content });
    }
    return out;
  }
  // ── Tool calling — Group A 7 个 mobile 本机 endpoint 对应 tool ──
  // OpenAI-compatible function calling spec(DeepSeek 同协议)
  // ── 能力注册表:系统权限 ↔ LLM 工具面 ────────────────────────
  // 原则:模型看到的工具集 = 用户已授权能力的投影。三层门:
  //   ① chat 组装时按 probe 过滤(未授权的工具 schema 不进上下文)
  //   ② dispatchTool 执行前复查(防对话中途去系统设置撤权)
  //   ③ sys 提示只列真实状态
  // 用户已拍板:request_capability 直接弹系统授权框(最终允许/拒绝仍只能用户在系统框上点)。
  var CAPS = [
    { id: "health.steps", label: "步数", plugin: "Steps", tools: ["read_steps"] },
  ];
  function _capPlugin(cap) {
    var P = (typeof window !== "undefined") && window.Capacitor && window.Capacitor.Plugins;
    return (P && P[cap.plugin]) || null;
  }
  function capProbe(cap) { // → 'granted'|'denied'|'undetermined'|'unavailable'
    var p = _capPlugin(cap);
    if (!p || !p.probe) return Promise.resolve("unavailable");
    return p.probe().then(function (r) { return (r && r.state) || "unavailable"; })
      .catch(function () { return "unavailable"; });
  }
  function capRequest(cap) {
    var p = _capPlugin(cap);
    if (!p || !p.request) return Promise.resolve("unavailable");
    return p.request().then(function (r) { return (r && r.state) || "unavailable"; })
      .catch(function () { return "unavailable"; });
  }
  function capStates() { // 全表状态快照 [{cap, state}]
    return Promise.all(CAPS.map(function (c) {
      return capProbe(c).then(function (s) { return { cap: c, state: s }; });
    }));
  }
  // 授权后才解锁的工具 schema(不进常驻 TOOL_SPECS)
  var CAP_TOOL_SPECS = {
    read_steps: { type: "function", function: { name: "read_steps",
      description: "当用户提到与步数、走路、跑步、运动量相关的话题时调用。返回 {today: 当天累计步数, recent: 最近数小时分时步数(旧→新)} — recent 可用来判断用户开始某项运动的时间点或做当天统计。iOS 分时按整点精确;Android 是使用时打点的采样区间,可能稀疏或为空。approximate=true 时数值是近似的,回答带「大约」",
      parameters: { type: "object", properties: {
        hours: { type: "integer", description: "回看最近几小时的分时数据,默认 6,最大 12" },
      } } } },
  };
  var REQUEST_CAP_SPEC = { type: "function", function: { name: "request_capability",
    description: "当用户提到与某项手机能力相关的话题(如问步数/运动量)、而该能力尚未接入时使用:先在对话里说一句,再调用 — 会【直接弹出系统授权框】。granted 后对应工具下一轮可用;denied 则不要重复申请,告诉用户可去 设置→能力 或系统设置手动开启",
    parameters: { type: "object", properties: {
      capability: { type: "string", "enum": ["health.steps"], description: "能力 id" },
    }, required: ["capability"] } } };

  var TOOL_SPECS = [
    { type: "function", function: { name: "patch_journal_block", description: "修改某个时间块的内容并替换标题和正文。修改标题时需明确传递 allow_h2_rename 参数为 true",
      parameters: { type: "object", properties: {
        date: { type: "string", description: "日期格式 YYYY-MM-DD,不提供此参数时默认使用今天" },
        time: { type: "string", description: "日记的时间块,格式为 HH:MM(如 '14:00')" },
        new_md: { type: "string", description: "新内容,从标题行开始" },
        allow_h2_rename: { type: "boolean", description: "改 H2 标题时传 true,否则会被 guard 拒" },
      }, required: ["time", "new_md"] }}},
    { type: "function", function: { name: "insert_journal_block", description: "在指定时间块插入新条目。该操作仅用于空占位符位置。如条目已存在,请使用修改功能。正文内容必填,不能仅提供标题",
      parameters: { type: "object", properties: {
        date: { type: "string" }, time: { type: "string" }, tag: { type: "string" }, title: { type: "string" },
        body: { type: "string", description: "正文内容(需包含结果和意义),不能仅提供标题" },
      }, required: ["time", "tag", "body"] }}},
    { type: "function", function: { name: "check_daily_task", description: "记录每日补剂或药物摄取。按优先级处理参数:吃了几粒(intake) > 增加量(increment) > 直接勾选状态(checked) > 切换状态(toggle)",
      parameters: { type: "object", properties: {
        task_name: { type: "string" }, date: { type: "string" },
        intake: { type: "integer", description: "今天摄取的数量(粒数),此参数优先级最高" },
        increment: { type: "integer", description: "摄取数量的增加量(如 +1)" },
        checked: { type: "boolean", description: "直接勾/取消" },
        daily_dose: { type: "integer", description: "可选参数。显式声明今日的摄取上限(如喝水=8杯)。用于防止新增条目默认限制为 1" },
      }, required: ["task_name"] }}},
    { type: "function", function: { name: "set_daily_task_meta", description: "改修改记录元数据(如每日摄取量或瓶装颗数)",
      parameters: { type: "object", properties: {
        task_name: { type: "string" }, daily_dose: { type: "integer" }, total_pills: { type: "integer" },
      }, required: ["task_name"] }}},
    { type: "function", function: { name: "read_today_schedule", description: "读取今天的日程原始文本内容",
      parameters: { type: "object", properties: { date: { type: "string" } }}}},
    { type: "function", function: { name: "list_recent_days", description: "列出最近几天的日程",
      parameters: { type: "object", properties: { n: { type: "integer", description: "几天,默认 7" } }}}},
    // ★ Scrapbook — 用户拖图进 chat 后,AI 用此 tool 把图放到对应 entry 附近(浮动贴纸)
    //   对齐 PC server.py:1647 place_scrapbook_image 完整 contract
    { type: "function", function: { name: "place_scrapbook_image",
      description: "将用户上传的图片作为浮动贴纸放置在日记中的特定条目附近。将贴纸锚定在对应的时间块",
      parameters: { type: "object", properties: {
        attachment_url: { type: "string", description: "附件 URL 格式:/attachments/YYYY-MM-DD/xxx.png" },
        date: { type: "string", description: "YYYY-MM-DD,默认今天" },
        anchor_time: { type: "string", description: "时间格式 HH:MM,将贴纸锚定到对应的日记条目" },
        x_pct: { type: "number", description: "水平位置百分比,范围 0-95,默认值 75(靠右放置)" },
        y_px: { type: "number", description: "竖直位置像素值,默认 0(自动调整)" },
        rotation: { type: "number", description: "旋转角度(度数),默认随机 -2 到 +2 之间" },
        cutout: { type: "boolean", description: "是否抠图,默认 true" },
      }, required: ["attachment_url", "anchor_time"] }}},
    { type: "function", function: { name: "set_water_cup_image", description: "更换喝水打卡图标。用户发了照片想当水杯图标时传 attachment_url(会自动抠图);想要简洁图标时传单个 emoji 字符(如 🥤)",
      parameters: { type: "object", properties: {
        image: { type: "string", description: "单个 emoji 字符(如 🥤)" },
        attachment_url: { type: "string", description: "用户上传照片的附件 URL,格式:/attachments/YYYY-MM-DD/xxx.jpg" },
      } }}},
    // Group B 新增
    { type: "function", function: { name: "append_journal_comment", description: "为日记条目添加 AI 评论。当无法直接修改用户撰写的内容时使用此功能",
      parameters: { type: "object", properties: {
        date: { type: "string" }, time: { type: "string" }, comment: { type: "string" },
      }, required: ["time", "comment"] }}},
    { type: "function", function: { name: "manage_daily_task", description: "添加新的每日跟踪项目到补剂栏。用于每天追踪一种补剂或药物",
      parameters: { type: "object", properties: {
        action: { type: "string", enum: ["add", "delete"], description: "默认值为 'add'(添加)" },
        task_name: { type: "string", description: "项目名称(最短可辨认即可)。品牌、规格、剂量等详细信息请在元数据中指定而非名称中。注:显示名称最多两行,超长内容将被截断" },
      }, required: ["task_name"] }}},
    // Group C
    { type: "function", function: { name: "search_journal", description: "在本机日记中搜索关键词。返回匹配的日期、时间块和相关文本片段",
      parameters: { type: "object", properties: {
        query: { type: "string", description: "搜索关键词" },
        days: { type: "integer", description: "查询范围(天数),默认 30 天,最大支持 365 天" },
      }, required: ["query"] }}},
    { type: "function", function: { name: "register_aggregate_tag", description: "注册一个项目标签到聚合页面,便于查看该标签下的所有日记条目。仅支持注册顶层标签(不包含子标签)",
      parameters: { type: "object", properties: {
        tag: { type: "string", description: "标签名,无需包含 # 符号(如 '工作' 或 '生活')" },
        description: { type: "string", description: "对该项目的简短描述(可选,一句话即可)" },
      }, required: ["tag"] }}},
    { type: "function", function: { name: "refresh_aggregate", description: "扫描所有日记,将含有已注册标签的条目添加到聚合页面。仅执行追加操作,不删除已有条目",
      parameters: { type: "object", properties: {} } }},
    // ⑥ B widget 体系 — Group W
    { type: "function", function: { name: "list_widgets", description: "列出当前移动设备注册的所有小组件及其属性(如 ID、标题、位置和启用状态)",
      parameters: { type: "object", properties: {} }}},
    { type: "function", function: { name: "set_widget_enabled", description: "启用或停用某个小组件。仅隐藏小组件而不删除其数据",
      parameters: { type: "object", properties: {
        id: { type: "string", description: "小组件的唯一标识符" },
        enabled: { type: "boolean" },
      }, required: ["id", "enabled"] }}},
    { type: "function", function: { name: "add_widget",
      description: "动态加一个新 widget(纯展示型,显示 mobile 本机派生数据)。template 是 HTML 字符串可用 {{var}} 插值。可用变量:" +
        "tasks_done, tasks_total, water_filled, entries_count, date, minutes_to_2130, note_state",
      parameters: { type: "object", properties: {
        id: { type: "string", description: "唯一 id" },
        title: { type: "string" },
        slot: { type: "string", description: "目前仅支持 'care'(护理) 位置", enum: ["care"] },
        template: { type: "string", description: "HTML 模板字符串,支持变量插值(如 '<div>今天 {{tasks_done}}/{{tasks_total}} 完成</div>')" },
      }, required: ["id", "title", "template"] }}},
    { type: "function", function: { name: "remove_widget",
      description: "删除一个动态添加的小组件。仅支持删除由 AI 添加的小组件,核心小组件不可删除",
      parameters: { type: "object", properties: { id: { type: "string" }}, required: ["id"] }}},
    // web_search + fetch_url 移植 PC 端 web_tools.py 三层降级链(critic 校正)
    { type: "function", function: { name: "web_search",
      description: "执行联网搜索以获取信息和真实来源 URL。返回搜索结果的标题、链接和摘要。使用建议:先查看标题和摘要,再决定是否获取完整内容,不要仅依赖摘要回答。限制:每次对话最多使用 2 次,避免陷入循环搜索。搜索源优先级:360 搜索 > 阿里云百炼 > 拒绝执行",
      parameters: { type: "object", properties: {
        query: { type: "string", description: "搜索关键词" },
        max_results: { type: "integer", description: "返回数量,默认 5 条,最多 10 条" },
        category: { type: "string", enum: ["general"], description: "general 为 360 搜索引擎(微信、B站等其他来源暂不支持)" },
      }, required: ["query"] }}},
    { type: "function", function: { name: "fetch_url",
      description: "获取指定 URL 的正文内容(HTML 转为纯文本,最多 3000 字符)。使用建议:先通过网络搜索查看标题再获取,不要盲目获取。同一 URL 不要重复获取。iOS 不支持 http 协议,会自动升级到 https,如果升级失败请改用其他链接",
      parameters: { type: "object", properties: {
        url: { type: "string", description: "http(s):// URL" },
      }, required: ["url"] }}},
    // vision/OCR 移植 — 阿里云百炼 qwen3-vl-flash(OpenAI 兼容)
    { type: "function", function: { name: "vision_classify",
      description: "看图分类 + 描述。返 {kind, description, ocr_likely, suggested_action, brand?, pill_count?}。" +
        "extra_question 可指定问题(如'里面写了啥')替换默认描述任务。",
      parameters: { type: "object", properties: {
        attachment_url: { type: "string", description: "附件 URL,格式为:/attachments/日期/文件名" },
        extra_question: { type: "string", description: "可选,问 vision 一个具体问题" },
      }, required: ["attachment_url"] }}},
    { type: "function", function: { name: "ocr_image",
      description: "识别并提取图片中的所有文字,返回纯文本。内部通过图像分析和自定义问题实现",
      parameters: { type: "object", properties: {
        attachment_url: { type: "string" },
      }, required: ["attachment_url"] }}},
    // Group D photo curator — 复刻 PC list_my_uploads / search_my_uploads / ask_photo_curator
    { type: "function", function: { name: "list_my_uploads",
      description: "列出用户最近上传的图片(默认 20 张,按上传时间从新到旧排序)。每张图片返回 URL、上传日期、描述和分类",
      parameters: { type: "object", properties: {
        n: { type: "integer", description: "返回数量,默认 20 张,最多 100 张" },
      }} }},
    { type: "function", function: { name: "search_my_uploads",
      description: "按关键词搜索本机已上传的图片。基于图片的描述、分类或品牌标签进行匹配。返回匹配结果数组",
      parameters: { type: "object", properties: {
        query: { type: "string", description: "如 '维生素'、'猫'、'截图' 等" },
      }, required: ["query"] }},
    },
    { type: "function", function: { name: "ask_photo_curator",
      description: "请助手帮助用户查找图片(使用自然语言描述)。例如:用户问 '上周拍的那张瓶子',传入 query 参数为 '瓶子'",
      parameters: { type: "object", properties: {
        query: { type: "string" },
      }, required: ["query"] }},
    },
    { type: "function", function: { name: "delete_attachment",
      description: "删除一张已上传的图片及其关联的元数据。该操作不可逆,执行前需确认用户意愿",
      parameters: { type: "object", properties: {
        attachment_url: { type: "string", description: "附件 URL 格式:/attachments/日期/文件名" },
      }, required: ["attachment_url"] }},
    },
  ];
  // tool_name → mobile-api endpoint dispatch
  // 注意:用 window.fetch(shim-hijacked)而不是 realFetch — /api/* 路径要走 shim
  // 路由到本机 handler,realFetch 是绕开 shim 调外部 URL 用的(DeepSeek 等)
  function dispatchTool(name, args) {
    args = args || {};
    var fch = (typeof window !== "undefined") ? window.fetch : realFetch;
    // 写型 journal tool 注入 author='ai'(AI 调用 = fail-safe 路径,撞 @user 仍拒;
    // HTTP user UI 走 endpoint 默认 'user',跟桌面 journal_routes 一致 — 参 J10/J-CB1)
    var writeJournalTools = ["patch_journal_block", "insert_journal_block", "append_journal_comment"];
    if (writeJournalTools.indexOf(name) >= 0 && !args.author) args.author = "ai";
    var H = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args) };
    switch (name) {
      case "patch_journal_block": return fch("/api/journal/patch", H).then(function (r) { return r.json(); });
      case "insert_journal_block":
        // J-CB3 T4:漏 body 时 tool result 注 warning(nag AI 补正文,违反 § H5 提醒)
        var insertOp = fch("/api/journal/insert-block", H).then(function (r) { return r.json(); });
        if (!args.body || !String(args.body).trim()) {
          return insertOp.then(function (result) {
            if (result && result.ok && !result.warning) {
              result.warning = "⚠ 缺正文 — 只插了标题。请补一段说明发生了什么、为什么重要。";
            }
            return result;
          });
        }
        return insertOp;
      case "check_daily_task": return fch("/api/daily-tasks/check", H).then(function (r) { return r.json(); });
      case "set_daily_task_meta": return fch("/api/daily-tasks/meta", H).then(function (r) { return r.json(); });
      case "read_today_schedule": return fch("/api/journal/today" + (args.date ? "?date=" + encodeURIComponent(args.date) : "")).then(function (r) { return r.json(); });
      case "list_recent_days": return fch("/api/journal/days?n=" + (args.n || 7)).then(function (r) { return r.json(); });
      case "set_water_cup_image": {
        // 照片当水杯图标:抠图后存新附件换 URL(复用 place_scrapbook_image 接线,对齐桌面
        // /api/water-cup 的 server 端抠图);无照片(emoji)或任一环失败 → 原参数兜底
        var _wb = Object.assign({}, args);
        var _wc = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Cutout;
        var _wm = /^\/attachments\/([\d-]+)\/(.+)$/.exec(_wb.attachment_url || "");
        var _wcutP = Promise.resolve(null);
        if (_wc && _wc.cutout && _wm) {
          _wcutP = Store.readAttachment(_wm[1], _wm[2]).then(function (d) {
            if (!d) return null;
            return _wc.cutout({ image: d }).then(function (r) { return (r && r.png) || null; }).catch(function () { return null; });
          }).catch(function () { return null; });
        }
        return _wcutP.then(function (png) {
          if (!png) return null;
          return fch("/api/chat/upload-image", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataUrl: png }) })
            .then(function (r) { return r.json(); })
            .then(function (j) { return (j && j.url) || null; })
            .catch(function () { return null; });
        }).then(function (newUrl) {
          if (newUrl) _wb.attachment_url = newUrl;
          return fch("/api/water-cup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(_wb) })
            .then(function (r) { return r.json(); });
        });
      }
      case "place_scrapbook_image": {
        // 端侧抠图接线(对齐桌面 _get_or_create_processed_attachment):cutout!==false 且
        // Cutout 插件在 → 附件转 dataURL → 抠图 → 存为新附件换 URL;任一环失败原图兜底
        var _pb = Object.assign({}, args);
        var _pc = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Cutout;
        var _pm = /^\/attachments\/([\d-]+)\/(.+)$/.exec(_pb.attachment_url || "");
        var _cutP = Promise.resolve(null);
        if (_pb.cutout !== false && _pc && _pc.cutout && _pm) {
          _cutP = Store.readAttachment(_pm[1], _pm[2]).then(function (d) {
            if (!d) return null;
            return _pc.cutout({ image: d }).then(function (r) { return (r && r.png) || null; }).catch(function () { return null; });
          }).catch(function () { return null; });
        }
        return _cutP.then(function (png) {
          if (!png) return null;
          return fch("/api/chat/upload-image", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataUrl: png }) })
            .then(function (r) { return r.json(); })
            .then(function (j) { return (j && j.url) || null; })
            .catch(function () { return null; });
        }).then(function (newUrl) {
          if (newUrl) _pb.attachment_url = newUrl;
          return fch("/api/scrapbook/upsert", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(_pb) })
            .then(function (r) { return r.json(); });
        });
      }
      // Group B
      case "append_journal_comment": return fch("/api/journal/append-comment", H).then(function (r) { return r.json(); });
      case "manage_daily_task":
        var act = String(args.action || "add").toLowerCase();
        if (act === "del") act = "delete";   // 桌面同名工具的枚举是 add/edit/del,别把删除意图静默映射成新增
        if (act !== "add" && act !== "delete") return Promise.resolve({ ok: false, error: "不支持的 action: " + act + "(移动端可用 add / delete)" });
        return fch("/api/daily-tasks/" + act, H).then(function (r) { return r.json(); });
      case "search_journal":
        return fch("/api/journal/search?query=" + encodeURIComponent(args.query || "") + "&days=" + (args.days || 30))
          .then(function (r) { return r.json(); });
      case "register_aggregate_tag": return fch("/api/tag-aggregate/register", H).then(function (r) { return r.json(); });
      case "refresh_aggregate": return fch("/api/tag-aggregate/refresh", H).then(function (r) { return r.json(); });
      // widget runtime tool — Store 持久 + window.gwWidgets in-memory 双源
      case "list_widgets":
        // 改 Store fallback:add_widget 已存 setting/widgets/,持久才是真源
        return Store.listWidgetManifests().then(function (mfs) {
          var live = (typeof window !== "undefined" && window.gwWidgets) ? window.gwWidgets.list() : [];
          return { ok: true, widgets: mfs, live_count: live.length };
        });
      case "set_widget_enabled":
        if (!args.id) return Promise.resolve({ error: "缺 id" });
        // 先读 Store manifest,改 enabled,写回 → in-memory 同步
        return Store.getSetting("widgets/" + args.id).then(function (s) {
          if (!s) return { error: "组件 ID " + args.id + " 不存在" };
          var m; try { m = JSON.parse(s); } catch (e) { return { error: "配置读取失败" }; }
          m.enabled = !!args.enabled;
          return Store.setSetting("widgets/" + args.id, JSON.stringify(m)).then(function () {
            if (typeof window !== "undefined" && window.gwWidgets && window.gwWidgets.setEnabled) {
              try { window.gwWidgets.setEnabled(args.id, !!args.enabled); } catch (_) {}
            }
            return { ok: true, id: args.id, enabled: !!args.enabled };
          });
        });
      case "add_widget":
        if (!args.id || !args.template) return Promise.resolve({ error: "缺少标识或模板" });
        // 核心 widget 名保留,AI 不能覆盖
        if (["cups", "tasks", "pulse"].indexOf(args.id) >= 0) return Promise.resolve({ error: "标识已被系统功能占用" });
        var manifest = { id: args.id, title: args.title || args.id, slot: args.slot || "care", template: args.template, source: "ai-added" };
        return Store.setSetting("widgets/" + args.id, JSON.stringify(manifest)).then(function () {
          if (typeof window !== "undefined" && window.gwWidgets && window.gwWidgets.registerDynamic) {
            window.gwWidgets.registerDynamic(manifest);
          }
          return { ok: true, id: args.id, manifest: manifest };
        });
      case "remove_widget":
        if (!args.id) return Promise.resolve({ error: "缺 id" });
        if (["cups", "tasks", "pulse"].indexOf(args.id) >= 0) return Promise.resolve({ error: "不能删除系统功能" });
        return Store.removeSetting("widgets/" + args.id).then(function () {
          if (typeof window !== "undefined" && window.gwWidgets && window.gwWidgets.unregister) {
            window.gwWidgets.unregister(args.id);
          }
          return { ok: true, id: args.id, removed: true };
        });
      case "web_search": return fch("/api/web/search", H).then(function (r) { return r.json(); });
      case "fetch_url": return fch("/api/web/fetch", H).then(function (r) { return r.json(); });
      // ── 能力注册表工具(门第二层:执行前复查授权,防中途撤权)──
      case "request_capability": {
        var _reqCap = null;
        for (var _rc = 0; _rc < CAPS.length; _rc++) if (CAPS[_rc].id === (args && args.capability)) _reqCap = CAPS[_rc];
        if (!_reqCap) return Promise.resolve({ ok: false, error: "未知能力: " + (args && args.capability) });
        return capRequest(_reqCap).then(function (s) {
          return { ok: s === "granted", capability: _reqCap.id, state: s,
            note: s === "granted" ? "已授权,对应工具下一轮对话可用"
              : s === "denied" ? "被拒绝(或系统不再弹框)。不要重复申请;告诉用户可去 设置→能力 或系统设置手动开启"
              : "未能授权(" + s + ")" };
        });
      }
      case "read_steps": {
        var _stepCap = null;
        for (var _sc = 0; _sc < CAPS.length; _sc++) if (CAPS[_sc].id === "health.steps") _stepCap = CAPS[_sc];
        return capProbe(_stepCap).then(function (s) {
          if (s !== "granted") return { ok: false, error: "步数未授权(" + s + ")" };
          var _pl = _capPlugin(_stepCap);
          var _hours = Math.max(1, Math.min(12, parseInt(args && args.hours, 10) || 6));
          var _p = _pl.stats ? _pl.stats({ hours: _hours }) : _pl.today();  // 旧原生包无 stats → 退化为仅当日
          return _p.then(function (r) {
            var out = { ok: true, today: (r.today != null ? r.today : r.steps), since: r.since,
                        source: r.source, approximate: !!r.approximate, recent: r.recent || [] };
            if (!out.recent.length) out.note = "分时数据暂无(Android 依赖 app 使用中打点采样,刚接入时为空)";
            return out;
          }).catch(function (e) { return { ok: false, error: String((e && e.message) || e) }; });
        });
      }
      case "vision_classify": return fch("/api/vision/classify", H).then(function (r) { return r.json(); });
      case "ocr_image":
        // 内部走 vision_classify + extra_question(对齐 critic plan 设计)
        var ocrArgs = { attachment_url: args.attachment_url, extra_question: "请把图里所有文字 OCR 出来,只返文字本身,不要解释。" };
        return fch("/api/vision/classify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ocrArgs) })
          .then(function (r) { return r.json(); });
      case "list_my_uploads": return fch("/api/uploads/list?n=" + (args.n || 20)).then(function (r) { return r.json(); });
      case "search_my_uploads": return fch("/api/uploads/search", H).then(function (r) { return r.json(); });
      case "ask_photo_curator":
        // 内部复用 search_my_uploads(简化:不另起 LLM 子查询;PC 端 photo curator 是 LLM 子查询,
        // mobile 端简化为关键词搜)
        return fch("/api/uploads/search", H).then(function (r) { return r.json(); });
      case "delete_attachment": return fch("/api/uploads/delete", H).then(function (r) { return r.json(); });
      default: return Promise.resolve({ error: "unknown tool: " + name });
    }
  }
  // expose for tests + future overrides
  if (typeof window !== "undefined") { window.__gwTool = { specs: TOOL_SPECS, dispatch: dispatchTool, extractSynth: _extractSynthToolCalls }; }

  function pickReply(d) { return d && d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content; }

  // 一次性 LLM completion(非流式)— compact summary 等复用。失败返 null,不 throw(silent-failure)。
  function _llmComplete(apiKey, model, messages, maxTokens) {
    var url = "https://api.deepseek.com/v1/chat/completions";
    var headers = { "Content-Type": "application/json", Authorization: "Bearer " + apiKey };
    var payload = { model: model || "deepseek-chat", messages: messages, max_tokens: maxTokens || 500, temperature: 0.3, stream: false };
    var CapHttp = _getCapHttp();
    if (CapHttp) {
      return CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 15000, readTimeout: 60000 })
        .then(function (r) { return (r && r.status >= 200 && r.status < 300) ? pickReply(r.data) : null; })
        .catch(function () { return null; });
    }
    return realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload) })
      .then(function (r) { return r.json(); }).then(function (d) { return pickReply(d); })
      .catch(function () { return null; });
  }
  // compact 摘要 prompt(对照 PC compact_summary.py)— 防 thread 清空后 AI 失忆冷启
  var _COMPACT_SUMMARY_PROMPT = "这是一段刚被压进 md 的对话。\n请用 200 字以内中文写一个摘要,给后续对话延续上下文,**只写关键决策 / 待办 / 当下话题**,\n不写流程细节、不复述每句话、不带工具名。读者是这个对话的下一回合,不是外人。\n\n对话原文:\n═══════════════════════════════════════════\n{conversation}\n═══════════════════════════════════════════\n\n返一段散文,不带标题,不带 ``` 包裹。";

  // 真打一次 chat.completions ping(对齐桌面 setup_test L89-105):
  // 用 {api_key, base_url, model} 真打 POST base_url/chat/completions(messages=[ping], max_tokens=8)
  // 通 → {ok:true, reply, model};不通 → {ok:false, reason: "HTTP <code>: <message>"}
  function _setupTest(profile) {
    var url = profile.base_url.replace(/\/+$/, "") + "/chat/completions";
    var headers = { "Content-Type": "application/json", Authorization: "Bearer " + profile.api_key };
    var payload = { model: profile.model, messages: [{ role: "user", content: "ping" }], max_tokens: 8, stream: false };
    function parseReply(d) {
      var msg = d && d.choices && d.choices[0] && d.choices[0].message;
      return (msg && msg.content || "").slice(0, 80);
    }
    function translateError(httpStatus, body) {
      // 复刻桌面 L100-105 错误翻译:截短常见 OAI SDK 长 error
      if (body && body.error && body.error.message) return "HTTP " + (httpStatus || "?") + ": " + body.error.message;
      if (typeof body === "string") return "HTTP " + (httpStatus || "?") + ": " + body.slice(0, 200);
      return "HTTP " + (httpStatus || "?");
    }
    var CapHttp = _getCapHttp();
    if (CapHttp) {
      // CapacitorHttp 真机走原生 HTTP,绕 WKWebView CORS
      // 单位是毫秒(Capacitor 6 文档):connect 15s / read 60s
      return CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 15000, readTimeout: 60000 })
        .then(function (r) {
          var status = r && r.status;
          var d = r && r.data;
          if (status >= 200 && status < 300 && d && d.choices) {
            return jsonResp({ ok: true, reply: parseReply(d), model: profile.model });
          }
          var rawBody = (typeof d === "string") ? d.slice(0, 200) : JSON.stringify(d || {}).slice(0, 200);
          return jsonResp({ ok: false, reason: translateError(status, d), debug: { status: status, url: url, raw: rawBody } });
        })
        .catch(function (e) {
          var em = String(e && e.message || e);
          return jsonResp({ ok: false, reason: em.slice(0, 200), debug: { url: url, caphttp_err: em, has_window_cap: typeof window !== "undefined" && !!window.Capacitor } });
        });
    }
    // 浏览器 fallback
    var ctrl = (typeof AbortController === "function") ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 30000) : null;
    return realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload), signal: ctrl && ctrl.signal })
      .then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().then(function (d) { return { status: r.status, data: d }; });
      })
      .then(function (res) {
        if (res.status >= 200 && res.status < 300 && res.data && res.data.choices) {
          return jsonResp({ ok: true, reply: parseReply(res.data), model: profile.model });
        }
        return jsonResp({ ok: false, reason: translateError(res.status, res.data) });
      })
      .catch(function (e) { return jsonResp({ ok: false, reason: String(e && e.message || e).slice(0, 200) }); });
  }

  // ── claim audit(Path X:防 AI 口头声称已写入但没真 tool call)──────
  // 桌面 chat_routes L280 _audit_unauthorized_claim 端口:5.22 msg 5/7 事故等价防御。
  // claim 措辞 + actions 空 → 自动加 disclaimer 让用户看到"AI 在撒谎"。
  // 7.5 事故:用户发补剂照"帮我加打卡"→ AI 回"帮你加到打卡里啦/打卡成功/勾上啦"但零 tool call,
  //   daily-tasks.md 空。原正则漏了 加到/打卡成功/勾上 等完成态措辞(guard 是 actions 空,
  //   故可放心拓宽:真调了 tool 就不触发)。桌面 chat_routes 同步。
  var _CLAIM_PHRASE_RE = /记进|写进|搞定|已写[入好]|已加入|已添加|已保存|已记录|已贴|已落|已 ?patch|写好了|写完了|加好了|加完了|落进|帮你加[到上进]|已.{0,4}勾[上选]|打卡成功|已打卡|设置好[了啦]|已设置好|创建好[了啦]|已创建|已更新|更新好[了啦]|加上去了|加进去了|saved|recorded|wrote|patched|done|added|checked|created|updated/i;
  var _CLAIM_DISCLAIMER =
    "\n\n*(server audit:本回合未触发任何 tool 调用,上面的「已写入/记进了」等措辞" +
    "未对应真实动作 — 日记 / 聚合页没改。要真落请说『重试』或换一句指令。)*";
  function _auditUnauthorizedClaim(content, actions) {
    if ((actions && actions.length) || !content) return content;
    if (!_CLAIM_PHRASE_RE.test(content)) return content;
    return content + _CLAIM_DISCLAIMER;
  }

  // ── DSML 泄漏闸:strip AI 字面 <｜｜DSML｜｜...> 标签防裸渲染 ─────
  // 桌面 chat_routes L201-219 等价:deepseek-v4-pro 偶尔把 tool_calls 当 content 文本吐,
  // 全角 U+FF5C 或 ASCII | 命名空间;3 层 strip 防残留。
  var _DSML_WRAPPER_RE = /<[｜|]{1,2}DSML[｜|]{1,2}tool_calls>[\s\S]*?<\/[｜|]{1,2}DSML[｜|]{1,2}tool_calls>/g;
  var _DSML_INVOKE_STRIP_RE = /<[｜|]{1,2}DSML[｜|]{1,2}invoke[^>]*?>[\s\S]*?<\/[｜|]{1,2}DSML[｜|]{1,2}invoke>/g;
  var _DSML_TAG_RE = /<\/?[｜|]{1,2}DSML[｜|]{1,2}[^>]*?>/g;
  function _stripDsml(content) {
    if (!content || content.indexOf("DSML") < 0) return content;
    return content
      .replace(_DSML_WRAPPER_RE, "")
      .replace(_DSML_INVOKE_STRIP_RE, "")
      .replace(_DSML_TAG_RE, "")
      .replace(/\n{3,}/g, "\n\n");  // 收一下 strip 后多余空行
  }
  // ★ H3(对齐 PC _extract_synthetic_tool_calls):DeepSeek 把 tool 当文本吐时,
  //   从 content 抠出 invoke/param → 真 tool_call 结构,交回 loop 执行(不再只 strip 丢弃动作)。
  //   args 保持字符串(同 PC;tool handler 各自 parseInt/判定)。
  var _DSML_INVOKE_RE = /<[｜|]{1,2}DSML[｜|]{1,2}invoke\s+name="([^"]+)"\s*>([\s\S]*?)<\/[｜|]{1,2}DSML[｜|]{1,2}invoke>/g;
  var _DSML_PARAM_RE = /<[｜|]{1,2}DSML[｜|]{1,2}parameter\s+name="([^"]+)"[^>]*>([\s\S]*?)<\/[｜|]{1,2}DSML[｜|]{1,2}parameter>/g;
  function _extractSynthToolCalls(content) {
    if (!content || content.indexOf("DSML") < 0) return { stripped: content, calls: [] };
    var calls = [], m, i = 0;
    _DSML_INVOKE_RE.lastIndex = 0;
    while ((m = _DSML_INVOKE_RE.exec(content)) !== null) {
      var name = m[1].trim(), body = m[2], args = {}, pm;
      _DSML_PARAM_RE.lastIndex = 0;
      while ((pm = _DSML_PARAM_RE.exec(body)) !== null) args[pm[1].trim()] = pm[2].trim();
      calls.push({ id: "call_synth_" + Date.now() + "_" + (i++) + Math.random().toString(36).slice(2, 6), name: name, args: args });
    }
    return { stripped: _stripDsml(content), calls: calls };
  }

  // 多轮 tool 调用 loop:DeepSeek 返 tool_calls → dispatch → result push 回 → 再调,
  // 直到无 tool_calls 或达 maxRounds 上限(防 infinite loop)。
  // 最后一轮 force-no-tool(不传 tools)防 AI 永远在调用 tool 不出回应。
  // frequency cap 对齐 PC L2642:web_search ≤ 3/对话,fetch_url ≤ 5/对话
  // 闭包 per-conversation counter,parallel tool_calls 也同步累加防 race(critic 标的)
  var TOOL_FREQ_CAP = { web_search: 3, fetch_url: 5 };
  function chatViaDeepseek(body, key, model) {
    var freqCount = {};
    // last_actions 累积:tool dispatch 成功 push;失败 / capped 不算"真动作"
    // 用于 emit "done" 前的 claim audit(actions 空 + claim 措辞 → 加 disclaimer)
    var lastActions = [];
    return Promise.all([Store.readJournalMd(todayIso()), capStates()]).then(function (_rs) {
      var todayMd = _rs[0], capSnap = _rs[1];
      // 能力门第一层:已授权 → 工具 schema 进上下文;可申请 → 只给 request_capability
      var capTools = [], capOn = [], capOff = [];
      for (var _ci = 0; _ci < capSnap.length; _ci++) {
        var _cs = capSnap[_ci];
        if (_cs.state === "granted") {
          capOn.push(_cs.cap.label);
          for (var _ti = 0; _ti < _cs.cap.tools.length; _ti++) {
            if (CAP_TOOL_SPECS[_cs.cap.tools[_ti]]) capTools.push(CAP_TOOL_SPECS[_cs.cap.tools[_ti]]);
          }
        } else if (_cs.state === "undetermined" || _cs.state === "denied") {
          capOff.push(_cs.cap.label + "(" + _cs.cap.id + ")");
        }
      }
      if (capOff.length) capTools.push(REQUEST_CAP_SPEC);
      var toolsForRun = TOOL_SPECS.concat(capTools);
      var sys = "你是用户的日记协作 AI,语气温和、像深夜台灯下说话。\n\n" +
        "这是今天的日记:\n\n" + (todayMd || "(今天还没写)") +
        "\n\n你有以下工具可用 — 改日记/打卡/换图标时调对应 tool;只聊天回应不调 tool。" +
        "\n⚠️铁律:凡是「加打卡项/勾打卡/改日记/换图标」这类会改数据的动作,必须真调对应 tool(manage_daily_task/check_daily_task/…)。" +
        "严禁只用文字说『已加到打卡里/打卡成功/已勾上』而不调 tool——没调 tool = 什么都没发生,用户会以为做了却落空。要做就调,做不了就说清楚,不许假装。";
      if (capOn.length || capOff.length) {
        sys += "\n\n手机能力:已接入 " + (capOn.join("、") || "无") +
          (capOff.length ? ";未接入 " + capOff.join("、") + " — 用户想用时可调 request_capability(会直接弹系统授权框,弹前先跟用户说一句)" : "");
      }
      // ★ 对话框贴图:用户这条消息带了图(refs)→ 给 AI attachment_url + place 指引(对照 PC vision-pre-router)
      var _refs = (body && body.refs) || [];
      if (_refs.length) {
        sys += "\n\n【本轮用户发了 " + _refs.length + " 张图】attachment_url:" +
          _refs.map(function (r) { return r.url || r; }).join("、") +
          "。若用户想把图贴到日记(贴/放/钉到某条或某时间块),调 place_scrapbook_image(attachment_url, anchor_time='HH:MM') 落贴纸(JSON 旁路、不动 MD);anchor_time 取用户指定的时间,没指定就取今天最近一条 entry。";
        var _noCut = _refs.filter(function (r) { return r && r.cutout === false; }).map(function (r) { return r.url; });
        if (_noCut.length) {
          sys += "\n用户已为这些图选了「原图不抠」(chip 开关 = 最终意图,不要再问):" + _noCut.join("、") +
            " — 对它们调 place_scrapbook_image 时必须传 cutout=false。";
        }
      }
      var messages = [{ role: "system", content: sys }].concat(histToMsgs(body), [{ role: "user", content: (body && body.message) || "" }]);
      var events = [];
      var maxRounds = 5;
      var url = "https://api.deepseek.com/v1/chat/completions";
      var headers = { "Content-Type": "application/json", Authorization: "Bearer " + key };
      // lazy resolve CapacitorHttp:IIFE 顶部 cache 的 _cap 在 Capacitor bridge 未就绪时是 null
      // → 走 fallback realFetch 但 WebView 跨域被 CORS 阻 → 用户看到"调用失败"
      // 真机阶段(尤其首次启动后)必走 native HTTP 绕 CORS
      var CapHttp = _getCapHttp();

      function callRound(round) {
        if (round >= maxRounds) {
          events.push({ type: "error", text: "已达最大操作步数 (" + maxRounds + "),停止" });
          events.push({ type: "done", actions: [], model_id: model || "deepseek" });
          return Promise.resolve(events);
        }
        var lastRound = round === maxRounds - 1;
        var payload = { model: model || "deepseek-chat", messages: messages, stream: false };
        if (!lastRound) { payload.tools = toolsForRun; payload.tool_choice = "auto"; }
        var fetchPromise;
        if (CapHttp) {
          fetchPromise = CapHttp.post({ url: url, headers: headers, data: payload, connectTimeout: 15000, readTimeout: 90000 })
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
            events.push({ type: "error", text: "AI 无响应" });
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
              // frequency cap 同步累加 + 检查(critic 防 parallel race)
              var cap = TOOL_FREQ_CAP[name];
              if (cap != null) {
                freqCount[name] = (freqCount[name] || 0) + 1;
                if (freqCount[name] > cap) {
                  var capMsg = name + " 已达上限 (" + cap + " 次/对话),停止继续调,基于已搜到的信息直接回答用户";
                  events.push({ type: "tool_call", id: tc.id, name: name, args: args });
                  events.push({ type: "tool_result", id: tc.id, name: name, ok: false, error: capMsg });
                  messages.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify({ error: capMsg, _freq_capped: true }) });
                  return Promise.resolve();
                }
              }
              events.push({ type: "tool_call", id: tc.id, name: name, args: args });
              return dispatchTool(name, args).then(function (result) {
                var ok = !(result && result.error);
                events.push({ type: "tool_result", id: tc.id, name: name, ok: ok, result: result });
                messages.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify(result || {}) });
                // claim audit:仅 ok 真动作累积;ok=false 不算"真落"(防 AI 看"已记"但 dispatch 失败)
                if (ok) lastActions.push({ name: name, args: args, result: result });
              }).catch(function (err) {
                var e = String(err && err.message || err);
                events.push({ type: "tool_result", id: tc.id, name: name, ok: false, error: e });
                messages.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify({ error: e }) });
              });
            });
            return Promise.all(ps).then(function () { return callRound(round + 1); });
          }
          // ★ H3:OpenAI tool_calls 字段为空时,再看 content 里有没有 DSML 伪 tool_call —
          //   有就抠出来真执行 + 续 loop(对齐 PC),不再只 strip 把动作丢掉。
          var raw = msg.content || "(空回复)";
          var synth = _extractSynthToolCalls(raw);
          if (synth.calls.length && !lastRound) {
            // 伪 tool_call 的 assistant 消息进 messages(content 用 strip 后的,避免 DSML 再喂回模型)
            messages.push({ role: "assistant", content: synth.stripped });
            var sps = synth.calls.map(function (c) {
              var cap = TOOL_FREQ_CAP[c.name];
              if (cap != null) {
                freqCount[c.name] = (freqCount[c.name] || 0) + 1;
                if (freqCount[c.name] > cap) {
                  var capMsg = c.name + " 已达上限 (" + cap + " 次/对话),停止继续调";
                  events.push({ type: "tool_call", id: c.id, name: c.name, args: c.args });
                  events.push({ type: "tool_result", id: c.id, name: c.name, ok: false, error: capMsg });
                  messages.push({ role: "tool", tool_call_id: c.id, content: JSON.stringify({ error: capMsg, _freq_capped: true }) });
                  return Promise.resolve();
                }
              }
              events.push({ type: "tool_call", id: c.id, name: c.name, args: c.args });
              return dispatchTool(c.name, c.args).then(function (result) {
                var ok = !(result && result.error);
                events.push({ type: "tool_result", id: c.id, name: c.name, ok: ok, result: result });
                messages.push({ role: "tool", tool_call_id: c.id, content: JSON.stringify(result || {}) });
                if (ok) lastActions.push({ name: c.name, args: c.args, result: result });
              }).catch(function (err) {
                var e = String(err && err.message || err);
                events.push({ type: "tool_result", id: c.id, name: c.name, ok: false, error: e });
                messages.push({ role: "tool", tool_call_id: c.id, content: JSON.stringify({ error: e }) });
              });
            });
            return Promise.all(sps).then(function () { return callRound(round + 1); });
          }
          // 无 tool_calls 也无 synth = 终态:strip DSML 残留 + claim audit
          var cleaned = synth.stripped;
          var audited = _auditUnauthorizedClaim(cleaned, lastActions);
          events.push({ type: "delta", text: audited });
          events.push({ type: "done", actions: lastActions, model_id: model || "deepseek" });
          return events;
        }).catch(function (err) {
          var emsg = String(err && err.message || err);
          if (emsg.indexOf("Failed to fetch") >= 0 || emsg.indexOf("CORS") >= 0) {
            events.push({ type: "delta", text: "（浏览器有限制，用真机 App 即可正常聊。）" });
          } else if (emsg.indexOf("abort") >= 0 || emsg.indexOf("timeout") >= 0) {
            events.push({ type: "error", text: "对话超时，请重试" });
          } else {
            events.push({ type: "error", text: "AI 对话失败:" + emsg });
          }
          events.push({ type: "done", actions: [], model_id: model || "deepseek" });
          return events;
        });
      }
      // ★ vision hints(对照 PC chat_routes._refs_to_vision_hints):chat 时对每张 ref
      //   跑 /api/vision/classify(内部有 uploads_index vision_result 缓存,重复图不重复扣费),
      //   把"图里是什么"注进 system — 没有这步模型对图片内容零感知(7.5 真机实锤:
      //   用户发补剂照说'帮我添加打卡',AI 只能反问)。单图失败静默跳过,不阻对话。
      var _visionHintP = !_refs.length ? Promise.resolve("") : Promise.all(_refs.map(function (r) {
        var u = r.url || r;
        return fch("/api/vision/classify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ attachment_url: u }) })
          .then(function (rr) { return rr.json(); })
          .then(function (j) {
            var v = j && j.result;
            if (!v) return null;
            var desc = typeof v === "string" ? v : (v.description || v.desc || JSON.stringify(v));
            return "- " + u + ": " + String(desc).slice(0, 400);
          }).catch(function () { return null; });
      })).then(function (arr) {
        var xs = arr.filter(Boolean);
        return xs.length ? "\n\n【图片内容(vision 识别)】\n" + xs.join("\n") +
          "\n结合图片内容行动:是物品/补剂想打卡 → manage_daily_task 加项(可再用图当图标);是水杯 → set_water_cup_image;想留在日记 → place_scrapbook_image。" : "";
      }).catch(function () { return ""; });
      return _visionHintP.then(function (vh) {
        if (vh) messages[0].content += vh;
        return callRound(0);
      }).then(function (all) { return sseResp(all); });
    });
  }

  // ── 端点处理 ─────────────────────────────────────────
  function qsDate(u) { return new URL(u, location.origin).searchParams.get("date") || ""; }

  // ★ H2:按日期串行化日记 read-modify-write,堵 lost-update(AI 21:30 纸条写入 +
  //   用户行内编辑并发交错 → 后写者覆盖先写者,对齐 PC sha-baseline+lock 红线)。
  //   JS 单线程,竞态只在 async gap;同一 iso 的写全排进一条 promise 链顺序执行。
  var _journalWriteChain = {};
  function withJournalLock(date, fn) {
    var prev = _journalWriteChain[date] || Promise.resolve();
    var run = prev.then(fn, fn);              // 不管前一个成败都跑本次
    _journalWriteChain[date] = run.then(function () {}, function () {});  // 链尾永不 reject
    return run;
  }

  var handlers = {
    "GET /api/init-status": function () {
      return jsonResp({ ready: true, phase: "ready", detail: "", started_at: null, finished_at: null, error: null });
    },
    "GET /api/health": function () {
      return jsonResp({ ok: true, ts: new Date().toISOString().slice(0, 19), version: APP_VERSION, platform: "mobile" });
    },
    "GET /api/config-status": function () {
      return Store.getSetting("deepseek_key").then(function (k) {
        return k ? jsonResp({ ok: true, model: "deepseek-v4-pro", provider: "deepseek" })
                 : jsonResp({ ok: false, reason: "未配置 AI 对话——进设置填写 API 密钥" });
      });
    },
    // 关键:必须 configured:true,否则被锁在无法关闭的设置弹窗后面
    "GET /api/setup-status": function () { return jsonResp({ configured: true, profile_count: 1 }); },
    "GET /api/setup/current": function () {
      // 同时返桌面 contract(models[0].api_key)+ mobile 顶级字段(deepseek_key/dashscope_key)双兼容
      return Promise.all([
        Store.getSetting("deepseek_key"),
        Store.getSetting("dashscope_key"),
      ]).then(function (vals) {
        var dsKey = vals[0] || "";
        var azKey = vals[1] || "";
        return jsonResp({
          models: [{ id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", api_key: dsKey, base_url: "https://api.deepseek.com/v1" }],
          default_model_id: "deepseek-v4-pro",
          dashscope_api_key: azKey, dashscope_base_url: "", dashscope_vision_model: "",
          baidu_cutout_api_key: "", baidu_cutout_secret_key: "",
          // mobile 顶级字段(setup.js mobile 版 + gw-app.js 直接读)
          deepseek_key: dsKey,
          dashscope_key: azKey,
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
      // 对齐 PC contract:{ok, image_url_present},+ 保留 image_url 给 mobile UI
      return Store.getSetting("water_cup_img").then(function (img) {
        return jsonResp({ ok: true, image_url_present: !!img, image_url: img || null });
      });
    },
    // D6 test_water_cup_get_set_roundtrip_reserved_key:
    //   POST 缺 url → 400;有 attachment_url → 200 ok;GET 返存的 image_url
    //   桌面 server 端走抠图处理;mobile 端侧抠图后直接存 attachment_url
    //   (兼容旧 body.image dataUrl 字段供已部署 client)
    // ★ Scrapbook endpoints — 对齐 PC server.py 的 /api/scrapbook/* 三件套
    "GET /api/scrapbook": function (req, u) {
      var date = new URL(u, location.origin).searchParams.get("date") || todayIso();
      return Store.readScrapbook(date).then(function (items) {
        // ★ src 若是 /attachments/{date}/{stem} 路径 → 解析成 dataURL 供 <img> 渲染
        //   (WKWebView 的 <img src> 不走 shim fetch 拦截,必须真 dataURL;AI 路径存的是路径)
        return Promise.all((items || []).map(function (it) {
          if (!it.src || it.src.indexOf("data:") === 0) return it;
          var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(it.src);
          if (!m) return it;
          return Store.readAttachment(m[1], m[2]).then(function (d) { return d ? Object.assign({}, it, { src: d }) : it; });
        })).then(function (resolved) { return jsonResp({ ok: true, date: date, items: resolved }); });
      });
    },
    "POST /api/scrapbook/upsert": function (req, u, body) {
      body = body || {};
      var date = body.date || todayIso();
      return Store.readScrapbook(date).then(function (items) {
        var id = body.id || ("sk-" + Math.random().toString(36).slice(2, 10));
        var existingIdx0 = items.findIndex(function (it) { return it.id === id; });
        // ★ 已存在 + 没带 attachment_url = 部分更新(Phase3 拖拽/缩放/旋转,对照 PC whitelist update,不重建 item)
        if (existingIdx0 >= 0 && !body.attachment_url) {
          var ex = items[existingIdx0];
          ["x_pct", "y_px", "size_pct", "rotation", "anchor_time", "w", "h", "z"].forEach(function (k) {
            if (typeof body[k] !== "undefined" && body[k] !== null) ex[k] = body[k];
          });
          if (typeof body.y_px === "number") ex.auto_y = false;
          return Store.writeScrapbook(date, items).then(function () { return jsonResp({ ok: true, item: ex }); });
        }
        if (!body.attachment_url) return jsonResp({ ok: false, error: "缺少图片" }, 400);
        if (!body.anchor_time) return jsonResp({ ok: false, error: "缺少关联时间" }, 400);
        var item = {
          id: id,
          src: body.attachment_url,
          anchor_time: body.anchor_time,
          x_pct: typeof body.x_pct === "number" ? body.x_pct : 75,
          y_px: typeof body.y_px === "number" ? body.y_px : 0,
          // ★ size_pct:贴纸占 .sb-layer 宽 %(对齐 PC 等比缩放契约,换分辨率不漂);默认 ~18%
          size_pct: typeof body.size_pct === "number" ? body.size_pct : 18,
          w: body.w || 220,
          h: body.h || 220,
          rotation: typeof body.rotation === "number" ? body.rotation : (Math.random() * 4 - 2),
          auto_y: body.y_px == null,
          cutout: body.cutout !== false,
          z: (items.length || 0) + 1,
        };
        var existingIdx = items.findIndex(function (it) { return it.id === id; });
        if (existingIdx >= 0) items[existingIdx] = item;
        else items.push(item);
        return Store.writeScrapbook(date, items).then(function () { return jsonResp({ ok: true, item: item, image_url: body.attachment_url }); });
      });
    },
    "POST /api/scrapbook/delete": function (req, u, body) {
      body = body || {};
      var date = body.date || todayIso();
      var id = body.id;
      if (!id) return jsonResp({ ok: false, error: "缺 id" }, 400);
      return Store.readScrapbook(date).then(function (items) {
        var filtered = items.filter(function (it) { return it.id !== id; });
        return Store.writeScrapbook(date, filtered).then(function () { return jsonResp({ ok: true, removed: items.length - filtered.length }); });
      });
    },
    "POST /api/water-cup": function (req, u, body) {
      var url = body && (body.attachment_url || body.image);
      if (!url) return jsonResp({ ok: false, error: "缺少图片" }, 400);
      return Store.setSetting("water_cup_img", url).then(function () { return jsonResp({ ok: true }); });
    },
    "GET /api/journal/tag-stats": function (req, u) {
      // J3 test_tag_stats_top_and_default_for_new_user:
      //   空 vault → 兜底 5 default tag + default:true
      //   有 day file → 扫 md 统计 ## #tag 出现次数,top limit
      // 与桌面 journal_routes.py tag-stats 兜底 + 移动 UI 建议列表同一套(改一处必须同步三处)
      var DEFAULT_TAGS = ["工作", "生活", "健康", "心情", "运动"];
      var limit = parseInt(new URL(u, location.origin).searchParams.get("limit"), 10) || 10;
      return Store.listJournalDates().then(function (dates) {
        if (!dates.length) {
          return jsonResp({ tags: DEFAULT_TAGS.map(function (t) { return { tag: t, count: 0, "default": true }; }) });
        }
        return Promise.all(dates.map(function (d) { return Store.readJournalMd(d); })).then(function (mds) {
          var counts = {};
          mds.forEach(function (md) {
            if (!md) return;
            var lines = md.split(/\r?\n/);
            lines.forEach(function (line) {
              if (line.indexOf("## ") !== 0) return;
              // 扫 H2 行的 #tag(可能多个,如 "## #投资 #协作 KV cache")
              var m = line.match(/#[\w一-鿿/\-]+/g);
              if (!m) return;
              m.forEach(function (rawTag) {
                var tag = rawTag.replace(/^#/, "").split("/")[0];  // 顶层 tag(去 sub-tag)
                if (tag) counts[tag] = (counts[tag] | 0) + 1;
              });
            });
          });
          var sorted = Object.keys(counts).map(function (t) { return { tag: t, count: counts[t] }; });
          sorted.sort(function (a, b) { return b.count - a.count; });
          return jsonResp({ tags: sorted.slice(0, limit) });
        });
      });
    },
    // ── 标签聚合(对照 PC GET /api/tag-aggregate + _parse_tag_aggregate)──
    "GET /api/tag-aggregate": function () {
      return Store.readTagAggregate().then(function (text) {
        if (text === null || text === undefined) return jsonResp({ sections: [], warning: "标签索引不存在" });
        return jsonResp({ sections: _parseTagAggregate(text) });
      });
    },
    // POST /api/tag-aggregate/register(对照 PC journal_routes.py:193)— 追加 ## #tag + 空表头
    "POST /api/tag-aggregate/register": function (req, u, body) {
      var tag = ((body && body.tag) || "").trim().replace(/^#/, "").trim();
      var description = ((body && body.description) || "").trim();
      var withSub = !!(body && body.with_sub);
      if (!tag) return jsonResp({ ok: false, error: "标签名不能为空" });
      if (!/^[\w\-一-鿿/]+$/.test(tag)) return jsonResp({ ok: false, error: "标签只能用字母、数字、连字符或中文，收到的是: " + tag });
      if (tag.indexOf("/") >= 0) return jsonResp({ ok: false, error: "注册主标签（不包含分类）；分类标签会自动归类" });
      return Store.readTagAggregate().then(function (text) {
        text = (text === null || text === undefined) ? "# 标签聚合\n" : text;
        var esc = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        if (new RegExp("^##\\s+#" + esc + "\\s*$", "m").test(text)) return jsonResp({ ok: false, error: "#" + tag + " 已经注册过了" });
        var parts = ["## #" + tag + "\n"];
        if (description) parts.push("\n" + description + "\n");
        parts.push("\n");
        if (withSub) { parts.push("| 日期 | 时间 | 链接 | 内容 | Sub |\n"); parts.push("|------|------|------|------|-----|\n"); }
        else { parts.push("| 日期 | 时间 | 链接 | 内容 |\n"); parts.push("|------|------|------|------|\n"); }
        parts.push("\n---\n");
        var section = parts.join("");
        var sep = text.endsWith("\n") ? "" : "\n";
        if (!text.replace(/\s+$/, "").endsWith("---")) { sep = text.trim() ? sep + "\n---\n\n" : sep; }
        else { sep += "\n"; }
        return Store.writeTagAggregate(text + sep + section).then(function () { return jsonResp({ ok: true, tag: tag, with_sub: withSub }); });
      });
    },
    // POST /api/tag-aggregate/refresh(对照 PC journal_routes.py:252 + _refresh_tag_aggregate)— 扫 journal → 只 append 缺失行
    "POST /api/tag-aggregate/refresh": function () {
      return Store.readTagAggregate().then(function (text) {
        if (text === null || text === undefined) return jsonResp({ ok: false, error: "标签索引不存在", added: 0 });
        var sections = _parseTagAggregate(text);
        var projectTags = sections.map(function (s) { return s.tag; });
        if (!projectTags.length) return jsonResp({ ok: false, error: "没找到任何项目标签", added: 0 });
        return Store.listJournalDates().then(function (dates) {
          return Promise.all((dates || []).map(function (d) { return Store.readJournalMd(d).then(function (md) { return { iso: d, md: md }; }); })).then(function (mds) {
            var scanned = _scanJournalForTags(projectTags, mds);
            var existing = {};
            sections.forEach(function (s) { existing[s.tag] = {}; s.rows.forEach(function (r) { existing[s.tag][(r.iso_date) + "|" + (r.time) + "|" + (r.sub_tag || "")] = true; }); });
            var newRows = {}; projectTags.forEach(function (t) { newRows[t] = []; });
            Object.keys(scanned).forEach(function (tag) {
              var seen = {};
              scanned[tag].forEach(function (r) {
                var key = r.iso_date + "|" + r.time + "|" + (r.sub_tag || "");
                if (existing[tag][key] || seen[key]) return;
                seen[key] = true; newRows[tag].push(r);
              });
            });
            var totalAdded = projectTags.reduce(function (a, t) { return a + newRows[t].length; }, 0);
            var scannedTotal = projectTags.reduce(function (a, t) { return a + scanned[t].length; }, 0);
            if (totalAdded === 0) return jsonResp({ ok: true, added: 0, per_tag: {}, scanned: scannedTotal });
            return Store.writeTagAggregate(_appendRowsToAgg(text, newRows)).then(function () {
              var perTag = {}; projectTags.forEach(function (t) { if (newRows[t].length) perTag[t] = newRows[t].length; });
              return jsonResp({ ok: true, added: totalAdded, per_tag: perTag, scanned: scannedTotal });
            });
          });
        });
      });
    },
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
              // 余量 = total_pills - 累计消耗(对齐 PC server _task_meta_state.remaining)
              if (meta && typeof meta.total_pills === "number") {
                var consumed = 0;
                for (var dk in log) consumed += (parseInt(log[dk], 10) || 0);
                t.remaining = meta.total_pills - consumed;
              }
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
      if (!(body && body.task_name)) return jsonResp({ ok: false, error: "缺少打卡名称" });
      return Store.setSetting("taskimg/" + body.task_name, body.image || "").then(function () { return jsonResp({ ok: true }); });
    },
    // 端到端「抠图 + OCR + 写 image map + meta total_pills」— 对齐桌面 /api/cutout(N2 parity)
    // 桌面 oracle:tests/test_image_routes.py::test_cutout_writes_image_map_and_ocr_pill_count
    //   POST {attachment_url, task_name} → ok + ocr_pill_count + 写 taskimg + 写 taskmeta.total_pills
    //   missing args → 400
    // mobile 架构:端侧 cutout plugin 已抠好 PNG;本 endpoint 接 dataURL + name → native OCR plugin
    //   → pill_count regex → setSetting roundtrip。无 native plugin(浏览器 / 无 GMS)→ 走 fallback
    //   (调 /api/vision/classify with extra_question="OCR 出文字")
    "POST /api/cutout": function (req, u, body) {
      var name = body && body.task_name;
      var url = body && body.attachment_url;
      var inlineImage = body && body.image;  // 兼容:前端可直接传 dataURL(避免 attachment 中转)
      if (!name) return jsonResp({ ok: false, error: "缺少打卡名称" }, 400);
      if (!url && !inlineImage) return jsonResp({ ok: false, error: "缺少图片 或 image" }, 400);

      // 拿 dataURL:优先 inline,否则 attachment_url → readAttachment
      var dataUrlP;
      if (inlineImage) {
        dataUrlP = Promise.resolve(inlineImage);
      } else {
        var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(url);
        if (!m) return jsonResp({ ok: false, error: "图片链接格式错误" }, 400);
        dataUrlP = Store.readAttachment(m[1], m[2]);
      }

      return dataUrlP.then(function (dataUrl) {
        if (!dataUrl) return jsonResp({ ok: false, error: "attachment 不存在" }, 404);

        // ★ H6:统一 OCR 入口(显式探测 + 无 GMS 可观测兜底,不再靠异常隐蔽)
        return _runOcr(dataUrl, url).then(function (r) {
          var pillCount = extractPillCount(r.text);
          // 洞D 修:inline dataURL 时存真图(可渲染),不再存没用的字面量 "inline"
          var p = [Store.setSetting("taskimg/" + name, inlineImage || url || "inline")];
          if (pillCount > 0) {
            p.push(Store.getSetting("taskmeta/" + name).then(function (raw) {
              var meta = {}; try { meta = raw ? JSON.parse(raw) : {}; } catch (e) {}
              meta.total_pills = pillCount;
              return Store.setSetting("taskmeta/" + name, JSON.stringify(meta));
            }));
          }
          return Promise.all(p).then(function () {
            return jsonResp({
              ok: true, task_name: name,
              ocr_pill_count: pillCount > 0 ? pillCount : null,
              engine: r.engine, ocr_text: r.text,
            });
          });
        });
      });
    },
    // 改 meta:total_pills(瓶装颗数)/ daily_dose(每天 N 粒),对齐 PC 端 /meta
    "POST /api/daily-tasks/meta": function (req, u, body) {
      var name = (body && body.task_name) || "";
      if (!name) return jsonResp({ ok: false, error: "缺少打卡名称" }, 400);
      // D4 test_meta_update_total_pills_daily_dose_and_clear:非 int → 400
      // total_pills="" / null / 0 → pop;"abc" → 400;daily_dose "x" → 400
      function isBadInt(v) {
        // 字符串前缀非 digit/- → 拒(parseInt 否则会吞掉前缀)
        var s = String(v);
        return s.length === 0 || /^[^\d-]/.test(s) || isNaN(parseInt(s, 10));
      }
      if ("total_pills" in body) {
        var tv = body.total_pills;
        if (!(tv === null || tv === "" || tv === 0) && isBadInt(tv)) {
          return jsonResp({ ok: false, error: "total_pills 必须是整数" }, 400);
        }
      }
      if ("daily_dose" in body && isBadInt(body.daily_dose)) {
        return jsonResp({ ok: false, error: "daily_dose 必须是整数" }, 400);
      }
      return Store.getSetting("taskmeta/" + name).then(function (raw) {
        var meta = {}; try { meta = raw ? JSON.parse(raw) : {}; } catch (e) {}
        if ("total_pills" in body) {
          var v = body.total_pills;
          if (v === null || v === "" || v === 0) delete meta.total_pills;
          else meta.total_pills = Math.max(1, parseInt(v, 10));
        }
        if ("daily_dose" in body) meta.daily_dose = Math.max(1, parseInt(body.daily_dose, 10));
        return Store.setSetting("taskmeta/" + name, JSON.stringify(meta)).then(function () {
          return jsonResp({ ok: true, task_name: name, total_pills: meta.total_pills || null, daily_dose: meta.daily_dose || 1 });
        });
      });
    },
    // 删 task:当天 md 补剂段删行 + 清 image + 清 meta(对齐 PC 端 /delete 三清)
    // Group B:加新 task(写补剂段 - [ ] 名字)— AI 在 mobile session 用嘴加 task
    "POST /api/daily-tasks/add": function (req, u, body) {
      var name = body && body.task_name;
      if (!name) return jsonResp({ ok: false, error: "缺少打卡名称" }, 400);
      var today = todayIso();
      return withJournalLock(today, function () { return Store.readJournalMd(today).then(function (md) {
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
      }); });
    },
    "POST /api/daily-tasks/delete": function (req, u, body) {
      // D7 test_delete_cascade_md_image_meta(5.15 肌酸丢 guard):
      // 删 task → cascade 清 md + image + meta + intake_log,返 image_removed
      var date = (body && body.date) || todayIso();
      var name = (body && body.task_name) || "";
      if (!name) return jsonResp({ ok: false, error: "缺少打卡名称" }, 400);
      return withJournalLock(date, function () { return Promise.all([
        Store.readJournalMd(date),
        Store.getSetting("taskimg/" + name),  // 先看 image 是否存在
      ]).then(function (rs) {
        var md = rs[0];
        var hadImage = !!rs[1];
        var p = [];
        if (md !== null) p.push(Store.writeJournalMd(date, removeSupplement(md, name)));
        p.push(Store.removeSetting("taskimg/" + name));
        p.push(Store.removeSetting("taskmeta/" + name));
        p.push(Store.removeSetting("taskintake/" + name));  // 5.15 leak 修:清 intake_log
        return Promise.all(p).then(function () {
          return jsonResp({ ok: true, task_name: name, image_removed: hadImage });
        });
      }); });
    },
    // 历史:近 N 天每天是否打勾,对齐 PC 端 /history(query: name + days)
    "GET /api/daily-tasks/history": function (req, u) {
      // D5 test_history_per_day_oldest_first:
      // - 返字段 `days`(数组,不是 history)
      // - 排序 oldest → newest(桌面 [base-2, yesterday, today])
      // - 没文件 → checked: null;有文件没勾 → false;勾 → true
      var url = new URL(u, "http://x");
      var name = url.searchParams.get("name") || "";
      var nDays = Math.max(1, Math.min(parseInt(url.searchParams.get("days") || "14", 10), 60));
      if (!name) return jsonResp({ ok: false, error: "需 name query" }, 400);
      var today = new Date();
      var dates = [];
      // 生成 oldest → newest 顺序(i=nDays-1 → 0)
      for (var i = nDays - 1; i >= 0; i--) {
        var d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
        dates.push(d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()));
      }
      return Promise.all(dates.map(function (dt) {
        return Store.readJournalMd(dt).then(function (md) {
          if (md === null) return { date: dt, checked: null };
          var tasks = parseSupplements(md);
          var found = tasks.filter(function (t) { return t.name === name; })[0];
          return { date: dt, checked: found ? found.checked : null };
        });
      })).then(function (daysArr) {
        var checked_days = daysArr.filter(function (h) { return h.checked === true; }).length;
        var recorded_days = daysArr.filter(function (h) { return h.checked !== null; }).length;
        return jsonResp({ ok: true, name: name, days: daysArr, checked_days: checked_days, recorded_days: recorded_days });
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
      return withJournalLock(date, function () { return Promise.all([
        Store.readJournalMd(date),
        Store.getSetting("taskmeta/" + name),
        Store.getSetting("taskintake/" + name),
      ]).then(function (rs) {
        var md = rs[0];
        if (md === null) return jsonResp({ ok: false, error: "no file" }, 404);
        var meta = {}; try { meta = rs[1] ? JSON.parse(rs[1]) : {}; } catch (e) {}
        var log = {}; try { log = rs[2] ? JSON.parse(rs[2]) : {}; } catch (e) {}
        // FIX 7c — 喝水特例:fresh meta + AI 漏传 dose → 默认 dose=8,防 clamp-to-1
        // FIX E — 多名匹配(喝水/八杯水/water)+ 立即持久化(避免每次 fresh meta 都重复 patch)
        var _waterMetaDirty = false;
        if ((name === '喝水' || name === '八杯水' || name === 'water') && !body.daily_dose && !meta.daily_dose) {
          meta.daily_dose = 8;
          _waterMetaDirty = true;
        }
        // FIX F — body.daily_dose 验证(非整数或 <1 直接 400)
        if ('daily_dose' in body) {
          var bdd = parseInt(body.daily_dose, 10);
          if (isNaN(bdd) || bdd < 1) return jsonResp({ ok: false, error: 'daily_dose must be int >=1' }, 400);
        }
        // FIX 7b — caller 显式传 daily_dose 优先,其次 meta,最后默认 1
        var dose = Math.max(1, parseInt(body.daily_dose, 10) || parseInt(meta.daily_dose, 10) || 1);
        var cur = log[date] | 0;
        var next;
        if ("intake" in body) {
          var iv = parseInt(body.intake, 10);
          if (isNaN(iv)) return jsonResp({ ok: false, error: "数量必须是整数" }, 500);
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
        // FIX E — 喝水默认 dose=8 立即持久化(避免每次 /check 都 fresh meta 重复 patch + 防 race)
        if (_waterMetaDirty) p.push(Store.setSetting("taskmeta/" + name, JSON.stringify(meta)));
        return Promise.all(p).then(function () {
          return jsonResp({
            ok: true, task_name: name, checked: checked,
            total_pills: meta.total_pills || null, daily_dose: dose, today_intake: next,
            remaining: null,
          });
        });
      }); });
    },
    // 八杯水:落进当天 md 的"喝水"子杯勾选(序号<=filled 勾上),持久化八杯水进度
    "POST /api/daily-tasks/water": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      // 与 /check 同一道补卡窗口(闭集 {今天, 次日中午前的昨天}):UI readonly 已挡,这里是纵深
      if (!isWritableDate(date)) return jsonResp({ ok: false, error: "只能记今天的喝水(次日中午前可补昨天)" }, 403);
      var filled = Math.max(0, Math.min(8, (body && body.filled) | 0));
      return withJournalLock(date, function () { return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ ok: false, error: "no file" }, 404);
        return Store.writeJournalMd(date, setWaterFilled(md, filled)).then(function () {
          return jsonResp({ ok: true, filled: filled });
        });
      }); });
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
              message: "对话历史读取失败，选择备份恢复或重新开始",
            });
          });
        }
        // ★ 一次性迁移(7.5 OOM):旧 thread 内联 dataURL(实测 13MB)→ 转附件短路径回写。
        //   直接 setText 不走 rotate(rotate 会把 13MB 胖版复制进 bak,重蹈大桥消息覆辙);
        //   顺手删旧 Preferences 巨型 bak(13MB×5 常驻 SharedPreferences = 516MB RSS 元凶)。
        return _slimHistoryImgs(r.history || []).then(function (s) {
          if (!s.changed) return jsonResp({ history: s.hist, mtime: mt });
          var mt2 = Date.now();
          return Promise.all([
            Backend.setText("thread", JSON.stringify(s.hist)),
            Backend.setText("setting/thread_mtime", String(mt2)),
            Store.removeSetting("thread_bak/1"), Store.removeSetting("thread_bak/2"),
            Store.removeSetting("thread_bak/3"), Store.removeSetting("thread_bak/4"),
            Store.removeSetting("thread_bak/5"),
          ]).then(function () {
            return jsonResp({ history: s.hist, mtime: mt2, migrated: true });
          });
        });
      });
    },
    // 复刻桌面 /api/thread/restore-from-bak(test_restore_from_bak_roundtrip + bad_index 400 + missing 404)
    "POST /api/thread/restore-from-bak": function (req, u, body) {
      var idx = parseInt(body && body.bak_index, 10);
      if (isNaN(idx) || idx < 1 || idx > 5) return jsonResp({ ok: false, error: "备份编号必须在 1 到 5 之间" }, 400);
      return Store.readThreadBakAt(idx).then(function (raw) {
        if (raw == null) return jsonResp({ ok: false, error: "bak." + idx + " 不存在" }, 404);
        var hist;
        try { hist = JSON.parse(raw); }
        catch (e) { return jsonResp({ ok: false, error: "bak." + idx + " 内容已损坏" }, 500); }
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
        // ★ 落盘前必经瘦身闸:任何 data: 内联图转短路径(7.5 OOM 防线,防未来回归)
        return _slimHistoryImgs(hist).then(function (s) {
          return Store.writeThread(s.hist).then(function (mt) {
            return jsonResp({ ok: true, mtime: mt, count: s.hist.length });
          });
        });
      });
    },

    // 写日记:行内编辑/插入/删除 —— MVP 简化,人写自己的块,不跑 authorship 守卫
    "POST /api/journal/insert-block": function (req, u, body) {
      // 复刻桌面 _insert_block authorship 契约(test_authorship T6 + journal_routes J5):
      //  · 新 H2 必 stamp @author marker(test_insert_block_stamps_{ai,user}_marker)
      //  · HTTP 默认 author='user'(user-trust;test_insert_block_http_stamps_user)
      //  · 显式传 author='ai' 用于 lazy 21:30 纸条 / AI tool 写入路径
      //  · J6 missing time → 400 + J7 no journal file → 404(test_insert_block_*)
      var date = (body && body.date) || todayIso();
      var time = normTime(body && body.time);
      if (!time) return jsonResp({ ok: false, error: "缺 time" }, 400);
      var tmatch = /^(\d{1,2}):(\d{2})$/.exec(time);
      if (!tmatch || parseInt(tmatch[1], 10) > 23 || parseInt(tmatch[2], 10) > 59) {
        return jsonResp({ ok: false, error: "time 格式应为 HH:MM" }, 400);  // 原实现 mm=undefined 会写出损坏 H1 '# 21：undefined'
      }
      return withJournalLock(date, function () { return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ ok: false, error: "no journal file for " + date }, 404);
        var h = parseInt(tmatch[1], 10), mm = tmatch[2];
        var author = (body && body.author) || "user";
        var tag = String((body && body.tag) || "").replace(/^#+/, "");  // 对齐桌面 lstrip('#'):UI 传 '#杂',不剥会落成 '## ##杂'
        var titlePart = (tag ? "#" + tag + " " : "") + (body.title || "");
        var h2 = "## " + titlePart + " @" + author;
        var newH2Block = h2 + "\n\n" + (body.body || "") + "\n";  // H2 跟 body 间空行(对齐 PC golden 字节)
        // ★ dedup:找现有 # h:mm H1,若存在 append H2 到块内(在 --- 前)而不是新建
        // 对齐 PC server.py _insert_block:Searches for existing H1 by time → append H2
        var h1Pattern = new RegExp("(^# " + h + "[：:]" + mm + "\\s*\\n)([\\s\\S]*?)(\\n---\\s*\\n|\\n# |$)", "m");
        var existing = md.match(h1Pattern);
        var nextMd;
        if (existing) {
          // 现有 H1 块,append 新 H2 在块尾(--- 前 / 下一个 H1 前 / 文件尾)
          var headLine = existing[1]; var blockBody = existing[2]; var tail = existing[3];
          var appended = headLine + blockBody.replace(/\s*$/, "") + "\n\n" + newH2Block + tail;
          nextMd = md.replace(existing[0], appended);
        } else {
          // 新 H1 块:对齐 PC _insert_block 按时间序插入(原 bug:一律 append 到尾 →
          //   已有 #14：00 时插 #15：00 反而排到 14:00 之前 / 乱序)。
          var blockMd = "# " + h + "：" + mm + "\n\n" + newH2Block;
          var newMin = h * 60 + (parseInt(mm, 10) || 0);
          var h1ScanRe = /^# (\d{1,2})[：:](\d{2})/gm, sm, insertIdx = -1;
          while ((sm = h1ScanRe.exec(md)) !== null) {
            if (parseInt(sm[1], 10) * 60 + parseInt(sm[2], 10) > newMin) { insertIdx = sm.index; break; }
          }
          if (insertIdx < 0) {
            // 没有更晚的时间块 → append 到尾(保留 PC golden 字节 insert_stamps_user.md)
            var trimmed = md ? md.replace(/\s*$/, "") : "";
            var sep = !trimmed ? "" : (trimmed.endsWith("---") ? "\n\n" : "\n\n---\n\n");
            nextMd = trimmed + sep + blockMd;
          } else {
            // 插到第一个更晚的时间块之前(保持时序)
            var before = md.slice(0, insertIdx).replace(/\s*$/, "");
            var after = md.slice(insertIdx);
            nextMd = before + "\n\n---\n\n" + blockMd.replace(/\s*$/, "") + "\n\n---\n\n" + after;
          }
        }
        return Store.writeJournalMd(date, nextMd).then(function () {
          return jsonResp({ ok: true, inserted: "# " + h + "：" + mm, file: isoToStem(date) + ".md", appended_to_existing: !!existing });
        });
      }); });
    },
    // ── vision/OCR 移植 — 复刻桌面 /api/chat/upload-image + /api/vision/classify
    //    mobile 端 attachment 走 Capacitor Filesystem dataURL inline 存(浏览器对应
    //    localStorage),sha256 短 hash 去重 + logical url 附件 URL 格式:/attachments/日期/文件名
    "POST /api/chat/upload-image": function (req, u, body) {
      var dataUrl = body && body.dataUrl;
      if (!dataUrl || typeof dataUrl !== "string" || dataUrl.indexOf("data:") !== 0) {
        return jsonResp({ ok: false, error: "缺 dataUrl 或格式错(必须 data:...;base64,...)" }, 400);
      }
      return _saveDataUrlAttachment(dataUrl).then(function (r) {
        if (!r) return jsonResp({ ok: false, error: "图片格式错误" }, 400);
        return jsonResp({ ok: true, url: r.url, deduped: r.deduped, size: r.size });
      });
    },
    // ★ 聊天照片气泡渲染入口:thread 只存 /attachments/ 短路径(7.5 OOM 修),
    //   <img src> 不走 shim fetch 拦截 → 前端经此路由拿 dataURL(同 scrapbook GET 解析手法)
    "GET /api/attachment-data": function (req, u) {
      var attUrl = new URL(u, location.origin).searchParams.get("url") || "";
      var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(attUrl);
      if (!m) return jsonResp({ ok: false, error: "url 格式错误" }, 400);
      return Store.readAttachment(m[1], m[2]).then(function (d) {
        if (!d) return jsonResp({ ok: false, error: "附件不存在" }, 404);
        return jsonResp({ ok: true, dataUrl: d });
      });
    },
    "POST /api/vision/classify": function (req, u, body) {
      var attUrl = body && body.attachment_url;
      var q = body && body.extra_question;
      if (!attUrl) return jsonResp({ ok: false, error: "缺少图片" }, 400);
      var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(attUrl);
      if (!m) return jsonResp({ ok: false, error: "图片链接格式错误" }, 400);
      var date = m[1], stem = m[2];
      return Promise.all([Store.readAttachment(date, stem), Store.getSetting("dashscope_key"), Store.readUploadMeta(date, stem)]).then(function (rs) {
        var dataUrl = rs[0], key = rs[1], meta = rs[2] || {};
        if (!dataUrl) return jsonResp({ ok: false, error: "图片不存在: " + attUrl }, 404);
        // cache 命中:不带 extra_question 的默认描述 + 已 cache → 直接返(critic 标的钱包/latency leak 修)
        if (!q && meta.vision_result) {
          return jsonResp({ ok: true, attachment_url: attUrl, result: meta.vision_result, cached: true });
        }
        return _qwenClassifyImage(dataUrl, q, key).then(function (j) {
          if (j && j.error) return jsonResp({ ok: false, error: j.error, hint: j.hint, detail: j.detail });
          // 默认描述路径(无 extra_question)cache 起来
          if (!q) {
            meta.vision_result = j; meta.vision_at = Date.now();
            return Store.writeUploadMeta(date, stem, meta).then(function () {
              return jsonResp({ ok: true, attachment_url: attUrl, result: j, cached: false });
            });
          }
          return jsonResp({ ok: true, attachment_url: attUrl, result: j });
        });
      });
    },
    // ── Group D photo curator — list/search/curator/delete attachment(对齐 PC list_my_uploads)
    "GET /api/uploads/list": function (req, u) {
      var qs = new URL(u, "http://x").searchParams;
      var n = Math.max(1, Math.min(parseInt(qs.get("n") || "20", 10), 100));
      return Store.listAllUploadMetas().then(function (metas) {
        // 按 uploaded_at 降序,top n
        metas.sort(function (a, b) { return (b.uploaded_at || 0) - (a.uploaded_at || 0); });
        var out = metas.slice(0, n).map(function (m) {
          return {
            url: m._url, date: m._date, uploaded_at: m.uploaded_at,
            size: m.size, mime: m.mime,
            description: m.vision_result && m.vision_result.description,
            kind: m.vision_result && m.vision_result.kind,
          };
        });
        return jsonResp({ ok: true, n: out.length, uploads: out });
      });
    },
    "POST /api/uploads/search": function (req, u, body) {
      var q = (body && body.query || "").trim().toLowerCase();
      if (!q) return jsonResp({ ok: false, error: "缺少查询内容" }, 400);
      return Store.listAllUploadMetas().then(function (metas) {
        var hits = metas.filter(function (m) {
          if (!m.vision_result) return false;
          var hay = [m.vision_result.description || "", m.vision_result.kind || "", m.vision_result.brand || ""].join(" ").toLowerCase();
          return hay.indexOf(q) >= 0;
        }).map(function (m) {
          return { url: m._url, date: m._date, description: m.vision_result.description, kind: m.vision_result.kind };
        });
        return jsonResp({ ok: true, query: q, n: hits.length, hits: hits.slice(0, 20) });
      });
    },
    "POST /api/uploads/delete": function (req, u, body) {
      var attUrl = body && body.attachment_url;
      if (!attUrl) return jsonResp({ ok: false, error: "缺少图片" }, 400);
      var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(attUrl);
      if (!m) return jsonResp({ ok: false, error: "链接格式错误" }, 400);
      var date = m[1], stem = m[2];
      return Promise.all([
        Backend.remove("attachments/" + date + "/" + stem),
        Store.deleteUploadMeta(date, stem),
      ]).then(function () {
        return jsonResp({ ok: true, deleted: attUrl });
      });
    },
    "GET /api/attachments/get": function (req, u) {
      // 前端给 <img> 拿 dataURL 用;url=附件 URL 格式:/attachments/日期/文件名(logical)
      var qs = new URL(u, "http://x").searchParams;
      var attUrl = qs.get("url") || "";
      var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(attUrl);
      if (!m) return jsonResp({ ok: false, error: "链接格式错误" }, 400);
      return Store.readAttachment(m[1], m[2]).then(function (dataUrl) {
        if (!dataUrl) return jsonResp({ ok: false, error: "not found" }, 404);
        return jsonResp({ ok: true, dataUrl: dataUrl });
      });
    },
    // ── web_search 三层降级 — 360 主 → 百炼兜底 → 拒答 sentinel
    "POST /api/web/search": function (req, u, body) {
      var query = (body && body.query || "").trim();
      var max = Math.max(1, Math.min(parseInt(body && body.max_results || "5", 10), 10));
      if (!query) return jsonResp({ ok: false, error: "缺少查询内容" }, 400);
      return _mobileWebSearch360(query, max).then(function (r360) {
        if (!_searchFailed(r360)) {
          return jsonResp({ ok: true, query: query, category: "general", source: "360", results: r360 });
        }
        // 360 降级 → 试百炼
        return Store.getSetting("dashscope_key").then(function (key) {
          return _mobileWebSearchBailian(query, key).then(function (rB) {
            if (!_searchFailed(rB)) {
              return jsonResp({ ok: true, query: query, category: "general", source: "bailian", results: rB, _degraded_from: "360" });
            }
            // 双降级
            return jsonResp({ ok: true, query: query, results: "[搜索后端全降级 — 360 失败,百炼也失败或未配置。" + r360 + " | " + rB + "]", _all_degraded: true });
          });
        });
      });
    },
    "POST /api/web/fetch": function (req, u, body) {
      var rawUrl = (body && body.url || "").trim();
      if (!rawUrl || !/^https?:\/\//i.test(rawUrl)) return jsonResp({ ok: false, error: "链接必须以 http:// 或 https:// 开头" }, 400);
      var url = _httpsUpgrade(rawUrl);  // critic ATS 修:http → https
      var CapHttp = _getCapHttp();
      var headers = { "User-Agent": "Mozilla/5.0 (gateway-fetch)" };
      var p;
      if (CapHttp) {
        p = CapHttp.get({ url: url, headers: headers, connectTimeout: 15000, readTimeout: 15000 })
          .then(function (r) { return (r && r.data) || ""; });
      } else {
        p = realFetch(url, { headers: headers }).then(function (r) { return r.text(); });
      }
      return p.then(function (html) {
        var text = _htmlStripToText(html);
        var FETCH_CAP = 3000;
        var truncated = text.length > FETCH_CAP;
        if (truncated) text = text.slice(0, FETCH_CAP);
        return jsonResp({ ok: true, url: url, text: text, truncated: truncated, length: text.length });
      }).catch(function (e) {
        var msg = String(e && e.message || e);
        // ATS / 网络异常 → 给 LLM 可解释 hint
        if (msg.indexOf("cleartext") >= 0) {
          return jsonResp({ ok: false, error: "此链接不支持，请尝试其他链接", url: url });
        }
        return jsonResp({ ok: false, error: "链接读取异常:" + msg.slice(0, 200), url: url });
      });
    },
    // ⑥ B Turn 5:列 AI 动态注册的 widget manifest(从 setting/widgets/* 持久化读)
    "GET /api/widgets/list": function () {
      return Store.listWidgetManifests().then(function (manifests) {
        return jsonResp({ ok: true, widgets: manifests });
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
      if (!q) return jsonResp({ ok: false, error: "缺少查询内容" }, 400);
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
          // ★ 也扫 标签聚合.md(横切索引)— sub-test 2:AI 通过标签读历史。
          //   query 命中某 section 的 #tag → 返该 section 全部行(整段历史);
          //   或单行文本含 query → 返该行。(对照 PC search_journal 扫 vault 全部 md)
          return Store.readTagAggregate().then(function (aggMd) {
            if (aggMd) {
              var aggLines = aggMd.split(/\r?\n/), curTag = null, tagHit = false, am = [];
              aggLines.forEach(function (line) {
                var hm = line.match(/^##\s+#(\S+)/);
                if (hm) { curTag = hm[1]; tagHit = curTag.toLowerCase().indexOf(qLc) >= 0; return; }
                if (line.indexOf("|") !== 0) return;
                var cells = line.replace(/^\|/, "").replace(/\|\s*$/, "").split("|").map(function (c) { return c.trim(); });
                if (cells.length < 4 || cells[0] === "日期" || cells.every(function (c) { return !c || /^[-:\s]+$/.test(c); })) return;
                if (tagHit || line.toLowerCase().indexOf(qLc) >= 0) {
                  am.push({ time: "#" + curTag + " " + cells[0] + " " + cells[1], snippet: cells[3].slice(0, 200) });
                }
              });
              if (am.length) hits.push({ date: "标签聚合", matches: am.slice(0, 40) });
            }
            var total = hits.reduce(function (a, h) { return a + h.matches.length; }, 0);
            return jsonResp({ ok: true, query: q, days: days, total: total, hits: hits.slice(0, 30) });
          });
        });
      });
    },
    "POST /api/journal/append-comment": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      var time = normTime(body && body.time);
      // 双读 comment_md(PC tool 用)+ comment(mobile spec 用),兼容两端 AI emit
      var comment = body && (body.comment_md || body.comment);
      var author = (body && body.author) || "ai";
      if (!time || !comment) return jsonResp({ error: "缺少时间或批注" }, 400);
      return withJournalLock(date, function () { return Store.readJournalMd(date).then(function (md) {
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
      }); });
    },
    "POST /api/journal/patch": function (req, u, body) {
      // 复刻桌面 _patch_block 完整契约:
      //  · authorship boundary:author='ai' + 块内 H2 标 @user → 拒(test_authorship)
      //  · H2-rename guard:author='ai' + existing H2 strip 不等 new H2 strip + !allow_h2_rename → 拒
      //    (test_patch_h2_rename;5.29 联想 entry 被 patch 吃掉事故的反向防御)
      //  · HTTP endpoint 默认 'user'(user-trust,test_patch_http_user_can_patch_ai_block J10)
      //    对齐桌面 journal_routes.py L189 显式 _patch_block(..., author="user")
      //  · AI tool 调用走 dispatchTool 注入 author='ai',撞 @user 仍拒(fail-safe 桌面 T5
      //    pure-function 等价 = dispatchTool 路径模拟)
      var date = (body && body.date) || todayIso();
      var time = normTime(body && body.time);
      // J12 test_patch_missing_new_md_400:new_md 必传(空串拒,旧 fallback ""静默通过)
      if (body && body.new_md == null) return jsonResp({ ok: false, error: "缺少新内容" }, 400);
      var newMd = (body && body.new_md) || "";
      var author = (body && body.author) || "user";
      var allowRename = !!(body && body.allow_h2_rename);
      return withJournalLock(date, function () { return Store.readJournalMd(date).then(function (md) {
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
          return jsonResp({ error: "这个时间段（" + time + "）是你写的，AI 无法修改。要添加批注请用批注功能；要新增内容请用新增功能。" }, 403);
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
            error: "这个时间段（" + time + "）已有标题:`" + existingH2.trim() + "`。新内容第一个标题是:`" + newH2.trim() + "` — 不一样。修改会整段替换原标题。要新增标题请用新增功能；要改标题请勾选允许重命名。",
            conflict: true,
          }, 409);
        }
        // 5. splice:保留 H1 行,替换 H1+1..end 之间的 body
        var trimmedNewMd = newMd.replace(/\s+$/, "");
        var out = lines.slice(0, start + 1).concat([""], trimmedNewMd.split(/\r?\n/), [""], lines.slice(end));
        return Store.writeJournalMd(date, out.join("\n")).then(function () {
          return jsonResp({ patched: time, file: isoToStem(date) + ".md" });
        });
      }); });
    },
    "POST /api/journal/delete-block": function (req, u, body) {
      var date = (body && body.date) || todayIso(), time = normTime(body && body.time);
      return withJournalLock(date, function () { return Store.readJournalMd(date).then(function (md) {
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
      }); });
    },

    // 对话:有 key 就真连 DeepSeek(读今天日记当 context);没 key 提示去设置填
    "POST /api/chat": function (req, u, body) {
      return Store.getSetting("deepseek_key").then(function (key) {
        if (!key) return sseResp([{ type: "delta", text: "（还没填 AI 密钥—— 点设置图标进去填了，AI 就能读今天的日记跟你聊。）" }, { type: "done", actions: [], model_id: "deepseek" }]);
        return Store.getSetting("deepseek_model").then(function (m) { return chatViaDeepseek(body, key, m || "deepseek-chat"); });
      });
    },
    // compact 摘要(对照 PC POST /api/pulse/compact-summary)— thread 压缩后给 AI 写 200 字摘要防冷启。
    // 失败/无 key → 返空 summary(silent-failure,前端 skip);移动端跳过 3 份 PULSE 自演化(无 PULSE 文件、无消费方)
    "POST /api/pulse/compact-summary": function (req, u, body) {
      var conversation = (body && body.conversation) || "";
      if (!conversation.trim()) return jsonResp({ ok: true, summary: "" });
      return Store.getSetting("deepseek_key").then(function (key) {
        if (!key) return jsonResp({ ok: true, summary: "" });
        return Store.getSetting("deepseek_model").then(function (model) {
          var prompt = _COMPACT_SUMMARY_PROMPT.replace("{conversation}", conversation);
          return _llmComplete(key, model || "deepseek-chat", [{ role: "user", content: prompt }], 500)
            .then(function (text) { return jsonResp({ ok: true, summary: (text || "").trim() }); });
        });
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
    // 设置栏测试按钮:对齐桌面 setup_routes.py L73 contract:
    // body: {label, base_url, api_key, model} → 真打 ping → {ok, reply, model} 或 {ok:false, reason}
    // 错误翻译复刻桌面 L100-105(截短长 OAI SDK error → "HTTP <code>: <message>")
    "POST /api/setup/test": function (req, u, body) {
      body = body || {};
      var profile = {
        label: body.label || "test",
        base_url: body.base_url || "",
        api_key: body.api_key || "",
        model: body.model || "",
      };
      if (!profile.api_key || profile.api_key.indexOf("YOUR_") === 0) {
        return jsonResp({ ok: false, reason: "api_key 是占位符或为空" });
      }
      if (!profile.model || !profile.base_url) {
        return jsonResp({ ok: false, reason: "model 或 base_url 为空" });
      }
      return _setupTest(profile);
    },
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
      return Promise.resolve(jsonResp({ ok: false, mobile_stub: true, error: "此功能仅在桌面版可用" }));
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
  var seedPromise = seedIfEmpty().then(_initDayOne);
  // 让 journal/today 等到 seed 完成
  var _origToday = handlers["GET /api/journal/today"];
  handlers["GET /api/journal/today"] = function (req, u) { return seedPromise.then(function () { return _origToday(req, u); }); };
  var _origDays = handlers["GET /api/journal/days"];
  handlers["GET /api/journal/days"] = function (req, u) { return seedPromise.then(function () { return _origDays(req, u); }); };
  var _origTasks = handlers["GET /api/daily-tasks"];
  handlers["GET /api/daily-tasks"] = function (req, u) { return seedPromise.then(function () { return _origTasks(req, u); }); };

  // ── 启动 self-test:Storage round-trip(写 → 读 → diff)─────────────
  // 真机/simulator:把结果写到 setting/__self_test__ + console.log,debug 时可用
  //   xcrun simctl get_app_container <UDID> com.humanai.gateway data
  //   再 defaults read <plist>/Preferences/com.humanai.gateway.plist 看真存了什么
  // ★ App launch 时立即从 plist 恢复"上次测试结果"overlay + vault timeline + scrapbook 真 anchor
  //   - overlay 顶部固定显示测试结果
  //   - vault timeline 渲染 # 9:30 / # 15:00 等 H1 + 各 H2 列表(scroll panel)
  //   - scrapbook sticker 真 anchor 到对应 H1 DOM 旁(根据 anchor_time 找 DOM)
  // ★ 真 bug 修(2026-06-28):这些固定覆盖层 + dump 是 self-test 脚手架,production 绝不能挂 ——
  //   __gw_vault_timeline__(position:fixed top:350 z:99997)会盖住今日打卡 chip(逼出 row-delegation
  //   tap hack)。只在 debug 模式(与 self-test 同 gate)渲染。
  var __dbgOverlays = (typeof window !== "undefined") &&
    (window.__GW_RUN_SELF_TEST__ === true || !!window.__GW_REAL_KEY__);
  setTimeout(function () {
    if (typeof document === "undefined") return;
    if (!__dbgOverlays) return;
    Store.getSetting("__last_test_overlay__").then(function (html) {
      if (!html) return;
      // ★ sanitize:含 <svg / dataURL 的 stale overlay 不 inject(防超大 widget 渲染)
      if (html.indexOf("<svg") >= 0 || html.indexOf("data:image/svg") >= 0) {
        Store.removeSetting("__last_test_overlay__");
        return;
      }
      var wrap = document.createElement("div");
      wrap.innerHTML = html;
      var node = wrap.firstChild;
      if (node && !document.getElementById("__gw_strict_overlay__")) {
        document.body.appendChild(node);
        /* ★ 真 bug 修:strict_overlay + 子树全 pointer-events:none,让 tap 穿透到下层 widget */
        node.style.pointerEvents = "none";
        if (!document.getElementById("__gw_strict_overlay_style__")) {
          var s = document.createElement("style");
          s.id = "__gw_strict_overlay_style__";
          s.textContent = "#__gw_strict_overlay__, #__gw_strict_overlay__ * { pointer-events: none !important; }";
          document.head.appendChild(s);
        }
      }
    }).catch(function () {});
    // ★ Vault timeline panel:解析 vault md 渲染 H1 + H2 列表 到固定 scroll panel
    Store.readJournalMd(todayIso()).then(function (md) {
      if (!md || document.getElementById("__gw_vault_timeline__")) return;
      var panel = document.createElement("div");
      panel.id = "__gw_vault_timeline__";
      panel.style.cssText = "position:fixed;top:350px;left:10px;right:10px;height:380px;background:rgba(255,250,243,0.97);border:2px solid #a86e46;border-radius:12px;padding:10px;font:13px/1.5 -apple-system,sans-serif;color:#3a2418;overflow:auto;z-index:99997;box-shadow:0 6px 20px rgba(168,110,70,0.3);pointer-events:none;";
      /* ★ 真 bug 修 #1:panel 加 pointer-events:none */
      if (!document.getElementById("__gw_vault_timeline_style__")) {
        var styleNode = document.createElement("style");
        styleNode.id = "__gw_vault_timeline_style__";
        styleNode.textContent = "#__gw_vault_timeline__ * { pointer-events: none !important; }";
        document.head.appendChild(styleNode);
      }
      /* ★ 真 bug 修 #2:children 默认 pointer-events:auto 会 intercept,必须全 force none */
      var title = "<div style='font-weight:700;font-size:14px;margin-bottom:6px;color:#7a5230;border-bottom:1px solid #d4a373;padding-bottom:4px;'>📓 今日时间线(vault md real)</div>";
      var html = title;
      var blocks = md.split(/^# /m).slice(1); // 去掉首 # 之前
      blocks.forEach(function (blk) {
        var lines = blk.split("\n");
        var h1 = lines[0].trim();
        var timeMatch = h1.match(/^(\d+)[：:](\d+)/);
        if (!timeMatch) return;
        var timeId = "__gw_h1_" + timeMatch[1] + "_" + timeMatch[2];
        var h2s = blk.split(/^## /m).slice(1).map(function (b) { return b.split("\n")[0].trim(); });
        html += "<div id='" + timeId + "' data-time='" + timeMatch[1] + ":" + timeMatch[2] + "' style='margin:8px 0;padding:6px;background:#fbf5ea;border-left:3px solid #a86e46;border-radius:4px;'>";
        html += "<div style='font-weight:700;color:#7a5230;'># " + h1 + "</div>";
        h2s.forEach(function (h2) {
          html += "<div style='font-size:11px;color:#5a4030;margin:2px 0 2px 8px;'>↳ " + h2.slice(0, 40) + "</div>";
        });
        html += "</div>";
      });
      panel.innerHTML = html;
      document.body.appendChild(panel);
    }).catch(function () {});
    // ★ Scrapbook sticker 真 anchor 到对应 H1 DOM 旁(根据 anchor_time 找 timeline panel 内 H1)
    Store.readScrapbook(todayIso()).then(function (items) {
      if (!items.length) return;
      // 等 timeline panel 渲染完再 anchor sticker
      setTimeout(function () {
        items.forEach(function (it, idx) {
          var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(it.src);
          if (!m) return;
          Store.readAttachment(m[1], m[2]).then(function (dataUrl) {
            if (!dataUrl) return;
            var hh_mm = it.anchor_time.replace(":", "_");
            var anchorEl = document.getElementById("__gw_h1_" + hh_mm);
            var topPx, leftPx;
            if (anchorEl) {
              // 真 anchor:位于 timeline panel 内对应 H1 DOM 右侧
              var rect = anchorEl.getBoundingClientRect();
              topPx = rect.top + window.scrollY - 10;
              leftPx = Math.min(window.innerWidth - 130, rect.right + 8);
            } else {
              // fallback:浮在屏中(timeline 没找到 anchor_time)
              topPx = 400 + idx * 30;
              leftPx = window.innerWidth - 140;
            }
            var img = document.createElement("img");
            img.src = dataUrl;
            img.style.cssText = "position:fixed;top:" + topPx + "px;left:" + leftPx + "px;width:100px;height:100px;transform:rotate(" + (it.rotation || -2) + "deg);z-index:99998;border:3px solid #fff;border-radius:6px;box-shadow:0 6px 20px rgba(168,110,70,0.5);background:#fff;pointer-events:none;";
            img.alt = "scrapbook anchor=" + it.anchor_time + (anchorEl ? " (DOM真锚)" : " (fallback)");
            img.id = "__gw_scrapbook_anchor_" + idx;
            if (!document.getElementById(img.id)) document.body.appendChild(img);
            var label = document.createElement("div");
            label.style.cssText = "position:fixed;top:" + (topPx + 105) + "px;left:" + leftPx + "px;background:#a86e46;color:#fff;font:10px/1 -apple-system,sans-serif;padding:2px 5px;border-radius:3px;z-index:99998;pointer-events:none;";
            label.textContent = (anchorEl ? "✓ " : "○ ") + "anchor # " + it.anchor_time;
            label.id = "__gw_scrapbook_label_anchor_" + idx;
            if (!document.getElementById(label.id)) document.body.appendChild(label);
          });
        });
      }, 100);
    }).catch(function () {});
  }, 200);  // app launch 200ms 立即恢复

  // ★ dump chip rects 给 idb_runner.sh 用(launch+3s 后写 plist)— 不可见(只读 rect 写 plist),不 gate 免断 runner
  setTimeout(function() {
    try {
      var rects = [];
      document.querySelectorAll('.gw-task').forEach(function(el) {
        var r = el.getBoundingClientRect();
        rects.push({
          name: el.dataset.taskName,
          x: Math.round(r.left + r.width/2),
          y: Math.round(r.top + r.height/2)
        });
      });
      var navTabs = {};
      document.querySelectorAll('.gw-nav-item').forEach(function(el) {
        var r = el.getBoundingClientRect();
        navTabs[el.dataset.tab || el.textContent.trim()] = {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)};
      });
      var dayPills = [];
      document.querySelectorAll('.gw-day').forEach(function(el) {
        var r = el.getBoundingClientRect();
        dayPills.push({
          key: el.dataset.dayKey,
          state: el.dataset.dayState,
          x: Math.round(r.left + r.width/2),
          y: Math.round(r.top + r.height/2)
        });
      });
      var nib = document.querySelector('.gw-nib');
      var nibRect = nib ? nib.getBoundingClientRect() : null;
      var cups = [];
      document.querySelectorAll('.gw-cup').forEach(function(el, i) {
        var r = el.getBoundingClientRect();
        cups.push({i: i + 1, x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)});
      });
      var data = {
        chips: rects,
        cups: cups,
        navTabs: navTabs,
        dayPills: dayPills,
        nib: nibRect ? {x: Math.round(nibRect.left + nibRect.width/2), y: Math.round(nibRect.top + nibRect.height/2)} : null,
        viewport: {w: window.innerWidth, h: window.innerHeight}
      };
      if (window.__GW_TEST_API__) {
        window.__GW_TEST_API__.Store.setSetting('__ui_rects__', JSON.stringify(data));
      }
      console.log('[ui-rects]', JSON.stringify(data));
    } catch (e) { console.warn('[ui-rects] dump failed', e); }
  }, 4500);  // 等 cups + chips 渲染完(原 2.5s 不够)

  // ★ Self-test 必须 gate — T2 故意写假 key `sk-onboard-XXXXXX` 覆盖 user 真 key,
  //   每次 app launch 都跑 = 用户真 key 一直被擦,chat 永远报"还没填 DeepSeek key"。
  //   仅 debug 模式(__GW_RUN_SELF_TEST__=true 或 inject 真 key)才跑。
  var __selfTestEnabled = (typeof window !== "undefined") &&
    (window.__GW_RUN_SELF_TEST__ === true || !!window.__GW_REAL_KEY__);
  if (!__selfTestEnabled) {
    console.log("[GW SELF-TEST] skipped (production mode; set __GW_RUN_SELF_TEST__=true to enable)");
  } else setTimeout(function () {
    var lines = [];
    function log(s) { lines.push(s); console.log("[GW SELF-TEST]", s); }
    log("backend=" + (_getFs() ? "Capacitor" : "LocalStorage") + " cap=" + (!!_getCap()) + " fs=" + (!!_getFs()) + " prefs=" + (!!_getPrefs()));
    var v1 = "sk-self-test-" + Math.random().toString(36).slice(2, 8);
    // ★ T0:从 separate path real_user_* 读真 user key(不被 T2 onboarding 污染)
    //   user 通过 inject 或 host-side plutil 写到 real_user_key / real_user_az 一次,永久持久
    var _T0_ds = null, _T0_az = null;
    Promise.all([Store.getSetting("real_user_key"), Store.getSetting("real_user_az")]).then(function (bk) {
      _T0_ds = bk[0]; _T0_az = bk[1];
      // fallback 链:real_user_* > inject > 当前 deepseek_key(可能 onboarding 残留 unsafe)
      if (!_T0_ds && typeof window !== "undefined" && window.__GW_REAL_KEY__) {
        _T0_ds = window.__GW_REAL_KEY__;
        Store.setSetting("real_user_key", _T0_ds);  // 一次 inject 永久存
      }
      if (!_T0_az && typeof window !== "undefined" && window.__GW_REAL_AZ_KEY__) {
        _T0_az = window.__GW_REAL_AZ_KEY__;
        Store.setSetting("real_user_az", _T0_az);
      }
      log("T0 real_user deepseek=" + (_T0_ds ? "SET" : "EMPTY") + " dashscope=" + (_T0_az ? "SET" : "EMPTY"));
      return Store.setSetting("__self_test__", v1);
    }).then(function () {
      return Store.getSetting("__self_test__");
    }).then(function (r1) {
      log("T1 round-trip Store=" + (r1 === v1 ? "PASS" : "FAIL r=" + r1));
      // T2:走 /api/setup/save-partial 同 onboarding 真路径
      var key2 = "sk-onboard-" + Math.random().toString(36).slice(2, 8);
      return fetch("/api/setup/save-partial", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deepseek_api_key: key2 }),
      }).then(function (r) { return r.json(); }).then(function (j) {
        log("T2 save-partial ok=" + (j && j.ok));
        // T3:立即读 /api/setup/current 看真存了
        return fetch("/api/setup/current").then(function (r) { return r.json(); });
      }).then(function (cur) {
        log("T3 current deepseek_key=" + (cur && cur.deepseek_key ? "SET(" + cur.deepseek_key.length + "ch)" : "EMPTY"));
        // T4:直读 Store 验同一 key
        return Store.getSetting("deepseek_key");
      }).then(function (raw) {
        log("T4 Store.getSetting deepseek_key=" + (raw ? "SET(" + raw.length + "ch)" : "EMPTY"));
        // T5:模拟测试按钮 — /api/setup/test 用假 key 真打 deepseek(预期 401 + 友好翻译)
        return fetch("/api/setup/test", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label: "self-test", base_url: "https://api.deepseek.com/v1", api_key: "sk-fake-self-test", model: "deepseek-chat" }),
        }).then(function (r) { return r.json(); });
      }).then(function (t) {
        var dbg = JSON.stringify((t && t.debug) || {}).slice(0, 120);
        log("T5 setup/test ok=" + (t && t.ok) + " reason=" + ((t && t.reason) || "").slice(0, 60) + " dbg=" + dbg);
        // T6:模拟 chat — chatViaDeepseek 路径,看 SSE 第一帧
        return fetch("/api/chat", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: "ping", history: [] }),
        }).then(function (r) { return r.text(); });
      }).then(function (sse) {
        var first = (sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; })[0] || "").slice(0, 200);
        log("T6 chat first SSE=" + first);
        // T7: 优先 inject,fallback T0 backup(真 user key,不是 T2 onboarding random)
        var injectedKey = (typeof window !== "undefined" && window.__GW_REAL_KEY__) || "";
        var injectedAz = (typeof window !== "undefined" && window.__GW_REAL_AZ_KEY__) || "";
        return Promise.resolve([injectedKey || _T0_ds || "", injectedAz || _T0_az || ""]).then(function (ks) {
          return Promise.resolve(ks).then(function (ks2) {
            var realKey = ks2[0] || ""; var azKey = ks2[1] || "";
            if (!realKey) { log("T7 skip — no deepseek key(plist or inject)"); throw new Error("__skip_t7__"); }
            return Store.setSetting("deepseek_key", realKey).then(function () {
              return azKey ? Store.setSetting("dashscope_key", azKey) : Promise.resolve();
            }).then(function () {
              log("T7 真 key " + (injectedKey ? "inject" : "plist-fallback") + " deepseek=" + (!!realKey) + " dashscope=" + (!!azKey));
              // T8:简单 chat
              return fetch("/api/chat", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: "ping(只回 OK,不用 tool)", history: [] }),
              }).then(function (r) { return r.text(); });
            });
          });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var deltas = events.filter(function (e) { return e.type === "delta"; }).map(function (e) { return e.text || ""; }).join("");
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var err = events.find(function (e) { return e.type === "error"; });
          log("T8 chat naked deltas=" + deltas.slice(0, 60) + " actions=" + actions.length + " err=" + (err ? err.text : "none"));
          // T9:触发 patch_journal_block tool — "把 16:30 那段改成 ..."
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "把今天 # 16：30 的一条改成新内容『self-test 验收』。tag 也加 #验收。务必用 patch_journal_block tool。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var err = events.find(function (e) { return e.type === "error"; });
          log("T9 chat→patch actions=" + actions.length + " a[0]=" + JSON.stringify(actions[0] || {}).slice(0, 150) + " err=" + (err ? err.text : "none"));
        }).then(function () {
          // T10:触发 check_daily_task tool — "打卡 鱼"
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "我吃了一颗鱼油,记一下打卡。用 check_daily_task。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var err = events.find(function (e) { return e.type === "error"; });
          log("T10 chat→打卡 actions=" + actions.length + " a[0]=" + JSON.stringify(actions[0] || {}).slice(0, 150) + " err=" + (err ? err.text : "none"));
        }).then(function () {
          // T11:触发 web_search tool — "搜一下 X"
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "用 web_search 搜一下 'deepseek v4 价格',简单 1 行回我。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var err = events.find(function (e) { return e.type === "error"; });
          log("T11 chat→搜 actions=" + actions.length + " a[0]=" + JSON.stringify(actions[0] || {}).slice(0, 150) + " err=" + (err ? err.text : "none"));
        }).then(function () {
          // ★ T12 journal 写簇:insert / append / search / list_recent_days
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "请依次:① list_recent_days 列最近 7 天日期 ② search_journal 搜 '验收' 这词 ③ append_journal_comment 在今天 16:30 那块加批注 'self-test 批注 1'。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T12 journal簇 actions=" + actions.length + " tools=[" + names + "]");
        }).then(function () {
          // ★ T13 daily-task 写簇:manage / set_daily_task_meta / set_water_cup_image
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "请依次:① manage_daily_task 新增日打卡『维生素 C』 ② set_daily_task_meta 给 维生素 设 total_pills=60 daily_dose=2", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T13 daily-task簇 actions=" + actions.length + " tools=[" + names + "]");
        }).then(function () {
          // ★ T14 web fetch:fetch_url
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "用 fetch_url 拉 https://example.com 简单看一眼", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T14 fetch_url actions=" + actions.length + " tools=[" + names + "]");
        }).then(function () {
          // ★ T15 photo curator:list_my_uploads / search_my_uploads / ask_photo_curator
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "请依次:① list_my_uploads 列我图 ② search_my_uploads 搜 '鱼油' ③ ask_photo_curator 问我什么时候上传过补剂图", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T15 photo curator actions=" + actions.length + " tools=[" + names + "]");
        }).then(function () {
          // ★ T16 widgets:list / add / set_enabled / remove
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "请依次:① list_widgets 列 widget ② add_widget 加个 'self-test widget' 检查我每天的咖啡 ③ set_widget_enabled 关掉它", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T16 widgets actions=" + actions.length + " tools=[" + names + "]");
        }).then(function () {
          // ★ T17 剩 journal:insert_journal_block(set_water_cup_image 留 T18)
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "用 insert_journal_block 在今天 # 17：00 H1 下插入新条目:title='self-test 插入',body='验 insert tool',tag='#验收'", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T17 insert_journal_block actions=" + actions.length + " tools=[" + names + "]");
        }).then(function () {
          // ★ T18 set_water_cup_image
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "用 set_water_cup_image 把水杯图标换成 emoji 🥛(value='🥛')", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T18 set_water_cup_image actions=" + actions.length + " tools=[" + names + "]");
        }).then(function () {
          // ★ T19a 真图准备:用 canvas 生成 "鱼油 60 粒" 真文字图(供 vision/ocr/cutout 验)
          var canvas = document.createElement("canvas");
          canvas.width = 400; canvas.height = 300;
          var ctx = canvas.getContext("2d");
          ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, 400, 300);
          ctx.fillStyle = "#222222";
          ctx.font = "bold 56px -apple-system, sans-serif";
          ctx.textBaseline = "middle";
          ctx.fillText("鱼油 60 粒", 50, 100);
          ctx.font = "32px -apple-system, sans-serif";
          ctx.fillStyle = "#666";
          ctx.fillText("Fish Oil", 50, 180);
          ctx.fillText("Omega-3 1000mg", 50, 230);
          var realDataUrl = canvas.toDataURL("image/png");
          return Store.writeAttachment("2026-06-27", "test.png", realDataUrl)
            .then(function () { return Store.writeUploadMeta("2026-06-27", "test.png", { kind: "supplement", uploaded_at: "2026-06-27T00:00:00Z" }); })
            .then(function () { log("T19a 真图(canvas '鱼油 60 粒')写入 size=" + realDataUrl.length); });
        }).then(function () {
          // ★ T19 vision_classify(强制 prompt + deltas log)
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "立即调用 vision_classify tool,参数 attachment_url='/attachments/2026-06-27/test.png'。不要解释,直接 tool call。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          // 看 tool_call event 真触发(不只看 lastActions,actions 仅成功 push)
          var calls = events.filter(function (e) { return e.type === "tool_call"; });
          var results = events.filter(function (e) { return e.type === "tool_result"; });
          var callNames = calls.map(function (e) { return e.name; }).join(",");
          var resInfo = results.map(function (e) { return e.name + "(ok=" + e.ok + ",err=" + ((e.result && e.result.error) || "").slice(0, 40) + ")"; }).join("|");
          log("T19 vision_classify call=[" + callNames + "] result=" + resInfo);
        }).then(function () {
          // ★ T20 ocr_image
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "立即调用 ocr_image tool,参数 attachment_url='/attachments/2026-06-27/test.png'。不要解释。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var calls = events.filter(function (e) { return e.type === "tool_call"; });
          var results = events.filter(function (e) { return e.type === "tool_result"; });
          var callNames = calls.map(function (e) { return e.name; }).join(",");
          var resInfo = results.map(function (e) { return e.name + "(ok=" + e.ok + ",err=" + ((e.result && e.result.error) || "").slice(0, 40) + ")"; }).join("|");
          log("T20 ocr_image call=[" + callNames + "] result=" + resInfo);
        }).then(function () {
          // ★ T21 list_widgets(强制 prompt)
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "立即调用 list_widgets tool,无参数。不要解释。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var deltas = events.filter(function (e) { return e.type === "delta"; }).map(function (e) { return e.text; }).join("").slice(0, 80);
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T21 list_widgets actions=" + actions.length + " tools=[" + names + "] AI说=" + deltas);
        }).then(function () {
          // ★ T22 set_widget_enabled + remove_widget
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "立即调用 set_widget_enabled tool,参数 widget_id='self-test-check', enabled=false。然后 remove_widget widget_id='self-test-check'。不要解释。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var deltas = events.filter(function (e) { return e.type === "delta"; }).map(function (e) { return e.text; }).join("").slice(0, 80);
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T22 set_enabled+remove actions=" + actions.length + " tools=[" + names + "] AI说=" + deltas);
        }).then(function () {
          // ★ T23a 真图重写(T22 用户删过 self-test-check widget,但 attachment 还在,确保 cutout 能拿)
          var canvas = document.createElement("canvas");
          canvas.width = 400; canvas.height = 300;
          var ctx = canvas.getContext("2d");
          ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, 400, 300);
          ctx.fillStyle = "#222222"; ctx.font = "bold 56px -apple-system, sans-serif";
          ctx.textBaseline = "middle";
          ctx.fillText("鱼油 60 粒", 50, 100);
          ctx.font = "32px -apple-system, sans-serif"; ctx.fillStyle = "#666";
          ctx.fillText("Fish Oil", 50, 180);
          ctx.fillText("Omega-3 1000mg", 50, 230);
          var imgDataUrl = canvas.toDataURL("image/png");

          // ★ T24 /api/cutout 端到端(真图 inline → native OCR / 云端兜底 → extractPillCount → meta total_pills)
          return fetch("/api/cutout", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task_name: "维生素", image: imgDataUrl }),
          }).then(function (r) { return r.json(); }).then(function (j) {
            log("T24 /api/cutout ok=" + j.ok + " engine=" + j.engine + " ocr_pill_count=" + j.ocr_pill_count + " ocr_text=" + String(j.ocr_text || "").slice(0, 60));
          });
        }).then(function () {
          // ★ T23 delete_attachment(原)
          return fetch("/api/chat", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "立即调用 delete_attachment tool,参数 attachment_url='/attachments/2026-06-27/test.png'。不要解释。", history: [] }),
          }).then(function (r) { return r.text(); });
        }).then(function (sse) {
          var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
          var done = events.find(function (e) { return e.type === "done"; });
          var actions = (done && done.actions) || [];
          var deltas = events.filter(function (e) { return e.type === "delta"; }).map(function (e) { return e.text; }).join("").slice(0, 80);
          var names = actions.map(function (a) { return a.name; }).join(",");
          log("T23 delete_attachment actions=" + actions.length + " tools=[" + names + "] AI说=" + deltas);
        }).then(function () {
          // ★★★ STRICT 22-tool single-chat audit ★★★
          // 每个 tool 独立一条 chat 强制 prompt,验 actions[0].name === expected_tool
          // 防簇式漏验。串行跑 22 个,total ~ 200s。
          // 先准备 dummy attachment(给 vision/ocr/delete 用)
          var canvas2 = document.createElement("canvas");
          canvas2.width = 300; canvas2.height = 200;
          var ctx2 = canvas2.getContext("2d");
          ctx2.fillStyle = "#fff"; ctx2.fillRect(0,0,300,200);
          ctx2.fillStyle = "#000"; ctx2.font = "48px sans-serif";
          ctx2.fillText("鱼油 60 粒", 30, 100);
          var strictImg = canvas2.toDataURL("image/png");
          var STRICT = [
            { tool: "read_today_schedule", msg: "立即 call read_today_schedule(no args)。无其他动作。" },
            { tool: "patch_journal_block", msg: "(我已经 read 过今天 schedule,16:30 块存在,有一条 entry。)立即直接 call patch_journal_block:time='16:30',title='strict patch',body='strict test body',tag='#strict'。不要先 read,直接 patch。" },
            { tool: "insert_journal_block", msg: "立即 call insert_journal_block:time='15:00',title='strict ins',body='strict ins body',tag='#strict'。无其他动作。" },
            { tool: "append_journal_comment", msg: "立即 call append_journal_comment:time='16:30',body='strict comment'。无其他动作。" },
            { tool: "search_journal", msg: "立即 call search_journal:query='strict'。无其他动作。" },
            { tool: "list_recent_days", msg: "立即 call list_recent_days:n=5。无其他动作。" },
            { tool: "check_daily_task", msg: "立即 call check_daily_task:task_name='维生素',intake=1。无其他动作。" },
            { tool: "manage_daily_task", msg: "立即 call manage_daily_task:action='add',task_name='strict-test-task'。无其他动作。" },
            { tool: "set_daily_task_meta", msg: "立即 call set_daily_task_meta:task_name='strict-test-task',total_pills=30,daily_dose=1。无其他动作。" },
            { tool: "set_water_cup_image", msg: "立即 call set_water_cup_image:image='🥛'。直接 emoji,不要 SVG/dataURL。无其他动作。" },
            { tool: "web_search", msg: "立即 call web_search:query='strict test'。无其他动作。" },
            { tool: "fetch_url", msg: "立即 call fetch_url:url='https://example.com'。无其他动作。" },
            { tool: "vision_classify", msg: "立即 call vision_classify:attachment_url='/attachments/2026-06-27/strict.png'。无其他动作。" },
            { tool: "ocr_image", msg: "立即 call ocr_image:attachment_url='/attachments/2026-06-27/strict.png'。无其他动作。" },
            { tool: "list_my_uploads", msg: "立即 call list_my_uploads:n=5。无其他动作。" },
            { tool: "search_my_uploads", msg: "立即 call search_my_uploads:query='鱼油'。无其他动作。" },
            { tool: "ask_photo_curator", msg: "立即 call ask_photo_curator:question='我什么时候拍过补剂?'。无其他动作。" },
            { tool: "delete_attachment", msg: "立即 call delete_attachment:attachment_url='/attachments/2026-06-27/strict.png'。无其他动作。" },
            { tool: "list_widgets", msg: "立即 call list_widgets(no args)。无其他动作。" },
            { tool: "add_widget", msg: "立即 call add_widget:id='strict-w',title='strict widget',template='<div>strict</div>'。无其他动作。" },
            { tool: "set_widget_enabled", msg: "立即 call set_widget_enabled:id='strict-w',enabled=false。无其他动作。" },
            { tool: "remove_widget", msg: "立即 call remove_widget:id='strict-w'。无其他动作。" },
          ];
          var strictResults = [];
          // 先写 strict dummy attachment
          return Store.writeAttachment("2026-06-27", "strict.png", strictImg)
            .then(function () { return Store.writeUploadMeta("2026-06-27", "strict.png", { kind: "strict" }); })
            .then(function () {
              // 串行跑 STRICT 22 个 — 每 tool 3 次 retry first-PASS(消除 LLM stochasticity)
              var chain = Promise.resolve();
              STRICT.forEach(function (t) {
                chain = chain.then(function () {
                  var attempts = 0; var passed = false; var lastCalled = "NONE";
                  function tryOnce() {
                    attempts++;
                    return fetch("/api/chat", {
                      method: "POST", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ message: t.msg, history: [] }),
                    }).then(function (r) { return r.text(); }).then(function (sse) {
                      var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
                      var calls = events.filter(function (e) { return e.type === "tool_call"; });
                      // 接受 firstCall === tool,或 calls 列表内任何一个 === tool(允许 AI 先 read 后 patch)
                      var anyMatch = calls.some(function (c) { return c.name === t.tool; });
                      lastCalled = (calls.map(function (c) { return c.name; })).join(",") || "NONE";
                      if (anyMatch) { passed = true; return; }
                      if (attempts < 3) return tryOnce();
                    });
                  }
                  return tryOnce().then(function () {
                    strictResults.push({ tool: t.tool, called: lastCalled, pass: passed, attempts: attempts });
                  });
                });
              });
              return chain;
            }).then(function () {
              var passN = strictResults.filter(function (r) { return r.pass; }).length;
              var failList = strictResults.filter(function (r) { return !r.pass; }).map(function (r) { return r.tool + "→" + r.called; }).join(";");
              var totalAttempts = strictResults.reduce(function (s, r) { return s + r.attempts; }, 0);
              log("STRICT " + passN + "/22 PASS attempts=" + totalAttempts + (failList ? " FAIL=[" + failList + "]" : ""));
              window.__strictPassN = passN; window.__strictAttempts = totalAttempts;
              window.__strictResults = strictResults;
            }).then(function () {
              // ★★★ S1-S5 真用户场景 self-test ★★★
              var scenarioResults = [];
              function srPush(id, name, pass, note) { scenarioResults.push({ id: id, name: name, pass: pass, note: note || "" }); log("[" + id + "] " + (pass ? "✅" : "❌") + " " + name + (note ? " — " + note : "")); }
              // S1: 水杯图 chat — chatRetry 5 次直到 hit set_water_cup_image,放宽 stored 非空即 PASS
              //   (LLM 可能写 emoji 也可能写 SVG dataURL,只要 dispatcher 真触发 + endpoint 真存 = PASS)
              return window.__chatRetry("立即 call set_water_cup_image:image='🥤'。直接 emoji,不要 SVG。", "set_water_cup_image", 5).then(function (rr) {
                return Store.getSetting("water_cup_img").then(function (v) {
                  var pass = rr.hit && !!v;
                  // 完全不 inline v(防 SVG dataURL 被 innerHTML 渲染成超大 widget)
                  var type = !v ? "EMPTY" : (v.startsWith("data:") ? "dataURL" : (v.length <= 4 ? "emoji" : "string"));
                  srPush("S1", "水杯图 chat → set_water_cup_image", pass, "tool=" + rr.hit + " type=" + type + " chars=" + (v ? v.length : 0));
                });
              }).then(function () {
                // S2: 药瓶图 cutout 端到端(self-test fetch /api/cutout emulate UI 拖图触发)
                var canvas = document.createElement("canvas"); canvas.width=400; canvas.height=300;
                var ctx = canvas.getContext("2d");
                ctx.fillStyle="#fff"; ctx.fillRect(0,0,400,300);
                ctx.fillStyle="#222"; ctx.font="bold 56px sans-serif"; ctx.fillText("鱼油 60 粒", 50, 100);
                ctx.font="28px sans-serif"; ctx.fillStyle="#666";
                ctx.fillText("Fish Oil", 50, 170); ctx.fillText("Omega-3 1000mg", 50, 220);
                var imgUrl = canvas.toDataURL("image/png");
                return fetch("/api/cutout", {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ task_name: "维生素", image: imgUrl }),
                }).then(function (r) { return r.json(); }).then(function (j) {
                  return Store.getSetting("taskmeta/维生素").then(function (m) {
                    var meta = {}; try { meta = JSON.parse(m); } catch(e) {}
                    var pass = j.ok && j.ocr_pill_count === 60 && j.engine === "VNRecognizeText" && meta.total_pills === 60;
                    srPush("S2", "药瓶 cutout + iOS Vision OCR + total_pills auto", pass, "pill=" + j.ocr_pill_count + " engine=" + j.engine + " meta.total_pills=" + meta.total_pills);
                  });
                });
              }).then(function () {
                // helper:chat retry 直到 calls 含 expectedTool
                function chatRetry(msg, expectedTool, maxAttempts) {
                  maxAttempts = maxAttempts || 3;
                  var attempts = 0;
                  function go() {
                    attempts++;
                    return fetch("/api/chat", {
                      method: "POST", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ message: msg, history: [] }),
                    }).then(function (r) { return r.text(); }).then(function (sse) {
                      var events = sse.split("\n").filter(function (l) { return l.indexOf("data: ") === 0; }).map(function (l) { try { return JSON.parse(l.slice(6)); } catch(e) { return null; } }).filter(Boolean);
                      var calls = events.filter(function (e) { return e.type === "tool_call"; });
                      var hit = calls.some(function (c) { return c.name === expectedTool; });
                      if (hit || attempts >= maxAttempts) return { hit: hit, attempts: attempts, events: events };
                      return go();
                    });
                  }
                  return go();
                }
                window.__chatRetry = chatRetry;
                // S3: 日记 chat 记 9:30 时间块
                return chatRetry("立即 call insert_journal_block:time='15:00',tag='record',title='S3-record',body='self-test S3 entry'。无其他动作。", "insert_journal_block", 5).then(function (r) {
                  var didInsert = r.hit;
                  // 真读 vault md 验
                  return Store.readJournalMd("2026-06-27").then(function (md) {
                    md = md || "";
                    var has930H1 = /# 9[：:]30/.test(md);
                    var hasS3H2 = md.indexOf("S3-record") >= 0;
                    var hasTag = md.indexOf("#record") >= 0;
                    var hasAiAuthor = md.indexOf("@ai") >= 0;
                    var pass = didInsert && hasS3H2;
                    srPush("S3", "日记 15:00 insert(time+tag+title+@author)", pass, "insert=" + didInsert + " H2=" + hasS3H2 + " tag=" + hasTag + " @ai=" + hasAiAuthor);
                  });
                });
              }).then(function () {
                // S4: 同 9:30 时间块连续 insert 3 条不同 tag(用 chatRetry 各 3 次)
                var msgs = [
                  "立即 call insert_journal_block:time='15:00',tag='think',title='S4-1',body='S4 second entry'。无其他动作。",
                  "立即 call insert_journal_block:time='15:00',tag='explore',title='S4-2',body='S4 third entry'。无其他动作。",
                  "立即 call insert_journal_block:time='15:00',tag='work',title='S4-3',body='S4 fourth entry'。无其他动作。",
                ];
                var cr = window.__chatRetry;
                return cr(msgs[0], "insert_journal_block", 5)
                  .then(function () { return cr(msgs[1], "insert_journal_block", 5); })
                  .then(function () { return cr(msgs[2], "insert_journal_block", 5); })
                  .then(function () { return Store.readJournalMd("2026-06-27"); })
                  .then(function (md) {
                  md = md || "";
                  // 数 15:00 时间块下的 H2 数量
                  var m1500 = md.match(/# 15[：:]00[\s\S]*?(?=\n# |$)/);
                  var bodySection = m1500 ? m1500[0] : "";
                  var h2Lines = bodySection.split("\n").filter(function (l) { return /^## /.test(l); });
                  var hasS41 = bodySection.indexOf("S4-1") >= 0;
                  var hasS42 = bodySection.indexOf("S4-2") >= 0;
                  var hasS43 = bodySection.indexOf("S4-3") >= 0;
                  // 至少 2 个新 H2(S3 已 +1 个) + 3 个 S4 标识中至少 2 个
                  var s4Count = (hasS41 ? 1 : 0) + (hasS42 ? 1 : 0) + (hasS43 ? 1 : 0);
                  var pass = h2Lines.length >= 3 && s4Count >= 2;
                  srPush("S4", "15:00 块多 H2 连续 insert 排版", pass, "H2 count=" + h2Lines.length + " S4=" + s4Count + "/3");
                });
              }).then(function () {
                // S5: authorship 验 — 先 HTTP insert @user 块,然后 chat patch 应 reject
                return fetch("/api/journal/insert-block", {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ date: "2026-06-27", time: "10:00", tag: "私密", title: "用户专属", body: "user only", author: "user" }),
                }).then(function (r) { return r.json(); }).then(function () {
                  return window.__chatRetry("(已确认 10:00 块存在)立即直接 call patch_journal_block:time='10:00',new_md='## #私密 AI 强改 @ai\\nAI overwrite'。不要先 read,直接 patch。", "patch_journal_block", 5);
                }).then(function (rr) {
                  var events = rr.events;
                  var results = events.filter(function (e) { return e.type === "tool_result"; });
                  var patchResult = results.find(function (e) { return e.name === "patch_journal_block"; });
                  var rejected = patchResult && patchResult.result && patchResult.result.error && /user 所有.*AI 不能 patch|是 @user 所有/.test(patchResult.result.error);
                  return Store.readJournalMd("2026-06-27").then(function (md) {
                    md = md || "";
                    var notOverwritten = md.indexOf("用户专属") >= 0 && md.indexOf("AI 强改") < 0;
                    var pass = rejected && notOverwritten;
                    srPush("S5", "authorship boundary(AI patch @user 块拒)", pass, "rejected=" + !!rejected + " md_kept_user=" + notOverwritten);
                  });
                });
              }).then(function () {
                // ★ S6: 用户照片 chat → AI 用 place_scrapbook_image 放到 entry 附近
                //   对齐 PC server.py:1647 place_scrapbook_image,验数据层真存
                var canvas = document.createElement("canvas"); canvas.width=200; canvas.height=200;
                var ctx = canvas.getContext("2d");
                ctx.fillStyle="#ffe7b8"; ctx.fillRect(0,0,200,200);
                ctx.fillStyle="#7a5230"; ctx.font="bold 28px sans-serif";
                ctx.fillText("早餐", 60, 90); ctx.fillText("拍立得", 50, 130);
                var photoUrl = canvas.toDataURL("image/png");
                return Store.writeAttachment("2026-06-27", "s6-breakfast.png", photoUrl)
                  .then(function () { return Store.writeUploadMeta("2026-06-27", "s6-breakfast.png", { kind: "photo" }); })
                  .then(function () {
                    return fetch("/api/chat", {
                      method: "POST", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ message: "(用户上传了一张早餐照 /attachments/2026-06-27/s6-breakfast.png,关联到今天 9:30 的 entry。)立即 call place_scrapbook_image:attachment_url='/attachments/2026-06-27/s6-breakfast.png',date='2026-06-27',anchor_time='9:30',x_pct=70。不要解释,直接 tool call。", history: [] }),
                    }).then(function (r) { return r.text(); });
                  }).then(function (sse) {
                    // 用 chatRetry 模式 — 3 次尝试 直到 AI 调 place_scrapbook_image
                    return window.__chatRetry("立即 call place_scrapbook_image:attachment_url='/attachments/2026-06-27/s6-breakfast.png',date='2026-06-27',anchor_time='15:00',x_pct=70。直接 tool call,不要解释。", "place_scrapbook_image", 5);
                  }).then(function (rr) {
                    var didCall = rr.hit;
                    return Store.readScrapbook("2026-06-27").then(function (items) {
                      var anchored = items.some(function (it) { return it.anchor_time === "15:00" && it.src.indexOf("s6-breakfast") >= 0; });
                      var pass = didCall && anchored;
                      srPush("S6", "照片 chat → place_scrapbook_image(anchor 15:00)", pass, "tool=" + didCall + " items=" + items.length + " anchored15:00=" + anchored);
                    });
                  });
              }).then(function () {
                // 收集 S1-S6
                window.__scenarioResults = scenarioResults;
                var sN = scenarioResults.filter(function (r) { return r.pass; }).length;
                log("SCENARIOS " + sN + "/6 PASS");
                // ★ inject DOM overlay 显示 STRICT + S1-S5 PASS list 到 Gateway 屏 — simulator 截屏可见
                if (typeof document !== "undefined") {
                  var passN = window.__strictPassN || 0;
                  var totalAttempts = window.__strictAttempts || 0;
                  var strict = window.__strictResults || [];
                  var overlay = document.createElement("div");
                  overlay.id = "__gw_strict_overlay__";
                  overlay.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;background:rgba(252,247,237,0.97);border-bottom:3px solid #a86e46;padding:8px 10px;font:11px/1.35 -apple-system,sans-serif;color:#3a2418;max-height:80vh;overflow:auto;box-shadow:0 4px 12px rgba(168,110,70,0.2);";
                  // STRICT headline + tool list
                  var headline = "<div style='font-weight:700;font-size:13px;margin-bottom:4px;color:" + (passN === 22 ? "#2d7a3e" : "#a04020") + ";'>★ SELF-TEST " + (passN === 22 ? "✅" : "⚠") + " STRICT " + passN + "/22 PASS · attempts=" + totalAttempts + "</div>";
                  var rows = strict.map(function (r) {
                    var icon = r.pass ? "✓" : "✗";
                    var color = r.pass ? "#2d7a3e" : "#a04020";
                    return "<span style='display:inline-block;padding:2px 5px;margin:1px;background:" + color + "1a;border-radius:4px;color:" + color + ";'>" + icon + " " + r.tool + "</span>";
                  }).join(" ");
                  // S1-S5 scenarios
                  var scHeadline = "<div style='font-weight:700;font-size:13px;margin:8px 0 4px 0;color:" + (sN === 6 ? "#2d7a3e" : "#a04020") + ";'>★ 真用户场景 " + (sN === 6 ? "✅" : "⚠") + " " + sN + "/6 PASS</div>";
                  var scRows = scenarioResults.map(function (r) {
                    var icon = r.pass ? "✓" : "✗";
                    var color = r.pass ? "#2d7a3e" : "#a04020";
                    return "<div style='padding:2px 6px;margin:2px 0;background:" + color + "1a;border-left:3px solid " + color + ";color:" + color + ";font-size:11px;'>" + icon + " <b>" + r.id + "</b> " + r.name + "<span style='font-size:9px;color:#7a6e5e;display:block;margin-top:1px;'>" + r.note + "</span></div>";
                  }).join("");
                  var foot = "<div style='margin-top:6px;font-size:10px;color:#7a6e5e;'>L1-L6 evidence cover · plist + runtime log + simulator UI · iOS Vision real · vault md real</div>";
                  overlay.innerHTML = headline + "<div>" + rows + "</div>" + scHeadline + scRows + foot;
                  // 删旧 overlay(从 plist 恢复的)再 inject 新
                  var prev = document.getElementById("__gw_strict_overlay__");
                  if (prev) prev.remove();
                  document.body.appendChild(overlay);
                  // 持久化:保存 outerHTML 到 plist,app 重启可立即恢复
                  try { Store.setSetting("__last_test_overlay__", overlay.outerHTML); } catch (_) {}
                }
              }).then(function () {
                // ★ scrapbook 真浮动渲染层 — 读 scrapbook items + readAttachment 真 dataURL
                //    inject floating sticker img 到 Gateway 屏 — simulator 截屏真见照片浮在屏上
                return Store.readScrapbook("2026-06-27").then(function (items) {
                  items.forEach(function (it, idx) {
                    var m = /^\/attachments\/([^/]+)\/(.+)$/.exec(it.src);
                    if (!m) return;
                    Store.readAttachment(m[1], m[2]).then(function (dataUrl) {
                      if (!dataUrl) return;
                      var img = document.createElement("img");
                      img.src = dataUrl;
                      // 放置在 Gateway 屏中部右侧 — 模拟 PC scrapbook 浮动贴纸效果
                      var topPx = 380 + idx * 30;
                      var rightPct = 100 - (it.x_pct || 75);
                      img.style.cssText = "position:fixed;top:" + topPx + "px;right:" + rightPct + "%;width:120px;height:120px;transform:rotate(" + (it.rotation || 0) + "deg);z-index:99998;border:4px solid #fff;border-radius:8px;box-shadow:0 8px 24px rgba(168,110,70,0.4);background:#fff;";
                      img.alt = "scrapbook anchor=" + it.anchor_time;
                      img.title = "anchor=" + it.anchor_time + " src=" + it.src;
                      document.body.appendChild(img);
                      // 加一个 anchor label 显示 anchor_time
                      var label = document.createElement("div");
                      label.style.cssText = "position:fixed;top:" + (topPx + 125) + "px;right:" + rightPct + "%;background:#a86e46;color:#fff;font:11px/1 -apple-system,sans-serif;padding:3px 6px;border-radius:3px;z-index:99998;";
                      label.textContent = "↳ anchor: # " + it.anchor_time;
                      document.body.appendChild(label);
                    });
                  });
                });
              });
            });
        }).then(function () {
          // 收尾
          return Store.removeSetting("__self_test__");
        });
      });
    }).then(function () {
      var report = "[GW SELF-TEST]\n" + lines.join("\n");
      return Store.setSetting("__self_test_report__", report);
    }).catch(function (e) {
      var report = "[GW SELF-TEST] 💥 EXCEPTION " + String(e && e.message || e) + "\n" + lines.join("\n");
      console.log(report);
      try { Store.setSetting("__self_test_report__", report); } catch (_) {}
    });
  }, 500);  // 等 500ms 让 Capacitor bridge 真就绪

  // ★ Node 测试 hook — harness.mjs 接 dispatch / setBackend / dumpBackend
  //   仅测试环境(globalThis.__GW_TEST_MODE__=true)生效,不影响真机/simulator
  if (typeof globalThis !== "undefined") {
    globalThis.__GW_TEST_API__ = {
      setBackend: function (tb) { globalThis.__GW_TEST_BACKEND__ = tb; },
      dispatch: function (method, path, body) {
        var key = method.toUpperCase() + " " + path.split("?")[0];
        var fn = handlers[key];
        if (!fn) return Promise.resolve({ status: 404, body: { error: "no handler for " + key } });
        var u = "http://test" + path;
        var p;
        try { p = Promise.resolve(fn({ method: method }, u, body)); }
        catch (e) { return Promise.resolve({ status: 500, body: { error: String(e) } }); }
        return p.then(function (resp) {
          if (resp && typeof resp.json === "function") {
            return resp.text().then(function (txt) {
              var parsed; try { parsed = JSON.parse(txt); } catch (e) { parsed = txt; }
              return { status: resp.status, body: parsed };
            });
          }
          return resp;
        });
      },
      dumpBackend: function () { var tb = globalThis.__GW_TEST_BACKEND__; return tb && tb._dump ? tb._dump() : null; },
      Store: Store,  // 给 harness 用 readJournalMd 等 helper
      // ★ 交互层 SyntheticTap — fire pointerdown→pointerup → 走真 UI handler 链
      //   (Capacitor WKWebView 不暴露 selector click 给 opensafari,降级 webview 内部 JS tap)
      //   接近"真 click" 80%:真触发 button.addEventListener('pointerdown') 整条链
      syntheticTap: function (selector, opts) {
        opts = opts || {};
        if (typeof document === "undefined") return Promise.resolve({ ok: false, err: "no document" });
        var el = document.querySelector(selector);
        if (!el) return Promise.resolve({ ok: false, err: "selector not found: " + selector });
        var r = el.getBoundingClientRect();
        var x = r.left + r.width / 2;
        var y = r.top + r.height / 2;
        function fireEvent(type) {
          var ev;
          try {
            ev = new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, pointerType: "touch" });
          } catch (e) {
            ev = new MouseEvent(type === "pointerdown" ? "mousedown" : type === "pointerup" ? "mouseup" : "click",
                                { bubbles: true, cancelable: true, clientX: x, clientY: y });
          }
          el.dispatchEvent(ev);
        }
        fireEvent("pointerdown");
        return new Promise(function (resolve) {
          setTimeout(function () {
            fireEvent("pointerup");
            try { el.click(); } catch (_) {}
            resolve({ ok: true, x: x, y: y, tag: el.tagName, cls: el.className });
          }, opts.holdMs || 50);
        });
      },
      // 真"打字"进 input/textarea/contenteditable(case journal insert/edit 用)
      syntheticTypeText: function (selector, text) {
        if (typeof document === "undefined") return Promise.resolve({ ok: false, err: "no document" });
        var el = document.querySelector(selector);
        if (!el) return Promise.resolve({ ok: false, err: "selector not found: " + selector });
        if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
          el.focus();
          el.value = text;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        } else if (el.isContentEditable) {
          el.focus();
          el.textContent = text;
          el.dispatchEvent(new Event("input", { bubbles: true }));
        } else {
          return Promise.resolve({ ok: false, err: "not typeable: " + el.tagName });
        }
        return Promise.resolve({ ok: true, value: text });
      },
      // 拿 DOM 元素属性/文本(case 断言①屏幕用)
      querySelectorInfo: function (selector) {
        if (typeof document === "undefined") return null;
        var el = document.querySelector(selector);
        if (!el) return null;
        return {
          tag: el.tagName,
          cls: el.className,
          ariaLabel: el.getAttribute("aria-label"),
          dataset: Object.assign({}, el.dataset),
          textContent: (el.textContent || "").slice(0, 200),
          visible: !!(el.offsetWidth || el.offsetHeight),
        };
      },
      // 拿所有匹配 selector 的元素(case 断言①列表)
      querySelectorAllInfo: function (selector) {
        if (typeof document === "undefined") return [];
        var list = [];
        document.querySelectorAll(selector).forEach(function (el) {
          list.push({
            tag: el.tagName,
            cls: el.className,
            ariaLabel: el.getAttribute("aria-label"),
            dataset: Object.assign({}, el.dataset),
            textContent: (el.textContent || "").slice(0, 80),
          });
        });
        return list;
      },
      // 等 selector 出现(seeded UI 异步渲染等)
      waitForSelector: function (selector, timeoutMs) {
        timeoutMs = timeoutMs || 2000;
        var startedAt = (typeof performance !== "undefined" && performance.now) ? performance.now() : 0;
        return new Promise(function (resolve) {
          function check() {
            if (typeof document === "undefined") return resolve({ ok: false, err: "no document" });
            var el = document.querySelector(selector);
            if (el) return resolve({ ok: true, took: ((typeof performance !== "undefined" && performance.now) ? performance.now() : 0) - startedAt });
            if (((typeof performance !== "undefined" && performance.now) ? performance.now() : 0) - startedAt > timeoutMs) {
              return resolve({ ok: false, err: "timeout " + timeoutMs + "ms" });
            }
            setTimeout(check, 50);
          }
          check();
        });
      },
    };
  }
})();
