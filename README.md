<h1 align="center">Gateway</h1>

<p align="center">
  AI 原生的日记应用 · 人与 AI 的协作框架 · 笔记即 AI 记忆
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-early%20beta-orange" />
  <a href="./LICENSE"><img src="https://img.shields.io/github/license/Huangleyang125207/human-ai-gateway" /></a>
  <img src="https://img.shields.io/badge/built%20with-Claude%20Code-7C3AED" />
</p>

## 设计理念

**AI 原生。** 整个软件从一开始就是基于 AI 自身打造,而不是把 AI 强行嫁接进现成软件。架构起点不是"人怎么用",而是"人和 AI 怎么一起用"——数据结构、文件格式、工具接口都为协作设计。

**笔记本是协议层。** 半小时切一格、每段用 `#tag` 归类的 markdown,人和 AI 都通过它读写。md 是 canonical,HTML 是镜像。

**笔记 = AI 记忆。** 写出来的东西反过来构成 AI 下一轮的输入。AI 启动通过工具读 vault 拿回上下文,标签聚合页是横切索引,跨夜留言板延续对话——记忆是明文 markdown,没有 RAG 黑箱,搬家就 copy 一个目录。

**AI 隐形。** 不霸屏,右键任意元素跟它说话。需要才出现。

**单 API，本地优先。** 日记、对话和附件保存在设备上。使用 AI 功能时，设备把本次推理所需的上下文和图片直接发给 DeepSeek，费用计入你自己的 API 账户。

## 功能

- 半小时块时间戳 + 标签分类,Obsidian 兼容 markdown,人 AI 双签留评论
- DeepSeek 主对话 + V4 Flash 子 agent 做语义检索,30+ 工具(读 / 写 / 搜 / 看图)
- 拖图自动:端侧抠图 + 视觉分类 + OCR,智能路由到打卡 / 聊天 / scrapbook
- 21:30 自动复盘当天,macOS 推送通知
- vault 自动 git commit 双签可追溯,训练语料一键导出
- Tauri 自动更新(macOS)

## 装

下 [latest release](https://github.com/Huangleyang125207/human-ai-gateway/releases/latest):

- **macOS**(Apple Silicon):`Gateway_x.y.z_aarch64.dmg` 拖进 `/Applications` — Apple Developer 签名 + notarized,无 Gatekeeper 警告
- **Windows**(x64):`Gateway-Setup-x.y.z-x64.exe` 双击装,自动加开始菜单 + 卸载列表 — **未做代码签名**,首次运行 Windows Defender SmartScreen 会拦,点 _"更多信息 → 仍要运行"_ 即可。杀软误报装不上时可下 `Gateway-windows-x64.zip` 解压跑(不依赖 installer)

首次启动后，在设置里填写一把个人 DeepSeek API Key，对话和看图共用。如果之前用的是内测设备令牌，升级后需填写个人 Key。[DeepSeek API 密钥管理](https://platform.deepseek.com/api_keys)

数据在 `~/.human-ai/vault/`(可用 Obsidian 同时打开)。

## 从源码跑

```bash
git clone https://github.com/Huangleyang125207/human-ai-gateway
cd human-ai-gateway
pip install -r requirements.txt
python -m uvicorn server:app --port 4321
```

打桌面壳:

```bash
# macOS (需要 Rust + tauri-cli + Xcode CLT)
bash build-sidecar.sh && cd src-tauri && cargo tauri build

# Windows
build-win.bat
```

## 架构

Tauri 桌面壳 → PyInstaller sidecar(FastAPI)→ 本地 vault + SQLite + DeepSeek。

前端 vanilla JS,无 npm / build step。

需要重构或排障时，先读 [文档入口](docs/INDEX.md)；全仓架构、风险与演进清单在 [架构清册](docs/ARCHITECTURE_LEDGER.md)。原生移动端的独立开发入口在 [`../gateway-rn/docs/README.md`](../gateway-rn/docs/README.md)。

## 隐私

AI 推理会使用日记片段、对话历史、工具结果或所选照片。桌面匿名诊断单独征求同意，可在「设置 → 数据 → 云上报」中关闭。详见 [隐私政策](PRIVACY.md)。

## License

MIT — 详见 [LICENSE](LICENSE)。
