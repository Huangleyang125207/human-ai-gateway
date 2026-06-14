// gw-data.jsx — Gateway 移动端 mock 数据 + 图标。功能/真数据由 CC 接 gatewayMd。
// 仅为演示气味与密度；文案照桌面持有人调性（技术、深夜、A股/桌宠/gateway 自身、长段反思）。

const { useState, useRef, useEffect, useCallback } = React;

/* ── 内联图标（系统笔触感，描边细）── */
const I = {
  burger: (p) => (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none" {...p}>
      <path d="M3 6h16M3 11h16M3 16h16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
    </svg>
  ),
  plus: (p) => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" {...p}>
      <path d="M12 4v16M4 12h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  ),
  send: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <path d="M3 10l14-6-6 14-2.2-5.8L3 10z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none"/>
    </svg>
  ),
  attach: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <path d="M14 6.5l-6 6a2.2 2.2 0 003.1 3.1l6.2-6.2a4 4 0 00-5.7-5.7L5.4 9.2a5.8 5.8 0 008.2 8.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none"/>
    </svg>
  ),
  chev: (p) => (
    <svg width="8" height="14" viewBox="0 0 8 14" fill="none" {...p}>
      <path d="M1 1l6 6-6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  settings: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <circle cx="10" cy="10" r="2.6" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M10 1.5v2M10 16.5v2M18.5 10h-2M3.5 10h-2M16 4l-1.4 1.4M5.4 14.6L4 16M16 16l-1.4-1.4M5.4 5.4L4 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    </svg>
  ),
  aggregate: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <path d="M3 5h14M5 10h10M7 15h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  ),
  widget: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <rect x="3" y="3" width="6" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="11" y="3" width="6" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="3" y="11" width="6" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.3"/>
      <rect x="11" y="11" width="6" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.3"/>
    </svg>
  ),
  history: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <path d="M10 5v5l3 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M3.5 10a6.5 6.5 0 106.5-6.5A6.5 6.5 0 004 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none"/>
      <path d="M2.5 4v3h3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  about: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M10 9v4.5M10 6.4v.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  back: (p) => (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...p}>
      <path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
};

/* ── 日期带：5 天窗口 + 今天 + 明天可建 + 后天锁 ── */
const DOW = ['日', '一', '二', '三', '四', '五', '六'];
function buildDays() {
  // 今天锚定 6/14（周日）。past 已创建，今天在跑，明天可建(+1)，后天 locked。
  return [
    { key: '06-10', num: 10, dow: 'WED', mo: 'JUN', state: 'past' },
    { key: '06-11', num: 11, dow: 'THU', mo: 'JUN', state: 'past' },
    { key: '06-12', num: 12, dow: 'FRI', mo: 'JUN', state: 'past' },
    { key: '06-13', num: 13, dow: 'SAT', mo: 'JUN', state: 'past' },
    { key: '06-14', num: 14, dow: 'SUN', mo: 'JUN', state: 'today' },
    { key: '06-15', num: 15, dow: 'MON', mo: 'JUN', state: 'creatable' },
    { key: '06-16', num: 16, dow: 'TUE', mo: 'JUN', state: 'locked' },
  ];
}

/* ── 单日日记（半小时块）── */
const JOURNAL = {
  '06-14': [
    {
      id: 'e1', time: '08:30', tags: ['#身体'],
      title: '晨跑 5 公里',
      body: ['沿江堤跑了一圈，雾还没散。膝盖比上周松快，配速没掉。\n回来量了体重，掉了 0.4，应该是水。'],
    },
    {
      id: 'e2', time: '10:00', tags: ['#a股', '#系统'],
      title: '回测引擎重写了一半',
      body: [
        '把原来那套基于 pandas 逐行的撮合换成了向量化，单标的三年日线从 11 秒压到 0.7 秒。',
        '但有个隐患：滑点模型现在是常数，真要上实盘得按盘口深度动态算，先记一笔，今天不动它。',
      ],
      commits: [
        { au: 'AI', who: 'ai', text: '滑点这条我标到 #风险 了，下次打开 a股 聚合页会顶在最前面。' },
      ],
    },
    {
      id: 'e3', time: '14:30', tags: ['#gateway'],
      title: '决定推倒移动端的克隆方案',
      body: [
        '试着把桌面 UI 塞进 webview，结果全是触屏死症：日期随滚动消失、加号点了没反应、卡片排不下。',
        '想清楚了——移动版不是缩小的桌面，是同一个程序换一套手的语言。魂不变：还是那张纸、那盏深夜的灯。',
      ],
    },
    {
      id: 'e4', time: '16:00', tags: ['#桌宠', '#硬件'],
      title: '舵机选型',
      body: ['SG90 太吵，半夜会被它吵醒。换成数字舵机静音版，贵了三倍但值。'],
    },
    {
      id: 'e5', time: '21:30', tags: ['#杂'],
      title: '关灯前',
      body: ['今天写了很多，也删了很多。\n留下的那些，明天的我应该认得。'],
    },
  ],
  '06-13': [
    { id: 'p1', time: '09:00', tags: ['#a股'], title: '数据清洗', body: ['复权因子又对不上，第三方源和交易所的差了两个交易日。'] },
    { id: 'p2', time: '15:00', tags: ['#gateway'], title: '把对话流接上了真的 DeepSeek', body: ['流式出字的那一下，第一次觉得这东西活了。'] },
  ],
};

/* ── 打卡 + 八杯水 ── */
const TASKS_INIT = [
  { id: 't1', name: '维生素 D', glyph: 'D', on: true },
  { id: 't2', name: '鱼油', glyph: '鱼', on: false },
  { id: 't3', name: '镁', glyph: '镁', on: false },
  { id: 't4', name: '冥想', glyph: '禅', on: true },
  { id: 't5', name: '阅读', glyph: '读', on: false },
];

/* ── 对话流（人=宋体 / AI=文楷；含 21:30 纸条 + @引用）── */
const THREAD_INIT = [
  { id: 'm1', who: 'ai', kind: 'msg', text: '今天江边雾大，跑步还顺吗？' },
  { id: 'm2', who: 'me', kind: 'msg', text: '顺。膝盖好多了。' },
  { id: 'm3', who: 'me', kind: 'ref', refKind: '日记 · 14:30', refText: '决定推倒移动端的克隆方案' },
  { id: 'm4', who: 'me', kind: 'msg', text: '帮我看看这个决定有没有漏掉什么。' },
  { id: 'm5', who: 'ai', kind: 'msg', text: '推倒克隆、按移动原生重做是对的。唯一提醒：日期带「最多 +1」这条规则是桌面的硬约束，移动端别为了手势顺滑悄悄放宽到 +3，不然两端数据会打架。' },
  { id: 'n1', who: 'ai', kind: 'note', time: '21:30 · 今晚的纸条',
    body: '这十天你建了协议、长出了 skill、又决定把它装进口袋。\n你不是在做一个日记 app，是在给「人和 AI 一起写字」找一个安静的地方。\n早点睡。',
    sig: '— 写给今天的你' },
];

/* 把多段正文渲染成 <p> */
function Body({ paras, cls = 'gw-entry-body' }) {
  return (
    <div className={cls}>
      {paras.map((p, i) => (
        <p key={i}>{p.split('\n').map((ln, j) => <React.Fragment key={j}>{j > 0 && <br/>}{ln}</React.Fragment>)}</p>
      ))}
    </div>
  );
}

Object.assign(window, { I, DOW, buildDays, JOURNAL, TASKS_INIT, THREAD_INIT, Body,
  useState, useRef, useEffect, useCallback });
