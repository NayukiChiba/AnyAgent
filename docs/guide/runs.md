# Run API

Run 是执行的一等公民。创建 Run 后执行在服务端独立运行，客户端通过 SSE 订阅事件；**订阅断开不会停止执行**，断线后按事件序号续订即可补发遗漏事件。会话与已完成的历史照旧写入本机 SQLite，Run 的输入、结果与终态同样落库。

## 端点

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/v1/runs` | 创建 Run，返回 201 与 Run 快照。携带 `session_id` 时会话执行并提交历史；缺省为无会话执行 |
| `GET /api/v1/runs/{id}` | 查询状态、结果、错误与配置快照（不回放完整输入） |
| `GET /api/v1/runs/{id}/events` | SSE 订阅事件流；`id:` 行为事件单调序号，请求头 `Last-Event-ID` 支持断点续传 |
| `POST /api/v1/runs/{id}/cancel` | 请求取消；已终态返回 409 `invalid_state` |

创建示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<会话id>","content":"请使用工具计算 2+3"}'
```

订阅事件（断线重连时带上最后收到的序号）：

```bash
curl -N http://127.0.0.1:8000/api/v1/runs/<run_id>/events \
  -H 'Last-Event-ID: 12'
```

## 事件流

SSE 帧携带 `id`（事件序号）、`event`（事件类型）与 `data`（JSON，含 `seq`、`type`、`data`）：

```text
id: 3
event: result
data: {"seq":3,"type":"result","data":{"content":"结果是 5"}}
```

事件类型：`status`（状态迁移）、`delta`（文本增量）、`tool_call`/`tool_result`（工具过程）、`result`（最终结果）。序号从 0 连续递增；断线重连按 `Last-Event-ID` 之后的序号补发，订阅方按序号去重。慢订阅者消费不过来时收到 `subscription_lagged` 错误帧并被终止订阅，不影响执行与其他订阅者。

错误帧沿用 `{"type":"error","data":{"code":"...","message":"..."}}` 结构。SSE 建立后不能改 HTTP 状态码，执行错误通过 `status: failed` 帧携带错误信息。

## 状态与终态

状态机：`queued → running → succeeded | failed | cancelled`，取消经 `running → cancelling → cancelled`。终态唯一，终态事件在提交完成后才发布：

- `succeeded` 携带非空结果，会话历史在同一事务内提交
- `failed` 携带错误码与对外消息（不泄漏上游凭据）
- `cancelled` 不提交半轮历史

取消已结束的 Run 返回 409；服务重启后，上次未能收尾的执行被标记为 `failed` / `run_interrupted`，不自动重跑，可继续通过查询接口查看。

## 执行链路

执行链路为洋葱中间件包裹顺序阶段：`日志上下文 → 异常归一 → Runner 清理` 包裹 `上下文组装 → 执行 → 提交`。新增 Runner 实现 `stream` / `aclose` 端口即可接入，不在这条链路中添加厂商分支。

内存中为每个 Run 保留事件环形缓冲（500 条）用于重放；终态记录超出保留上限后清理最早的，已落库的 Run 仍可查询。

::: tip
旧端点 `POST /sessions/{id}/stream` 与 WebSocket 聊天已在 M1 移除；OpenAI 兼容网关（`/v1/chat/completions`）保留，内部走无会话 Run。
:::
