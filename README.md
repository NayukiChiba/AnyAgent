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

当前配置保存在 `data/config.json`。首次启动时，根目录 `configs/default.py` 创建默认 JSON；`configs/load.py` 加载并校验配置，`configs/__init__.py` 导出共享的 `config`，启动入口和 `src` 模块通过 `from configs import config` 使用。

可以停止服务后修改 `data/config.json`，再重新启动。配置示例：

```json
{
  "paths": {"data_dir": "data"},
  "server": {"host": "127.0.0.1", "port": 8000}
}
```

路径统一相对于项目根目录解析，数据路径必须位于根目录 `data/` 内。配置缺失时创建默认值；JSON 编码、格式或内容无效时，原文件备份为 `data/config.json.<时间戳>.bak`，再创建默认配置。读写权限等文件系统错误直接报告。命令行的 `--host`、`--port` 只覆盖本次启动值，不修改 JSON。

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
│   ├── default.py       # 默认配置与 JSON 创建
│   ├── load.py          # 当前配置加载、校验与路径解析
│   └── __init__.py      # 导出共享 config
├── src/anyagent/
│   └── bootstrap.py      # FastAPI 创建与生命周期
├── tests/               # 配置与路径行为测试
├── data/                # 运行数据，不提交 Git
│   └── config.json      # 首次加载时自动创建的当前配置
└── plans/               # 本地临时规划，不提交 Git
```

根目录 `configs/` 只保存 Python 配置代码，配置 JSON 只保存在 `data/`。其他模块使用共享配置中的已解析路径，不自行拼接业务目录。后续数据库、知识索引、文件和 Runner 状态也统一放入 `data/`。

## 开发检查

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`uv.lock` 纳入版本控制；`plans/` 与 `data/` 保持本地使用。
