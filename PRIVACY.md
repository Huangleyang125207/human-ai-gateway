# Privacy

Gateway 默认收集两类匿名数据,帮我们改进软件。两类都可以在 设置 → 数据 → 云上报 里关闭,关了之后立刻不再上送。

## 收什么

### 错误上报(failures)

API 调用 / 识图 / 抠图 / 搜索 等失败的错误码 + 简短上下文,只用来反向定位 bug。

示例:

```json
{
  "ts": "2026-06-03T00:00:00",
  "client_id": "a3b9c2... (匿名 UUID, 不绑邮箱/姓名)",
  "error_type": "vision_classify_auth",
  "message": "qwen returned 401",
  "context": { "model_id": "qwen3-vl-flash", "file_size_kb": 1240 },
  "app_version": "0.1.3",
  "platform": "darwin-arm64"
}
```

### 使用心跳(heartbeat)

每天一次,看活跃用户和版本分布:

```json
{
  "client_id": "a3b9c2...",
  "version": "0.1.3",
  "platform": "darwin-arm64",
  "tz_offset_min": 480
}
```

## 不收什么

明确不收的:

- vault markdown 内容(任何日记内容)
- 聊天对话(任何用户消息或 AI 回复)
- 文件名 / 路径 / 任何附件
- API key / 密钥 / 凭据
- 邮箱 / 真名 / 手机号
- IP 地址(server 端代码层 drop,不写入 SQLite)
- 浏览器历史 / 系统信息 / cookies

## 端点

腾讯云国内服务器:`http://101.42.108.30:18080`(规划接入 TLS 后切 HTTPS)

服务端只我们看,不卖、不分享、不接广告系统。

## 如何关闭

- **设置 → 数据 → 云上报**:勾两个 checkbox 自由开关
- **完全断网**:Gateway 没网也能本地用,只是云上报相关数据进本地 jsonl ring buffer 兜底

## 重置匿名 ID

担心 ID 关联多个事件?设置里点"重置"会换新 UUID,server 端看作新设备。

## 源码可审

所有上报代码在 `server.py` 里搜 `_report_silent_failure` / `_hb_sender_loop` 看完整链路;
接收端在 `agents/feedback-sink/app/main.py`。

## 联系

发现 bug / 想关掉某个具体上报字段:开 issue。
