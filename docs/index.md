---
layout: home
hero:
  name: AnyAgent
  text: 多 Agent Runner 应用平台
  tagline: 以 FastAPI 为入口，统一执行契约，集中管理配置与运行数据。
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/getting-started
    - theme: alt
      text: 查看源码
      link: https://github.com/NayukiChiba/AnyAgent
features:
  - title: 统一入口
    details: 通过 main.py 启动服务，提供健康检查和 OpenAPI 文档。
  - title: 数据集中
    details: 当前配置与日志保存在根目录 data/，便于管理和迁移。
  - title: Runner 解耦
    details: 后续通过独立适配器接入不同执行后端，并复用 MCP、RAG 等应用服务。
---

## 当前状态

项目处于开发初期，已实现服务启动、JSON 配置加载、健康检查和日志管理。

LangChain、LangGraph、Pi、Coze、Dify、DeerFlow 适配，以及 MCP、RAG 和 Agent 执行接口仍在后续开发范围内，当前版本尚未提供。
