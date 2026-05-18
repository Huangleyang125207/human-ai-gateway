/* ritual.js · gateway v0.6
 *
 * Care strip: 8 杯水 + N 颗 daily task (横排个人化照片) + 一块 hatch.
 * 点 cup → level meter, click 任意 cup 设到该水位
 * 点 task 照片 → toggle today done (灰度 ↔ 彩色,写回 md - [x])
 * 点空 task 加号 → 弹文件选择 → 上传 + 调百度抠图 → 落到 task
 * 长按 task → 大图 modal (今日 check + 历史 streak)
 * 点 hatch → addRef '想追个新东西' + 唤起 AI 对话
 *
 * 水位状态:localStorage(按日期 key)。
 * task check 状态:写到 md 顶部 - [x],服务端真相,避免双源不同步。
 */

(function () {
  const CUPS_TOTAL = 8;
  const WATER_TASK_NAME = "喝水";  // 跟 daily-tasks.md 一行 + meta(daily_dose=8) 绑定 — 真相进 md

  function todayKey() {
    const d = new Date();
    return `${d.getFullYear()}.${d.getMonth() + 1}.${d.getDate()}`;
  }
  const LS_PREFIX = "gateway.ritual.";

  function load() {
    try {
      const raw = localStorage.getItem(LS_PREFIX + todayKey());
      if (!raw) return null;
      return JSON.parse(raw);
    } catch { return null; }
  }
  function save(s) {
    try { localStorage.setItem(LS_PREFIX + todayKey(), JSON.stringify(s)); } catch {}
  }

  function defaultState() {
    return { cups: 0 };  // pills 不再用 localStorage,转走 md 真相
  }

  let _cupImageUrl = null;  // 用户上传水杯抠完的 PNG url(若有)
  let _viewDate = null;     // null = 今天;"YYYY-MM-DD" = 在看历史日(只读)
  let _viewIsToday = true;

  async function init() {
    const care = document.getElementById("care");
    if (!care) return;
    // 水杯图全局只拉一次(跨天不变)
    try {
      const imgR = await fetch("/api/water-cup").then(r => r.json());
      _cupImageUrl = imgR.image_url || null;
    } catch {}
    // 默认渲今天 + 监听切日
    await loadDay(null);
    document.addEventListener("gateway:day-change", (e) => {
      loadDay(e.detail?.date || null);
    });
  }

  async function loadDay(dateISO) {
    const care = document.getElementById("care");
    if (!care) return;
    _viewDate = dateISO;
    const qs = dateISO ? `?date=${encodeURIComponent(dateISO)}` : "";
    let tasksR = { tasks: [], is_today: true };
    try {
      tasksR = await fetch("/api/daily-tasks" + qs).then(r => r.json());
    } catch (e) {
      console.warn("[ritual] /api/daily-tasks failed:", e);
    }
    _viewIsToday = tasksR.is_today !== false;
    const wt = (tasksR.tasks || []).find(t => t.name === WATER_TASK_NAME);
    let intakeFromMd = wt ? Math.max(0, Math.min(CUPS_TOTAL, wt.today_intake || 0)) : 0;

    // LS → server 一次性迁移,只在今天做
    if (_viewIsToday && wt) {
      const ls = load();
      if (ls && ls.cups > intakeFromMd) {
        try {
          const r = await fetch("/api/daily-tasks/check", {
            method: "POST", headers: {"Content-Type":"application/json"},
            body: JSON.stringify({task_name: WATER_TASK_NAME, intake: Math.min(CUPS_TOTAL, ls.cups), daily_dose: CUPS_TOTAL}),
          });
          const d = await r.json();
          intakeFromMd = Math.max(intakeFromMd, d.today_intake || ls.cups);
        } catch {}
      }
      try { localStorage.removeItem(LS_PREFIX + todayKey()); } catch {}
    }

    care.classList.toggle("care-readonly", !_viewIsToday);
    const state = { cups: intakeFromMd, readonly: !_viewIsToday };
    render(care, state);
    renderTasksFromData(tasksR.tasks || [], !_viewIsToday);
  }

  function render(care, state) {
    const cupsHtml = Array.from({ length: CUPS_TOTAL }, (_, k) => {
      const filled = k < state.cups ? " filled" : "";
      if (_cupImageUrl) {
        return `<div class="cup with-image${filled}" data-k="${k}"><img src="${_cupImageUrl}" alt=""></div>`;
      }
      return `<div class="cup${filled}" data-k="${k}"><div class="cup-fill"></div></div>`;
    }).join("");

    care.innerHTML = `
      <div class="care-block" data-block="water">
        <div class="care-label">water</div>
        <div class="cups">${cupsHtml}</div>
        <div class="care-count"><b id="cups-count">${state.cups}</b> / ${CUPS_TOTAL} 杯</div>
      </div>
      <div class="care-block care-block-tasks" data-block="tasks">
        <div class="care-label">daily tasks</div>
        <div class="daily-tasks" id="dailyTasks">
          <div class="daily-tasks-loading">⋯</div>
        </div>
        <div class="care-count"><b id="tasks-count">0</b> / 0 项</div>
      </div>
      <div class="care-hatch" id="careHatch" title="想追个新东西"></div>
    `;

    // cup click → 注水 (silent, no thread popup)
    // long-press 600ms → 指着今日水量跟 AI 说话
    // 历史日:cup 只读,click 弹 toast,但 long-press 还能 "指给 AI" 看那天的水量
    [...care.querySelectorAll(".cup")].forEach((cup) => {
      let pressT = null;
      cup.addEventListener("pointerdown", () => {
        pressT = setTimeout(() => {
          pressT = null;
          const label = state.readonly
            ? `${_viewDate} 水量 ${state.cups}/${CUPS_TOTAL}`
            : `今日水量 ${state.cups}/${CUPS_TOTAL}`;
          const payload = state.readonly
            ? `${_viewDate} 喝水: ${state.cups} / ${CUPS_TOTAL} 杯`
            : `今天喝水: ${state.cups} / ${CUPS_TOTAL} 杯`;
          window.gateway.thread?.addRef({ kind: "ritual", label, payload });
        }, 600);
      });
      const cancelPress = () => { if (pressT) { clearTimeout(pressT); pressT = null; } };
      cup.addEventListener("pointermove", cancelPress);
      cup.addEventListener("pointerleave", cancelPress);
      cup.addEventListener("pointerup", () => {
        if (!pressT) return;          // long-press 已经触发
        clearTimeout(pressT); pressT = null;
        if (state.readonly) {
          window.gatewayToast?.("回到今天才能打卡");
          return;
        }
        // level-meter:click cup #k 把 state.cups 设到 k+1 (上调) 或 k (降到该级以下,把刚点的也清空)
        const k = +cup.dataset.k;
        const prev = state.cups;
        const next = (k + 1 > prev) ? (k + 1) : k;
        if (next === prev) return;     // no-op
        state.cups = next;
        // 重渲染 cup 填充态
        [...care.querySelectorAll(".cup")].forEach((c, i) => {
          c.classList.toggle("filled", i < next);
        });
        // 涨上去那一级 just-filled 动画
        if (next > prev) {
          const top = care.querySelector(`.cup[data-k="${next - 1}"]`);
          if (top) {
            top.classList.add("just-filled");
            setTimeout(() => top.classList.remove("just-filled"), 1300);
          }
        }
        document.getElementById("cups-count").textContent = state.cups;
        // 写真相到 md(via daily-task intake_log);失败不影响 UI,下次 reload 时 re-sync
        // daily_dose=CUPS_TOTAL 是首次 init 用 — server 仅当 meta 没设过 dose 时采纳,
        // 老用户已有 daily_dose=8 不受影响。
        fetch("/api/daily-tasks/check", {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({task_name: WATER_TASK_NAME, intake: next, daily_dose: CUPS_TOTAL}),
        }).catch(() => {});
        if (next > prev) {
          window.gateway.korok?.yahaha?.(...rectCenter(cup));
          window.gateway.korok?.tick?.("water");
        }
      });

      // 右键 cup → 换水杯图(配合 5.14 加的"重新上传"功能)
      cup.addEventListener("contextmenu", (e) => {
        window.gateway.menu?.show(e, [
          { label: "🔄 更换水杯图片", action: () => uploadForCup() },
          { label: "💬 指给 AI 看今日水量", action: () => {
            window.gateway.thread?.addRef({
              kind: "ritual",
              label: `今日水量 ${state.cups}/${CUPS_TOTAL}`,
              payload: `今天喝水: ${state.cups} / ${CUPS_TOTAL} 杯`,
            });
          }},
        ]);
      });
    });
    // wire 5s dock-max for cups
    wireDockMax([...care.querySelectorAll(".cup")]);

    // ── daily-tasks 横排 strip(异步拉数据后填) ────────
    // 详细 wiring 在 refreshTasks() / wireTask() 里
    // (这里留空,等异步)

    // hatch (the korok "+" — air at end of pills row)
    const hatch = document.getElementById("careHatch");
    if (hatch) {
      hatch.addEventListener("click", () => {
        window.gateway.thread?.addRef({
          kind: "想追个",
          label: "新追踪 · ?",
          payload: "用户想加一个新的日常追踪 widget。可能是: 咖啡 / 阅读页数 / 步数 / 心情 / 冥想 / 创业指标 / 客户对话频度 / ... 你应该问她想追什么，然后用 add_widget 工具给她做一个，挂在 sidebar slot。",
        });
        window.gateway.thread?.open();
        // prefilled hint
        const input = document.getElementById("threadInput");
        if (input && !input.value) {
          input.value = "帮我追个 ";
          input.focus();
          // place cursor at end
          const r = document.createRange();
          r.selectNodeContents(input);
          r.collapse(false);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(r);
        }
      });
    }
  }

  function rectCenter(el) {
    const r = el.getBoundingClientRect();
    return [r.left + r.width / 2, r.top + r.height / 2];
  }

  // ── 5 秒长悬停 → 加 .dock-max(配 CSS 单图最大化) ──
  // 适用 .cup / .task。鼠标离开 / 移到子元素外清 timer。
  const DOCK_MAX_DELAY = 5000;
  function wireDockMax(elements) {
    elements.forEach(el => {
      let timer = null;
      const start = () => {
        if (timer) return;
        timer = setTimeout(() => {
          el.classList.add("dock-max");
          timer = null;
        }, DOCK_MAX_DELAY);
      };
      const cancel = () => {
        if (timer) { clearTimeout(timer); timer = null; }
        el.classList.remove("dock-max");
      };
      el.addEventListener("mouseenter", start);
      el.addEventListener("mouseleave", cancel);
    });
  }

  // ── daily-tasks 横排 strip ───────────────────────────
  // refreshTasks 拉今天数据后渲染(老调用方:点击 / 上传抠图后刷新)
  async function refreshTasks() {
    // 不打扰 _viewDate;只刷今天那份数据,但若当前在历史日则保持 readonly
    const qs = _viewDate ? `?date=${encodeURIComponent(_viewDate)}` : "";
    try {
      const r = await fetch("/api/daily-tasks" + qs);
      const data = await r.json();
      renderTasksFromData(data.tasks || [], data.is_today === false);
    } catch (e) {
      const container = document.getElementById("dailyTasks");
      if (container) container.innerHTML = `<div class="daily-tasks-empty">load failed: ${e.message}</div>`;
    }
  }

  function renderTasksFromData(tasks, readonly) {
    const container = document.getElementById("dailyTasks");
    const counter = document.getElementById("tasks-count");
    if (!container) return;
    // 「喝水」在水杯 grid 单独显示,不重复在补剂 tile 行
    tasks = (tasks || []).filter(t => t.name !== WATER_TASK_NAME);
    if (!tasks.length) {
      container.innerHTML = `<div class="daily-tasks-empty">没有 daily task — 右键页面空白 → 「加一项每日任务」</div>`;
      if (counter) counter.parentElement.innerHTML = `<b id="tasks-count">0</b> / 0 项`;
      return;
    }
    container.innerHTML = "";
    const rowSizes = splitRows(tasks.length, 4);
    let idx = 0;
    for (const size of rowSizes) {
      const row = document.createElement("div");
      row.className = "tasks-row";
      for (let i = 0; i < size; i++) {
        row.appendChild(taskNode(tasks[idx++], readonly));
      }
      container.appendChild(row);
    }
    if (counter) {
      const done = tasks.filter(t => t.checked).length;
      counter.parentElement.innerHTML = `<b id="tasks-count">${done}</b> / ${tasks.length} 项`;
    }
    wireDockMax([...container.querySelectorAll(".task")]);
  }

  function splitRows(n, max) {
    const rows = [];
    let r = n;
    while (r > 0) { const t = Math.min(max, r); rows.push(t); r -= t; }
    if (rows.length >= 2 && rows[rows.length - 1] === 1 && rows[rows.length - 2] === max) {
      rows[rows.length - 2] -= 1;
      rows[rows.length - 1] += 1;
    }
    return rows;
  }

  function taskNode(t, readonly) {
    const el = document.createElement("article");
    const dose = Math.max(1, t.daily_dose || 1);
    // 兼容:md 已 [x] 但 meta 没 intake 记录 → 按满计(老数据迁移)
    const rawIntake = (t.checked && !t.today_intake) ? dose : (t.today_intake || 0);
    const intake = Math.max(0, Math.min(dose, rawIntake));
    const fullyOn = intake >= dose;
    el.className = "task" + (fullyOn ? " on" : "") + (intake > 0 && !fullyOn ? " partial" : "")
                 + (t.image_url ? "" : " no-image")
                 + (readonly ? " readonly" : "");
    el.dataset.name = t.name;

    const photo = document.createElement("button");
    photo.className = "task-photo";
    photo.type = "button";
    if (t.image_url) {
      // 双层:base 始终灰,fill 用 intake/dose 比例从底部填彩色
      const base = document.createElement("img");
      base.src = t.image_url; base.alt = t.name;
      base.className = "task-photo-base";
      photo.appendChild(base);

      const fillWrap = document.createElement("div");
      fillWrap.className = "task-photo-fill";
      fillWrap.style.setProperty("--intake-frac", String(intake / dose));
      const fillImg = document.createElement("img");
      fillImg.src = t.image_url; fillImg.alt = "";
      fillWrap.appendChild(fillImg);
      photo.appendChild(fillWrap);

      // 分段刻度线(N-1 根横线,在 1/N、2/N…(N-1)/N 高度处)
      if (dose > 1) {
        const segs = document.createElement("div");
        segs.className = "task-photo-segs";
        for (let k = 1; k < dose; k++) {
          const div = document.createElement("div");
          div.className = "seg-divider";
          div.style.bottom = `${(k / dose) * 100}%`;
          segs.appendChild(div);
        }
        photo.appendChild(segs);
      }

      // 库存余量徽标
      if (typeof t.remaining === "number") {
        const badge = document.createElement("span");
        const urgent = t.remaining <= Math.max(3, dose * 3);  // 3 天内的量
        badge.className = "task-remaining-badge" + (urgent ? " urgent" : "");
        badge.textContent = `余${t.remaining}`;
        photo.appendChild(badge);
      }
    } else {
      photo.innerHTML = `<span class="task-add">+</span><span class="task-add-hint">加图</span>`;
    }
    el.appendChild(photo);

    const name = document.createElement("div");
    name.className = "task-name";
    name.textContent = t.name;
    el.appendChild(name);

    // tap 用 click 事件(浏览器自带 down+up 同元素 + jitter 容忍);
    // pointer 只用来检测 600ms 长按。
    // 之前用 pointerup 走 cup 同款代码,但 task 大(138×192,dock-max 2.6× 后 360×500),
    // 鼠标小幅 jitter → pointermove → cancelPress → 整个 click 被吞 = "点了不响应"。
    let pressT = null;
    let longPressFired = false;
    photo.addEventListener("pointerdown", () => {
      longPressFired = false;
      pressT = setTimeout(() => {
        longPressFired = true;
        pressT = null;
        openTaskModal(t);
      }, 600);
    });
    const clearLP = () => { if (pressT) { clearTimeout(pressT); pressT = null; } };
    photo.addEventListener("pointerup", clearLP);
    photo.addEventListener("pointerleave", clearLP);
    photo.addEventListener("pointercancel", clearLP);
    photo.addEventListener("click", (e) => {
      if (longPressFired) { longPressFired = false; return; }   // 长按已开 modal,跳过 click
      if (readonly) {
        window.gatewayToast?.("回到今天才能打卡");
        return;
      }
      if (!t.image_url) return uploadForTask(t.name);

      const curDose = Math.max(1, t.daily_dose || 1);
      const prev = Math.max(0, Math.min(curDose, t.today_intake || 0));
      // 算 click 落在第几档(底→顶,0-indexed)
      const rect = photo.getBoundingClientRect();
      const yFromBottom = rect.bottom - e.clientY;
      const k = Math.max(0, Math.min(curDose - 1,
        Math.floor((yFromBottom / rect.height) * curDose)));
      // cup 同款:next = (k+1 > prev) ? (k+1) : k
      const next = (k + 1 > prev) ? (k + 1) : k;
      if (next === prev) return;

      // 同步落地视觉 + state(跟 cup 字字对仗)
      t.today_intake = next;
      t.checked = next >= curDose;
      const fillWrap = photo.querySelector(".task-photo-fill");
      if (fillWrap) fillWrap.style.setProperty("--intake-frac", String(next / curDose));
      el.classList.toggle("on", t.checked);
      el.classList.toggle("partial", next > 0 && !t.checked);
      if (next > prev) {
        window.gateway.korok?.yahaha?.(...rectCenter(photo));
        window.gateway.korok?.tick?.("supplement");
      }
      const counter = document.getElementById("tasks-count");
      if (counter) {
        const all = [...document.querySelectorAll(".task")];
        counter.textContent = all.filter(x => x.classList.contains("on")).length;
      }

      // 后台 save,不挡视觉
      fetch("/api/daily-tasks/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_name: t.name, intake: next }),
      }).then(r => r.json()).then(data => {
        t.remaining = data.remaining;
        const badge = photo.querySelector(".task-remaining-badge");
        if (badge && typeof data.remaining === "number") {
          badge.textContent = `余${data.remaining}`;
          badge.classList.toggle("urgent", data.remaining <= Math.max(3, (data.daily_dose || curDose) * 3));
        }
      }).catch(e => {
        window.gatewayToast?.("打卡保存失败: " + e.message);
      });
    });

    return el;
  }

  // 水杯换图(右键 cup 触发)
  function uploadForCup() {
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.style.display = "none";
    document.body.appendChild(fileInput);
    fileInput.addEventListener("change", async () => {
      const f = fileInput.files?.[0];
      fileInput.remove();
      if (!f) return;
      window.gatewayToast?.("上传中⋯");
      try {
        const fd = new FormData();
        fd.append("file", f);
        const upR = await fetch("/api/chat/upload-image", { method: "POST", body: fd });
        const up = await upR.json();
        if (!up.url) throw new Error(up.detail || "upload failed");
        window.gatewayToast?.("抠图中⋯ (1-3 秒)");
        const cutR = await fetch("/api/water-cup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attachment_url: up.url }),
        });
        const cut = await cutR.json();
        if (!cut.ok) throw new Error(cut.detail || "cutout failed");
        window.gatewayToast?.("✓ 水杯图已更新,刷一下页面");
        // 重新拉新图刷渲染(可选,刷新页也行)
        _cupImageUrl = cut.image_url + "?t=" + Date.now();  // bust img 缓存
        const care = document.getElementById("care");
        const state = load() || defaultState();
        if (care) render(care, state);
      } catch (e) {
        window.gatewayToast?.("失败: " + e.message);
      }
    });
    fileInput.click();
  }

  function uploadForTask(taskName) {
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.style.display = "none";
    document.body.appendChild(fileInput);
    fileInput.addEventListener("change", async () => {
      const f = fileInput.files?.[0];
      fileInput.remove();
      if (!f) return;
      window.gatewayToast?.("上传中⋯");
      try {
        const fd = new FormData();
        fd.append("file", f);
        const upR = await fetch("/api/chat/upload-image", { method: "POST", body: fd });
        const up = await upR.json();
        if (!up.url) throw new Error(up.detail || "upload failed");
        window.gatewayToast?.("抠图中⋯ (1-3 秒)");
        const cutR = await fetch("/api/cutout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attachment_url: up.url, task_name: taskName }),
        });
        const cut = await cutR.json();
        if (!cut.ok) throw new Error(cut.detail || "cutout failed");
        if (cut.ocr_pill_count) {
          window.gatewayToast?.(`✓ 已落 ${taskName} · OCR 识别 ${cut.ocr_pill_count} 颗`);
        } else {
          window.gatewayToast?.("✓ 已落 " + taskName + " · 未识别到颗数,弹卡片让你确认");
          // 走 AI thread:发交互卡片让用户确认/输入颗数
          window.gateway.thread?.addRef?.({
            kind: "task-pillcount",
            label: `📦 ${taskName} · 待填颗数`,
            payload: `刚上传了「${taskName}」的图,但 OCR 没识别到瓶装颗数(常见原因: 字太花/被反光遮挡/在瓶底没拍到)。\n\n请问用户这瓶大概多少颗,然后调 \`set_daily_task_meta\` 工具(task_name="${taskName}", total_pills=数字)写入。也可以让用户在卡片上直接点 + 来手填。`,
          });
          window.gateway.thread?.open?.();
          const input = document.getElementById("threadInput");
          if (input && !input.value) {
            input.textContent = `「${taskName}」一瓶多少颗?(OCR 没识别到,我帮你登记下)`;
            input.focus();
          }
        }
        refreshTasks();
      } catch (e) {
        window.gatewayToast?.("失败: " + e.message);
      }
    });
    fileInput.click();
  }

  async function openTaskModal(t) {
    const overlay = document.createElement("div");
    overlay.className = "task-modal-overlay";
    const dose = Math.max(1, t.daily_dose || 1);
    const rawIntake = (t.checked && !t.today_intake) ? dose : (t.today_intake || 0);
    const intake = Math.max(0, Math.min(dose, rawIntake));
    const fullyOn = intake >= dose;
    const totalVal = (t.total_pills == null) ? "" : String(t.total_pills);
    const remainingTxt = (typeof t.remaining === "number") ? `${t.remaining} 颗` : "—";
    overlay.innerHTML = `
      <div class="task-modal">
        <header class="task-modal-head">
          <span class="task-modal-name">${escapeHtml(t.name)}</span>
          <button class="task-modal-close" aria-label="close">×</button>
        </header>
        <div class="task-modal-scroll">
        <div class="task-modal-photo${fullyOn ? ' on' : ''}">
          ${t.image_url ? `<img src="${t.image_url}" alt="">` : `<div class="task-modal-noimg">还没设图</div>`}
        </div>

        <div class="task-meta-grid">
          <label class="task-meta-row">
            <span class="task-meta-label">每日剂量</span>
            <span class="task-meta-stepper">
              <button type="button" data-act="dose-minus">−</button>
              <input type="number" min="1" max="20" id="tmDose" value="${dose}">
              <button type="button" data-act="dose-plus">+</button>
              <span class="task-meta-unit">颗</span>
            </span>
          </label>
          <label class="task-meta-row">
            <span class="task-meta-label">今日已吃</span>
            <span class="task-meta-stepper">
              <button type="button" data-act="intake-minus">−</button>
              <input type="number" min="0" id="tmIntake" value="${intake}">
              <button type="button" data-act="intake-plus">+</button>
              <span class="task-meta-unit">/ <b id="tmDoseEcho">${dose}</b> 颗</span>
            </span>
          </label>
          <label class="task-meta-row">
            <span class="task-meta-label">瓶装总颗数</span>
            <span class="task-meta-stepper">
              <input type="number" min="1" max="9999" id="tmTotal" placeholder="OCR 自动 / 手填" value="${totalVal}">
              <span class="task-meta-unit">颗 · 余 <b id="tmRemaining">${remainingTxt}</b></span>
            </span>
          </label>
        </div>

        <div class="task-modal-actions">
          <button class="task-modal-change-img">${t.image_url ? '🔄 更换图片' : '+ 上传抠图'}</button>
        </div>
        <div class="task-modal-history">
          <div class="task-modal-history-label">最近 14 天</div>
          <div class="task-modal-history-grid" id="taskModalHistGrid">⋯</div>
        </div>
        <div class="task-modal-danger">
          <button class="task-modal-delete">🗑 删除该补剂</button>
        </div>
        </div><!-- /.task-modal-scroll -->
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector(".task-modal-close").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", function onEsc(e) {
      if (e.key === "Escape") { close(); document.removeEventListener("keydown", onEsc); }
    });

    const $dose = overlay.querySelector("#tmDose");
    const $intake = overlay.querySelector("#tmIntake");
    const $total = overlay.querySelector("#tmTotal");
    const $doseEcho = overlay.querySelector("#tmDoseEcho");
    const $remaining = overlay.querySelector("#tmRemaining");

    async function pushIntake(val) {
      const v = Math.max(0, Math.min(parseInt($dose.value || "1", 10), parseInt(val, 10) || 0));
      $intake.value = v;
      try {
        const r = await fetch("/api/daily-tasks/check", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_name: t.name, intake: v }),
        });
        const d = await r.json();
        $remaining.textContent = (typeof d.remaining === "number") ? `${d.remaining} 颗` : "—";
        refreshTasks();
      } catch (e) { window.gatewayToast?.("更新失败: " + e.message); }
    }
    async function pushMeta(field, val) {
      const body = { task_name: t.name };
      body[field] = val;
      try {
        const r = await fetch("/api/daily-tasks/meta", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const d = await r.json();
        $remaining.textContent = (typeof d.remaining === "number") ? `${d.remaining} 颗` : "—";
        $doseEcho.textContent = String(d.daily_dose);
        // dose 改了:intake 上限会变,前端先 clamp
        if (field === "daily_dose") {
          const cur = parseInt($intake.value || "0", 10);
          if (cur > d.daily_dose) $intake.value = d.daily_dose;
        }
        refreshTasks();
      } catch (e) { window.gatewayToast?.("更新失败: " + e.message); }
    }

    overlay.querySelector('[data-act="dose-minus"]').addEventListener("click", () => {
      const v = Math.max(1, parseInt($dose.value || "1", 10) - 1);
      $dose.value = v; pushMeta("daily_dose", v);
    });
    overlay.querySelector('[data-act="dose-plus"]').addEventListener("click", () => {
      const v = Math.min(20, parseInt($dose.value || "1", 10) + 1);
      $dose.value = v; pushMeta("daily_dose", v);
    });
    $dose.addEventListener("change", () => pushMeta("daily_dose", parseInt($dose.value || "1", 10)));

    overlay.querySelector('[data-act="intake-minus"]').addEventListener("click", () => {
      pushIntake(parseInt($intake.value || "0", 10) - 1);
    });
    overlay.querySelector('[data-act="intake-plus"]').addEventListener("click", () => {
      pushIntake(parseInt($intake.value || "0", 10) + 1);
    });
    $intake.addEventListener("change", () => pushIntake(parseInt($intake.value || "0", 10)));

    $total.addEventListener("change", () => {
      const v = parseInt($total.value || "", 10);
      pushMeta("total_pills", isNaN(v) ? null : v);
    });

    overlay.querySelector(".task-modal-change-img")?.addEventListener("click", () => {
      close();
      uploadForTask(t.name);
    });

    overlay.querySelector(".task-modal-delete")?.addEventListener("click", async () => {
      if (!confirm(`确定要删除「${t.name}」吗?\n会同时删掉打卡条目、图片和库存数据。`)) return;
      try {
        const r = await fetch("/api/daily-tasks/delete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_name: t.name }),
        });
        const d = await r.json();
        if (!d.ok) throw new Error(d.detail || "delete failed");
        window.gatewayToast?.("✓ 已删除 " + t.name);
        close();
        refreshTasks();
      } catch (e) { window.gatewayToast?.("删除失败: " + e.message); }
    });

    // history fetch
    try {
      const r = await fetch(`/api/daily-tasks/history?name=${encodeURIComponent(t.name)}&days=14`);
      const data = await r.json();
      const grid = overlay.querySelector("#taskModalHistGrid");
      grid.innerHTML = (data.days || []).map(d => {
        const cls = d.checked === true ? "on" : (d.checked === false ? "off" : "void");
        const label = d.date.slice(5);
        return `<div class="hist-cell hist-${cls}" title="${d.date}">${label}</div>`;
      }).join("");
    } catch (e) {
      overlay.querySelector("#taskModalHistGrid").textContent = "history load failed";
    }
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
  }

  // expose for journal contextmenu / 其他模块手动触发
  window.gateway = window.gateway || {};
  window.gateway.ritual = { refreshTasks };

  // wait for thread.js to set up window.gateway, then init
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
