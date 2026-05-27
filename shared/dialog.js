/* dialog.js · 页内 confirm / prompt / alert —— 替代浏览器原生弹窗。
 *
 * 为什么:Tauri 的 WKWebView(及 WebView2 / WebKitGTK)默认**不弹** window.confirm/
 * alert/prompt —— 嵌入式 app 里这些原生 JS 对话框被抑制,confirm() 直接返回 false。
 * 于是所有 `if (!confirm(...)) return;` 的删除/清空确认在壳里全失灵(删不掉照片就是这个)。
 *
 * 解法:纯前端自定义弹窗,promise 化。浏览器 + 三平台 webview 行为一致,贴合"安静像纸"调。
 * 铁律延伸:不依赖 webview 的原生能力,自己画。
 *
 * API(都返 Promise,可 await):
 *   gatewayConfirm(msg, {okText, cancelText, danger}) -> bool
 *   gatewayPrompt(msg, defaultValue, {okText, cancelText, placeholder}) -> string | null(取消)
 *   gatewayAlert(msg, {okText}) -> void
 *
 * 注意:原生 confirm/prompt 是**同步**的,换成本模块后调用处要 `await`,
 * 且 enclosing 函数要 async。
 */
(function () {
  function buildOverlay() {
    const ov = document.createElement("div");
    ov.className = "gw-dlg-overlay";
    document.body.appendChild(ov);
    return ov;
  }

  // 通用核:渲染一个弹窗,resolve 由各 flavor 决定
  function open({ message, withInput, defaultValue, placeholder, okText, cancelText, danger, showCancel }) {
    return new Promise((resolve) => {
      const ov = buildOverlay();
      const card = document.createElement("div");
      card.className = "gw-dlg";

      const msg = document.createElement("div");
      msg.className = "gw-dlg-msg";
      msg.textContent = message;          // textContent → 自动转义 + 保留 \n(配 white-space:pre-wrap)
      card.appendChild(msg);

      let input = null;
      if (withInput) {
        input = document.createElement("input");
        input.className = "gw-dlg-input";
        input.type = "text";
        input.value = defaultValue || "";
        if (placeholder) input.placeholder = placeholder;
        card.appendChild(input);
      }

      const btns = document.createElement("div");
      btns.className = "gw-dlg-btns";

      const cleanup = () => { ov.remove(); document.removeEventListener("keydown", onKey, true); };
      const done = (val) => { cleanup(); resolve(val); };

      if (showCancel) {
        const cancel = document.createElement("button");
        cancel.className = "gw-dlg-btn";
        cancel.textContent = cancelText || "取消";
        cancel.addEventListener("click", () => done(withInput ? null : false));
        btns.appendChild(cancel);
      }
      const ok = document.createElement("button");
      ok.className = "gw-dlg-btn primary" + (danger ? " danger" : "");
      ok.textContent = okText || "确定";
      ok.addEventListener("click", () => done(withInput ? (input.value) : true));
      btns.appendChild(ok);
      card.appendChild(btns);

      // 点遮罩空白 = 取消
      ov.addEventListener("mousedown", (e) => { if (e.target === ov) done(withInput ? null : false); });

      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); done(withInput ? null : false); }
        else if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); done(withInput ? input.value : true); }
      }
      document.addEventListener("keydown", onKey, true);

      ov.appendChild(card);
      requestAnimationFrame(() => {
        ov.classList.add("on");
        if (input) { input.focus(); input.select(); } else { ok.focus(); }
      });
    });
  }

  window.gatewayConfirm = (message, opts = {}) =>
    open({ message, showCancel: true, okText: opts.okText, cancelText: opts.cancelText, danger: opts.danger });

  window.gatewayPrompt = (message, defaultValue = "", opts = {}) =>
    open({ message, withInput: true, defaultValue, placeholder: opts.placeholder,
           showCancel: true, okText: opts.okText, cancelText: opts.cancelText });

  window.gatewayAlert = (message, opts = {}) =>
    open({ message, showCancel: false, okText: opts.okText || "知道了" }).then(() => undefined);

  /* ── gatewayUndo · 撤回交互(替代删除确认) ──────────────────────────
   * 模型:延迟执行。删除点**先乐观隐藏 UI**,真正的破坏性操作(onCommit)
   * 推迟到撤回窗口(默认 5s)过后才跑;撤回 = 取消提交 + onUndo 复原 UI。
   * 好处:不需要任何"恢复"逻辑,再重的删除也安全(没真删)。
   *
   *   gatewayUndo("已删除「X」", {
   *     onCommit: async () => { await fetch(delete...); refresh(); },  // 窗口过后真删
   *     onUndo:   () => { el.style.display = ""; },                    // 撤回时复原
   *     seconds:  5,
   *   })
   *
   * 同时只挂一个:开新的会**立即提交**上一个(commit-then-replace)。
   */
  let activeUndo = null;
  function clearActiveUndo() {
    if (!activeUndo) return;
    clearTimeout(activeUndo.timer);
    activeUndo.el.remove();
    activeUndo = null;
  }
  window.gatewayUndo = function (message, { onCommit, onUndo, seconds = 5 } = {}) {
    // 已有一个待提交的 → 先把它提交掉,再开新的(避免堆叠)
    if (activeUndo) { const prev = activeUndo; activeUndo = null; clearTimeout(prev.timer); prev.el.remove(); try { prev.onCommit?.(); } catch (e) { console.warn(e); } }

    const toast = document.createElement("div");
    toast.className = "gw-undo";
    const txt = document.createElement("span");
    txt.className = "gw-undo-msg";
    txt.textContent = message;
    const btn = document.createElement("button");
    btn.className = "gw-undo-btn";
    btn.textContent = "撤回";
    const bar = document.createElement("div");
    bar.className = "gw-undo-bar";
    toast.append(txt, btn, bar);
    document.body.appendChild(toast);

    const commit = () => {
      if (activeUndo?.el !== toast) return;     // 已被取消/替换
      activeUndo = null;
      toast.classList.remove("on");
      setTimeout(() => toast.remove(), 200);
      try { onCommit?.(); } catch (e) { console.warn("[undo] commit failed:", e); }
    };
    const undo = () => {
      if (activeUndo?.el !== toast) return;
      clearTimeout(activeUndo.timer);
      activeUndo = null;
      toast.classList.remove("on");
      setTimeout(() => toast.remove(), 200);
      try { onUndo?.(); } catch (e) { console.warn("[undo] restore failed:", e); }
    };
    btn.addEventListener("click", undo);

    const timer = setTimeout(commit, seconds * 1000);
    activeUndo = { el: toast, timer, onCommit };
    requestAnimationFrame(() => {
      toast.classList.add("on");
      // 进度条 seconds 内走完 = 视觉倒计时
      bar.style.transition = `transform ${seconds}s linear`;
      requestAnimationFrame(() => { bar.style.transform = "scaleX(0)"; });
    });
  };
})();
