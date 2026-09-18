# LangChain Agent

当前版本使用 LangChain 官方 `create_agent` 和 `ChatOpenAI`，提供多轮对话和一个计算工具。前端为 Vue 3，接口为普通 HTTP、HTTP 上的 SSE 流，以及 WebSocket。会话通过 SQLAlchemy 异步仓储保存到本机 SQLite，重启后恢复标题与已完成的历史窗口。

## 配置模型

首次启动后打开 [网页设置](./settings.md)，填写连接信息、启用模型、保存并测试连接，再返回聊天。无需手动编辑配置文件。

实际设置保存到 `data/configs/model_config.json`，手动部署时可使用以下格式：

```json
{
  "enabled": true,
  "streaming": true,
  "base_url": "https://your-provider.example/v1",
  "model": "your-model-name",
  "api_key": "your-api-key",
  "temperature": 0.7,
  "timeout_seconds": 60,
  "max_retries": 0,
  "stream_usage": false
}
```

支持自定义 OpenAI 兼容模型地址、名称和密钥。服务需支持标准 Chat Completions 和工具调用，开启流式输出时还需支持流式响应。地址填接口前缀，SDK 自动追加 `/chat/completions`。无认证本地服务填写占位密钥 `local`。

`streaming: true` 为流式模型调用，会产生 `delta` 文本增量；`false` 为上游非流式模型调用，收到完整模型回复后输出最终结果，不发送 `delta`。两种模式仍提供工具调用与结果。开关独立于 HTTP/SSE 和 WebSocket 连接方式：通过 SSE/WebSocket 使用非流式模型时，工具步骤仍可作为事件发送，最终文本完整发送。

`max_retries` 控制 SDK 重试次数，默认为 0；`stream_usage` 默认为 false，仅在服务支持流式用量信息时开启。

模型配置在每次新执行时读取，修改后无需重启；已运行请求继续使用原快照。页面点击“刷新配置”更新显示状态。密钥留在后端，状态接口不返回密钥；`data/` 不提交 Git。关闭 `enabled` 可停止新请求调用模型，既有执行不受影响。

无效 JSON 或配置值遵循[独立恢复规范](./configuration.md#缺失与无效配置)：备份原文件，再恢复禁用状态的默认模型配置。尚未配置模型时，后端仍正常启动并提供配置状态、页面与会话接口。

## 配置 Agent

`data/configs/langchain_config.json`：

```json
{
  "system_prompt": "You are a helpful assistant. Use the calculate tool for arithmetic.",
  "max_steps": 12,
  "max_sessions": 64,
  "max_history_messages": 40,
  "max_concurrent_runs": 4,
  "run_timeout_seconds": 120,
  "max_input_chars": 8000,
  "max_output_chars": 32000,
  "max_event_chars": 64000,
  "cleanup_timeout_seconds": 5
}
```

这些设置在启动时读取，修改后重启。`max_steps` 是 LangChain 图执行步数上限，不是工具调用次数。历史窗口按完整用户/助手轮次裁剪；窗口为奇数时向下取偶数。输入、最终回复和过程事件大小分别由 `max_input_chars`、`max_output_chars`、`max_event_chars` 控制，默认分别为 8000、32000、64000；`cleanup_timeout_seconds` 控制模型连接清理时限。页面输入上限由状态接口读取，与后端使用同一配置。

初始工具 `calculate` 接收 `operation`（add/subtract/multiply/divide）、`a`、`b`，支持加减乘除。它不执行任意代码。公共 ToolExecutor、MCP、RAG 和其他 Runner 仍在后续开发范围内。

## 前端运行配置

`data/configs/frontend_config.json`：

```json
{
  "default_transport": "websocket",
  "cancel_timeout_ms": 1500
}
```

`default_transport` 支持 `websocket` 和 `http`，决定页面初始连接方式；`cancel_timeout_ms` 控制 WebSocket 取消确认等待时间。状态接口刷新时重新加载该文件，重新打开页面采用最新默认连接；手动选择的连接不会因刷新状态被重置。

## 使用工作台

先按[快速开始](./getting-started.md)构建前端，运行 `main.py` 后访问 <http://127.0.0.1:8000/>。

1. 打开“设置”，填写模型连接信息，保存并测试后返回聊天。
2. 输入“请使用工具计算 2+3”，观察工具参数、工具结果和最终回复。修改模型配置的 `streaming` 可以切换流式和非流式输出。
3. 在“连接方式”切换 WebSocket 或 HTTP · SSE。
4. 使用“新建会话”、会话列表和“删除会话”管理本机会话；“停止生成”取消当前轮次。

只有成功执行的用户消息与完整回复写入历史。失败、超时或取消不会留下半轮对话；刷新页面或重启服务后仍能读取已保存的历史窗口。工具过程展示属于本轮临时状态，刷新后不恢复。

## 调用接口

先创建会话：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sessions
```

使用返回的 `id`：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sessions/<id>/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"请使用工具计算 2+3"}'

curl -N -X POST http://127.0.0.1:8000/api/v1/sessions/<id>/stream \
  -H 'Content-Type: application/json' \
  -d '{"content":"请使用工具计算 2+3"}'
```

普通 HTTP 返回 `content` 和 `events`。SSE 响应的 `data` 与 WebSocket JSON 共用事件结构：

```json
{"type":"tool_call","data":{"id":"call_1","name":"calculate","arguments":{"operation":"add","a":2,"b":3}}}
{"type":"tool_result","data":{"id":"call_1","name":"calculate","content":"5.0"}}
{"type":"delta","data":{"content":"结果是 5"}}
{"type":"result","data":{"session_id":"...","content":"结果是 5"}}
```

`result` 是完整结果，用于替换增量显示，避免重复拼接。错误事件为 `{"type":"error","data":{"code":"...","message":"..."}}`。SSE 已建立后不能改 HTTP 状态码，执行错误通过该事件返回。

连接 `ws://127.0.0.1:8000/ws/sessions/<id>`，发送：

```json
{"type":"message","content":"请使用工具计算 2+3"}
```

取消发送 `{"type":"cancel"}`，完成后收到 `{"type":"cancelled","data":{}}`。HTTP 流取消通过断开该请求实现。两种连接断开都会结束其执行，本轮不支持后台 Run、断线续跑或事件重放。

同一会话有执行中的请求时，其他请求收到 `session_busy`。普通 HTTP 使用 409、503、504 等状态码报告会话冲突、模型未配置和超时。完整接口见服务的 `/docs`。

## 验证范围

自动测试通过本地确定性 OpenAI 兼容协议夹具调用真实 LangChain SDK，覆盖工具循环、历史、热重载和三种接口；Vue 浏览器测试覆盖首次配置、分类设置、错误输入、未保存提醒、连接测试、输出模式、聊天、会话操作与取消。

这些测试不调用云端模型。配置真实服务后仍需验证该模型的流式输出与工具调用能力。当前版本未实现生产鉴权、多进程会话共享、持久执行和执行断点恢复。
