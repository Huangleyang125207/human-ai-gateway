/* thread.js · gateway v0.5
 *
 * 永久 chat thread + @引用系统。
 * 任何外部代码（journal.js / ritual.js / korok.js）调
 *   window.gateway.thread.addRef({kind, label, payload})
 * 把一个 ref 加进 pending area。
 * 用户输入 message + ⏎ 发送 → /api/chat with history + refs as context。
 * AI 回复落进 thread 持续累积。
 *
 * 也暴露 window.gateway.whisper(text) ——AI 偶尔说一句话，不需要打开 thread。
 */

(function () {
  const THREAD_KEY = "gateway.thread.history.v1";
  const MTIME_KEY = "gateway.thread.synced_mtime.v1";  // 本地缓存所基于的 server mtime
  const MODEL_KEY = "gateway.thread.model_id.v1";
  const MAX_HISTORY = 100;      // 发给 server 的总条数;server 取最近 20 原文,更早的做摘要
  const PERSIST_LIMIT = 200;    // localStorage 最多存 N 条

  // 本地日期 YYYY-MM-DD,从不为 null。fallback for view_date,跨过午夜也始终是真今天
  function todayLocalISO() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  }
  // 每条消息的时间戳 — 给 history_exporter 用作 commit↔chat 时间窗 join 的锚
  function nowISO() {
    return new Date().toISOString();
  }
  // 跨午夜检测 — 页面不刷新一直开着的情况,view_date 别卡昨天
  let _lastSeenDate = todayLocalISO();
  setInterval(() => {
    const t = todayLocalISO();
    if (t !== _lastSeenDate) {
      _lastSeenDate = t;
      // 触发 journal refresh — 哪种回调存在用哪种,都不在也不抛
      try { window.gateway?.journal?.refresh?.(); } catch {}
      try { window.gateway?.journal?.loadToday?.(); } catch {}
    }
  }, 60_000);

  // ── state ────────────────────────────────────────────
  const state = {
    history: loadHistory(),   // [{role: 'user'|'assistant', content, refs?: [...]}]
    pending: [],              // [{kind, label, payload}]
    open: false,
    apiOk: null,
  };
  // server-side mtime — 本地缓存所基于的 server 状态版本。判同步靠它(recency),不靠条数。
  // 从 localStorage 恢复:重开标签页时知道自己缓存的是哪个 server 版本,避免旧缓存盖新历史。
  let lastServerMtime = (function () {
    try { return Number(localStorage.getItem(MTIME_KEY)) || 0; } catch { return 0; }
  })();
  function _persistMtime() {
    try { localStorage.setItem(MTIME_KEY, String(lastServerMtime)); } catch {}
  }
  function _persistLocal() {
    try { localStorage.setItem(THREAD_KEY, JSON.stringify(state.history.slice(-PERSIST_LIMIT))); } catch {}
    _persistMtime();
  }
  function _rerender() {
    if (typeof stream !== "undefined" && stream) {
      stream.innerHTML = "";
      for (const m of state.history) appendMsg(m);
    }
  }

  function loadHistory() {
    try {
      const raw = localStorage.getItem(THREAD_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.slice(-PERSIST_LIMIT) : [];
    } catch { return []; }
  }
  function saveHistory() {
    // 1. localStorage(离线缓存 + 同源跨 tab storage event)
    try {
      localStorage.setItem(
        THREAD_KEY,
        JSON.stringify(state.history.slice(-PERSIST_LIMIT))
      );
    } catch {}
    // 2. server(跨浏览器 / 跨设备真相源)
    //    带 base_mtime 做 CAS:server 若发现期间有人写过(mtime 变了)→ 409,
    //    说明本 tab 的 state 陈旧,绝不能覆盖 → 改为拉取 server 最新(防 5.26 那种事故)
    fetch("/api/thread/save", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ history: state.history.slice(-PERSIST_LIMIT), base_mtime: lastServerMtime }),
    }).then(async r => {
      if (r.status === 409) {
        console.warn("[thread] save 冲突(base_mtime 陈旧)— server 有更新状态,放弃覆盖,改拉 server");
        await forceReloadFromServer();
        return;
      }
      const d = await r.json();
      if (d && d.mtime) { lastServerMtime = d.mtime; _persistMtime(); }
    }).catch(() => {});  // 离线 / server down 都不阻塞
  }

  async function forceReloadFromServer() {
    // 冲突后无条件采纳 server(它 mtime 更新 = 更 canonical)。
    // 本 tab 的内容仍留在 localStorage 兜底,不会凭空消失。
    try {
      const r = await fetch("/api/thread/history");
      const d = await r.json();
      const hist = Array.isArray(d.history) ? d.history : [];
      state.history = hist.slice(-PERSIST_LIMIT);
      lastServerMtime = d.mtime || 0;
      _persistLocal();
      _rerender();
    } catch {}
  }

  async function syncFromServer() {
    // 轮询:server mtime > 本地基线 → server 更新了 → 采纳。
    // 不再用条数判断(条数多≠更新;陈旧标签页条数可能更多但内容旧 — 5.26 事故根因)。
    try {
      const r = await fetch("/api/thread/history");
      const d = await r.json();
      const mtime = d.mtime || 0;
      if (mtime <= lastServerMtime) return false;  // server 没更新
      const hist = Array.isArray(d.history) ? d.history : [];
      // 唯一例外:server 推进到「空」但本地有内容 → 疑似文件被误删/污染,
      // 不采纳空、也不 push(避免覆盖战),只 warn,留人工处理。
      if (hist.length === 0 && state.history.length > 0) {
        console.warn("[thread] server 推进到空但本地有历史 — 疑似 server 文件异常,暂不同步");
        return false;
      }
      state.history = hist.slice(-PERSIST_LIMIT);
      lastServerMtime = mtime;
      _persistLocal();
      _rerender();
      return true;
    } catch { return false; }
  }

  async function initSync() {
    // 真相源 = server 文件。localStorage 只是离线缓存,带它对应的 syncedMtime(lastServerMtime)。
    // 判定靠 recency(mtime),不靠条数:
    //   server.mtime > 本地基线 → server 更新 → 采纳 server(canonical)
    //   server 空 + 本地有       → server 文件丢/首次 → push 本地救场
    //   本地基线 > server.mtime  → 本地缓存比 server 还新(离线编辑过)→ push(CAS 复核)
    //   相等                      → 已同步,no-op
    // 旧版 localStorage 没存过 syncedMtime → lastServerMtime=0 → server>0 必采纳 server,
    // 顺带清掉「陈旧 100 条」那种毒缓存(5.26 事故)。
    try {
      const r = await fetch("/api/thread/history");
      const d = await r.json();
      const serverHist = Array.isArray(d.history) ? d.history : [];
      const serverMtime = d.mtime || 0;

      if (serverMtime > lastServerMtime) {
        if (serverHist.length === 0 && state.history.length > 0) {
          console.warn("[thread] server 空但本地有历史 — 不采纳空,push 本地救场");
          saveHistory();
          return;
        }
        state.history = serverHist.slice(-PERSIST_LIMIT);
        lastServerMtime = serverMtime;
        _persistLocal();
        _rerender();
      } else if (serverMtime === 0 && state.history.length > 0) {
        saveHistory();  // server 没文件 / 首次 → push 本地
      } else if (lastServerMtime > serverMtime && state.history.length > 0) {
        saveHistory();  // 本地缓存更新(离线编辑)→ push,CAS 会复核
      }
      // 其余:相等 → 已同步
    } catch {}
  }

  // ── DOM ──────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const thread = $("thread");
  const tab = $("threadTab");
  const stream = $("threadStream");
  const pendingBox = $("threadPending");
  const input = $("threadInput");
  const statusEl = $("threadStatus");
  const closeBtn = $("threadClose");
  const toggleBtn = $("threadToggleTop");
  const whisperEl = $("whisper");
  const hintLeft = $("threadHintLeft");
  const modelSel = $("threadModel");

  // ── model picker (multi-provider 切换) ─────────────────
  let activeModelId = (() => { try { return localStorage.getItem(MODEL_KEY) || ""; } catch { return ""; } })();
  async function loadModels() {
    if (!modelSel) return;
    try {
      const r = await fetch("/api/models");
      const d = await r.json();
      const opts = d.models || [];
      modelSel.innerHTML = "";
      if (!opts.length) {
        modelSel.innerHTML = `<option value="">(no models)</option>`;
        modelSel.disabled = true;
        return;
      }
      const initial = opts.find(o => o.id === activeModelId) ? activeModelId : (d.default_id || opts[0].id);
      activeModelId = initial;
      for (const o of opts) {
        const op = document.createElement("option");
        op.value = o.id;
        op.textContent = o.label || o.id;
        if (o.id === initial) op.selected = true;
        modelSel.appendChild(op);
      }
      modelSel.addEventListener("change", () => {
        activeModelId = modelSel.value;
        try { localStorage.setItem(MODEL_KEY, activeModelId); } catch {}
        whisper(`已切换到 ${modelSel.options[modelSel.selectedIndex].text}`);
      });
    } catch (e) {
      modelSel.innerHTML = `<option value="">⚠</option>`;
      modelSel.disabled = true;
    }
  }

  // ── open / close ─────────────────────────────────────
  function setOpen(v) {
    state.open = v;
    thread.classList.toggle("on", v);
    document.body.classList.toggle("thread-open", v);
    if (v) {
      setTimeout(() => input.focus({ preventScroll: true }), 350);
      scrollToBottom();
    }
  }
  function toggle() { setOpen(!state.open); }
  tab.addEventListener("click", toggle);
  toggleBtn.addEventListener("click", toggle);
  closeBtn.addEventListener("click", () => setOpen(false));

  // ── pending refs ─────────────────────────────────────
  function renderPending() {
    pendingBox.innerHTML = "";
    for (const r of state.pending) {
      const chip = document.createElement("span");
      chip.className = r.kind === "image" ? "pending-ref pending-image" : "pending-ref";
      const cutOn = (r.payload?.cutout !== false);  // image 默认 true,非 image 没此选项
      if (r.kind === "image" && r.payload?.url) {
        chip.innerHTML = `<img class="pending-thumb" alt=""><span class="ref-label"></span><button class="cut-toggle" title="抠图开关(默认抠 — 切换后 AI 落原图)"></button><span class="x">×</span>`;
        chip.querySelector(".pending-thumb").src = r.payload.url;
        const btn = chip.querySelector(".cut-toggle");
        const paint = () => {
          const on = (r.payload.cutout !== false);
          btn.textContent = on ? "抠" : "原";
          btn.classList.toggle("on", on);
        };
        paint();
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          r.payload.cutout = !(r.payload.cutout !== false);  // toggle, default-true 翻 false
          paint();
        });
      } else {
        chip.innerHTML = `<span class="ref-label"></span><span class="x">×</span>`;
      }
      chip.querySelector(".ref-label").textContent = r.label;
      chip.querySelector(".x").addEventListener("click", (e) => {
        e.stopPropagation();
        state.pending = state.pending.filter(p => p !== r);
        renderPending();
        if (state.pending.length === 0) hintLeft.textContent = "点页面上任意东西 → 把它带进对话";
      });
      pendingBox.appendChild(chip);
    }
  }

  function addRef(ref) {
    // dedupe by (kind, label)
    if (state.pending.find(p => p.kind === ref.kind && p.label === ref.label)) {
      flash(ref.label);
      return;
    }
    state.pending.push(ref);
    renderPending();
    setOpen(true);
    hintLeft.textContent = `已捎上 ${state.pending.length} 处 · 跟它说`;
    flash(ref.label);
  }

  // ── image drop & upload ──────────────────────────────
  async function uploadImage(file) {
    const fd = new FormData();
    fd.append("file", file);
    statusEl.textContent = "上传中…";
    try {
      const r = await fetch("/api/chat/upload-image", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok) {
        statusEl.textContent = data.detail || "上传失败";
        statusEl.className = "thread-status err";
        setTimeout(() => fetch("/api/config-status").then(x=>x.json()).then(s=>{
          statusEl.textContent = s.ok ? (s.model||"ok") : (s.reason||"off");
          statusEl.className = s.ok ? "thread-status ok" : "thread-status err";
        }), 2200);
        return null;
      }
      statusEl.textContent = "图已存";
      statusEl.className = "thread-status ok";
      addRef({
        kind: "image",
        label: data.original || data.filename,
        // cutout 默认 true(对水杯/补剂/scrapbook 都该抠);用户可点 chip 上的 "抠/原" 切换
        payload: { url: data.url, filename: data.filename, original: data.original, size: data.size, cutout: true },
      });
      return data;
    } catch (e) {
      statusEl.textContent = "上传报错";
      statusEl.className = "thread-status err";
      return null;
    }
  }

  // 全文档级拖图:拖进任何位置自动弹开侧栏 + 高亮 dropzone
  let dragDepth = 0;
  function isFileDrag(e) {
    return e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  }
  document.addEventListener("dragenter", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    dragDepth++;
    if (dragDepth === 1) {
      setOpen(true);
      thread.classList.add("drag-over");
    }
  });
  document.addEventListener("dragleave", (e) => {
    if (!isFileDrag(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) thread.classList.remove("drag-over");
  });
  document.addEventListener("dragover", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  document.addEventListener("drop", async (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    dragDepth = 0;
    thread.classList.remove("drag-over");
    const files = [...(e.dataTransfer?.files || [])].filter(f => f.type.startsWith("image/"));
    if (files.length === 0) return;
    setOpen(true);
    for (const f of files) await uploadImage(f);
  });

  // 点 📎 按钮 → 选文件
  const attachBtn = document.getElementById("threadAttachBtn");
  const fileInput = document.getElementById("threadFileInput");
  if (attachBtn && fileInput) {
    attachBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", async () => {
      const files = [...(fileInput.files || [])].filter(f => f.type.startsWith("image/"));
      for (const f of files) await uploadImage(f);
      fileInput.value = ""; // 允许重选同一张
    });
  }

  // also allow paste image into textarea
  input.addEventListener("paste", async (e) => {
    const items = [...(e.clipboardData?.items || [])];
    const imgs = items.filter(it => it.kind === "file" && it.type.startsWith("image/"));
    if (imgs.length === 0) return;
    e.preventDefault();
    for (const it of imgs) {
      const f = it.getAsFile();
      if (f) await uploadImage(f);
    }
  });

  let flashTimer = null;
  function flash(label) {
    hintLeft.textContent = `← ${label}`;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      hintLeft.textContent = state.pending.length
        ? `已捎上 ${state.pending.length} 处 · 跟它说`
        : "点页面上任意东西 → 把它带进对话";
    }, 1400);
  }

  // ── rendering messages ───────────────────────────────
  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
    );
  }
  // 模型时不时会把相对 URL 自动补 http://localhost:NNNN(端口往往瞎编)前缀,
  // 导致 attachments 图全 404。剥掉这种本地前缀,留下原相对路径让 Tauri 解析。
  function stripLocalUrlPrefix(s) {
    return String(s || "").replace(
      /https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?(\/attachments\/)/g,
      "$1"
    );
  }
  function renderText(t) {
    const cleaned = stripLocalUrlPrefix(t);
    // 走全局 gatewayMd (marked + DOMPurify);fallback 到纯 escape
    return window.gatewayMd ? window.gatewayMd(cleaned) : escapeHtml(cleaned).replace(/\n/g, "<br>");
  }

  function renderRefsCard(refs) {
    if (!refs || !refs.length) return "";
    return refs.map(r => {
      if (r.kind === "image" && r.payload?.url) {
        return `<div class="t-ref t-ref-image">
          <img class="ref-thumb" src="${escapeHtml(r.payload.url)}" alt="">
          <span class="ref-text">${escapeHtml(r.label)}</span>
        </div>`;
      }
      return `<div class="t-ref">
        <span class="ref-kind">${escapeHtml(r.kind)}</span>
        <span class="ref-text">${escapeHtml(r.label)}</span>
      </div>`;
    }).join("");
  }

  // AI 在 chat 返的图默认缩略图(CSS 限尺寸),点击开全屏 lightbox 看大图
  function openLightbox(src) {
    let lb = document.getElementById("imgLightbox");
    if (!lb) {
      lb = document.createElement("div");
      lb.id = "imgLightbox";
      lb.className = "img-lightbox";
      lb.innerHTML = `<img alt="">`;
      const close = () => {
        lb.classList.remove("on");
        setTimeout(() => { lb.style.display = "none"; }, 180);
      };
      lb.addEventListener("click", close);
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && lb.style.display === "flex") close();
      });
      document.body.appendChild(lb);
    }
    lb.querySelector("img").src = src;
    lb.style.display = "flex";
    void lb.offsetWidth;        // 强制 reflow,让 .on 的 opacity transition 触发(比 rAF 在各上下文更可靠)
    lb.classList.add("on");
  }
  if (stream) {
    stream.addEventListener("click", (e) => {
      const img = e.target.closest(".body img");
      if (img && img.src) openLightbox(img.src);
    });
  }

  function appendMsg(m) {
    const el = document.createElement("div");
    el.className = `t-msg ${m.role === "user" ? "user" : "ai"}`;
    el.innerHTML = `
      <span class="who">${m.role === "user" ? "你" : "AI"}</span>
      ${renderRefsCard(m.refs)}
      <div class="body">${renderText(m.content)}</div>
    `;
    stream.appendChild(el);
    scrollToBottom();
  }
  function appendAction(text) {
    const el = document.createElement("div");
    el.className = "t-action";
    el.textContent = text;
    stream.appendChild(el);
    scrollToBottom();
  }

  // ── "AI 在想…" processing card(动态 logo,跟 brand 同一图)──
  function showProcessing(label = "在想⋯") {
    removeProcessing();
    const el = document.createElement("div");
    el.className = "t-processing";
    el.id = "tProcessing";
    el.innerHTML = `
      <img class="t-processing-logo" src="./brand/logo-animated.svg" alt="">
      <span class="t-processing-text"></span>
    `;
    el.querySelector(".t-processing-text").textContent = label;
    stream.appendChild(el);
    scrollToBottom();
  }
  function removeProcessing() {
    document.getElementById("tProcessing")?.remove();
  }
  // dedup pending rAF — streaming 时这个被狂调,不 dedup 每秒 30+ scrollTop 写入,
  // 跟 IME 抢主线程触发输入法卡顿(5.21 21:30 诊断)
  let _scrollPending = false;
  function scrollToBottom() {
    if (_scrollPending) return;
    _scrollPending = true;
    requestAnimationFrame(() => {
      _scrollPending = false;
      stream.scrollTop = stream.scrollHeight;
    });
  }

  // initial render of history(先用 LS 给即时画面,然后再 initSync 校准:
  // server 有数据 → 拉来覆盖;server 空 + LS 有 → 把 LS 推上去当种子)
  for (const m of state.history) appendMsg(m);
  initSync();

  // ── cross-client sync(三层)─────────────────────────
  // L1: storage event — 同源跨 tab 即时同步(<10ms)
  // L2: server poll(3s)— 跨浏览器 / 跨设备真相源
  // L3: tab 可见性变化 + window focus 时强 sync — 用户切回来立刻最新
  window.addEventListener("storage", (e) => {
    if (e.key === THREAD_KEY) {
      state.history = loadHistory();
      stream.innerHTML = "";
      for (const m of state.history) appendMsg(m);
    } else if (e.key === MODEL_KEY) {
      const newId = e.newValue || "";
      if (newId !== activeModelId) {
        activeModelId = newId;
        if (modelSel) modelSel.value = activeModelId;
      }
    }
  });
  setInterval(() => syncFromServer(), 3000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") syncFromServer();
  });
  window.addEventListener("focus", () => syncFromServer());

  // ── model picker init ────────────────────────────────
  loadModels();

  // ── API check ────────────────────────────────────────
  fetch("/api/config-status")
    .then(r => r.json())
    .then(s => {
      if (s.ok) {
        state.apiOk = true;
        statusEl.textContent = s.model || "ok";
        statusEl.className = "thread-status ok";
      } else {
        state.apiOk = false;
        statusEl.textContent = s.reason || "off";
        statusEl.className = "thread-status err";
      }
    })
    .catch(e => {
      state.apiOk = false;
      statusEl.textContent = "server?";
      statusEl.className = "thread-status err";
    });

  // ── sending ──────────────────────────────────────────
  async function send() {
    const msg = input.value.trim();
    if (!msg && state.pending.length === 0) return;

    const userMsg = {
      role: "user",
      content: msg || "(看这里)",
      refs: state.pending.slice(),
      ts: nowISO(),
    };
    state.history.push(userMsg);
    appendMsg(userMsg);
    saveHistory();

    const sentRefs = state.pending.slice();
    state.pending = [];
    renderPending();
    input.value = "";
    input.style.height = "auto";
    hintLeft.textContent = "⋯";
    showProcessing();

    if (state.apiOk === false) {
      removeProcessing();
      const aiMsg = { role: "assistant", content: "（AI 没接上 — 起 server / 设 api key 后再来）", ts: nowISO() };
      state.history.push(aiMsg);
      appendMsg(aiMsg);
      saveHistory();
      hintLeft.textContent = "点页面上任意东西 → 把它带进对话";
      return;
    }

    // ── streaming send ────────────────────────────────────
    // SSE 事件:action(工具完成) / delta(文本 chunk) / done(收尾) / error
    // 监控:连续 90s 没收到任何 chunk → AbortController 触发,显示错误
    const TASK_MUTATING = /^(manage_daily_task|check_daily_task|set_daily_task_image|set_water_cup_image|set_daily_task_meta)$/;
    const SCHEDULE_MUTATING = /^(patch_journal_block|insert_journal_block)$/;
    const SCRAPBOOK_MUTATING = /^place_scrapbook_image$/;
    let streamMsgEl = null;
    // 0.1.4 起: 本轮所有 tool 调用累计存这,done 时附在 assistant 消息上,下轮 send 时展开成 OpenAI tool_calls
    const turnActions = [];
    let streamBodyEl = null;
    let accumText = "";
    let needTaskRefresh = false, needScheduleRefresh = false, needScrapbookRefresh = false;

    const ctrl = new AbortController();
    let chunkTimer = null;
    const resetChunkTimer = () => {
      if (chunkTimer) clearTimeout(chunkTimer);
      // 90s 没新 chunk = 卡了。比纯 30s total 友好得多 — 长文输出也能写完
      chunkTimer = setTimeout(() => ctrl.abort(), 90000);
    };
    resetChunkTimer();

    try {
      const context = {
        type: "thread",
        // 当前用户正在浏览的日期(YYYY-MM-DD)。给 AI 看,落 scrapbook / patch_journal
        // 时默认走这一天。null 会让 server 兜底 today,但前端跨午夜不刷新时
        // current?.date 仍是昨天,所以这里直接拿本地真今天兜底(see todayLocalISO)。
        view_date: window.gateway?.journal?.current?.date || todayLocalISO(),
        refs: sentRefs.map(r => ({ kind: r.kind, label: r.label, payload: r.payload })),
      };
      // 0.1.4 起: assistant 消息里附带 _actions 数组 (本轮所有 tool 调用 + 结果),
      // 这里展开成 OpenAI/DeepSeek 期望的 assistant.tool_calls + role:tool 多条。
      // 不这样做的话工具结果丢失,AI 下轮重复 call 同一只读工具 → cache miss 飙升。
      const recentMsgs = state.history.slice(-MAX_HISTORY - 1, -1);
      const history = [];
      for (const m of recentMsgs) {
        if (m.role === "user") {
          const content = m.refs && m.refs.length
            ? `(用户指着这些):\n${m.refs.map(r => `[${r.kind}] ${r.label}`).join("\n")}\n\n${m.content}`
            : m.content;
          history.push({ role: "user", content });
        } else if (m.role === "assistant") {
          const acts = (m._actions || []).filter(a => a && a.id);
          if (acts.length) {
            // 1) assistant 带 tool_calls (content 可空)
            history.push({
              role: "assistant",
              content: m.content || "",
              tool_calls: acts.map(a => ({
                id: a.id,
                type: "function",
                function: {
                  name: a.name,
                  arguments: typeof a.args === "string" ? a.args : JSON.stringify(a.args || {}),
                },
              })),
            });
            // 2) 每个 tool 调用一条 role:tool 结果
            for (const a of acts) {
              history.push({
                role: "tool",
                tool_call_id: a.id,
                content: typeof a.result === "string" ? a.result : JSON.stringify(a.result),
              });
            }
          } else {
            history.push({ role: "assistant", content: m.content });
          }
        }
      }
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          context, message: msg || "看这里", history,
          model_id: activeModelId || undefined,
          stream: true,
        }),
        signal: ctrl.signal,
      });
      if (!r.ok) throw new Error("HTTP " + r.status);

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        resetChunkTimer();
        buf += decoder.decode(value, { stream: true });
        // SSE: 事件用 \n\n 分隔;每行 "data: <json>"
        const events = buf.split("\n\n");
        buf = events.pop() || "";
        for (const ev of events) {
          const line = ev.trim();
          if (!line.startsWith("data: ")) continue;
          let data;
          try { data = JSON.parse(line.slice(6)); } catch { continue; }

          if (data.type === "delta") {
            if (!streamMsgEl) {
              removeProcessing();
              streamMsgEl = appendStreamingMsg();
              streamBodyEl = streamMsgEl.querySelector(".body");
            }
            const chunk = data.text || "";
            accumText += chunk;
            // append-only text node — 不重写整段 textContent。
            // 旧实现每个 delta tear down + 重建所有 text nodes,30/s 节奏下
            // layout reflow 锁主线程,macOS IME composition 事件被延迟 → 输入法抽。
            // append textNode 只触发 incremental layout(成本 ~O(new chars))。
            if (chunk) streamBodyEl.appendChild(document.createTextNode(chunk));
            // 含 markdown 图(![描述](url))时实时渲染,不然用户看到的是
            // streaming 期间的源码 ![描述](url) 直到 done 才转图,体验上
            // 像是 AI 没贴图。throttle 到 600ms 避免每 chunk 重 render。
            if (accumText.includes("![") && (Date.now() - (streamMsgEl._lastMdRender || 0) > 600)) {
              streamMsgEl._lastMdRender = Date.now();
              streamBodyEl.innerHTML = renderText(accumText);
            }
            scrollToBottom();
          } else if (data.type === "action") {
            const summary = `tool · ${data.name} → ${JSON.stringify(data.result).slice(0, 140)}`;
            appendAction(summary);
            // 累计本轮 actions,done 时 attach 到 assistant 消息
            if (data.id) {
              turnActions.push({
                id: data.id, name: data.name, args: data.args, result: data.result,
              });
            }
            if (/^(add|patch)_widget$/.test(data.name) && !data.result?.error) {
              appendAction("widget 已落盘 · 刷新页面看效果");
            }
            if (TASK_MUTATING.test(data.name) && !data.result?.error) needTaskRefresh = true;
            if (SCHEDULE_MUTATING.test(data.name) && !data.result?.error) needScheduleRefresh = true;
            if (SCRAPBOOK_MUTATING.test(data.name) && !data.result?.error) needScrapbookRefresh = true;
          } else if (data.type === "error") {
            removeProcessing();
            appendAction(`⚠ AI 错: ${data.text}`);
            // PATTERN: chat — error-state placeholder
            // USE WHEN: stream 中断,model 没出完文 → 下次 turn model 看不到"上次崩了"会失忆
            // COPY THIS: 改 reason 字符串
            // 占位也进 history,让 model 下次能看见上次 turn 的状态
            const errMsg = { role: "assistant", content: `(上次回复出错: ${data.text} — 可重新问)`, ts: nowISO() };
            state.history.push(errMsg);
            saveHistory();
          } else if (data.type === "done") {
            // 收尾 — streamingMsg 升级成正式消息(渲 markdown)进 history
            if (streamMsgEl && accumText) {
              streamMsgEl.querySelector(".body").innerHTML = renderText(accumText);
              streamMsgEl.classList.remove("streaming");
            } else if (!streamMsgEl) {
              // 没文本(纯工具调用 / 全失败)— 提示一下
              if ((data.actions || []).length > 0) {
                appendAction("（已执行工具,模型未补充文字）");
              }
            }
            // server done payload 可能带 reasoning_content + model_id — 都存,给 post-train 用
            const meta = { ts: nowISO() };
            if (data.reasoning_content) meta.reasoning_content = data.reasoning_content;
            if (data.model_id) meta.model_id = data.model_id;
            // 0.1.4: 本轮所有 tool 调用累计到 _actions,下轮 send 时展开成 tool_calls/role:tool
            if (turnActions.length) meta._actions = turnActions.slice();
            if (accumText) {
              state.history.push({ role: "assistant", content: accumText, ...meta });
              saveHistory();
            } else if (turnActions.length > 0 || (data.actions || []).length > 0) {
              const names = turnActions.length
                ? turnActions.map(a => a.name).join(", ")
                : data.actions.map(a => a.name).join(", ");
              const summary = `(上轮执行了 ${names},未出文字)`;
              state.history.push({ role: "assistant", content: summary, ...meta });
              saveHistory();
            }
          }
        }
      }

      if (needTaskRefresh) window.gateway.ritual?.refreshTasks?.();
      if (needScheduleRefresh) window.gateway.journal?.refresh?.();
      if (needScrapbookRefresh) window.gateway.scrapbook?.refresh?.();
    } catch (e) {
      removeProcessing();
      const reason = e.name === "AbortError"
        ? "90s 没新字 — 可能 server 卡 / 网慢 / API down。打开 /reset.html 重置或刷新重试。"
        : e.message;
      appendAction(`请求失败 · ${reason}`);
      // 网络层 / abort 错误也进 history(同 error event 兜底)
      const errMsg = { role: "assistant", content: `(请求失败: ${reason})`, ts: nowISO() };
      state.history.push(errMsg);
      saveHistory();
    } finally {
      if (chunkTimer) clearTimeout(chunkTimer);
      removeProcessing();
      hintLeft.textContent = "点页面上任意东西 → 把它带进对话";
      try { input.focus({ preventScroll: true }); } catch {}
    }
  }

  function appendStreamingMsg() {
    const el = document.createElement("div");
    el.className = "t-msg ai streaming";
    el.innerHTML = `<span class="who">AI</span><div class="body"></div>`;
    stream.appendChild(el);
    scrollToBottom();
    return el;
  }

  // 输入法 composition 状态(macOS / Win 切中文 / 拼音候选期)。
  // 多处都需要 check:Enter 不发、Esc 不关、auto-resize 跳过。
  // 双保险:isComposing 字段 + 自维护 composing flag(部分浏览器 isComposing 不准)。
  let composing = false;
  input.addEventListener("compositionstart", () => { composing = true; });
  input.addEventListener("compositionend", () => {
    // composition 刚结束的极短窗口里有的浏览器还在 IME 状态,留 30ms buffer
    setTimeout(() => {
      composing = false;
      // composition 结束才 resize 一次,合成中频繁改 height 会干扰 macOS IME 状态
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    }, 30);
  });

  // auto-resize:composition 期间跳过(改 height 触发 reflow → macOS IME 偶尔失效)
  input.addEventListener("input", () => {
    if (composing) return;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });

  input.addEventListener("keydown", (e) => {
    const isIME = composing || e.isComposing || e.keyCode === 229;
    if (e.key === "Enter" && !e.shiftKey) {
      if (isIME) return;  // 输入法中按 Enter 是确认候选,放过
      e.preventDefault();
      send();
    } else if (e.key === "Escape") {
      if (isIME) return;  // 输入法中 Esc 是取消候选,不关侧栏
      setOpen(false);
    }
  });

  // ── whisper (ambient AI utterance, no thread anchor) ─
  let whisperTimer = null;
  function whisper(text, dur = 3800) {
    if (!whisperEl) return;
    whisperEl.textContent = text;
    whisperEl.classList.add("on");
    clearTimeout(whisperTimer);
    whisperTimer = setTimeout(() => whisperEl.classList.remove("on"), dur);
  }

  // ── public API ───────────────────────────────────────
  window.gateway = window.gateway || {};
  window.gateway.thread = {
    addRef,
    open: () => setOpen(true),
    close: () => setOpen(false),
    toggle,
    isOpen: () => state.open,
    pushAI: (text) => {
      const m = { role: "assistant", content: text, ts: nowISO() };
      state.history.push(m);
      appendMsg(m);
      saveHistory();
    },
    history: () => state.history.slice(),
    clear: () => {
      state.history = [];
      saveHistory();
      stream.innerHTML = "";
    },
    // workflow #13 闭合:compact 后用 replaceHistory 收口,内部走 saveHistory CAS
    // 防 5.26 那种事故(localStorage 直写 → 跨 tab initSync 用 server 全量覆盖本地 compact)。
    // 任何外部模块改 thread.history 都走这一个 API,localStorage.setItem(THREAD_KEY) 旁路被废
    replaceHistory: (newHistory) => {
      state.history = Array.isArray(newHistory) ? newHistory.slice() : [];
      // 重渲染 DOM
      stream.innerHTML = "";
      for (const m of state.history) appendMsg(m);
      saveHistory();  // 走 CAS,base_mtime 不变就 ok,变了 forceReloadFromServer 救
    },
  };
  window.gateway.whisper = whisper;
  window.gatewayToast = whisper; // back-compat shim for old code

  // ── resizer:拖左边缘改 sidebar 宽度,持久化到 localStorage ──
  (function wireResizer() {
    const handle = document.getElementById("threadResizer");
    if (!handle) return;
    const KEY = "gateway.thread.width.v1";
    const MIN = 280, MAX_RATIO = 0.7;
    // 初始化:读上次保存的宽度
    const saved = parseInt(localStorage.getItem(KEY), 10);
    if (Number.isFinite(saved) && saved >= MIN) {
      document.documentElement.style.setProperty("--thread-w", saved + "px");
    }
    let dragging = false;
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      dragging = true;
      document.body.classList.add("thread-resizing");
      thread.classList.add("resizing");
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const w = window.innerWidth - e.clientX;
      const max = window.innerWidth * MAX_RATIO;
      const clamped = Math.max(MIN, Math.min(max, w));
      document.documentElement.style.setProperty("--thread-w", clamped + "px");
    });
    window.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      document.body.classList.remove("thread-resizing");
      thread.classList.remove("resizing");
      const cur = getComputedStyle(document.documentElement).getPropertyValue("--thread-w").trim();
      const px = parseInt(cur, 10);
      if (Number.isFinite(px)) localStorage.setItem(KEY, String(px));
    });
  })();

  // small greeting on first ever load
  if (state.history.length === 0) {
    setTimeout(() => {
      whisper("在听。点任意一段、一杯水、一颗药 — 就指给我看。");
    }, 1800);
  }
})();
