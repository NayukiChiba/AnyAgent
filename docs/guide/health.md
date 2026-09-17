# 健康检查

当前服务提供以下接口：

| 接口 | 用途 | 成功响应 |
| --- | --- | --- |
| `GET /health/live` | 确认服务能够处理请求 | `200 {"status":"ok"}` |
| `GET /health/ready` | 确认应用生命周期初始化完成 | `200 {"status":"ready"}` |
| `GET /openapi.json` | 获取 API 描述 | OpenAPI JSON |
| `GET /docs` | 浏览和调试 API | 交互式文档页面 |

应用未就绪时，就绪检查返回 `503 {"status":"not_ready"}`。当前就绪状态仅反映已有初始化流程，不代表尚未实现的 Agent Runner、MCP 或 RAG 已可用。

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```
