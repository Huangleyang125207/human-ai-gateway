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
      const r = await fetch("/api/eval/today");
      const d = await r.json();
      if (!d.markdown) {
        renderEmpty();
        return;
      }
      renderCard(d);
    } catch (e) {
      boardContent.innerHTML = `<div class="board-empty">加载失败 — ${escapeHtml(e.message)}</div>`;
    }
  }

  function renderEmpty() {
    boardContent.innerHTML = `
      <div class="board-empty">
        <div>今晚还没复盘。</div>
        <div style="margin-top: 8px; font-size: 12px;">日程跑到 21:30 自动出,也可以现在手动跑。</div>
        <button id="boardRunNow">立刻跑一次</button>
      </div>
    `;
    document.getElementById("boardRunNow").addEventListener("click", runEvalNow);
  }

  async function runEvalNow() {
    const btn = document.getElementById("boardRunNow");
    if (btn) { btn.disabled = true; btn.textContent = "AI 在写⋯ (可能要 1-2 分钟)"; }
    try {
      const r = await fetch("/api/eval/run", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({}),
      });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error || "未知错误");
      // 跑完重新加载
      await loadBoard();
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "× " + e.message + " (再试)"; }
    }
  }

  function renderCard(data) {
    const title = data.is_today ? "今晚复盘" : `复盘 · ${data.date}`;
    const dateLabel = data.is_today
      ? new Date().toLocaleDateString("zh-CN", {month: "long", day: "numeric", weekday: "long"})
      : data.date;

    // markdown → html。优先 gatewayMd(全局 marked + DOMPurify),fallback 简易转
    const bodyHtml = window.gatewayMd
      ? window.gatewayMd(stripTopHeading(data.markdown))
      : escapeHtml(stripTopHeading(data.markdown)).replace(/\n/g, "<br>");

    boardContent.innerHTML = `
      <div class="board-card">
        <div class="board-card-head">
          <span class="board-card-title">${escapeHtml(title)}</span>
          <span class="board-card-date">${escapeHtml(dateLabel)}</span>
        </div>
        <div class="board-card-body">${bodyHtml}</div>
        <div class="board-actions">
          <button id="boardRefreshBtn">重新生成</button>
        </div>
      </div>
    `;
    document.getElementById("boardRefreshBtn").addEventListener("click", runEvalNow);
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
