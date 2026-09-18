# AnyAgent

基于 FastAPI 的多 Agent Runner 应用平台。当前已实现首个 LangChain Agent：OpenAI 兼容模型、多轮对话、计算工具和统一 HTTP/WebSocket 流式事件。会话保存在单进程内存中，服务重启后清空，暂不接入 SQLite。

## 启动

需要 Python 3.12+、Node.js 22+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
uv run main.py
```

前端首次构建后，`main.py` 同时提供 FastAPI 和 Vue 3 聊天页面，无需单独启动前端服务。修改前端源码后重新构建即可；构建产物不提交 Git。服务默认监听 `127.0.0.1:8000`，聊天页面位于 <http://127.0.0.1:8000/>，交互式 API 文档位于 <http://127.0.0.1:8000/docs>。可用 `uv run main.py --host 0.0.0.0 --port 8080` 覆盖本次监听参数。按 `Ctrl+C` 退出。

源码通过根目录 `anyagent/` 模块直接运行；uv 只管理依赖，不安装项目本身或生成 `egg-info`。

## 模型配置与热重载

首次启动会创建 `data/configs/model_config.json`。填写自己的 OpenAI 兼容服务：

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

兼容服务需要支持 Chat Completions、流式响应和工具调用。`base_url` 填接口前缀，由 SDK 追加 `/chat/completions`；本地无认证服务可以填写占位密钥，例如 `local`。模型名和地址均由你定义。

`streaming: true` 启用模型文本增量，`false` 使用上游非流式请求并等待完整回复。两种模式都保留工具调用与最终结果，HTTP/SSE 和 WebSocket 均可使用；该开关控制模型输出模式，连接方式由页面选择。`max_retries` 控制 SDK 重试次数；`stream_usage` 仅在兼容服务支持流式用量信息时开启。

每次新执行重新读取模型 JSON，无需重启；正在运行的请求使用自己的配置快照。API Key 只保存在后端配置中，状态接口不返回密钥。无效配置按现有加载规范先备份再恢复默认值；默认模型禁用，不会自动调用模型服务。

LangChain 的 prompt、步骤、会话数、历史窗口、并发数和执行时限单独保存在 `data/configs/langchain_config.json`，该配置在启动时读取，修改后重启生效。初始工具 `calculate` 支持加减乘除，不执行任意代码。

## Vue 3 Agent 工作台

页面提供会话创建、切换和删除，多轮对话、工具参数与结果展示，以及停止生成。默认连接从 `data/configs/frontend_config.json` 的 `default_transport` 读取（`websocket` 或 `http`），也可在页面切换。该文件中的 `cancel_timeout_ms` 控制 WebSocket 取消确认等待时间。页面显示模型的“流式输出”或“非流式输出”模式；保存模型 JSON 后刷新配置即可更新。模型 JSON 保存后点击“刷新配置”，即可使用新的连接配置；密钥不发送给浏览器。刷新页面可恢复当前服务内的历史，服务重启后历史清空。

前端依赖与源码独立放在 `frontend/`。开发时启动后端，再在 frontend 运行 `npm run dev`，Vite 将 `/api` 和 `/ws` 转发到本地 `8000` 端口；监听其他端口时修改 frontend 的 Vite proxy。

## Agent 接口

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/agent` | 模型配置状态、Runner、工具和连接方式 |
| `GET /api/v1/sessions` | 会话列表 |
| `POST /api/v1/sessions` | 创建会话 |
| `GET /api/v1/sessions/{id}` | 查询会话历史 |
| `DELETE /api/v1/sessions/{id}` | 删除未执行中的会话 |
| `POST /api/v1/sessions/{id}/messages` | 普通 HTTP 对话，返回最终结果与过程事件 |
| `POST /api/v1/sessions/{id}/stream` | HTTP 流式对话，响应格式为 SSE |
| `WS /ws/sessions/{id}` | WebSocket 对话与取消 |
| `GET /health/live`、`GET /health/ready` | 健康检查 |

HTTP 请求体为 `{"content":"请使用工具计算 2+3"}`。SSE 是 HTTP 响应流，保留用于不使用 WebSocket 的调用方；通过 `fetch` 发起 POST 并消费流，而不是 GET EventSource。

WebSocket 发送 `{"type":"message","content":"请使用工具计算 2+3"}`，发送 `{"type":"cancel"}` 停止当前连接上的生成。

两种流式连接统一接收 `{"type":"事件类型","data":{...}}`：`delta` 为文本增量，`tool_call` 为工具名和参数，`tool_result` 为工具结果，`result` 为完整最终回复，`error` 为错误。WebSocket 取消成功后收到 `cancelled`。`result` 用于替换显示中的增量文本，避免重复拼接。

仅成功完成的轮次写入历史；失败、超时、取消不提交半轮对话。断开流式连接会取消对应执行，目前不提供后台 Run、事件重放或断线续跑。SSE 开始后的错误通过 `error` 事件报告；普通 HTTP 错误通过状态码和 `detail` 报告。同一会话同时只能执行一个请求。历史按完整用户/助手轮次保留最近窗口。

## 配置、日志与分层

实际 JSON 和运行数据统一位于根目录 `data/`，不提交 Git：

- `data/configs/cmd_config.json`：数据路径和监听参数，修改后重启。
- `data/configs/logging_config.json`：队列日志、级别和轮转参数，修改后重启。
- `data/configs/model_config.json`：模型连接与密钥，新执行热重载。
- `data/configs/langchain_config.json`：Agent prompt、步骤、历史、并发、输入/输出/事件大小和清理时限，修改后重启。
- `data/configs/frontend_config.json`：前端默认连接和取消确认等待时间；刷新配置读取，默认连接在重新加载页面时采用。
- `data/logs/anyagent.log`：应用和服务器日志。

缺失配置独立创建默认值；已有有效 JSON 自动补齐新增默认项，保留显式值与密钥，完整配置不重复写入；格式、字段或路径无效时，原文件备份为 `data/configs/<文件名>.<时间戳>.bak`，仅恢复该类型。权限错误直接报告。旧 `data/config.json` 自动拆分迁移，已有新文件优先。

```text
anyagent/
├── configs/         # 配置模型、独立加载与 paths.py
├── core/
│   ├── domain/      # 消息、会话、事件、错误
│   ├── ports/       # Runner、Factory 和会话仓储 Protocol
│   └── services/    # 会话执行、提交、预算与清理
├── adapters/runners/langchain/ # 官方 SDK 和工具适配
├── infrastructure/memory/    # 可替换的内存仓储
├── api/             # HTTP、SSE、WebSocket、静态页面与错误转换
├── runtime/         # 配置注入、依赖装配和生命周期
└── utils/           # 日志等技术支撑
```

核心层不依赖 SDK、Web 框架、数据库或全局配置。新增 Runner 实现端口并由 runtime 装配，不在通用聊天 API 中添加厂商分支。实际路径只在 `anyagent/configs/paths.py` 定义。包根仅保留版本与包标识，Python 代码只使用绝对导入。

LangGraph、Pi、Coze、Dify、DeerFlow，以及公共 MCP、RAG 和 pipeline 是后续开发目标，当前未实现。本轮先交付 LangChain 与 Vue 3 最小闭环，后续再替换内存仓储接入 SQLite；当前不承诺生产鉴权、持久执行或多进程部署。`plans/` 是本地计划目录，不提交。

## 开发验证与文档

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

SDK 集成测试使用本地确定性的 OpenAI 兼容协议夹具，验证真实 LangChain 工具循环和连接契约；不需要云端密钥，也不代表已验证某个真实模型服务。

前端验证（先同步 Python 依赖并构建前端）：

```bash
cd frontend
npm test
npx playwright install chromium
npm run test:e2e
```

浏览器测试自动启动隔离的本地模型协议服务，不读取你的真实模型密钥。Playwright 浏览器仅用于开发测试。

VitePress 文档依赖位于 `docs/`，需要 Node.js 22+：

```bash
cd docs
npm ci
npm run dev
npm run build
```

GitHub Actions 自动构建文档并上传 `docs-site` 产物，不提交构建输出、缓存或运行数据。
