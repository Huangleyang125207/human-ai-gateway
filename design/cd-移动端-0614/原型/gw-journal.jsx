// gw-journal.jsx — 日记页：八杯水(滑动点亮+放大) · 打卡横滑 · 时间线(左滑删/长按拉进对话)
const { useState, useRef, useEffect, useCallback } = React;

/* ───────── 八杯水：滑动点亮，触点那杯放大 ───────── */
function WaterCups({ readonly }) {
  const N = 8;
  const [filled, setFilled] = useState(3);
  const [focus, setFocus] = useState(-1);
  const [justIdx, setJustIdx] = useState(-1);
  const ref = useRef(null);

  const idxAt = (clientX) => {
    const cups = ref.current.querySelectorAll('.gw-cup');
    let best = -1, bestD = 1e9;
    cups.forEach((c, i) => {
      const r = c.getBoundingClientRect();
      const d = Math.abs(clientX - (r.left + r.width / 2));
      if (d < bestD) { bestD = d; best = i; }
    });
    return best;
  };
  const apply = (clientX) => {
    if (readonly) return;
    const i = idxAt(clientX);
    if (i < 0) return;
    setFocus(i);
    setFilled((prev) => { if (i + 1 > prev) setJustIdx(i); return i + 1; });
  };
  const onDown = (e) => { if (readonly) return; try { e.currentTarget.setPointerCapture(e.pointerId); } catch {} apply(e.clientX); };
  const onMove = (e) => { if (readonly) return; if (!e.currentTarget.hasPointerCapture?.(e.pointerId)) return; apply(e.clientX); };
  const onUp = () => { setFocus(-1); setTimeout(() => setJustIdx(-1), 950); };

  return (
    <div className="gw-care-block">
      <div className="gw-care-label">八杯水</div>
      <div className="gw-cups" ref={ref} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
        {Array.from({ length: N }).map((_, i) => (
          <div key={i} className={'gw-cup' + (i < filled ? ' filled' : '') + (i === focus ? ' cup-focus' : (Math.abs(i - focus) === 1 && focus >= 0 ? ' cup-near' : '')) + (i === justIdx ? ' just' : '')}>
            <div className="gw-cup-fill" />
          </div>
        ))}
      </div>
      <div className="gw-cups-count"><b>{filled}</b> / {N} 杯 · {readonly ? '历史日只读' : '滑过杯子点亮'}</div>
    </div>
  );
}

/* ───────── 打卡：横滑卡片，点 toggle ───────── */
function TaskStrip({ tasks, onToggle, readonly }) {
  return (
    <div className="gw-care-block">
      <div className="gw-care-label">今日打卡</div>
      <div className="gw-tasks">
        {tasks.map((t) => (
          <button key={t.id} className={'gw-task' + (t.on ? ' on' : '')} disabled={readonly}
            onClick={() => !readonly && onToggle(t.id)}>
            <span className="gw-task-glyph">{t.glyph}</span>
            <span className="gw-task-name">{t.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ───────── 单条 entry：左滑删除 + 长按拉进对话 ───────── */
function Entry({ entry, readonly, onDelete, onPull }) {
  const [dx, setDxState] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [lp, setLp] = useState(false);          // long-press 命中
  const [arming, setArming] = useState(false);  // 环动画中
  const st = useRef({ x: 0, y: 0, mode: null, timer: null, captured: false });
  const dxRef = useRef(0);
  const setDx = (v) => { dxRef.current = v; setDxState(v); };

  const clearTimer = () => { if (st.current.timer) { clearTimeout(st.current.timer); st.current.timer = null; } };

  const onDown = (e) => {
    if (e.button === 2) return;
    st.current = { x: e.clientX, y: e.clientY, mode: null, timer: null, captured: false };
    setArming(true);
    st.current.timer = setTimeout(() => {                 // 长按命中
      if (st.current.mode === null) {
        st.current.mode = 'lp';
        setLp(true);
        if (navigator.vibrate) navigator.vibrate(12);
        setTimeout(() => { onPull(entry); setLp(false); setArming(false); }, 420);
      }
    }, 480);
  };
  const onMove = (e) => {
    const adx = e.clientX - st.current.x, ady = e.clientY - st.current.y;
    if (st.current.mode === null && (Math.abs(adx) > 8 || Math.abs(ady) > 8)) {
      clearTimer(); setArming(false);
      if (Math.abs(adx) > Math.abs(ady) && adx < 0) {
        st.current.mode = 'swipe';
        st.current.captured = true;
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch {}
        setDragging(true);
      } else {
        st.current.mode = 'scroll';
      }
    }
    if (st.current.mode === 'swipe' && !readonly) {
      setDx(Math.max(-96, Math.min(0, adx)));
    }
  };
  const onUp = (e) => {
    clearTimer(); setArming(false);
    if (st.current.mode === 'swipe') {
      setDragging(false);
      if (dxRef.current < -60) {                          // 删除
        setDx(-window.innerWidth);
        setTimeout(() => onDelete(entry.id), 240);
      } else setDx(0);
    }
    st.current.mode = st.current.mode || 'tap';
  };

  return (
    <div className="gw-entry-wrap">
      <div className="gw-entry-del">删除</div>
      <div className={'gw-entry' + (dragging ? ' dragging' : '') + (lp ? ' longpress' : '') + (arming && !dragging ? ' lp-arming' : '')}
        style={{ transform: `translateX(${dx}px)` }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        onContextMenu={(e) => e.preventDefault()}>
        <div className="gw-lp-hint" />
        <div className="gw-entry-time"><span className="hr">{entry.time.split(':')[0]}</span>:{entry.time.split(':')[1]}</div>
        <div className="gw-entry-main">
          <div className="gw-entry-tags">
            {entry.tags.map((t) => <span key={t} className="gw-tag">{t}</span>)}
          </div>
          {entry.title && <div className="gw-entry-title">{entry.title}</div>}
          <Body paras={entry.body} />
          {entry.commits && (
            <div className="gw-commits">
              {entry.commits.map((c, i) => (
                <div key={i} className={'gw-commit ' + c.who}>
                  <span className="gw-commit-au">{c.who === 'ai' ? 'AI' : '我'}</span>
                  <span className="gw-commit-text">{c.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ───────── 日记页 ───────── */
function JournalScreen({ dayKey, entries, tasks, onToggleTask, onDelete, onPull, readonly }) {
  return (
    <div>
      <div className="gw-care">
        <WaterCups readonly={readonly} />
        <TaskStrip tasks={tasks} onToggle={onToggleTask} readonly={readonly} />
      </div>
      <div className="gw-stream">
        {entries.length === 0 ? (
          <div className="gw-empty"><b>这一天还是空白</b>点下面的 + 写下第一块，<br/>或滑日期带到今天自动落骨架。</div>
        ) : entries.map((e) => (
          <Entry key={e.id} entry={e} readonly={readonly} onDelete={onDelete} onPull={onPull} />
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { WaterCups, TaskStrip, Entry, JournalScreen });
