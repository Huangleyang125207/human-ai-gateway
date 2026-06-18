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
    readThread: function () {
      return Backend.getText("thread").then(function (t) { try { return t ? JSON.parse(t) : []; } catch (e) { return []; } });
    },
    writeThread: function (arr) { return Backend.setText("thread", JSON.stringify(arr || [])); },
    getSetting: function (k) { return Backend.getText("setting/" + k); },
    setSetting: function (k, v) { return Backend.setText("setting/" + k, v); },
  };

  // ── 工具:日期 ───────────────────────────────────────
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function todayIso() { var d = new Date(); return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()); }
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
      var role = h.role === "ai" || h.role === "assistant" ? "assistant" : "user";
      var content = typeof h.content === "string" ? h.content : (h.text || "");
      if (content) out.push({ role: role, content: content });
    }
    return out;
  }
  function pickReply(d) { return d && d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content; }
  function chatViaDeepseek(body, key, model) {
    return Store.readJournalMd(todayIso()).then(function (todayMd) {
      var sys = "你是用户的日记协作 AI,语气温和、像深夜台灯下说话。这是今天的日记:\n\n" + (todayMd || "(今天还没写)");
      var messages = [{ role: "system", content: sys }].concat(histToMsgs(body), [{ role: "user", content: (body && body.message) || "" }]);
      var payload = { model: model || "deepseek-chat", messages: messages, stream: false };
      var url = "https://api.deepseek.com/v1/chat/completions";
      var headers = { "Content-Type": "application/json", Authorization: "Bearer " + key };
      var CapHttp = _cap && _cap.CapacitorHttp;
      if (CapHttp) {
        return CapHttp.post({ url: url, headers: headers, data: payload })
          .then(function (res) { return sseResp([{ type: "delta", text: pickReply(res && res.data) || "(空回复)" }, { type: "done", actions: [], model_id: model || "deepseek" }]); })
          .catch(function (e) { return sseResp([{ type: "error", text: "DeepSeek 调用失败:" + e }, { type: "done", actions: [], model_id: model || "deepseek" }]); });
      }
      return realFetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload) })
        .then(function (r) { return r.json(); })
        .then(function (d) { return sseResp([{ type: "delta", text: pickReply(d) || "(空回复)" }, { type: "done", actions: [], model_id: model || "deepseek" }]); })
        .catch(function () { return sseResp([{ type: "delta", text: "（浏览器直连 DeepSeek 受 CORS 限制 —— 真机经原生 HTTP 桥即可正常聊。）" }, { type: "done", actions: [], model_id: model || "deepseek" }]); });
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
        return Promise.all(tasks.map(function (t) {
          return Store.getSetting("taskimg/" + t.name).then(function (img) { t.image_url = img || null; return t; });
        })).then(function (ts) {
          return jsonResp({ tasks: ts, water_filled: water, date: date, is_today: date === todayIso(), is_writable: date >= todayIso() });
        });
      });
    },
    // 打卡图标:存抠好的 PNG(端侧抠图后由前端传来),按 task 名持久化
    "POST /api/daily-tasks/set-image": function (req, u, body) {
      if (!(body && body.task_name)) return jsonResp({ ok: false, error: "缺 task_name" });
      return Store.setSetting("taskimg/" + body.task_name, body.image || "").then(function () { return jsonResp({ ok: true }); });
    },
    "POST /api/daily-tasks/check": function (req, u, body) {
      var date = (body && body.date) || todayIso();
      var name = body && body.task_name;
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ ok: false, error: "no file" }, 404);
        var tasks = parseSupplements(md), cur = null, t;
        for (t = 0; t < tasks.length; t++) if (tasks[t].name === name) cur = tasks[t];
        var checked = body && typeof body.checked === "boolean" ? body.checked : !(cur && cur.checked);
        return Store.writeJournalMd(date, setSupplementChecked(md, name, checked)).then(function () {
          return jsonResp({ ok: true, task_name: name, checked: checked, total_pills: null, daily_dose: 1, today_intake: checked ? 1 : 0, remaining: null });
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
    "GET /api/thread/history": function () {
      return Store.readThread().then(function (arr) { return jsonResp({ history: arr, mtime: Date.now() }); });
    },
    "POST /api/thread/save": function (req, u, body) {
      var hist = (body && body.history) || [];
      return Store.writeThread(hist).then(function () { return jsonResp({ ok: true, mtime: Date.now(), count: hist.length }); });
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
    "POST /api/journal/patch": function (req, u, body) {
      var date = (body && body.date) || todayIso(), time = body && body.time;
      return Store.readJournalMd(date).then(function (md) {
        if (md === null) return jsonResp({ error: "no file" });
        // 找到 time 对应的块,替整块体(MVP:简单替换,块内第一条 H2 起到下个 H1/分隔前)
        var pad = pad2(parseInt((time || "0:0").split(":")[0], 10)) + ":" + (time || "0:00").split(":")[1];
        var lines = md.split(/\r?\n/), out = [], inBlock = false, replaced = false;
        for (var i = 0; i < lines.length; i++) {
          var tm = TIME_H1_RE.exec(lines[i]);
          if (tm) {
            var t = pad2(parseInt(tm[1], 10)) + ":" + tm[2];
            inBlock = (t === pad);
            out.push(lines[i]);
            if (inBlock && !replaced) { out.push("", body.new_md || ""); replaced = true; }
            continue;
          }
          if (inBlock) { if (lines[i].trim() === "---") { inBlock = false; out.push("", "---"); } continue; }
          out.push(lines[i]);
        }
        return Store.writeJournalMd(date, out.join("\n")).then(function () {
          return replaced ? jsonResp({ patched: time, file: isoToStem(date) + ".md" }) : jsonResp({ error: "block not found" });
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
    "POST /api/setup/save-partial": function () { return jsonResp({ ok: true }); },
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
  var realFetch = window.fetch.bind(window);

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
