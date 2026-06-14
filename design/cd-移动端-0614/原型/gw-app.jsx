// gw-app.jsx — 主壳：顶栏(下滑收起) · 渐变日期带(滑/点建明天) · 日记/对话 · 底栏 + / 输入 · 抽屉
const { useState, useRef, useEffect, useCallback } = React;

const REPLIES = [
  '记下了。这条我归到 #gateway，跟昨天「接上真 DeepSeek」串成一条线了。',
  '同意。不过别忘了——日期带「最多 +1」是桌面的硬规则，移动端只换手势、不动语义。',
  '好。我先不打扰你写，需要我夹批的时候长按那条拉给我就行。',
];

function GatewayApp({ platform, safeTop, safeBot, cardVariant, onHint }) {
  const [tab, setTab] = useState('journal');
  const [subPage, setSubPage] = useState(null);
  const [days, setDays] = useState(buildDays);
  const [dayKey, setDayKey] = useState('06-14');
  const [journal, setJournal] = useState(() => JSON.parse(JSON.stringify(JOURNAL)));
  const [tasks, setTasks] = useState(() => JSON.parse(JSON.stringify(TASKS_INIT)));
  const [thread, setThread] = useState(() => JSON.parse(JSON.stringify(THREAD_INIT)));
  const [cardOpen, setCardOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [grinding, setGrinding] = useState(false);
  const [topHidden, setTopHidden] = useState(false);
  const [undo, setUndo] = useState(null);
  const [hint, setHintState] = useState('');
  const [chatInput, setChatInput] = useState('');

  const scrollRef = useRef(null);
  const bandRef = useRef(null);
  const endRef = useRef(null);
  const lastTop = useRef(0);
  const undoTimer = useRef(null);
  const hintTimer = useRef(null);
  const replyIdx = useRef(0);

  const dayState = (days.find((d) => d.key === dayKey) || {}).state;
  const readonly = dayState === 'past';
  const entries = (journal[dayKey] || []).slice().sort((a, b) => a.time.localeCompare(b.time));

  const flash = useCallback((msg) => {
    setHintState(msg);
    clearTimeout(hintTimer.current);
    hintTimer.current = setTimeout(() => setHintState(''), 2200);
  }, []);

  // 顶栏：下滑收起 / 上滑唤回
  const onScroll = () => {
    const t = scrollRef.current.scrollTop;
    if (t > lastTop.current + 6 && t > 70) setTopHidden(true);
    else if (t < lastTop.current - 6) setTopHidden(false);
    lastTop.current = t;
  };

  // 居中今天
  useEffect(() => {
    const band = bandRef.current; if (!band) return;
    const el = band.querySelector('.today');
    if (el) band.scrollLeft = el.offsetLeft - band.clientWidth / 2 + el.offsetWidth / 2;
  }, []);

  // 对话滚到底
  useEffect(() => {
    if (tab === 'chat' && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [thread, grinding, tab]);

  const pickDay = (d) => {
    if (d.state === 'locked') { flash('最多只能建到明天（+1）'); return; }
    if (d.state === 'creatable') {              // 创建明天
      setJournal((j) => ({ ...j, [d.key]: [] }));
      setDays((ds) => ds.map((x) => x.key === d.key ? { ...x, state: 'created', born: true } : x));
      setDayKey(d.key); setTab('journal');
      flash('明天已创建 · 落了张空骨架');
      setTimeout(() => setDays((ds) => ds.map((x) => x.key === d.key ? { ...x, born: false } : x)), 1200);
      return;
    }
    setDayKey(d.key); setTab('journal');
  };

  const toggleTask = (id) => setTasks((ts) => ts.map((t) => t.id === id ? { ...t, on: !t.on } : t));

  const deleteEntry = (id) => {
    const ent = (journal[dayKey] || []).find((e) => e.id === id);
    setJournal((j) => ({ ...j, [dayKey]: (j[dayKey] || []).filter((e) => e.id !== id) }));
    setUndo({ entry: ent, dayKey });
    clearTimeout(undoTimer.current);
    undoTimer.current = setTimeout(() => setUndo(null), 5000);
  };
  const doUndo = () => {
    if (!undo) return;
    setJournal((j) => ({ ...j, [undo.dayKey]: [...(j[undo.dayKey] || []), undo.entry] }));
    setUndo(null); clearTimeout(undoTimer.current);
  };

  const pullToChat = (entry) => {
    setThread((t) => [...t, { id: 'ref-' + Date.now(), who: 'me', kind: 'ref', refKind: `日记 · ${entry.time}`, refText: entry.title || entry.body[0].slice(0, 24) }]);
    flash('已拉进对话 ✦ 指给 AI 看');
  };

  const saveCard = (entry) => {
    setJournal((j) => ({ ...j, [dayKey]: [...(j[dayKey] || []), entry] }));
    setCardOpen(false);
    flash('已落笔 · 写进 ' + entry.time);
  };

  const send = () => {
    const text = chatInput.trim(); if (!text) return;
    setChatInput('');
    setThread((t) => [...t, { id: 'u-' + Date.now(), who: 'me', kind: 'msg', text }]);
    setGrinding(true);
    setTimeout(() => {
      setGrinding(false);
      const id = 'a-' + Date.now();
      const full = REPLIES[replyIdx.current % REPLIES.length]; replyIdx.current++;
      setThread((t) => [...t, { id, who: 'ai', kind: 'msg', text: '', streaming: true }]);
      let i = 0;
      const iv = setInterval(() => {
        i++;
        setThread((t) => t.map((m) => m.id === id ? { ...m, text: full.slice(0, i) } : m));
        if (i >= full.length) { clearInterval(iv); setThread((t) => t.map((m) => m.id === id ? { ...m, streaming: false } : m)); }
      }, 34);
    }, 1050);
  };

  const pickMenu = (id) => { setMenuOpen(false); setSubPage(id); };

  const styleVars = { '--safe-top': safeTop + 'px', '--safe-bot': safeBot + 'px' };

  // 子页（设置 / 其余占位）
  if (subPage) {
    const meta = MENU.find((m) => m.id === subPage);
    return (
      <div className="gw" style={styleVars}>
        <div className="gw-breath" /><div className="gw-grain" />
        <div className="gw-top" style={{ position: 'static' }}>
          <div className="gw-top-row1">
            <button className="gw-burger" onClick={() => setSubPage(null)}>{I.back()}</button>
            <div className="gw-tabs"><span className="gw-tab on" style={{ cursor: 'default' }}>{meta.label}</span></div>
            <div className="gw-top-spacer" /><span className="gw-breathdot" />
          </div>
        </div>
        <div className="gw-scroll">
          {subPage === 'settings' ? <SettingsScreen /> : (
            <div className="gw-empty"><b>{meta.label}</b>{meta.desc}。<br/>桌面已有，移动端按路线图一个一个往上加。</div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="gw" style={styleVars}>
      <div className="gw-breath" /><div className="gw-grain" />

      <div className="gw-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className={'gw-top' + (topHidden ? ' hidden' : '')}>
          <div className="gw-top-row1">
            <button className="gw-burger" onClick={() => setMenuOpen(true)}>{I.burger()}</button>
            <div className="gw-tabs">
              <button className={'gw-tab' + (tab === 'journal' ? ' on' : '')} onClick={() => setTab('journal')}>日记</button>
              <button className={'gw-tab' + (tab === 'chat' ? ' on' : '')} onClick={() => setTab('chat')}>对话</button>
            </div>
            <div className="gw-top-spacer" />
            <span className="gw-breathdot" />
          </div>
          <div className="gw-dateband" ref={bandRef}>
            {days.map((d) => (
              <button key={d.key}
                className={'gw-day'
                  + (d.state === 'today' ? ' today' : '')
                  + (d.key === dayKey ? ' on' : '')
                  + (d.state === 'creatable' ? ' future creatable' : '')
                  + (d.state === 'locked' ? ' future locked' : '')
                  + (d.born ? ' born' : '')}
                onClick={() => pickDay(d)}>
                <span className="gw-day-dow">{d.dow}</span>
                <span className="gw-day-num">{d.num}</span>
                <span className="gw-day-mo">{d.state === 'today' ? '今天' : d.state === 'creatable' ? '明天' : d.mo}</span>
                {d.state === 'creatable' && <span className="gw-day-plus">+</span>}
              </button>
            ))}
          </div>
        </div>

        {tab === 'journal'
          ? <JournalScreen dayKey={dayKey} entries={entries} tasks={tasks} onToggleTask={toggleTask}
              onDelete={deleteEntry} onPull={pullToChat} readonly={readonly} />
          : <ChatScreen thread={thread} grinding={grinding} endRef={endRef} />}
      </div>

      {/* 底栏 */}
      <div className="gw-bottom">
        {tab === 'journal' ? (
          <div className="gw-fab-row">
            <button className={'gw-fab' + (cardOpen ? ' open' : '')} onClick={() => setCardOpen(true)} aria-label="新建条目">{I.plus()}</button>
          </div>
        ) : (
          <div className="gw-chatbar">
            <button className="gw-chat-attach">{I.attach()}</button>
            <textarea className="gw-chat-input" rows={1} value={chatInput} placeholder="跟 Gateway 说点什么…"
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <button className="gw-chat-send" disabled={!chatInput.trim()} onClick={send}>{I.send()}</button>
          </div>
        )}
      </div>

      {/* 撤回 toast */}
      {undo && (
        <div className="gw-undo on">
          <span className="gw-undo-msg">已删除「{undo.entry?.title || '条目'}」</span>
          <button className="gw-undo-btn" onClick={doUndo}>撤回</button>
          <span className="gw-undo-bar" style={{ animation: 'gw-undobar 5s linear forwards' }} />
        </div>
      )}

      <div className={'gw-hint-toast' + (hint ? ' on' : '')}>{hint}</div>

      <CardEditor variant={cardVariant} open={cardOpen} onClose={() => setCardOpen(false)} onSave={saveCard} />
      <MenuDrawer open={menuOpen} onClose={() => setMenuOpen(false)} onPick={pickMenu} />
    </div>
  );
}

Object.assign(window, { GatewayApp });
