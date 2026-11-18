# contracts/ — 只读契约档案

- `widget-spec.v1.schema.json` — DeepSeek 可生成的声明式 WidgetSpec v1 唯一结构契约。
- `widget-capabilities.v1.json` — Widget Capability Broker 当前公开的最小语义能力清单。
  两份文件在 `gateway-rn/services/contracts/` 有运行时副本，跨仓字节一致测试负责抓漂移。
- `mobile-api.reference.js` — WebView 版移动端 API 层(4419 行)的契约存档。gateway-rn 注释中的
  "mobile-api.js:行号" 引用以本档案为准(2026-07-21 自 mobile/mobile-api.js 存档,内容逐字节一致)。
  运行时原件已随 archive/webview-mobile/ 归档,桌面 index.html 已摘除加载(它在桌面本就惰性)。
