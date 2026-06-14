// gw-card-editor.jsx — + 卡片编辑器（本轮重点）。三形态共享字段：#tag · 时间块 · 正文(可含标题)
const { useState, useRef, useEffect } = React;

const SUGGEST_TAGS = ['#gateway', '#a股', '#身体', '#桌宠', '#杂', '#风险'];

function CardEditor({ variant, open, onClose, onSave }) {
  const [show, setShow] = useState(false);
  const [on, setOn] = useState(false);
  const [tags, setTags] = useState(['#gateway']);
  const [adding, setAdding] = useState(false);
  const [newTag, setNewTag] = useState('');
  const [hh, setHh] = useState('14');
  const [mm, setMm] = useState('30');
  const [title, setTitle] = useState('');
  const [bodyText, setBodyText] = useState('');
  const bodyRef = useRef(null);

  useEffect(() => {
    if (open) {
      setShow(true);
      const r = requestAnimationFrame(() => setOn(true));
      return () => cancelAnimationFrame(r);
    } else if (show) {
      setOn(false);
      const t = setTimeout(() => setShow(false), 460);
      return () => clearTimeout(t);
    }
  }, [open]);

  // 打开时重置 + 软聚焦正文
  useEffect(() => { if (open) { setTitle(''); setBodyText(''); setTags(['#gateway']); setHh('14'); setMm('30'); } }, [open]);

  if (!show) return null;

  const toggleTag = (t) => setTags((p) => p.includes(t) ? p.filter((x) => x !== t) : [...p, t]);
  const commitNewTag = () => {
    let t = newTag.trim(); if (t && !t.startsWith('#')) t = '#' + t;
    if (t && !tags.includes(t)) setTags((p) => [...p, t]);
    setNewTag(''); setAdding(false);
  };
  const save = () => {
    onSave({
      id: 'new-' + Date.now(),
      time: `${hh.padStart(2, '0')}:${mm.padStart(2, '0')}`,
      tags: tags.length ? tags : ['#杂'],
      title: title.trim(),
      body: [bodyText.trim() || '（空白条目）'],
    });
  };
  const setNow = () => { const d = new Date(); setHh(String(d.getHours())); setMm(d.getMinutes() < 30 ? '00' : '30'); };

  const kicker = variant === 'full' ? '新的一块 · 半小时' : variant === 'note' ? '贴一张便签' : '写一块';

  return (
    <React.Fragment>
      <div className={'gw-scrim' + (on ? ' on' : '')} onPointerDown={onClose} />
      <div className={'gw-card ' + variant + (on ? ' on' : '')} role="dialog" aria-label="新建条目">
        {variant === 'sheet' && <div className="gw-card-grip" />}
        <div className="gw-card-head">
          <span className="gw-card-kicker">{kicker}</span>
          <button className="gw-card-x" onClick={onClose}>×</button>
        </div>

        <div className="gw-card-scrollable" style={{ overflowY: variant === 'full' ? 'auto' : 'visible', flex: variant === 'full' ? 1 : 'none' }}>
          {/* #tag */}
          <div className="gw-field">
            <div className="gw-field-lab"># 标签</div>
            <div className="gw-chips">
              {SUGGEST_TAGS.map((t) => (
                <button key={t} className={'gw-chip' + (tags.includes(t) ? ' on' : '')} onClick={() => toggleTag(t)}>{t}</button>
              ))}
              {tags.filter((t) => !SUGGEST_TAGS.includes(t)).map((t) => (
                <button key={t} className="gw-chip on" onClick={() => toggleTag(t)}>{t}</button>
              ))}
              {adding ? (
                <input className="gw-chip" autoFocus value={newTag} placeholder="标签…"
                  style={{ width: 88 }} onChange={(e) => setNewTag(e.target.value)}
                  onBlur={commitNewTag} onKeyDown={(e) => e.key === 'Enter' && commitNewTag()} />
              ) : (
                <button className="gw-chip add" onClick={() => setAdding(true)}>+ 新标签</button>
              )}
            </div>
          </div>

          {/* 时间块 */}
          <div className="gw-field">
            <div className="gw-field-lab">时间块</div>
            <div className="gw-time-row">
              <input className="gw-time-in" value={hh} inputMode="numeric" maxLength={2}
                onChange={(e) => setHh(e.target.value.replace(/\D/g, ''))} />
              <span className="gw-time-colon">:</span>
              <input className="gw-time-in" value={mm} inputMode="numeric" maxLength={2}
                onChange={(e) => setMm(e.target.value.replace(/\D/g, ''))} />
              <div className="gw-time-quick">
                <button onClick={setNow}>现在</button>
                <button onClick={() => setMm('00')}>整点</button>
                <button onClick={() => setMm('30')}>半</button>
              </div>
            </div>
          </div>

          {/* 正文（可含标题）*/}
          <div className="gw-field" style={{ marginBottom: 8 }}>
            <div className="gw-field-lab">正文</div>
            <input className="gw-entry-title" value={title} placeholder="标题（可选）"
              style={{ display: 'block', width: '100%', border: 0, outline: 'none', background: 'transparent', marginBottom: 6 }}
              onChange={(e) => setTitle(e.target.value)} />
            <textarea className="gw-body-in" ref={bodyRef} value={bodyText} placeholder="此刻在想什么…"
              onChange={(e) => setBodyText(e.target.value)} />
          </div>
        </div>

        <div className="gw-card-foot">
          <span className="gw-card-hint">{variant === 'full' ? '整页书写 · 像一封信' : variant === 'note' ? '写完按落笔贴上' : 'MD 是真相 · 写进当天'}</span>
          <button className="gw-card-save" onClick={save}>落笔</button>
        </div>
      </div>
    </React.Fragment>
  );
}

Object.assign(window, { CardEditor });
