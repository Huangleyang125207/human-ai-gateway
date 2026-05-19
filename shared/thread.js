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
  const MODEL_KEY = "gateway.thread.model_id.v1";
  const MAX_HISTORY = 100;      // 发给 server 的总条数;server 取最近 20 原文,更早的做摘要
  const PERSIST_LIMIT = 200;    // localStorage 最多存 N 条

  // ── state ────────────────────────────────────────────
  const state = {
    history: loadHistory(),   // [{role: 'user'|'assistant', content, refs?: [...]}]
    pending: [],              // [{kind, label, payload}]
    open: false,
    apiOk: null,
  };
  // server-side mtime — 用于 poll diff:server > 这个值才重渲(避免自己写完被自己 pull 一次)
  let lastServerMtime = 0;

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
    fetch("/api/thread/save", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ history: state.history.slice(-PERSIST_LIMIT) }),
    }).then(r => r.json()).then(d => {
      if (d && d.mtime) lastServerMtime = d.mtime;
    }).catch(() => {});  // 离线 / server down 都不阻塞
  }

  async function syncFromServer() {
    // 轮询用:仅 server mtime > 本地基线 时尝试同步;且 server "比本地多" 才覆盖
    try {
      const r = await fetch("/api/thread/history");
      const d = await r.json();
      const mtime = d.mtime || 0;
      if (mtime <= lastServerMtime) return false;
      const hist = Array.isArray(d.history) ? d.history : [];
      // 防御:server 比 local 少 → 几乎一定是 server 文件被误删 / 测试污染 /
      // 其他 client 错误 reset。绝不让 server 蚕食本地;反过来推 LS 救场。
      if (hist.length < state.history.length) {
        saveHistory();
        return false;
      }
      state.history = hist.slice(-PERSIST_LIMIT);
      lastServerMtime = mtime;
      try { localStorage.setItem(THREAD_KEY, JSON.stringify(state.history)); } catch {}
      if (typeof stream !== "undefined" && stream) {
        stream.innerHTML = "";
        for (const m of state.history) appendMsg(m);
      }
      return true;
    } catch { return false; }
  }

  async function initSync() {
    // 启动时三分支(永远 "数据多" 的那侧赢,杜绝事故吃数据):
    //   server > local → server 覆盖本地(其他 client/设备写过)
    //   local > server → push 本地(server 是新的/被清/初次)
    //   等长 + server 有 mtime → 采 server(假定同份数据,基线对齐)
    try {
      const r = await fetch("/api/thread/history");
      const d = await r.json();
      const serverHist = Array.isArray(d.history) ? d.history : [];
      const serverMtime = d.mtime || 0;

      if (serverHist.length > state.history.length) {
        state.history = serverHist.slice(-PERSIST_LIMIT);
        lastServerMtime = serverMtime;
        try { localStorage.setItem(THREAD_KEY, JSON.stringify(state.history)); } catch {}
        if (stream) {
          stream.innerHTML = "";
          for (const m of state.history) appendMsg(m);
        }
      } else if (state.history.length > serverHist.length) {
        // local 更多 → push 上去
        saveHistory();
      } else if (serverMtime > 0) {
        // 等长 + server 有 mtime → 采 server 文本(可能内容一致,确保基线)
        state.history = serverHist.slice(-PERSIST_LIMIT);
        lastServerMtime = serverMtime;
      }
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
  function renderText(t) {
    // 走全局 gatewayMd (marked + DOMPurify);fallback 到纯 escape
    return window.gatewayMd ? window.gatewayMd(t) : escapeHtml(t).replace(/\n/g, "<br>");
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
  function scrollToBottom() {
    requestAnimationFrame(() => { stream.scrollTop = stream.scrollHeight; });
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
      const aiMsg = { role: "assistant", content: "（AI 没接上 — 起 server / 设 api key 后再来）" };
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
        // 时默认走这一天,不是 today。不带 → server 兜底 today。
        view_date: window.gateway?.journal?.current?.date || null,
        refs: sentRefs.map(r => ({ kind: r.kind, label: r.label, payload: r.payload })),
      };
      const history = state.history.slice(-MAX_HISTORY - 1, -1).map(m => ({
        role: m.role,
        content: m.refs && m.refs.length
          ? `(用户指着这些):\n${m.refs.map(r => `[${r.kind}] ${r.label}`).join("\n")}\n\n${m.content}`
          : m.content,
      }));
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
            }
            accumText += data.text || "";
            streamMsgEl.querySelector(".body").textContent = accumText;
            scrollToBottom();
          } else if (data.type === "action") {
            const summary = `tool · ${data.name} → ${JSON.stringify(data.result).slice(0, 140)}`;
            appendAction(summary);
            if (/^(add|patch)_widget$/.test(data.name) && !data.result?.error) {
              appendAction("widget 已落盘 · 刷新页面看效果");
            }
            if (TASK_MUTATING.test(data.name) && !data.result?.error) needTaskRefresh = true;
            if (SCHEDULE_MUTATING.test(data.name) && !data.result?.error) needScheduleRefresh = true;
            if (SCRAPBOOK_MUTATING.test(data.name) && !data.result?.error) needScrapbookRefresh = true;
          } else if (data.type === "error") {
            removeProcessing();
            appendAction(`⚠ AI 错: ${data.text}`);
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
            if (accumText) {
              state.history.push({ role: "assistant", content: accumText });
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
      const m = { role: "assistant", content: text };
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
