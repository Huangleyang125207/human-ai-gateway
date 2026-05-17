/* aggregate.js · 标签聚合页 viewer
 *
 * 入口: header 的 ⌘ icon (id="aggregateBtn")
 * 数据: GET /api/tag-aggregate (server 解析 数据库/valut/标签聚合.md)
 * 行为: 点 row → 关 panel + window.gateway.journal.goto(iso_date) 跳到那天
 */

(function () {
  const btn = document.getElementById("aggregateBtn");
  if (!btn) return;

  let overlay = null;
  let activeTag = null;       // 当前选中段
  let activeSubTag = null;    // 当前选中子标签 (null = 全部)
  let dataCache = null;

  async function open() {
    if (overlay) return;
    if (!dataCache) {
      try {
        const r = await fetch("/api/tag-aggregate");
        dataCache = await r.json();
      } catch (e) {
        alert("聚合页加载失败:" + e.message);
        return;
      }
    }
    render();
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    document.removeEventListener("keydown", onKey);
  }

  function render() {
    const sections = (dataCache && dataCache.sections) || [];
    if (!sections.length) {
      alert("聚合页为空" + (dataCache.warning ? " — " + dataCache.warning : ""));
      return;
    }
    if (!activeTag || !sections.find(s => s.tag === activeTag)) {
      activeTag = sections[0].tag;
      activeSubTag = null;
    }

    overlay = document.createElement("div");
    overlay.className = "agg-overlay";
    overlay.innerHTML = `
      <div class="agg-panel">
        <header class="agg-head">
          <div class="agg-title">标签聚合</div>
          <div class="agg-tabs" id="aggTabs"></div>
          <button class="agg-refresh" id="aggRefresh" title="AI 扫 schedule 同步新行(只 append 不 delete)">⟳ 刷新</button>
          <button class="agg-rules-btn" id="aggRulesBtn" title="聚合规则" aria-label="rules">规则</button>
          <button class="market-close" id="aggClose" aria-label="close">×</button>
        </header>
        <details class="agg-rules" id="aggRules">
          <summary>聚合规则(点开看)</summary>
          <div class="agg-rules-body">
            <p><strong>视图关系</strong>:schedule 按时间线索;本页按项目主题。两套视图必须一致。</p>
            <p><strong>什么会进聚合</strong>:H2 的 tag 命中已注册 project tag(<code>#yanpai #ESP32 #配置系统</code>)的 entry。
              <code>#parent/child</code> sub-tag roll-up 到 parent 段、Sub 列填 <code>/child</code>。</p>
            <p><strong>什么不进</strong>:generic tag(<code>#运动 #饮食 #娱乐</code>) / 单挂 <code>#协作</code> 没项目 tag / 没注册的新 tag(出现 ≥ 3 次再入聚合)。</p>
            <p><strong>表格列</strong>:Date(<code>M.D</code>) / Time(全角冒号<code>：</code>跟源 H1 一致) / Link(<code>file#anchor</code>) / Content(一句话提示词)/ Sub(可选)。一时间块 = 一行,不合并。</p>
            <p><strong>本页刷新做什么</strong>:扫 <code>半小时复盘/*.md</code> → diff 现有行 → append 缺失。<strong>只增不删</strong> — 删 / 改 / 重命名要手工处理(避免误杀)。</p>
          </div>
        </details>
        <div class="agg-meta" id="aggMeta"></div>
        <div class="agg-subtags" id="aggSubTags"></div>
        <div class="agg-body" id="aggBody"></div>
      </div>
    `;
    document.body.appendChild(overlay);
    document.getElementById("aggClose").addEventListener("click", close);
    document.getElementById("aggRefresh").addEventListener("click", refresh);
    document.getElementById("aggRulesBtn").addEventListener("click", () => {
      const det = document.getElementById("aggRules");
      det.open = !det.open;
    });
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey);

    renderTabs(sections);
    renderActiveSection();
  }

  async function refresh() {
    const btn = document.getElementById("aggRefresh");
    if (!btn) return;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "⟳ 扫描中⋯";
    try {
      const r = await fetch("/api/tag-aggregate/refresh", { method: "POST" });
      const data = await r.json();
      if (!data.ok) {
        btn.textContent = "× " + (data.error || "失败");
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2500);
        return;
      }
      // 重新拉数据 + 重渲
      dataCache = null;
      try {
        const r2 = await fetch("/api/tag-aggregate");
        dataCache = await r2.json();
      } catch (e) {
        btn.textContent = "× 重载失败";
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2500);
        return;
      }
      // 关 + 重开 — 简单粗暴(避免 partial DOM 更新出 bug)
      close();
      await open();
      // 提示加多少行
      const toast = data.added > 0
        ? `✓ 同步 ${data.added} 行(${Object.entries(data.per_tag || {}).map(([t,n])=>`#${t} +${n}`).join("  ")})`
        : `✓ 已是最新(扫到 ${data.scanned} 条)`;
      if (window.gateway?.whisper) {
        window.gateway.whisper(toast, 2800);
      } else {
        console.log(toast);
      }
    } catch (e) {
      btn.textContent = "× " + e.message;
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2500);
    }
  }

  function renderTabs(sections) {
    const tabs = document.getElementById("aggTabs");
    tabs.innerHTML = "";
    for (const s of sections) {
      const btn = document.createElement("button");
      btn.className = "agg-tab" + (s.tag === activeTag ? " on" : "");
      btn.innerHTML = `<span class="agg-tab-hash">#</span>${escape(s.tag)}<span class="agg-tab-count">${s.rows.length}</span>`;
      btn.addEventListener("click", () => {
        activeTag = s.tag;
        activeSubTag = null;
        document.querySelectorAll(".agg-tab").forEach(b => b.classList.remove("on"));
        btn.classList.add("on");
        renderActiveSection();
      });
      tabs.appendChild(btn);
    }
  }

  function renderActiveSection() {
    const sec = (dataCache.sections || []).find(s => s.tag === activeTag);
    if (!sec) return;
    document.getElementById("aggMeta").textContent = sec.description || "";

    // 子标签 chips (只在有 sub_tag 的段显示)
    const subTags = [...new Set(sec.rows.map(r => r.sub_tag).filter(Boolean))].sort();
    const subWrap = document.getElementById("aggSubTags");
    subWrap.innerHTML = "";
    if (subTags.length) {
      const all = chip("全部", activeSubTag === null, () => { activeSubTag = null; renderActiveSection(); });
      subWrap.appendChild(all);
      for (const st of subTags) {
        subWrap.appendChild(chip(st, activeSubTag === st, () => {
          activeSubTag = activeSubTag === st ? null : st;
          renderActiveSection();
        }));
      }
    }

    const body = document.getElementById("aggBody");
    body.innerHTML = "";
    let rows = sec.rows;
    if (activeSubTag) rows = rows.filter(r => r.sub_tag === activeSubTag);

    // 按 iso_date 倒序 (新 → 旧)
    rows = rows.slice().sort((a, b) => {
      if (!a.iso_date) return 1;
      if (!b.iso_date) return -1;
      return b.iso_date.localeCompare(a.iso_date) || (b.time || "").localeCompare(a.time || "");
    });

    if (!rows.length) {
      body.innerHTML = `<div class="agg-empty">这个 tag 下没有 entry</div>`;
      return;
    }

    let lastDate = null;
    for (const row of rows) {
      // 日期分组 header
      if (row.iso_date !== lastDate) {
        const dh = document.createElement("div");
        dh.className = "agg-date-head";
        dh.textContent = row.iso_date || row.date_short || "—";
        body.appendChild(dh);
        lastDate = row.iso_date;
      }
      body.appendChild(rowNode(row));
    }
  }

  function rowNode(row) {
    const el = document.createElement("article");
    el.className = "agg-row";
    if (!row.iso_date) el.classList.add("no-jump");
    el.innerHTML = `
      <span class="agg-row-time">${escape(row.time || "—")}</span>
      <span class="agg-row-content">${escape(row.content || "")}</span>
      ${row.sub_tag ? `<span class="agg-row-subtag">${escape(row.sub_tag)}</span>` : ""}
    `;
    if (row.iso_date) {
      el.addEventListener("click", () => {
        close();
        window.gateway?.journal?.goto?.(row.iso_date);
      });
    }
    return el;
  }

  function chip(label, on, handler) {
    const c = document.createElement("button");
    c.className = "agg-chip" + (on ? " on" : "");
    c.textContent = label;
    c.addEventListener("click", handler);
    return c;
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  function onKey(e) {
    if (e.key === "Escape") close();
  }

  btn.addEventListener("click", open);
  window.gateway = window.gateway || {};
  window.gateway.aggregate = { open, close };
})();
