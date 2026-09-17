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

启动默认值与路径配置集中在 `configs/app.toml`，不在启动代码中指定。路径相对于项目根目录解析，命令行的 `--host`、`--port` 覆盖配置文件中的值。也可选择其他配置文件：

```bash
uv run main.py --config configs/app.toml
```

相对的 `--config` 文件名也以项目根目录为基准；配置缺失或无效时启动失败，不会静默回退。

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
├── configs/
│   └── app.toml          # 路径与服务启动默认值
├── src/anyagent/
│   ├── configs/          # 配置校验与统一路径解析
│   └── bootstrap.py      # FastAPI 创建与生命周期
├── tests/               # 配置与路径行为测试
├── data/                # 启动时创建，运行数据，不提交 Git
└── plans/               # 本地临时规划，不提交 Git
```

`data/` 的位置由 `configs/app.toml` 的 `paths.data_dir` 配置决定，默认是项目根目录的 `data/`，不受启动时的工作目录影响。配置加载统一负责路径解析，并拒绝指向项目根目录外的数据路径。其他模块使用已经解析的路径，不自行拼接目录名。

`configs/` 保存纳入版本控制的启动配置，不保存密钥或运行时生成文件。后续动态配置、数据库、知识索引、文件和 Runner 状态统一放入 `data/`。

## 开发检查

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`uv.lock` 纳入版本控制；`plans/` 与 `data/` 保持本地使用。
