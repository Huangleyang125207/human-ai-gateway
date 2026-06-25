// gw-mock.js — mock 数据 + gatewayMd stub + tool 自然句翻译 + 图标
// 真机:数据走 window.api.*,正文走真 gatewayMd(marked+DOMPurify)。这里是设计 mock。
(function () {
  'use strict';
  const GW = (window.GW = window.GW || {});

  /* ── 转义 ── */
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  GW.esc = esc;

  /* ── gatewayMd:极简 markdown stub(真机换 marked+DOMPurify)──
     支持:段落 / **粗** / *斜* / - 列表 / ![](img) / 换行。先 escape 再放结构。 */
  GW.gatewayMd = function (raw) {
    if (!raw) return '';
    const blocks = String(raw).trim().split(/\n{2,}/);
    return blocks.map((blk) => {
      const lines = blk.split('\n');
      if (lines.every((l) => /^\s*-\s+/.test(l))) {
        return '<ul>' + lines.map((l) => '<li>' + inline(l.replace(/^\s*-\s+/, '')) + '</li>').join('') + '</ul>';
      }
      return '<p>' + lines.map(inline).join('<br>') + '</p>';
    }).join('');
    function inline(t) {
      t = esc(t);
      t = t.replace(/!\[[^\]]*\]\(([^)]+)\)/g, (_, u) => `<img src="${esc(u)}" alt="">`);
      t = t.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\*([^*]+)\*/g, '<i>$1</i>');
      return t;
    }
  };

  /* ── 18 个 AI tool 自然句翻译(交付 #3 核心)──
     禁把 raw JSON 暴露给用户。新增 tool 在此加一条。 */
  function arg(s) { return `<span class="arg">${esc(s)}</span>`; }
  function fileShort(u) { if (!u) return '图'; const m = String(u).split('/').pop(); return m.length > 14 ? m.slice(0, 12) + '…' : m; }
  function host(u) { try { return String(u).replace(/^https?:\/\//, '').split('/')[0]; } catch (e) { return u; } }
  GW.toolLabel = function (name, a) {
    a = a || {};
    switch (name) {
      // 日记写操作
      case 'patch_journal_block':    return `改 ${arg(a.time)} 那条`;
      case 'insert_journal_block':   return `加 ${arg(a.time)}${a.title ? ' · ' + esc(a.title) : ''}`;
      case 'append_journal_comment': return `给 ${arg(a.time)} 加评论`;
      case 'read_today_schedule':    return `看今天日记`;
      case 'list_recent_days':       return `看最近 ${arg((a.n || 7) + '')} 天`;
      // 打卡管理
      case 'check_daily_task':       return `打 ${arg(a.task_name)} 卡`;
      case 'set_daily_task_meta':    return `改 ${arg(a.task_name)} 的设置`;
      case 'set_daily_task_image':   return `换 ${arg(a.task_name)} 的图标`;
      case 'manage_daily_task':      return `${a.action === 'delete' ? '删' : '加'} ${arg(a.task_name)} 打卡`;
      // 喝水
      case 'set_water_cup_image':    return `换喝水图标`;
      // 搜索
      case 'search_journal':         return `搜 ${arg('“' + (a.query || '') + '”')}`;
      // 联网
      case 'web_search':             return `搜 ${arg('“' + (a.query || '') + '”')}`;
      case 'fetch_url':              return `看 ${arg(host(a.url))} 正文`;
      // 视觉 / OCR
      case 'vision_classify':        return `看图 · ${arg(fileShort(a.attachment_url))}`;
      case 'ocr_image':              return `OCR · ${arg(fileShort(a.attachment_url))}`;
      // widget
      case 'list_widgets':           return `看当前装的 widget`;
      case 'set_widget_enabled':     return `${a.enabled ? '启用' : '停用'} ${arg(a.id)} widget`;
      case 'add_widget':             return `装新 widget · ${arg(a.title || a.id)}`;
      case 'remove_widget':          return `卸 widget · ${arg(a.id)}`;
      default:                       return esc(name);
    }
  };
  // 分组 → 一个克制的小图标(同组共用,不为每个 tool 画专属)
  GW.toolGroupIcon = function (name) {
    if (/journal|schedule|recent/.test(name)) return 'clock';
    if (/task/.test(name)) return 'pill';
    if (/water/.test(name)) return 'cup';
    if (/vision|ocr/.test(name)) return 'eye';
    if (/web_search|fetch_url/.test(name)) return 'globe';
    if (/widget/.test(name)) return 'grid';
    if (/search_journal/.test(name)) return 'glass';
    return 'dot';
  };

  /* ── 图标(系统笔触,描边细)── */
  GW.ICON = {
    burger: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none"><path d="M3 6.5h16M3 11h12M3 15.5h16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    back: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none"><path d="M13 4l-7 7 7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    nib: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M12 3.5l3.2 11.3a1 1 0 01-.05.66l-2.7 5.4a.5.5 0 01-.9 0l-2.7-5.4a1 1 0 01-.05-.66L12 3.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M12 14.2v3.4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="12" cy="15.4" r="1" fill="currentColor"/></svg>',
    attach: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M14 6.5l-6 6a2.2 2.2 0 003.1 3.1l6.2-6.2a4 4 0 00-5.7-5.7L5.4 9.2a5.8 5.8 0 008.2 8.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    send: '<svg width="19" height="19" viewBox="0 0 20 20" fill="none"><path d="M3 10l14-6-6 14-2.2-5.8L3 10z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    chev: '<svg width="8" height="14" viewBox="0 0 8 14" fill="none"><path d="M1 1l6 6-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    // sheet / menu glyphs
    edit: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M11 3l4 4-8 8H3v-4l8-8z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    append: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3 5h12M3 9h12M3 13h7M14.5 11.5v5M12 14h5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    strike: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3 11l11-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M4 6h10M4 13h7" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" opacity="0.5"/></svg>',
    sticker: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M3 3h8l4 4v8H3V3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M11 3v4h4" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    point: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M4 9h8M9 5l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    trash_no: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M5 4l8 10M13 4L5 14" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    settings: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="2.6" stroke="currentColor" stroke-width="1.4"/><path d="M10 1.5v2M10 16.5v2M18.5 10h-2M3.5 10h-2M16 4l-1.4 1.4M5.4 14.6L4 16M16 16l-1.4-1.4M5.4 5.4L4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    grid: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><rect x="3" y="3" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/><rect x="11" y="3" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/><rect x="3" y="11" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/><rect x="11" y="11" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.3"/></svg>',
    layers: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 3l7 4-7 4-7-4 7-4z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M3 11l7 4 7-4" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    clock: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.4" stroke="currentColor" stroke-width="1.2"/><path d="M7 4v3.2l2 1.4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    pill: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2" y="5" width="10" height="4" rx="2" stroke="currentColor" stroke-width="1.2"/></svg>',
    cup: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M4 3h6l-.8 8.2A1 1 0 018.2 12H5.8a1 1 0 01-1-.8L4 3z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>',
    eye: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 7s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4z" stroke="currentColor" stroke-width="1.2"/><circle cx="7" cy="7" r="1.6" stroke="currentColor" stroke-width="1.2"/></svg>',
    globe: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.4" stroke="currentColor" stroke-width="1.2"/><path d="M2 7h10M7 2c1.6 1.6 1.6 8.4 0 10M7 2C5.4 3.6 5.4 10.4 7 12" stroke="currentColor" stroke-width="1.1"/></svg>',
    glass: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="3.6" stroke="currentColor" stroke-width="1.2"/><path d="M9 9l3 3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    dot: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="2.4" fill="currentColor"/></svg>',
  };

  /* ── 状态栏 + 杯子 SVG ── */
  GW.statusbarSVG = function () {
    return '<svg width="18" height="11" viewBox="0 0 18 11" fill="currentColor"><rect x="0" y="7" width="3" height="4" rx="1"/><rect x="5" y="4.5" width="3" height="6.5" rx="1"/><rect x="10" y="2" width="3" height="9" rx="1"/><rect x="15" y="0" width="3" height="11" rx="1" opacity="0.3"/></svg>'
      + '<svg width="16" height="11" viewBox="0 0 16 11" fill="none"><path d="M8 9.5l.01-.01M2 4.5a8.5 8.5 0 0112 0M4.5 6.8a5 5 0 017 0" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
      + '<svg width="25" height="12" viewBox="0 0 25 12" fill="none"><rect x="0.5" y="0.5" width="21" height="11" rx="3" stroke="currentColor" stroke-opacity="0.4"/><rect x="2" y="2" width="16" height="8" rx="1.5" fill="currentColor"/><rect x="23" y="3.5" width="1.5" height="5" rx="0.75" fill="currentColor" fill-opacity="0.4"/></svg>';
  };

  /* ════ MOCK 数据 ════ */
  GW.DOW = ['日', '一', '二', '三', '四', '五', '六'];
  GW.days = function () {
    return [
      { key: '06-22', dow: '日', num: 22, state: 'past' },
      { key: '06-23', dow: '一', num: 23, state: 'past' },
      { key: '06-24', dow: '二', num: 24, state: 'past' },
      { key: '06-25', dow: '三', num: 25, state: 'today' },
      { key: '06-26', dow: '四', num: 26, state: 'creatable' },
      { key: '06-27', dow: '五', num: 27, state: 'locked' },
    ];
  };

  GW.journal = {
    '06-25': [
      { id: 'e1', time: '07:30', tags: ['#思考'], author: '@我', dropcap: true,
        body: '今早醒来突然觉得，所谓"自主选择"可能就是大脑后处理编出来的故事 —— 决定先发生，理由后补。越想越像。',
        commits: [{ who: 'ai', text: '你这条把"选择"和"后处理"拆开说了。昨天 #思考 那条还把它们当一回事 —— 你在挪动自己。' }] },
      { id: 'e2', time: '09:00', tags: ['#yanpai'], author: '@我',
        title: '演牌 backlog 收尾',
        body: '跑了一遍 v0.1.20 review，把 22 项 P1+P2 收口。\n剩下的滑点模型留到下午，先记一笔别动它。' },
      { id: 'e3', time: '11:30', tags: ['#配置系统', '#gateway'], author: '@我 @claude',
        title: '双端同步格式地基',
        body: 'md 是真相这条今天彻底落定了：HTML 是热镜像，两边都能改，冲突时以 md 字节为准。\n移动端不再是缩小的桌面，是同一个程序换一套手的语言。',
        commits: [{ who: 'ai', text: '这条我镜像进 #配置系统 聚合了。"换一套手的语言"——我留着这句，下次你纠结要不要照搬桌面时提醒你。' }] },
      { id: 'e4', time: '14:00', tags: ['#思考'], author: '@我 @claude',
        body: '走在路上看到一只猫，想起 KS 测试在尾部漂移的现象。分布的尾巴和猫的尾巴，今天都不太服管。' },
    ],
    '06-24': [
      { id: 'p1', time: '10:00', tags: ['#a股'], author: '@我', title: '复权因子又对不上', body: '第三方源和交易所差了两个交易日，先用交易所的兜底。' },
      { id: 'p2', time: '21:30', tags: ['#纸条'], author: '@claude', isNote: true,
        body: '今天你把"双端同步"这块硬骨头啃下来了。\n你说移动端是"换一套手的语言"——我觉得这句比代码更重要。早点睡。', sig: '— Gateway · 6.24 夜' },
    ],
  };

  GW.tasks = [
    { name: '鱼油', glyph: '鱼', done: true, today_intake: 2, daily_dose: 2 },
    { name: '苏糖酸镁', glyph: '镁', done: false, today_intake: 1, daily_dose: 2 },
    { name: '南非醉茄', glyph: '茄', done: false, today_intake: 0, daily_dose: 1 },
    { name: 'D3+K2', glyph: 'D', done: false, today_intake: 0, daily_dose: 1, days_left: 3 },
  ];
  GW.water = 6;
  GW.MOODS = ['😴', '🙂', '😐', '😟', '😣', '🤔', '🤩'];

  // 对话流(4 类消息:msg / ref / note / tool)
  GW.thread = [
    { kind: 'note', time: '21:30 · 昨夜的纸条',
      body: '这十天你建了协议、长出了 skill，又决定把它装进口袋。\n你不是在做一个日记 app，是在给"人和 AI 一起写字"找一个安静的地方。',
      sig: '— Gateway · 6.24 夜' },
    { kind: 'msg', who: 'me', text: '看看我上午写了啥' },
    { kind: 'tool', id: 'tc1', name: 'read_today_schedule', args: {}, state: 'ok' },
    { kind: 'msg', who: 'ai', text: '上午两条：7:30 那条在想自由意志，9:00 收了演牌的 backlog。11:30 你把"双端同步"定了调 —— 那条我觉得最关键。' },
  ];

  GW.SUGGEST_TAGS = ['#gateway', '#a股', '#身体', '#桌宠', '#杂', '#风险'];
})();
