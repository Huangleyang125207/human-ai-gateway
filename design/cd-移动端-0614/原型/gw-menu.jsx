// gw-menu.jsx — ☰ 底部抽屉 + 设置页（双钥匙：阿里云·眼睛 / DeepSeek·声音）
const { useState } = React;

const MENU = [
  { id: 'settings', glyph: I.settings, label: '设置', desc: '钥匙 · 模型 · 皮肤' },
  { id: 'aggregate', glyph: I.aggregate, label: '聚合页', desc: '按 #标签 横切' },
  { id: 'widget', glyph: I.widget, label: '小组件', desc: '打卡 · 八杯水 · 脉搏' },
  { id: 'history', glyph: I.history, label: '历史', desc: '往日翻阅' },
  { id: 'about', glyph: I.about, label: '关于', desc: 'Gateway · 私印小报' },
];

function MenuDrawer({ open, onClose, onPick }) {
  const [show, setShow] = useState(false);
  const [on, setOn] = useState(false);
  React.useEffect(() => {
    if (open) { setShow(true); requestAnimationFrame(() => setOn(true)); }
    else if (show) { setOn(false); const t = setTimeout(() => setShow(false), 460); return () => clearTimeout(t); }
  }, [open]);
  if (!show) return null;
  return (
    <React.Fragment>
      <div className={'gw-scrim' + (on ? ' on' : '')} onPointerDown={onClose} />
      <div className={'gw-drawer' + (on ? ' on' : '')}>
        <div className="gw-drawer-grip" />
        <div className="gw-drawer-head">
          <span className="gw-drawer-brand">Gateway</span>
          <span className="gw-drawer-sub">人和 AI 共写的一本日记</span>
        </div>
        {MENU.map((m) => (
          <button key={m.id} className="gw-menu-item" onClick={() => onPick(m.id)}>
            <span className="gw-menu-glyph">{m.glyph()}</span>
            <span className="gw-menu-label">{m.label}</span>
            <span className="gw-menu-desc">{m.desc}</span>
            <span className="gw-menu-chev">{I.chev()}</span>
          </button>
        ))}
      </div>
    </React.Fragment>
  );
}

/* ───────── 设置页（钥匙 / 模型 / 皮肤 / 数据）───────── */
function SettingsScreen() {
  const [k1, setK1] = useState('');
  const [k2, setK2] = useState('sk-••••••••••••3f9a');
  const [k1ok, setK1ok] = useState(false);
  const [k2ok, setK2ok] = useState(true);
  const [testing, setTesting] = useState('');
  const [skin, setSkin] = useState('day');
  const [breath, setBreath] = useState(true);
  const [reduce, setReduce] = useState(false);

  const test = (which) => {
    setTesting(which);
    setTimeout(() => {
      if (which === 'k1') setK1ok(true); else setK2ok(true);
      setTesting('');
    }, 1100);
  };

  return (
    <div className="gw-set">
      <div className="gw-set-sec">
        <div className="gw-set-sec-lab">双钥匙 · 给它声音和眼睛</div>

        <div className={'gw-key' + (k2ok ? ' ok' : '')}>
          <div className="gw-key-head">
            <span className="gw-key-role">DeepSeek</span>
            <span className="gw-key-tag">· 说话的那个</span>
          </div>
          <div className="gw-key-desc">常驻对话、夹批、21:30 的纸条，都从这把钥匙发声。</div>
          <div className="gw-key-row">
            <input className="gw-key-in" value={k2} onChange={(e) => { setK2(e.target.value); setK2ok(false); }} placeholder="sk-…" />
            <button className="gw-key-test" onClick={() => test('k2')}>{testing === 'k2' ? '测试中…' : '测试'}</button>
          </div>
          <div className={'gw-key-status ' + (k2ok ? 'ok' : 'idle')}>{k2ok ? '已连通 · deepseek-chat' : '待测试'}</div>
        </div>

        <div className={'gw-key' + (k1ok ? ' ok' : '')}>
          <div className="gw-key-head">
            <span className="gw-key-role">阿里云百炼</span>
            <span className="gw-key-tag">· 看东西的那只眼</span>
          </div>
          <div className="gw-key-desc">抠图、看照片里有什么、自动定位贴纸——视觉都走这把钥匙。可选，填了才长出眼睛。</div>
          <div className="gw-key-row">
            <input className="gw-key-in" value={k1} onChange={(e) => { setK1(e.target.value); setK1ok(false); }} placeholder="粘贴百炼 API Key…" />
            <button className="gw-key-test" onClick={() => test('k1')}>{testing === 'k1' ? '测试中…' : '测试'}</button>
          </div>
          <div className={'gw-key-status ' + (k1ok ? 'ok' : 'idle')}>{k1ok ? '已连通 · qwen-vl' : '未填 · 暂无视觉'}</div>
        </div>
      </div>

      <div className="gw-set-sec">
        <div className="gw-set-sec-lab">皮肤</div>
        <div className="gw-row">
          <div className="gw-row-main">
            <div className="gw-row-title">私印小报 · classic</div>
            <div className="gw-row-desc">米黄纸 + 4 粉彩。夜色是另一套皮肤，暂未上线。</div>
          </div>
          <div className="gw-seg">
            <button className={skin === 'day' ? 'on' : ''} onClick={() => setSkin('day')}>日间</button>
            <button className={skin === 'night' ? 'on' : ''} onClick={() => setSkin('night')} style={{ opacity: 0.5 }}>夜</button>
          </div>
        </div>
        <div className="gw-row">
          <div className="gw-row-main">
            <div className="gw-row-title">呼吸暖光</div>
            <div className="gw-row-desc">页面背后那束慢慢起伏的光。</div>
          </div>
          <div className={'gw-toggle' + (breath ? ' on' : '')} onClick={() => setBreath(!breath)} />
        </div>
      </div>

      <div className="gw-set-sec">
        <div className="gw-set-sec-lab">数据 · 无障碍</div>
        <div className="gw-row">
          <div className="gw-row-main">
            <div className="gw-row-title">减少动效</div>
            <div className="gw-row-desc">关掉呼吸、墨迹、纸页翻动。</div>
          </div>
          <div className={'gw-toggle' + (reduce ? ' on' : '')} onClick={() => setReduce(!reduce)} />
        </div>
        <div className="gw-row">
          <div className="gw-row-main">
            <div className="gw-row-title">本地 vault 路径</div>
            <div className="gw-row-desc">MD 是真相 · 存在你自己的设备里。</div>
          </div>
          <span className="gw-row-val">~/Gateway ⟩</span>
        </div>
        <div className="gw-row">
          <div className="gw-row-main">
            <div className="gw-row-title">云上报与撤回</div>
            <div className="gw-row-desc">同意书 · 诊断 · 随时撤回。</div>
          </div>
          <span className="gw-menu-chev">{I.chev()}</span>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { MenuDrawer, SettingsScreen, MENU });
