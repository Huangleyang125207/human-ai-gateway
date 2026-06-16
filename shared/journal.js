/* journal.js · gateway v0.5.1
 *
 * 1. day strip 拉所有 schedule 文件渲染,点 pill 切换日期
 * 2. entry body 默认 render markdown(table / h3 / bold / br),点击切换 raw edit
 * 3. entry title / commit 都是 contenteditable,blur 时合并写回 md
 * 4. 编辑期间 poll 暂停,blur 后立刻拉一次新数据
 */

(function () {
  const POLL_MS = 15000;
  let activeEditEl = null;
  let lastSig = null;
  let currentDate = null;     // YYYY-MM-DD, null = today
  let dayList = [];           // [{date, stem, file}]

  // ── public state ─────────────────────────────────────
  window.gateway = window.gateway || {};
  window.gateway.journal = {
    current: null,
    refresh: () => fetchJournal(currentDate),
    goto: (d) => { currentDate = d; fetchJournal(d); },
  };

  // ── markdown 渲染:走全局 gatewayMd (shared/md.js,marked + DOMPurify) ──
  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
    );
  }
  function mdToHtml(md) {
    return window.gatewayMd ? window.gatewayMd(md) : escapeHtml(md);
  }

  // ── fetch + render ───────────────────────────────────
  async function fetchDays() {
    try {
      const r = await fetch("/api/journal/days");
      const data = await r.json();
      dayList = data.days || [];
    } catch { dayList = []; }
  }

  async function fetchJournal(date) {
    try {
      const url = date ? `/api/journal/today?date=${encodeURIComponent(date)}` : "/api/journal/today";
      const r = await fetch(url);
      const data = await r.json();
      if (data.error) { renderError(data); return; }
      render(data);
    } catch (e) {
      renderError({ error: "server 未起 · " + e.message });
    }
  }

  function renderError(data) {
    const head = document.getElementById("head");
    const stream = document.getElementById("stream");
    const noJournalToday = /no journal file for/i.test(data.error || "");
    if (head) head.innerHTML = `<div class="ord">⋯ ${escapeHtml(data.error || "no journal")}</div>`;
    if (stream) {
      if (noJournalToday) {
        // fresh / 没今天 → 给个"立刻创建"按钮,而非旧的"起 server" 误导提示
        stream.innerHTML = `
          <div style="padding:64px 0; text-align:center; color:var(--ink-4); font:14px var(--sans);">
            <div style="margin-bottom:18px;">今天的日记还没创建</div>
            <button id="streamCreateToday" style="
              padding:10px 22px; border:1px solid var(--ink-4); background:transparent;
              color:var(--ink); font:13px var(--sans); letter-spacing:.06em;
              cursor:pointer; border-radius:2px;">
              新建今天 +
            </button>
          </div>`;
        document.getElementById("streamCreateToday")?.addEventListener("click", async () => {
          try {
            const r = await fetch("/api/journal/new-day", {
              method: "POST", headers: {"Content-Type":"application/json"},
              body: JSON.stringify({})
            });
            const d = await r.json();
            if (!d.ok) throw new Error(d.error || "create failed");
            // 刷 days + 切到今天
            await fetchDays();
            await fetchJournal(null);
          } catch (e) {
            window.gatewayToast?.("创建失败: " + e.message);
          }
        });
      } else {
        // 真起不来 server / 其他错才显示旧 hint
        stream.innerHTML = `
          <div style="padding:32px 0; color:var(--ink-4); font:13px var(--sans); letter-spacing:.04em;">
            server 没起来?重启 Gateway 再刷新本页。
          </div>`;
      }
    }
  }

  function render(data) {
    if (activeEditEl) return;

    const sig = data.file + "::" + data.blocks.length + "::" +
      data.blocks.map(b => b.time + "|" + (b.h2 || []).map(h =>
        (h.tags || []).join(",") + ":" + (h.title || "")
      ).join(";")).join("|") + "::" + data.date;
    if (sig === lastSig) return;
    lastSig = sig;
    currentDate = data.date;
    window.gateway.journal.current = data;

    renderDays(data);
    renderHead(data);
    renderStream(data);
    // 重渲完同步刷 scrapbook(切日 + 内容刷新都自动跟)
    window.gateway.scrapbook?.refresh(data.date);
    // 通知 care strip(水杯 + 补剂 tile)按这一天的真相重渲
    document.dispatchEvent(new CustomEvent("gateway:day-change", { detail: { date: data.date } }));
  }

  function renderDays(data) {
    const el = document.getElementById("days");
    if (!el) return;
    // ensure current date exists in list (defensive — days endpoint might be slow)
    const has = (d) => dayList.some(x => x.date === d);
    if (!has(data.date)) dayList.push({ date: data.date, stem: "", file: "" });
    dayList.sort((a, b) => a.date < b.date ? -1 : 1);
    el.innerHTML = dayList.map(d => {
      const cls = d.date === data.date ? "day-pill on" : "day-pill";
      return `<button class="${cls}" data-date="${d.date}">${d.date.slice(5).replace("-", ".")}</button>`;
    }).join("");
    [...el.querySelectorAll(".day-pill")].forEach(p => {
      p.addEventListener("click", () => {
        const d = p.dataset.date;
        if (d === currentDate) return;
        lastSig = null;          // force re-render of new day
        currentDate = d;
        fetchJournal(d);
      });
    });
    // 横向拖动 + 边缘渐变 + 自动滚到当前 day
    const updateFade = window.gateway?.dragScroll?.(el);
    requestAnimationFrame(() => {
      const cur = el.querySelector(".day-pill.on");
      if (cur && cur.scrollIntoView) {
        cur.scrollIntoView({ block: "nearest", inline: "center", behavior: "auto" });
      }
      updateFade?.();
    });
  }

  function renderHead(data) {
    const el = document.getElementById("head");
    if (!el) return;
    const d = new Date(data.date + "T00:00:00");
    const wd = "日一二三四五六"[d.getDay()];
    el.innerHTML = `
      <div class="ord">${data.date.replace(/-/g, " · ")} · 周${wd}</div>
      <h1 class="title">${data.blocks.length} 个时辰 · 共写一日</h1>
      <p class="kicker">md 是真相,本页是它的暖镜像。点时辰旁的数字 / tag = 指给 AI 看;长按杯子 / 药丸 = 拉它进来聊。</p>
    `;
  }

  function renderStream(data) {
    const stream = document.getElementById("stream");
    if (!stream) return;
    stream.innerHTML = "";

    for (const [i, b] of data.blocks.entries()) {
      // 空块(没 h2 entry)也渲染一个 placeholder,让用户能看见 + 点进去写
      // (没这个的话:右键插入新时间块 → md 写了但页面看不见)
      const entries = (b.h2 && b.h2.length)
        ? b.h2
        : [{ tags: [], title: "", body: "", commits: [], _empty: true }];
      // 同时间块多 H2 → 只在第一条 entry 显示时间标签,后续 entry 隐藏时间(数据层保留独立叙事)
      for (const [k, h] of entries.entries()) {
        const el = renderEntry(b, h, i);
        if (k > 0) el.classList.add("entry-no-time");
        stream.appendChild(el);
      }
    }

    const io = new IntersectionObserver((ents) => {
      ents.forEach(ent => {
        if (ent.isIntersecting) {
          const el = ent.target;
          el.style.transitionDelay = Math.min((+el.dataset.i || 0) * 0.04, 0.35) + "s";
          el.classList.add("in");
          io.unobserve(el);
        }
      });
    }, { rootMargin: "-40px 0px -8% 0px", threshold: 0.04 });
    [...stream.querySelectorAll(".entry")].forEach(el => io.observe(el));
  }

  function renderEntry(b, h, i) {
    const art = document.createElement("article");
    art.className = "entry";
    art.dataset.i = i;
    art.dataset.time = b.time;

    const isCollab = (h.commits || []).some(c => /claude|gpt|minimax|deepseek|ai|@ai/i.test(c));
    if (isCollab) art.classList.add("is-collab");

    // timestamp (display only — right-click 走 entry contextmenu)
    const timeEl = document.createElement("div");
    timeEl.className = "entry-time";
    timeEl.textContent = b.time;
    timeEl.title = "右键 → 插块 / 指给 AI";
    art.appendChild(timeEl);

    // right-click on entry → context menu
    art.addEventListener("contextmenu", (e) => {
      window.gateway.menu?.show(e, [
        { label: "✚ 加新条目 (tag + 时间)",
          action: () => showTagInsertModal() },
        { label: "💬 指给 AI 看这一段",
          action: () => {
            const label = `${b.time}${h.title ? " · " + h.title.slice(0, 14) : ""}`;
            // payload 第一行带日期 + 时间块,让 AI 直接定位 (date, anchor_time)
            const payload = `[${currentDate} ${b.time}] ${h.tags.map(t => "#" + t).join(" ")} ${h.title || ""}\n${h.body || ""}`;
            window.gateway.thread?.addRef({ kind: "entry", label, payload });
          } },
        { label: "🗑 删整个时间块",
          action: () => {
            const date = currentDate;                  // 锁定日期(撤回窗口内可能切天)
            art.style.display = "none";                 // 乐观隐藏
            gatewayUndo(`已清空 ${b.time}`, {
              onUndo: () => { art.style.display = ""; },
              onCommit: async () => {                   // 撤回窗口过后才真删
                try {
                  const r = await fetch("/api/journal/delete-block", {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ time: b.time, date }),
                  });
                  const data = await r.json();
                  if (data.error || data.detail) {
                    window.gateway.whisper?.("删除失败: " + (data.error || data.detail));
                    art.style.display = "";             // 失败复原
                    return;
                  }
                  lastSig = null;
                  if (currentDate === date) fetchJournal(date);
                } catch (err) {
                  window.gateway.whisper?.("删除失败: " + err.message);
                  art.style.display = "";
                }
              },
            });
          } },
      ]);
    });

    const col = document.createElement("div");

    // tags row — 总是渲染,每个 tag 可右键删,末尾有 + 加 tag 的 inline 编辑框
    const tagsEl = document.createElement("div");
    tagsEl.className = "entry-tags";
    for (const t of (h.tags || [])) {
      tagsEl.appendChild(makeTagSpan(t, b, h));
    }
    // 末尾"+ tag" inline 添加
    const addTag = document.createElement("span");
    addTag.className = "tag-add";
    addTag.contentEditable = "true";
    addTag.spellcheck = false;
    addTag.dataset.placeholder = "+ tag";
    addTag.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addTag.blur(); }
      if (e.key === "Escape") { addTag.textContent = ""; addTag.blur(); }
    });
    addTag.addEventListener("blur", async () => {
      const raw = (addTag.textContent || "").trim().replace(/^#+/, "");
      addTag.textContent = "";
      if (!raw) return;
      // 拆分支持一次输入多个: "工作 探索"
      const toks = raw.split(/[\s,，]+/).filter(Boolean).map(t => t.replace(/^#+/, ""));
      h.tags = [...(h.tags || []), ...toks];
      await saveBlock(b);
      window.gateway.journal?.refresh?.();
    });
    tagsEl.appendChild(addTag);
    col.appendChild(tagsEl);

    // title — contenteditable (空也渲染,带 placeholder)
    const tEl = document.createElement("h3");
    tEl.className = "entry-title";
    tEl.contentEditable = "true";
    tEl.spellcheck = false;
    tEl.textContent = h.title || "";
    tEl.dataset.original = h.title || "";
    if (!h.title) tEl.dataset.placeholder = "+ 标题(可空)";
    bindFieldEdit(tEl, b, h, "title");
    col.appendChild(tEl);

    // body — 空也渲染 placeholder stub,点击即可写
    if (h.body) {
      const bEl = document.createElement("div");
      bEl.className = "entry-text";
      bEl.dataset.raw = h.body;
      bEl.innerHTML = mdToHtml(h.body);
      bindBodyEdit(bEl, b, h);
      col.appendChild(bEl);
    } else {
      const bEl = document.createElement("div");
      bEl.className = "entry-text empty-body";
      bEl.dataset.raw = "";
      bEl.dataset.placeholder = "+ 加正文";
      bEl.textContent = "";
      bindBodyEdit(bEl, b, h);
      col.appendChild(bEl);
    }

    // commits — each row contenteditable
    if (h.commits && h.commits.length) {
      const cb = document.createElement("div");
      cb.className = "commits";
      h.commits.forEach((rawLine, ci) => {
        const cm = document.createElement("div");
        const stripped = rawLine.replace(/^-\s*/, "").trim();
        // 识别 AI 署名:claude/gpt/minimax/ai 关键词都判 AI
        const isUser = !/claude|gpt|minimax|deepseek|ai/i.test(stripped);
        cm.className = "commit " + (isUser ? "user" : "ai");

        const m = stripped.match(/#commit\s*[（(]\s*([^）)]+)\s*[）)]\s*[:：]?\s*(.*)/s);
        // 署名优先用原 commit 写的 author(保留 历史 claude-opus-4-7 等);未署名时显示 AI
        const author = m ? m[1].trim() : (isUser ? "我" : "AI");
        const text = m ? m[2].trim() : stripped;

        const auEl = document.createElement("span");
        auEl.className = "commit-au";
        auEl.textContent = author;
        cm.appendChild(auEl);

        const txEl = document.createElement("span");
        txEl.className = "commit-text";
        txEl.contentEditable = "true";
        txEl.spellcheck = false;
        txEl.textContent = text;
        txEl.dataset.original = text;
        txEl.dataset.author = author;
        txEl.dataset.idx = ci;
        bindCommitEdit(txEl, b, h, ci);
        cm.appendChild(txEl);

        cb.appendChild(cm);
      });
      col.appendChild(cb);
    }

    art.appendChild(col);
    return art;
  }

  // ── editing handlers ─────────────────────────────────
  function bindFieldEdit(el, b, h, which) {
    el.addEventListener("focus", () => { activeEditEl = el; });
    let saveT = null;
    el.addEventListener("input", () => {
      if (saveT) clearTimeout(saveT);
      saveT = setTimeout(async () => {
        saveT = null;
        const cur = el.textContent.trim();
        if (cur === el.dataset.original) return;
        if (which === "title") h.title = cur;
        else h.body = cur;
        el.dataset.original = cur;
        await saveBlock(b);
      }, 800);
    });
    el.addEventListener("blur", async () => {
      if (saveT) { clearTimeout(saveT); saveT = null; }
      activeEditEl = null;
      const next = el.textContent.trim();
      if (next === el.dataset.original) return;
      if (which === "title") h.title = next;
      else h.body = next;
      el.dataset.original = next;
      await saveBlock(b);
    });
  }

  function bindBodyEdit(el, b, h) {
    el.addEventListener("click", () => {
      if (el.classList.contains("editing")) return;
      el.classList.add("editing");
      el.contentEditable = "true";
      el.spellcheck = false;
      el.textContent = el.dataset.raw;   // switch to raw md
      requestAnimationFrame(() => el.focus({ preventScroll: true }));
    });
    el.addEventListener("focus", () => { activeEditEl = el; });
    // 边输边存(800ms debounce):防止用户输完不点别处 → blur 没触发 → 内容丢
    let saveT = null;
    el.addEventListener("input", () => {
      if (saveT) clearTimeout(saveT);
      saveT = setTimeout(async () => {
        saveT = null;
        const cur = el.textContent.trim();
        if (cur === el.dataset.raw) return;
        el.dataset.raw = cur;
        h.body = cur;
        await saveBlock(b);
      }, 800);
    });
    el.addEventListener("blur", async () => {
      if (saveT) { clearTimeout(saveT); saveT = null; }    // 抢在 debounce 前 flush
      activeEditEl = null;
      const next = el.textContent.trim();
      el.classList.remove("editing");
      el.contentEditable = "false";
      if (next !== el.dataset.raw) {
        el.dataset.raw = next;
        h.body = next;
        el.innerHTML = mdToHtml(next);
        await saveBlock(b);
      } else {
        el.innerHTML = mdToHtml(el.dataset.raw);
      }
      // 编辑过程中 textContent= 把 sb-wrap 子元素冲掉了 → 编辑结束重 inject
      window.gateway.scrapbook?.refresh?.();
    });
  }

  function bindCommitEdit(el, b, h, ci) {
    el.addEventListener("focus", () => { activeEditEl = el; });
    el.addEventListener("blur", async () => {
      activeEditEl = null;
      const next = el.textContent.trim();
      if (next === el.dataset.original) return;
      // 空内容 = 删这条 commit (按 ci 拆出来)
      if (!next) {
        h.commits.splice(ci, 1);
        await saveBlock(b);
        window.gateway.journal?.refresh?.();
        return;
      }
      // reconstruct raw line
      const author = el.dataset.author;
      h.commits[ci] = `- #commit（${author}）：${next}`;
      el.dataset.original = next;
      await saveBlock(b);
    });
  }

  // tag span 工厂 — click 走老逻辑(指给 AI),右键删/编辑
  function makeTagSpan(t, b, h) {
    const tg = document.createElement("span");
    tg.className = "tag" + (t.startsWith("协作") || t === "ai" ? " collab" : "");
    tg.textContent = "#" + t;
    tg.title = "click 指给 AI · 右键编辑/删";
    tg.addEventListener("click", () => {
      window.gateway.thread?.addRef({
        kind: "tag",
        label: "#" + t,
        payload: `tag #${t} on entry [${b.time}]: ${h.title || ""}\n${h.body || ""}`,
      });
      bumpYahaha(tg);
    });
    tg.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      window.gateway.menu?.show(e, [
        { label: "✎ 改 tag", action: async () => {
          const cur = await gatewayPrompt("改 tag (不带 #):", t);
          if (cur == null) return;
          const cleaned = cur.trim().replace(/^#+/, "");
          if (!cleaned || cleaned === t) return;
          const idx = (h.tags || []).indexOf(t);
          if (idx >= 0) {
            h.tags[idx] = cleaned;
            await saveBlock(b);
            window.gateway.journal?.refresh?.();
          }
        } },
        { label: "✕ 删 tag", action: async () => {
          h.tags = (h.tags || []).filter(x => x !== t);
          await saveBlock(b);
          window.gateway.journal?.refresh?.();
        } },
      ]);
    });
    return tg;
  }

  // ── save back to MD ──────────────────────────────────
  async function saveBlock(b) {
    const new_md = reconstructBlockMd(b);
    try {
      const r = await fetch("/api/journal/patch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time: b.time, new_md, date: currentDate }),
      });
      const result = await r.json();
      if (result.error) {
        window.gateway.whisper?.("没存上 — " + result.error);
      } else {
        window.gateway.whisper?.("✓ " + b.time + " 已存回 md", 2200);
      }
    } catch (e) {
      window.gateway.whisper?.("没存上 — " + e.message);
    }
  }

  function reconstructBlockMd(b) {
    const lines = [];
    for (const h of b.h2) {
      const tagStr = (h.tags || []).map(t => "#" + t).join(" ");
      const h2Line = "## " + (tagStr ? tagStr + " " : "") + (h.title || "");
      lines.push(h2Line.trim());
      lines.push("");
      if (h.body) lines.push(h.body);
      if (h.commits && h.commits.length) {
        lines.push("");
        for (const c of h.commits) lines.push(c);
      }
      lines.push("");
    }
    return lines.join("\n").trimEnd();
  }

  function bumpYahaha(srcEl) {
    if (!window.gateway?.korok?.yahaha) return;
    const r = srcEl.getBoundingClientRect();
    window.gateway.korok.yahaha(r.left + r.width / 2, r.top);
  }

  // 逐天补建:目标 = 你看的这天的紧邻后一天(cur+1),填 journal 断档;上限到今天,
  // 已存在就退而建今天。跟 paper 单日页同款规则(paper 先落于 6.15,classic 6.16 补齐)。
  // 例:停在 6.13、6.14 缺 → 补 6.14(不跳今天 6.16);到了 6.14 再补 6.15,逐天往前。
  function _addDay(iso, n) {
    const d = new Date(iso + "T12:00:00");
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function _newDayTarget() {
    const today = new Date().toISOString().slice(0, 10);
    const cur = currentDate || today;
    const has = (x) => dayList.some((d) => d.date === x);
    const next = _addDay(cur, 1);
    return (next <= today && !has(next)) ? next : today;
  }

  // ── new-day button: 逐天补建(默认就近补断档,不再写死今天)──
  function wireNewDay() {
    const btn = document.getElementById("newDayBtn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "…";
      try {
        const target = _newDayTarget();
        const r = await fetch("/api/journal/new-day", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ date: target }),
        });
        const data = await r.json();
        if (!data.ok) {
          gatewayAlert("生成失败: " + (data.error || data.stdout || "unknown"));
          return;
        }
        // 刷新 days 列表 + 跳到补建的那天
        await fetchDays();
        lastSig = null;
        currentDate = target;
        fetchJournal(target);
        if (data.created) bumpYahaha(btn);
      } catch (e) {
        gatewayAlert("server 不通: " + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = orig;
      }
    });
  }

  // ── 加新条目 modal: tag 必填 + 时间默认当前半小时 ────
  function showTagInsertModal() {
    // 默认当前半小时(向下 floor)
    const now = new Date();
    const defH = now.getHours();
    const defM = now.getMinutes() < 30 ? 0 : 30;

    const overlay = document.createElement("div");
    overlay.className = "mini-modal-overlay";
    overlay.innerHTML = `
      <div class="mini-modal mini-modal-wide">
        <div class="mini-modal-title">加新条目</div>
        <div class="mini-modal-tag-chips" id="mmChips" data-loading="1">⋯</div>
        <div class="mini-modal-row">
          <label>tag</label>
          <input class="mini-modal-input wide" id="mmTag" type="text" placeholder="工作 / 投资 / 探索⋯ (不带 #)" autofocus>
        </div>
        <div class="mini-modal-row">
          <label>标题</label>
          <input class="mini-modal-input wide" id="mmTitle" type="text" placeholder="可空">
        </div>
        <div class="mini-modal-row">
          <label>时间</label>
          <div class="mini-modal-time-row">
            <input class="mini-modal-input" id="mmHH" type="text" maxlength="2" inputmode="numeric" value="${defH.toString().padStart(2,'0')}">
            <span class="mini-modal-colon">：</span>
            <input class="mini-modal-input" id="mmMM" type="text" maxlength="2" inputmode="numeric" value="${defM.toString().padStart(2,'0')}">
            <span class="mini-modal-time-hint">默认当前半小时,可改</span>
          </div>
        </div>
        <div class="mini-modal-msg" id="mmMsg"></div>
        <div class="mini-modal-btns">
          <button class="mini-modal-btn" id="mmCancel">取消</button>
          <button class="mini-modal-btn primary" id="mmOk">加</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const tag = overlay.querySelector("#mmTag");
    const title = overlay.querySelector("#mmTitle");
    const hh = overlay.querySelector("#mmHH");
    const mm = overlay.querySelector("#mmMM");
    const msg = overlay.querySelector("#mmMsg");
    const okBtn = overlay.querySelector("#mmOk");
    const cancelBtn = overlay.querySelector("#mmCancel");
    const chips = overlay.querySelector("#mmChips");
    tag.focus();

    // tag chip 行: 异步拉常用 5 个,默认/历史标记不同色,点击填 tag input
    fetch("/api/journal/tag-stats?limit=5").then(r => r.json()).then(d => {
      chips.innerHTML = "";
      chips.removeAttribute("data-loading");
      const tags = d.tags || [];
      if (!tags.length) { chips.style.display = "none"; return; }
      const lbl = document.createElement("span");
      lbl.className = "mini-modal-chip-label";
      lbl.textContent = tags[0].default ? "建议:" : "常用:";
      chips.appendChild(lbl);
      for (const t of tags) {
        const c = document.createElement("button");
        c.type = "button";
        c.className = "mini-modal-chip" + (t.default ? " default" : "");
        c.textContent = "#" + t.tag;
        if (t.count) c.title = `用过 ${t.count} 次`;
        c.addEventListener("click", () => {
          tag.value = t.tag;
          title.focus();
        });
        chips.appendChild(c);
      }
    }).catch(() => { chips.style.display = "none"; });

    hh.addEventListener("input", () => { hh.value = hh.value.replace(/\D/g, ""); });
    mm.addEventListener("input", () => { mm.value = mm.value.replace(/\D/g, ""); });

    function close() { overlay.remove(); }
    function submit() {
      const t = tag.value.trim().replace(/^#+/, "");
      if (!t) {
        msg.textContent = "tag 必填";
        tag.focus();
        return;
      }
      const h = parseInt(hh.value, 10);
      const m = parseInt(mm.value, 10);
      if (isNaN(h) || isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59) {
        msg.textContent = "时间不合法 (0-23 : 0-59)";
        return;
      }
      okBtn.disabled = true;
      msg.textContent = "加中⋯";
      const date = window.gateway.journal?.current?.date;
      fetch("/api/journal/insert-block", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date,
          time: `${h}:${m.toString().padStart(2, "0")}`,
          tag: t,
          title: title.value.trim(),
        }),
      }).then(r => r.json()).then(data => {
        if (data.error) {
          msg.textContent = data.error;
          okBtn.disabled = false;
          return;
        }
        close();
        lastSig = null;
        fetchJournal(currentDate);
      }).catch(e => {
        msg.textContent = "失败: " + e.message;
        okBtn.disabled = false;
      });
    }

    okBtn.addEventListener("click", submit);
    cancelBtn.addEventListener("click", close);
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        // 焦点在 tag 时 Enter 跳到 title; 在 title/time 时直接提交
        if (document.activeElement === tag && tag.value.trim()) {
          title.focus();
          e.preventDefault();
          return;
        }
        submit();
      }
      if (e.key === "Escape") close();
    });
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
  }

  // ── daily task add modal (顶部补剂打卡式) ──────────────
  async function showTaskAddModal() {
    const text = await gatewayPrompt("加新每日任务 (写文本即可,不用带 - [ ] 前缀):");
    if (!text || !text.trim()) return;
    fetch("/api/template/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "add", text: text.trim() }),
    }).then(r => r.json()).then(data => {
      lastSig = null;
      fetchJournal(currentDate);
    }).catch(e => gatewayAlert("失败: " + e.message));
  }

  async function showTaskEditModal(oldText) {
    const text = await gatewayPrompt("改这一项:", oldText);
    if (text === null || text.trim() === oldText) return;
    fetch("/api/template/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "edit", old_text: oldText, text: text.trim() }),
    }).then(r => r.json()).then(() => {
      lastSig = null;
      fetchJournal(currentDate);
    });
  }

  function showTaskDelConfirm(oldText) {
    // 撤回式:不弹确认,5s 撤回窗口过后才真删(低频配置操作,defer-only,不乐观隐藏)
    gatewayUndo(`已删除任务项「${oldText}」`, {
      onCommit: () => {
        fetch("/api/template/task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "del", old_text: oldText }),
        }).then(r => r.json()).then(() => {
          lastSig = null;
          fetchJournal(currentDate);
        });
      },
    });
  }

  // ── page-level right-click: header/blank/care section ──
  function wirePageContextmenu() {
    document.addEventListener("contextmenu", (e) => {
      // skip if inside thread sidebar or inside an entry (entry has its own handler)
      if (e.target.closest(".thread") || e.target.closest(".entry")) return;
      // skip if inside daily-task item (own handler)
      if (e.target.closest("[data-daily-task]")) return;

      const todayISO = new Date().toISOString().slice(0, 10);
      const hasToday = dayList.some(d => d.date === todayISO);
      const tomorrowISO = (() => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        return d.toISOString().slice(0, 10);
      })();
      const hasTomorrow = dayList.some(d => d.date === tomorrowISO);

      window.gateway.menu?.show(e, [
        { label: "📅 创建今天", disabled: hasToday,
          action: () => triggerNewDay() },
        { label: "📅 创建明天", disabled: hasTomorrow,
          action: () => triggerNewDay(tomorrowISO) },
        { divider: true },
        { label: "✚ 加新条目 (tag + 时间)",
          action: () => showTagInsertModal() },
        { label: "➕ 加一项每日任务",
          action: () => showTaskAddModal() },
      ]);
    });
  }

  async function triggerNewDay(dateISO) {
    try {
      const r = await fetch("/api/journal/new-day", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dateISO ? { date: dateISO } : {}),
      });
      const data = await r.json();
      if (!data.ok) {
        gatewayAlert("生成失败: " + (data.error || data.stdout || "unknown"));
        return;
      }
      await fetchDays();
      const goto = dateISO || new Date().toISOString().slice(0, 10);
      lastSig = null;
      currentDate = goto;
      fetchJournal(goto);
    } catch (e) {
      gatewayAlert("server 不通: " + e.message);
    }
  }

  // expose for care-block (supplement items) to wire daily-task right-click
  window.gateway.journal = window.gateway.journal || {};
  Object.assign(window.gateway.journal, {
    showTaskAddModal, showTaskEditModal, showTaskDelConfirm, showTagInsertModal,
  });

  // ── boot ─────────────────────────────────────────────
  (async () => {
    wireNewDay();
    wirePageContextmenu();
    await fetchDays();
    // pick: today if its file exists, else the most recent day on disk
    const today = new Date().toISOString().slice(0, 10);
    const initial = dayList.find(d => d.date === today)?.date
                 ?? dayList[dayList.length - 1]?.date
                 ?? null;
    currentDate = initial;
    fetchJournal(initial);
    setInterval(() => fetchJournal(currentDate), POLL_MS);
  })();
})();
