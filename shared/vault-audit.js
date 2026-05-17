/* vault-audit.js · 启动时 ping /api/vault/audit;有 drift 就横幅提醒,可一键修
 *
 * 检查的 drift 类型:
 *   - image_recoverable:图片被挪了,daily-task-images/ 内能找到 → 点修复自动 re-link
 *   - image_orphans:图片彻底找不到 → 报但不动
 *   - meta_orphans:meta 有 key 但 daily-tasks.md 没有 → 报但不动(可能是 task 改名了)
 *   - aggregate_broken_links:聚合页 link 404 → 报但不动
 */
(function () {
  async function init() {
    let report;
    try {
      const r = await fetch("/api/vault/audit");
      report = await r.json();
    } catch {
      return;
    }
    if (!report || report.total_drift === 0) return;
    renderBanner(report);
  }

  function renderBanner(report) {
    if (document.getElementById("vaultAuditBanner")) return;
    const banner = document.createElement("div");
    banner.id = "vaultAuditBanner";
    banner.className = "vault-audit-banner";
    const recoverable = (report.image_recoverable || []).length;
    const orphans = (report.image_orphans || []).length;
    const metaOrphans = (report.meta_orphans || []).length;
    const aggBroken = (report.aggregate_broken_links || []).length;
    const summaryParts = [];
    if (recoverable) summaryParts.push(`<b>${recoverable}</b> 张图被挪了`);
    if (orphans) summaryParts.push(`<b>${orphans}</b> 张图找不到`);
    if (metaOrphans) summaryParts.push(`<b>${metaOrphans}</b> 条历史失联(task 改名?)`);
    if (aggBroken) summaryParts.push(`<b>${aggBroken}</b> 条聚合 link 失效`);

    banner.innerHTML = `
      <div class="vab-icon">⚠</div>
      <div class="vab-msg">
        <div class="vab-title">文件映射检测到 ${report.total_drift} 处漂移</div>
        <div class="vab-summary">${summaryParts.join(" · ")}</div>
      </div>
      <div class="vab-actions">
        ${recoverable > 0 ? `<button class="vab-btn vab-fix">自动修复(${recoverable})</button>` : ""}
        <button class="vab-btn vab-detail">详情</button>
        <button class="vab-btn vab-dismiss" aria-label="dismiss">×</button>
      </div>
    `;
    // 放在 header 下面 main 之前
    const main = document.querySelector("main.page") || document.body;
    main.parentNode.insertBefore(banner, main);

    banner.querySelector(".vab-dismiss")?.addEventListener("click", () => banner.remove());
    banner.querySelector(".vab-fix")?.addEventListener("click", async () => {
      const btn = banner.querySelector(".vab-fix");
      btn.disabled = true; btn.textContent = "修复中⋯";
      try {
        const r = await fetch("/api/vault/repair", { method: "POST" });
        const d = await r.json();
        const fixed = d.fixed_images || 0;
        const remain = d.remaining?.total_drift || 0;
        banner.remove();
        if (remain > 0) {
          // 还有别的 drift → 重新画 banner
          renderBanner(d.remaining);
          window.gateway?.whisper?.(`✓ 修了 ${fixed} 张图;还有其他 drift,见 banner`, 3200);
        } else {
          window.gateway?.whisper?.(`✓ 修了 ${fixed} 张图,vault 干净了`, 2800);
        }
      } catch (e) {
        btn.disabled = false;
        btn.textContent = `× ${e.message}`;
      }
    });
    banner.querySelector(".vab-detail")?.addEventListener("click", () => {
      showDetail(report);
    });
  }

  function showDetail(report) {
    const lines = [];
    if (report.image_recoverable?.length) {
      lines.push("【图片被挪 — 可自动 re-link】");
      report.image_recoverable.slice(0, 20).forEach(it => {
        lines.push(`  · ${it.task}:${it.old_path} → ${it.new_path}`);
      });
    }
    if (report.image_orphans?.length) {
      lines.push("\n【图片找不到 — 需重传】");
      report.image_orphans.slice(0, 20).forEach(it => {
        lines.push(`  · ${it.task}:${it.path}`);
      });
    }
    if (report.meta_orphans?.length) {
      lines.push("\n【meta 历史失联 — task 可能被改名 / 删了】");
      report.meta_orphans.slice(0, 20).forEach(it => {
        lines.push(`  · ${it.task}(${it.intake_log_days} 天历史)`);
      });
    }
    if (report.aggregate_broken_links?.length) {
      lines.push("\n【聚合页 link 失效 — 源 md 被移走 / 重命名了】");
      report.aggregate_broken_links.slice(0, 20).forEach(it => {
        lines.push(`  · #${it.tag} ${it.row_date} ${it.row_time}:${it.link}`);
      });
    }
    alert(lines.join("\n"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    // 慢启动一下,让别的 init 先跑完
    setTimeout(init, 1200);
  });
})();
