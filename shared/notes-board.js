/* notes-board.js · 留言板 view — AI 给用户的今晚复盘卡片
 *
 * 跟 chat-view 同 panel,thread-head 用 tab 切换。
 * 数据源:GET /api/eval/today → 渲染 4 段 + feature_intro。
 * 空状态:[立刻跑一次] 按钮触发 POST /api/eval/run。
 */
(function () {
  const tvtChat = document.getElementById("tvtChat");
  const tvtBoard = document.getElementById("tvtBoard");
  const tvtBoardDot = document.getElementById("tvtBoardDot");
  const chatView = document.getElementById("chatView");
  const boardView = document.getElementById("boardView");
  const boardContent = document.getElementById("boardContent");
  if (!tvtChat || !tvtBoard || !chatView || !boardView) return;

  function setView(name) {
    const isChat = name === "chat";
    tvtChat.classList.toggle("on", isChat);
    tvtBoard.classList.toggle("on", !isChat);
    chatView.classList.toggle("on", isChat);
    boardView.classList.toggle("on", !isChat);
    if (!isChat) {
      tvtBoardDot.hidden = true;  // 看了就清 unread dot
      loadBoard();
    }
  }

  tvtChat.addEventListener("click", () => setView("chat"));
  tvtBoard.addEventListener("click", () => setView("board"));

  async function loadBoard() {
    boardContent.innerHTML = `<div class="board-empty">载入中⋯</div>`;
    try {
      const r = await fetch("/api/eval/list?n=14");
      const d = await r.json();
      const items = d.items || [];
      if (!items.length) {
        renderEmpty();
        return;
      }
      renderStack(items);
    } catch (e) {
      boardContent.innerHTML = `<div class="board-empty">加载失败 — ${escapeHtml(e.message)}</div>`;
    }
  }

  function renderEmpty() {
    boardContent.innerHTML = `
      <div class="board-empty">
        <div>还没有任何复盘。</div>
        <div style="margin-top: 8px; font-size: 12px;">日程跑到 21:30 自动出,也可以现在手动跑。</div>
        <button id="boardRunNow">立刻跑一次</button>
      </div>
    `;
    document.getElementById("boardRunNow").addEventListener("click", runEvalNow);
  }

  async function runEvalNow() {
    const btn = document.getElementById("boardRunNow") || document.getElementById("boardRefreshBtn");
    if (btn) { btn.disabled = true; btn.textContent = "AI 在写⋯ (可能要 1-2 分钟)"; }
    try {
      const r = await fetch("/api/eval/run", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({}),
      });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error || "未知错误");
      await loadBoard();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "× " + e.message + " (再试)"; }
    }
  }

  function renderStack(items) {
    // items 已按日期降序(newest first)。最新在顶,过去往下。
    const todayItem = items.find(x => x.is_today);
    const todayCard = todayItem ? cardHtml(todayItem, false) : `
      <div class="board-card board-card-empty">
        <div class="board-card-head">
          <span class="board-card-title">今晚还没复盘</span>
          <span class="board-card-date">${new Date().toLocaleDateString("zh-CN", {month:"long",day:"numeric",weekday:"long"})}</span>
        </div>
        <div class="board-card-body" style="opacity:.7;">21:30 自动出。也可以现在手动跑。</div>
        <div class="board-actions"><button id="boardRunNow">立刻跑一次</button></div>
      </div>`;
    const pastCards = items
      .filter(x => !x.is_today)
      .map(x => cardHtml(x, true))
      .join("");

    boardContent.innerHTML = `
      ${todayCard}
      ${pastCards ? `<div class="board-past-divider">过去 ${items.filter(x=>!x.is_today).length} 晚</div>${pastCards}` : ""}
    `;
    const runBtn = document.getElementById("boardRunNow");
    if (runBtn) runBtn.addEventListener("click", runEvalNow);
    const refreshBtn = document.getElementById("boardRefreshBtn");
    if (refreshBtn) refreshBtn.addEventListener("click", runEvalNow);
  }

  function cardHtml(item, isPast) {
    const title = item.is_today
      ? "今晚复盘"
      : new Date(item.date).toLocaleDateString("zh-CN", {month:"long",day:"numeric",weekday:"short"}) + " 复盘";
    const dateLabel = item.date;
    const bodyHtml = window.gatewayMd
      ? window.gatewayMd(stripTopHeading(item.markdown))
      : escapeHtml(stripTopHeading(item.markdown)).replace(/\n/g, "<br>");
    const cls = isPast ? "board-card board-card-past" : "board-card";
    const actions = item.is_today
      ? `<div class="board-actions"><button id="boardRefreshBtn">重新生成</button></div>`
      : "";
    return `
      <div class="${cls}">
        <div class="board-card-head">
          <span class="board-card-title">${escapeHtml(title)}</span>
          <span class="board-card-date">${escapeHtml(dateLabel)}</span>
        </div>
        <div class="board-card-body">${bodyHtml}</div>
        ${actions}
      </div>
    `;
  }

  function stripTopHeading(md) {
    // 去掉 "# Daily Eval — ..." 那行 + "_generated ..._" 那行,保留 H2 起的正文
    return md.replace(/^# .*\n_generated[^\n]*_?\n*/m, "").trim();
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  // 启动时如果今天有复盘 → 在 tab 上点个小红点(unread)
  // 但若用户首次就打开了 board → 点点立刻消
  fetch("/api/eval/today").then(r => r.json()).then(d => {
    if (d.is_today && tvtBoardDot && !boardView.classList.contains("on")) {
      tvtBoardDot.hidden = false;
    }
  }).catch(() => {});

  window.gateway = window.gateway || {};
  window.gateway.notesBoard = { open: () => setView("board"), refresh: loadBoard };
})();
