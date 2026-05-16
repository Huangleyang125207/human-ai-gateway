/* md.js · gateway 统一 markdown 渲染器
 *
 * 之前 3 套手撸 mini-renderer (journal.mdToHtml / thread.renderText / widget.renderMd)
 * 各支持子集 + 各自 escape。今天合并:
 *   - marked v12 (GFM,表格/有序列表/链接/任务列表)
 *   - DOMPurify v3 (XSS 防护,允许标签白名单)
 *
 * 用法:
 *   window.gatewayMd(rawMdString) → safe HTML string
 *
 * fallback:lib 没载入 → 退到纯 escape,不渲染但不崩。
 */

(function () {
  function escapeOnly(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
  }

  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    console.warn("[gateway] marked / DOMPurify not loaded — md fallback to plain escape");
    window.gatewayMd = (text) => escapeOnly(text).replace(/\n/g, "<br>");
    return;
  }

  marked.setOptions({
    gfm: true,         // GitHub-flavored: 表格 / 任务列表 / 删除线 / autolink
    breaks: true,      // 单换行 → <br>,匹配日记 / 聊天的口语化输入
    headerIds: false,  // 不给 heading 加 id,避免冲突
    mangle: false,     // 不混淆邮箱
  });

  const PURIFY_CONFIG = {
    ALLOWED_TAGS: [
      "p", "br", "hr", "div", "span",
      "b", "strong", "i", "em", "u", "s", "del", "sub", "sup",
      "code", "pre", "kbd",
      "h1", "h2", "h3", "h4", "h5", "h6",
      "ul", "ol", "li",
      "blockquote",
      "table", "thead", "tbody", "tr", "th", "td",
      "a", "img",
    ],
    ALLOWED_ATTR: ["href", "title", "target", "rel", "src", "alt", "class", "id"],
    ALLOW_DATA_ATTR: false,
  };

  window.gatewayMd = function (text) {
    if (text == null || text === "") return "";
    try {
      const raw = marked.parse(String(text));
      return DOMPurify.sanitize(raw, PURIFY_CONFIG);
    } catch (e) {
      console.warn("[gateway] md render failed, fallback to escape:", e);
      return escapeOnly(text).replace(/\n/g, "<br>");
    }
  };
})();
