/* korok.js · gateway v0.5
 *
 * 塞尔达式引导 + 三层反馈:
 *   呀哈哈 — 微反馈: 点任何东西飞起一片小叶子
 *   神庙   — 中期成就: 累积到某 milestone, 一处 ornament 永久 fade-in + AI whisper
 *   塔     — 解锁新区域: 第一次做某事, 暗示下一个动作可以做什么
 *
 * 首访 nudge: 第一个 entry 标题暖色脉冲 2 次, 第一个未填杯子轻晃, hatch 一次性闪.
 * 全部状态持久化到 localStorage. 摸过就回归日常.
 */

(function () {
  const LS_KEY = "gateway.korok.v1";
  const state = load();

  function load() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return defaultState();
      const s = JSON.parse(raw);
      return { ...defaultState(), ...s, counters: { ...defaultState().counters, ...(s.counters || {}) } };
    } catch { return defaultState(); }
  }
  function defaultState() {
    return {
      visits: 0,
      seenFirstNudge: false,
      counters: { water: 0, supplement: 0, ref: 0, edit: 0 },
      shrines: {},   // {water-7: true, supplement-all: true, ref-5: true, ...}
      towers: {},    // {first-thread-open, first-cup, first-pill, first-ref, first-hatch, first-edit}
    };
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch {}
  }

  // ── yahaha — micro 飞叶 ──────────────────────────────
  const LEAF = ["✦", "·", "‧", "•", "✧"];
  function yahaha(x, y) {
    const el = document.createElement("div");
    el.className = "yahaha";
    el.textContent = LEAF[Math.floor(Math.random() * LEAF.length)];
    el.style.left = (x - 9) + "px";
    el.style.top  = (y - 9) + "px";
    document.body.appendChild(el);
    requestAnimationFrame(() => el.classList.add("fly"));
    setTimeout(() => el.remove(), 1700);
  }

  // ── shrine — 累积到某 milestone, ornament + whisper ──
  const SHRINES = [
    { id: "water-3",        cond: () => state.counters.water >= 3,
      ornament: "氵", say: "三杯了 — 这就够了一半。" },
    { id: "water-7",        cond: () => state.counters.water >= 7,
      ornament: "氵氵", say: "今天第 7 杯水了。" },
    { id: "supplement-all", cond: () => state.counters.supplement >= 4,
      ornament: "丸", say: "四颗都齐了。" },
    { id: "ref-5",          cond: () => state.counters.ref >= 5,
      ornament: "✦", say: "今天我们已经看了 5 处 — 这一天有形状了。" },
    { id: "ref-12",         cond: () => state.counters.ref >= 12,
      ornament: "✦✦", say: "我们聊了 12 处了。明天回头看,这一天会清楚的。" },
  ];

  function checkShrines() {
    for (const s of SHRINES) {
      if (state.shrines[s.id]) continue;
      if (s.cond()) {
        state.shrines[s.id] = true;
        save();
        showOrnament(s.ornament);
        setTimeout(() => window.gateway?.whisper?.(s.say, 5200), 600);
      }
    }
  }

  function showOrnament(char) {
    const el = document.getElementById("shrineOrnament");
    if (!el) return;
    el.textContent = char;
    el.classList.add("on");
  }

  // restore previously-earned ornament on load
  function restoreOrnaments() {
    const earned = SHRINES.filter(s => state.shrines[s.id]);
    if (earned.length) {
      const last = earned[earned.length - 1];
      showOrnament(last.ornament);
    }
  }

  // ── tower — 第一次做某事, 解锁新元素或 hint ──────────
  const TOWERS = {
    "first-thread-open": "右栏一直在 — Esc 收回去。",
    "first-cup":         "水在记账。点的杯子会留下。",
    "first-pill":        "嗯。今天这一颗记上了。",
    "first-ref":         "我看见这一处了。说吧。",
    "first-hatch":       "好。告诉我想追什么 — 我现做。",
    "first-edit":        "改的字直接回到 md 那一边了。两边同一份。",
  };

  function unlockTower(id) {
    if (state.towers[id]) return false;
    state.towers[id] = true;
    save();
    const msg = TOWERS[id];
    if (msg) setTimeout(() => window.gateway?.whisper?.(msg, 4200), 200);
    return true;
  }

  // ── counter increment dispatch ───────────────────────
  function tick(kind) {
    state.counters[kind] = (state.counters[kind] || 0) + 1;
    save();
    checkShrines();

    // first-time towers wired to common kinds
    if (kind === "water")      unlockTower("first-cup");
    if (kind === "supplement") unlockTower("first-pill");
    if (kind === "ref")        unlockTower("first-ref");
    if (kind === "edit")       unlockTower("first-edit");
  }

  // ── first-visit nudge ────────────────────────────────
  function firstVisitNudge() {
    if (state.seenFirstNudge) return;
    state.visits++;
    if (state.visits < 1) state.visits = 1;
    // nudge after stream renders
    setTimeout(() => {
      const firstEntry = document.querySelector(".entry");
      if (firstEntry) firstEntry.classList.add("first-nudge");

      const firstEmptyCup = document.querySelector(".cup:not(.filled)");
      if (firstEmptyCup) firstEmptyCup.classList.add("wink");

      const hatch = document.getElementById("careHatch");
      if (hatch) {
        setTimeout(() => hatch.classList.add("wink"), 1800);
        setTimeout(() => hatch.classList.remove("wink"), 3200);
      }
    }, 1400);

    state.seenFirstNudge = true;
    save();
  }

  // ── 5-second-pause dots (margin korok) ───────────────
  let pauseTimer = null;
  function setupPauseDots() {
    document.addEventListener("mousemove", (e) => {
      const entry = e.target.closest?.(".entry");
      clearTimeout(pauseTimer);
      [...document.querySelectorAll(".entry-pause-dot.on")].forEach(d => d.classList.remove("on"));
      if (!entry) return;
      if (Math.random() > 0.35) return;  // 35% 概率
      pauseTimer = setTimeout(() => {
        if (!entry.querySelector(".entry-pause-dot")) {
          const dot = document.createElement("span");
          dot.className = "entry-pause-dot";
          dot.title = "我也注意到这里";
          dot.addEventListener("click", (ev) => {
            ev.stopPropagation();
            const time = entry.dataset.time;
            const text = entry.querySelector(".entry-text")?.textContent || "";
            window.gateway.thread?.addRef({
              kind: "korok",
              label: `${time} · 我也注意到这里`,
              payload: `用户在 [${time}] 这一段停了一会儿。原文:\n${text}`,
            });
          });
          entry.appendChild(dot);
        }
        entry.querySelector(".entry-pause-dot")?.classList.add("on");
      }, 5000);
    });
  }

  // ── hook thread open to fire 'first-thread-open' tower ──
  function hookThreadOpen() {
    const tab = document.getElementById("threadTab");
    const tt  = document.getElementById("threadToggleTop");
    [tab, tt].forEach(el => el?.addEventListener("click", () => {
      unlockTower("first-thread-open");
    }, { once: false }));
  }

  // ── hook addRef to count refs (intercept) ────────────
  function hookRefs() {
    const orig = window.gateway?.thread?.addRef;
    if (!orig) {
      // retry once thread.js is up
      setTimeout(hookRefs, 100);
      return;
    }
    window.gateway.thread.addRef = function (ref) {
      const r = orig(ref);
      tick("ref");
      return r;
    };
  }

  // ── public API ───────────────────────────────────────
  window.gateway = window.gateway || {};
  window.gateway.korok = { yahaha, tick, unlockTower };

  // ── boot ─────────────────────────────────────────────
  function boot() {
    restoreOrnaments();
    firstVisitNudge();
    setupPauseDots();
    hookThreadOpen();
    hookRefs();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
