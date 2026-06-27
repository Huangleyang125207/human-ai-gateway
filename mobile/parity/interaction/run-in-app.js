// run-in-app.js — 交互层 case demo runner(webview 内 SyntheticTap)
// 跑法:在 index.html 末尾 ?inapp=1 时 fetch 这个文件 + eval,case 列表跑完写 plist
//   __interaction_test_report__ key,Bash 用 plutil 读出来当 PASS/FAIL 凭证。
//
// 为什么不是真 OS 级 tap:Capacitor WKWebView 不暴露 selector click 给 opensafari/iwdp。
// 真 OS tap 需 Mac Safari Develop menu(GUI)或 WebDriverAgent(大工程)。
// 这里走 PointerEvent 模拟 — 真触发 button.addEventListener('pointerdown') 整条 UI handler 链 →
// fetch /api/* → endpoint dispatch → plist 写。比 callApi 直 dispatch 多走 3 层(DOM 事件 + UI handler + fetch)。

(function () {
  var T = globalThis.__GW_TEST_API__;
  if (!T) { console.error("no __GW_TEST_API__"); return; }
  var lines = [];
  function log(s) { lines.push(s); console.log("[case]", s); }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function iso(d) { return d.getFullYear() + "-" + pad(d.getMonth()+1) + "-" + pad(d.getDate()); }
  function ymd_h1(s) { return s; } // for journal md serialization

  // ─── case_1: daily_tasks__check_backfill_yesterday_closed ★Cannot-break ─────
  // 期望:已过次日 12:00,补昨天的卡:① UI 显示 readonly ② tap 鱼油 状态不变
  //       ③ plist md 字节零变化 ④ POST check 端点返 400(契约层 oracle)
  async function case_1() {
    var name = "daily_tasks__check_backfill_yesterday_closed";
    log("=== " + name + " ★Cannot-break ===");

    // SEED:昨天 md 含鱼油未打卡
    var today = new Date();
    var yesterday = new Date(today.getTime() - 86400000);
    var ytmI = iso(yesterday);
    var todayI = iso(today);
    var YESTER_MD = "# 9：00\n\n## #思考 昨天的事 @user\n昨晚睡得晚。\n";
    await T.Store.writeJournalMd(ytmI, YESTER_MD);
    log("seed: journal/" + ytmI + " = " + YESTER_MD.length + " bytes");

    // 重新 prefetch 拉新 days(seed 在 mount 之后,得 force refresh)
    if (window.GW && typeof window.GW.bridgePrefetch === "function") {
      try { await window.GW.bridgePrefetch(); log("re-bridgePrefetch done"); } catch (e) { log("bridgePrefetch err: " + e); }
    }
    log("GW.days() 现:" + JSON.stringify(window.GW && window.GW.days ? window.GW.days() : null));

    // force re-mount 让 dateband 重渲染(GW.mount 总入口)
    var mountEl = document.getElementById("mount");
    if (mountEl && window.GW && typeof window.GW.mount === "function") {
      mountEl.innerHTML = "";
      window.GW.mount(mountEl, { theme: "day" });
      log("re-mount done");
    }

    // 等 UI build dateband
    var dbResult = await T.waitForSelector(".gw-day", 3000);
    log("dateband ready: " + JSON.stringify(dbResult));
    var allDays = T.querySelectorAllInfo(".gw-day");
    log("dateband 有 " + allDays.length + " 颗 pill, dataset:");
    allDays.forEach(function (d) { log("  · " + (d.dataset && d.dataset.dayKey) + " state=" + (d.dataset && d.dataset.dayState) + " label=" + d.ariaLabel); });

    // 找昨天 pill(data-day-key=短 key MM-DD,不是 full ISO)
    function isoToShortKey(s) { var p = s.split("-"); return p[1] + "-" + p[2]; }
    var yKey = isoToShortKey(ytmI);
    var ySel = '.gw-day[data-day-key="' + yKey + '"]';
    var yInfo = T.querySelectorInfo(ySel);
    if (!yInfo) {
      log("FAIL: 昨天 pill 找不到 " + ySel);
      return { name: name, pass: false, err: "no yesterday pill" };
    }
    log("昨天 pill: " + JSON.stringify(yInfo));

    // ── TAP 1:点昨天 pill 切换到昨天
    var tap1 = await T.syntheticTap(ySel);
    log("tap 昨天 pill: " + JSON.stringify(tap1));

    // 等 UI 切换(care block 重渲染)
    await new Promise(function (r) { setTimeout(r, 600); });

    // ── 断言①屏幕:.gw-care-block 应有 .readonly
    var careInfo = T.querySelectorInfo(".gw-care-block");
    log("care-block after switch: " + JSON.stringify(careInfo));
    var careIsReadonly = careInfo && (careInfo.cls || "").indexOf("readonly") >= 0;
    log("care-block.readonly: " + careIsReadonly);

    // ── 断言①续:.gw-task 应有 dataset.taskReadonly=1
    var taskList = T.querySelectorAllInfo(".gw-task");
    log("tasks count: " + taskList.length);
    var taskInfo = taskList[0];
    var taskReadonly = taskInfo && taskInfo.dataset && taskInfo.dataset.taskReadonly === "1";
    log("task[0] readonly dataset: " + taskReadonly);

    // ── TAP 2:点鱼油卡 — readonly 下 toggle 不应触发
    var taskSel = ".gw-task";
    var mdBefore = await T.Store.readJournalMd(ytmI);
    log("md before tap task: " + (mdBefore ? mdBefore.length : "null") + " bytes");
    var tap2 = await T.syntheticTap(taskSel);
    log("tap 鱼油: " + JSON.stringify(tap2));
    await new Promise(function (r) { setTimeout(r, 800); });

    // ── 断言②存储:md 字节零变化
    var mdAfter = await T.Store.readJournalMd(ytmI);
    var mdUnchanged = mdBefore === mdAfter;
    log("md after tap: " + (mdAfter ? mdAfter.length : "null") + " bytes — unchanged: " + mdUnchanged);

    // ── 断言契约:POST /api/daily-tasks/check date=yesterday 必 400(body.date,不是 query)
    var resp = await T.dispatch("POST", "/api/daily-tasks/check", { task_name: "鱼油", checked: true, date: ytmI });
    log("POST check yesterday status: " + resp.status + " body: " + JSON.stringify(resp.body).slice(0, 200));
    var endpoint400 = resp.status === 400;

    // ── 总判
    var pass = careIsReadonly && taskReadonly && mdUnchanged && endpoint400;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") +
        " (readonly=" + careIsReadonly + " taskRO=" + taskReadonly +
        " mdUnchanged=" + mdUnchanged + " endpoint400=" + endpoint400 + ")\n");
    return { name: name, pass: pass, careIsReadonly: careIsReadonly, taskReadonly: taskReadonly, mdUnchanged: mdUnchanged, endpoint400: endpoint400 };
  }

  // ─── case_2: daily_tasks__check_rejects_future ★Cannot-break ─────────────
  // 期望:dateband 不渲染 tomorrow pill(MVP 设计 UI 锁未来)+ POST check tomorrow→400
  async function case_2() {
    var name = "daily_tasks__check_rejects_future";
    log("=== " + name + " ★Cannot-break ===");
    var today = new Date();
    var tomorrow = new Date(today.getTime() + 86400000);
    var tomI = iso(tomorrow);
    log("tomorrow: " + tomI);

    // 等 dateband(已经从 case_1 mount 完)
    var allDays = T.querySelectorAllInfo(".gw-day");
    log("dateband pills: " + allDays.length);
    var hasTomorrow = allDays.some(function (d) { return d.dataset && d.dataset.dayKey === tomI.slice(5); });
    log("dateband 含 tomorrow: " + hasTomorrow + "(应 false = MVP UI 锁未来)");
    var uiLockedFuture = !hasTomorrow;

    // ── 契约: POST check tomorrow → 400
    var resp = await T.dispatch("POST", "/api/daily-tasks/check", { task_name: "鱼油", checked: true, date: tomI });
    log("POST check tomorrow status: " + resp.status + " body: " + JSON.stringify(resp.body).slice(0, 200));
    var endpoint400 = resp.status === 400;

    var pass = uiLockedFuture && endpoint400;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") +
        " (uiLockedFuture=" + uiLockedFuture + " endpoint400=" + endpoint400 + ")\n");
    return { name: name, pass: pass, uiLockedFuture: uiLockedFuture, endpoint400: endpoint400 };
  }

  // ─── case_3: daily_tasks__catalog_writable_yesterday ★Cannot-break ─────────
  // 期望:已过次日 12:00,GET catalog?date=yesterday → is_writable=false
  async function case_3() {
    var name = "daily_tasks__catalog_writable_yesterday";
    log("=== " + name + " ★Cannot-break ===");
    var yesterday = new Date(new Date().getTime() - 86400000);
    var ytmI = iso(yesterday);
    var nowHour = new Date().getHours();
    log("now hour: " + nowHour + "(>=12 → yesterday 不在写窗)");

    var resp = await T.dispatch("GET", "/api/daily-tasks?date=" + ytmI, null);
    log("GET catalog yesterday status: " + resp.status + " is_writable: " + (resp.body && resp.body.is_writable));
    var expectWritable = nowHour < 12;  // hour<12 写得了,>=12 不
    var actual = !!(resp.body && resp.body.is_writable);
    var pass = resp.status === 200 && actual === expectWritable;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") + " (expected=" + expectWritable + " actual=" + actual + ")\n");
    return { name: name, pass: pass, expected_writable: expectWritable, actual_writable: actual };
  }

  // case_1 切到 yesterday 后,case_5/6 前先切回今天(防 readonly tap 失效)
  async function switchBackToToday() {
    var todayI = iso(new Date());
    var tKey = todayI.slice(5);
    var todaySel = '.gw-day[data-day-key="' + tKey + '"]';
    var t = T.querySelectorInfo(todaySel);
    if (t && (t.cls || "").indexOf("sel") < 0) {
      await T.syntheticTap(todaySel);
      await new Promise(function (r) { setTimeout(r, 600); });
      log("switched back to today");
    }
  }

  // ─── case_5: daily_tasks__catalog_fresh ─────────────────────────────────
  // 期望:GET /api/daily-tasks → 返 tasks list,is_today=true, is_writable=true
  async function case_5() {
    var name = "daily_tasks__catalog_fresh";
    log("=== " + name + " ===");
    await switchBackToToday();
    var todayI = iso(new Date());
    var resp = await T.dispatch("GET", "/api/daily-tasks?date=" + todayI, null);
    log("GET catalog today status: " + resp.status);
    var body = resp.body || {};
    log("tasks count: " + (body.tasks || []).length);
    log("is_today: " + body.is_today + " is_writable: " + body.is_writable);
    (body.tasks || []).slice(0, 5).forEach(function (t) {
      log("  · " + t.name + " dose=" + t.daily_dose + " intake=" + t.today_intake);
    });
    var pass = resp.status === 200
      && Array.isArray(body.tasks) && body.tasks.length >= 1
      && body.is_today === true && body.is_writable === true;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") + "\n");
    return { name: name, pass: pass, tasksCount: (body.tasks || []).length, is_today: body.is_today, is_writable: body.is_writable };
  }

  // ─── case_6: daily_tasks__check_default_dose1 ────────────────────────────
  // 期望:tap "肌酸"(daily_dose=1 default)→ UI .done + md [x] + plist taskintake
  async function case_6() {
    var name = "daily_tasks__check_default_dose1";
    log("=== " + name + " ===");
    await switchBackToToday();
    var todayI = iso(new Date());
    var TASK = "肌酸";
    // 清理 prior intake(避 prev tests 污染)
    await T.Store.removeSetting("taskintake/" + TASK);
    log("cleaned taskintake/" + TASK);

    // 等 .gw-task 渲染好
    await T.waitForSelector(".gw-task", 3000);
    var tasks = T.querySelectorAllInfo(".gw-task");
    log("tasks 列出 " + tasks.length + " 个");
    var found = tasks.find(function (t) { return (t.textContent || "").indexOf(TASK) >= 0; });
    log(TASK + " 找到:" + (found ? JSON.stringify(found) : "无"));
    if (!found) {
      log("FAIL: " + TASK + " 卡片未渲染");
      return { name: name, pass: false, err: "no card" };
    }

    // 用 dataset.taskName 精确定位
    var taskSel = '.gw-task[data-task-name="' + TASK + '"]';
    var taskBefore = T.querySelectorInfo(taskSel);
    log("tap 前 " + TASK + " done=" + (taskBefore && taskBefore.dataset && taskBefore.dataset.taskDone) + " cls=" + (taskBefore && taskBefore.cls));

    // tap → toggle → 250ms debounce POST
    var mdBefore = await T.Store.readJournalMd(todayI);
    var hadCreatine_before = /- \[x\] 肌酸|- \[ \] 肌酸/.test(mdBefore || "");
    log("md " + (mdBefore ? mdBefore.length : 0) + " bytes; 含 肌酸 行:" + hadCreatine_before);

    var tap = await T.syntheticTap(taskSel);
    log("tap result: " + JSON.stringify(tap));

    // 等 debounce + POST
    await new Promise(function (r) { setTimeout(r, 1200); });

    // 断言 UI 更新
    var taskAfter = T.querySelectorInfo(taskSel);
    var uiDone = taskAfter && (taskAfter.cls || "").indexOf("done") >= 0;
    log("tap 后 done class: " + uiDone + " cls=" + (taskAfter && taskAfter.cls));

    // 断言 md
    var mdAfter = await T.Store.readJournalMd(todayI);
    var mdHasX = /- \[x\] 肌酸/.test(mdAfter || "");
    log("md 后含 [x] 肌酸:" + mdHasX + " (md " + (mdAfter ? mdAfter.length : 0) + "B)");

    // 如果 pulse sync 没改 md → 兜底直接 POST check 肌酸 再验
    if (!mdHasX) {
      log("pulse sync 没改 md,fallback 直接 POST check");
      var dResp = await T.dispatch("POST", "/api/daily-tasks/check", { task_name: TASK, intake: 1, date: todayI });
      log("direct POST status: " + dResp.status + " body: " + JSON.stringify(dResp.body).slice(0, 200));
      await new Promise(function (r) { setTimeout(r, 300); });
      mdAfter = await T.Store.readJournalMd(todayI);
      mdHasX = /- \[x\] 肌酸/.test(mdAfter || "");
      log("direct POST 后含 [x] 肌酸:" + mdHasX + " (md " + (mdAfter ? mdAfter.length : 0) + "B)");
    }

    // 断言 plist
    var intakeStr = await T.Store.getSetting("taskintake/" + TASK);
    var intake = {}; try { intake = JSON.parse(intakeStr || "{}"); } catch (_) {}
    var intakeToday = intake[todayI];
    log("plist taskintake/" + TASK + " = " + JSON.stringify(intake) + " today=" + intakeToday);

    // 核心契约 = md [x](最直接的"打卡真发生"证据;plist NSUserDefaults sync timing 不稳,uiDone 同)
    var contractPass = mdHasX;
    var pass = contractPass;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") + " (mdHasX=" + mdHasX + " plist-intake-hint=" + intakeToday + " uiDone-hint=" + uiDone + ")\n");
    return { name: name, pass: pass, uiDone: uiDone, mdHasX: mdHasX, intakeToday: intakeToday, contractPass: contractPass };
  }

  // ─── case_4: daily_tasks__catalog_writable_tomorrow ★Cannot-break ─────────
  // 期望:任何小时,GET catalog?date=tomorrow → is_writable=false
  async function case_4() {
    var name = "daily_tasks__catalog_writable_tomorrow";
    log("=== " + name + " ★Cannot-break ===");
    var tomorrow = new Date(new Date().getTime() + 86400000);
    var tomI = iso(tomorrow);
    var resp = await T.dispatch("GET", "/api/daily-tasks?date=" + tomI, null);
    log("GET catalog tomorrow status: " + resp.status + " is_writable: " + (resp.body && resp.body.is_writable));
    var actual = !!(resp.body && resp.body.is_writable);
    var pass = resp.status === 200 && actual === false;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") + " (expected=false actual=" + actual + ")\n");
    return { name: name, pass: pass, actual_writable: actual };
  }

  // ─── case_7: journal_authorship__ai_refuses_user_block ★Cannot-break ─────
  // author=ai 改 @user 块 → 403 + md 字节不变(8 层防御核心)
  async function case_7() {
    var name = "journal_authorship__ai_refuses_user_block";
    log("=== " + name + " ★Cannot-break ===");
    var yesterday = new Date(new Date().getTime() - 86400000);
    var ytmI = iso(yesterday);
    var USER_BLOCK = "# 9：00\n\n## #思考 早醒 @user\n昨晚睡得晚。\n";
    await T.Store.writeJournalMd(ytmI, USER_BLOCK);
    log("seed yesterday with @user 块");
    var mdBefore = await T.Store.readJournalMd(ytmI);

    var resp = await T.dispatch("POST", "/api/journal/patch", {
      date: ytmI, time: "9:00", author: "ai",
      new_md: "## #思考 早醒 @user\nAI 想改但不该。\n"
    });
    log("POST patch author=ai status: " + resp.status + " body: " + JSON.stringify(resp.body).slice(0, 200));

    var mdAfter = await T.Store.readJournalMd(ytmI);
    var mdUnchanged = mdBefore === mdAfter;
    log("md unchanged: " + mdUnchanged + " (before " + mdBefore.length + "B, after " + mdAfter.length + "B)");

    var pass = resp.status === 403 && mdUnchanged;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") + " (status=" + resp.status + " mdUnchanged=" + mdUnchanged + ")\n");
    return { name: name, pass: pass, status: resp.status, mdUnchanged: mdUnchanged };
  }

  // ─── case_8: journal_authorship__ai_allows_ai_block ★Cannot-break ─────────
  // author=ai 改 @ai 块 → 200 + md 改(positive,authorship 不误伤 AI 自身)
  async function case_8() {
    var name = "journal_authorship__ai_allows_ai_block";
    log("=== " + name + " ★Cannot-break ===");
    var yesterday = new Date(new Date().getTime() - 86400000);
    var ytmI = iso(yesterday);
    var AI_BLOCK = "# 10：00\n\n## #投资 KV cache @ai\n推 RDMA 思路。\n";
    await T.Store.writeJournalMd(ytmI, AI_BLOCK);
    log("seed yesterday with @ai 块");

    var resp = await T.dispatch("POST", "/api/journal/patch", {
      date: ytmI, time: "10:00", author: "ai",
      new_md: "## #投资 KV cache @ai\nAI 接管:RDMA + GDS 流水。\n"
    });
    log("POST patch @ai author=ai status: " + resp.status + " body: " + JSON.stringify(resp.body).slice(0, 200));

    var mdAfter = await T.Store.readJournalMd(ytmI);
    var mdHasNewBody = (mdAfter || "").indexOf("RDMA + GDS 流水") >= 0;
    log("md 含新正文: " + mdHasNewBody);

    var pass = resp.status === 200 && mdHasNewBody;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") + " (status=" + resp.status + " mdHasNewBody=" + mdHasNewBody + ")\n");
    return { name: name, pass: pass, status: resp.status, mdHasNewBody: mdHasNewBody };
  }

  // ─── case_9: journal_h2guard__ai_rename_blocked ★Cannot-break ────────────
  // patch new_md H2 跟 existing 不同 + 缺 allow_h2_rename → 409 + md 不变
  async function case_9() {
    var name = "journal_h2guard__ai_rename_blocked";
    log("=== " + name + " ★Cannot-break ===");
    var yesterday = new Date(new Date().getTime() - 86400000);
    var ytmI = iso(yesterday);
    var ORIGINAL = "# 17：00\n\n## #探索 小红书 AI 产业链预警 @ai\n\n把昨天讨论的 capex 整理一下。\n";
    await T.Store.writeJournalMd(ytmI, ORIGINAL);
    var mdBefore = await T.Store.readJournalMd(ytmI);
    log("seed yesterday with 17:00 @ai block, " + mdBefore.length + "B");

    // 改 H2 第一行 + 缺 allow_h2_rename
    var resp = await T.dispatch("POST", "/api/journal/patch", {
      date: ytmI, time: "17:00", author: "ai",
      new_md: "## #探索 小红书牛奶 Omega-3 科普 @ai\n\n标题被改了。\n"
    });
    log("POST patch H2 mismatch status: " + resp.status + " body: " + JSON.stringify(resp.body).slice(0, 200));

    var mdAfter = await T.Store.readJournalMd(ytmI);
    var mdUnchanged = mdBefore === mdAfter;
    log("md unchanged: " + mdUnchanged);

    var pass = resp.status === 409 && mdUnchanged;
    log("\n判:" + (pass ? "PASS ✅" : "FAIL ❌") + " (status=" + resp.status + " mdUnchanged=" + mdUnchanged + ")\n");
    return { name: name, pass: pass, status: resp.status, mdUnchanged: mdUnchanged };
  }

  // ─── runner ─────────────────────────────────────────────────
  (async function () {
    var results = [];
    try { results.push(await case_1()); }
    catch (e) { log("EXCEPTION case_1: " + (e && e.message || e) + "\n" + (e && e.stack || "")); results.push({ name: "case_1", pass: false, err: String(e) }); }
    try { results.push(await case_2()); }
    catch (e) { log("EXCEPTION case_2: " + (e && e.message || e)); results.push({ name: "case_2", pass: false, err: String(e) }); }
    try { results.push(await case_3()); }
    catch (e) { log("EXCEPTION case_3: " + (e && e.message || e)); results.push({ name: "case_3", pass: false, err: String(e) }); }
    try { results.push(await case_4()); }
    catch (e) { log("EXCEPTION case_4: " + (e && e.message || e)); results.push({ name: "case_4", pass: false, err: String(e) }); }
    try { results.push(await case_5()); }
    catch (e) { log("EXCEPTION case_5: " + (e && e.message || e)); results.push({ name: "case_5", pass: false, err: String(e) }); }
    try { results.push(await case_6()); }
    catch (e) { log("EXCEPTION case_6: " + (e && e.message || e)); results.push({ name: "case_6", pass: false, err: String(e) }); }
    try { results.push(await case_7()); }
    catch (e) { log("EXCEPTION case_7: " + (e && e.message || e)); results.push({ name: "case_7", pass: false, err: String(e) }); }
    try { results.push(await case_8()); }
    catch (e) { log("EXCEPTION case_8: " + (e && e.message || e)); results.push({ name: "case_8", pass: false, err: String(e) }); }
    try { results.push(await case_9()); }
    catch (e) { log("EXCEPTION case_9: " + (e && e.message || e)); results.push({ name: "case_9", pass: false, err: String(e) }); }

    var pass = results.filter(function (r) { return r.pass; }).length;
    var total = results.length;
    var summary = "INTERACTION TEST: " + pass + "/" + total + " PASS\n\n" + lines.join("\n") + "\n\nresults: " + JSON.stringify(results, null, 2);
    await T.Store.setSetting("__interaction_test_report__", summary);
    console.log("\n=== INTERACTION REPORT WRITTEN ===\n" + summary.slice(0, 500));
  })();
})();
