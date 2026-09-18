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
    details: 通过 main.py 启动 FastAPI 和 Vue 3 聊天工作台，支持 HTTP 与 WebSocket。
  - title: 数据集中
    details: 当前配置与日志保存在根目录 data/，便于管理和迁移。
  - title: Runner 解耦
    details: 首个 LangChain SDK 通过 Runner 端口接入，工具循环与内存会话形成最小闭环。
---

## 当前状态

已实现 LangChain Agent、多轮对话、计算工具、模型配置热重载和 Vue 3 工作台，会话暂存内存。

LangGraph、Pi、Coze、Dify、DeerFlow、公共 MCP/RAG、完整 pipeline 与 SQLite 持久化仍在后续开发范围内。
