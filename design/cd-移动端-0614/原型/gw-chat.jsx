// gw-chat.jsx — 对话流：人(宋体)/AI(文楷)气泡 · @引用卡 · 21:30 纸条仪式 · 磨墨等待
const { useEffect, useRef } = React;

function ChatScreen({ thread, grinding, endRef }) {
  return (
    <div className="gw-thread">
      {thread.map((m) => {
        if (m.kind === 'ref') return (
          <div key={m.id} className="gw-ref">
            <div className="rk">{m.refKind}</div>
            <div className="rt">{m.refText}</div>
          </div>
        );
        if (m.kind === 'note') return (
          <div key={m.id} className="gw-note">
            <div className="gw-note-time">{m.time}</div>
            <div className="gw-note-body">
              {m.body.split('\n').map((ln, j) => <React.Fragment key={j}>{j > 0 && <br/>}{ln}</React.Fragment>)}
            </div>
            <div className="gw-note-sig">{m.sig}</div>
          </div>
        );
        return (
          <div key={m.id} className={'gw-msg ' + m.who}>
            <span className="who">{m.who === 'ai' ? 'Gateway' : '我'}</span>
            <div className={'gw-bubble' + (m.streaming ? ' gw-cursor' : '')}>{m.text}</div>
          </div>
        );
      })}
      {grinding && (
        <div className="gw-grind">
          <span className="gw-grind-stone" />
          <span className="gw-grind-text">磨墨中…</span>
        </div>
      )}
      <div ref={endRef} style={{ height: 1 }} />
    </div>
  );
}

Object.assign(window, { ChatScreen });
