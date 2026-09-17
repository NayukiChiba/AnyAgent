# AnyAgent

AnyAgent 是以 FastAPI 为入口的多 Agent Runner 应用平台，目标是通过统一 HTTP API 对接不同 Agent 框架，并提供 MCP、RAG、工具调用和会话管理能力，方便其他平台接入。

项目目前处于开发初期，已实现 `main.py` 启动入口、服务生命周期、健康检查与根目录 `data/` 初始化。Runner 适配、MCP、RAG 和 Agent 执行接口尚未实现。

## 快速启动

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在项目根目录运行：

```bash
uv sync --locked
uv run main.py
```

服务默认监听 `127.0.0.1:8000`。启动后可访问：

- API 文档：<http://127.0.0.1:8000/docs>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>
- 存活检查：<http://127.0.0.1:8000/health/live>
- 就绪检查：<http://127.0.0.1:8000/health/ready>

可指定监听地址与端口：

```bash
uv run main.py --host 0.0.0.0 --port 8080
```

已安装项目依赖时，也可以使用虚拟环境中的 Python 直接启动：

```bash
python main.py
```

按 `Ctrl+C` 停止服务。

## 设计方向

- 采用洋葱分层与 pipeline，领域和应用逻辑通过端口与具体后端解耦。
- Runner 优先适配 LangChain、LangGraph、Pi SDK 和 Coze SDK，随后接入 Dify、DeerFlow。
- MCP 与 RAG 属于应用核心能力，各 Runner 通过公共服务使用，并按实际能力声明支持范围。
- 平台管理的运行数据统一保存在根目录 `data/`，便于后续迁移；不建设插件系统或插件市场。

上述是后续开发方向，当前服务仅提供启动基础与健康检查。

## 项目目录

```text
AnyAgent/
├── main.py              # 项目启动入口
├── pyproject.toml       # 项目元数据与依赖
├── uv.lock              # 依赖锁文件
├── src/anyagent/
│   └── bootstrap.py     # FastAPI 创建与生命周期
├── data/                # 启动时创建，运行数据，不提交 Git
└── plans/               # 本地临时规划，不提交 Git
```

`data/` 的位置由 `main.py` 所在目录决定，不受启动时的工作目录影响。当前只初始化目录，后续配置、数据库、知识索引、文件和 Runner 状态统一放入该目录。

## 开发检查

```bash
uv run ruff check .
uv run ruff format --check .
```

`uv.lock` 纳入版本控制；`plans/` 与 `data/` 保持本地使用。
