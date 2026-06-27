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

  // ─── runner ─────────────────────────────────────────────────
  (async function () {
    var results = [];
    try { results.push(await case_1()); }
    catch (e) { log("EXCEPTION case_1: " + (e && e.message || e) + "\n" + (e && e.stack || "")); results.push({ name: "case_1", pass: false, err: String(e) }); }

    var pass = results.filter(function (r) { return r.pass; }).length;
    var total = results.length;
    var summary = "INTERACTION TEST: " + pass + "/" + total + " PASS\n\n" + lines.join("\n") + "\n\nresults: " + JSON.stringify(results, null, 2);
    await T.Store.setSetting("__interaction_test_report__", summary);
    console.log("\n=== INTERACTION REPORT WRITTEN ===\n" + summary.slice(0, 500));
  })();
})();
