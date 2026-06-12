# gateway · v3 交付(给 CC)

四件 + 一个 js,文件名按约定:

| 文件 | 是什么 |
|---|---|
| `design-tokens.css` | 双模式两套变量,`html[data-theme="day"\|"night"]` 切,默认跟系统。日间光语义(天光 vs 台灯)写在注释里 |
| `components.css` | 全部组件,零裸色值。v3 追加:信笺消息流 / PULSE 行 / 天列表行 / 更新通知条 / 折页+信笺 / 磨墨 / 昼夜小印 / focus·链接·选中通用态。每个组件头部注释里有最小 HTML 片段 |
| `总览排版.html` + `.js` | 首页排版稿,夜版;两状态(有一天 / 第一次打开)用左上角「样张」切——**那段评审件 vendor 时删** |
| `icons.html` | 八组小件图记,全部可点,昼夜可切 |
| `设置样张.html` | 设置家族(市集面板/钥匙/开关/同意书/动作行/诊断/便签模态/轻提示/上架行)装进市集跑一遍,组件本体在 components.css v4 段 |

## 落地注意

- 字体只写了字体名(Noto Serif SC / LXGW WenKai 及系统回退),**没挂任何 CDN**,vendor 锁版在你们侧
- 总览/图记里指向 `单日页 v2.html`、`单日页·空白态.html` 的链接在本文件夹会 404——接 repo 里真页面时换路径
- 主题键 `localStorage["gateway-theme"]`,三态:day / night / 缺省跟系统
- 信笺展开:`body[data-chat="open"]`,主纸让位半个 `--chat-w`;<1180px 时不让位、信笺盖上层
- `data-frozen` 路径:无帧环境(打印、被节流的 iframe)掐断全部过渡、以终态示人——别删,这是打印/导出能用的前提
- 所有动效已 gate 在 `prefers-reduced-motion: no-preference`
