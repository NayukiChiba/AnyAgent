# AnyAgent

AnyAgent 是以 FastAPI 为入口的多 Agent Runner 应用平台，目标是通过统一 HTTP API 对接不同 Agent 框架，并提供 MCP、RAG、工具调用和会话管理能力，方便其他平台接入。

项目目前处于开发初期，已实现 `main.py` 启动入口、服务生命周期、健康检查、独立日志模块与根目录 `data/` 初始化。Runner 适配、MCP、RAG 和 Agent 执行接口尚未实现。

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

当前配置保存在 `data/configs/cmd_config.json`。首次启动时，根目录 `configs/default.py` 按类型创建默认 JSON；`configs/load.py` 提供独立加载和校验，`configs/__init__.py` 导出 `cmd_config`、`logging_config`，并以 `config` 作为主配置别名。

可以停止服务后修改 `data/configs/cmd_config.json`，再重新启动。配置示例：

```json
{
  "paths": {"data_dir": "data"},
  "server": {"host": "127.0.0.1", "port": 8000}
}
```

日志参数单独保存在 `data/configs/logging_config.json`，其他模块也可通过 `load_config(名称, 校验模型, 默认值)` 使用独立配置文件。


路径统一相对于项目根目录解析，数据路径必须位于根目录 `data/` 内。配置缺失时创建默认值；JSON 编码、格式或内容无效时，原文件备份为 `data/configs/<配置文件名>.<时间戳>.bak`，再创建默认配置。读写权限等文件系统错误直接报告。某个配置损坏只恢复该文件，不影响其他类型。首次加载时会将旧的 `data/config.json` 拆分迁移，保留原文件备份；已有新文件优先，不覆盖其内容。命令行的 `--host`、`--port` 只覆盖本次启动值，不修改 JSON。

已安装项目依赖时，也可以使用虚拟环境中的 Python 直接启动：

```bash
python main.py
```

按 `Ctrl+C` 停止服务。应用和 Uvicorn 日志同时输出到控制台和 `data/logs/anyagent.log`，支持队列写入与文件轮转；退出时会清空队列。日志参数从独立的 `logging_config` 获取。

代码统一使用 `from anyagent.logger import logger` 获取日志入口。

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
├── docs/                # VitePress 文档，package.json 和锁文件均在此目录
├── src/anyagent/
│   ├── bootstrap.py     # FastAPI 创建与生命周期
│   └── logger.py        # 控制台、队列写入与文件轮转
├── tests/               # 配置与路径行为测试
├── data/                # 运行数据，不提交 Git
│   ├── configs/         # 按类型组织的运行配置
│   │   ├── cmd_config.json
│   │   └── logging_config.json
│   └── logs/            # 应用和服务日志
└── plans/               # 本地临时规划，不提交 Git
```

根目录 `configs/` 只保存 Python 配置代码，配置 JSON 统一保存在 `data/configs/`。其他模块使用共享配置中的已解析路径，不自行拼接业务目录。后续数据库、知识索引、文件和 Runner 状态也统一放入 `data/`。

## 开发检查

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`uv.lock` 纳入版本控制；`plans/` 与 `data/` 保持本地使用。

## 文档

需要 Node.js 22+。所有文档依赖在 `docs/` 内管理：

```bash
cd docs
npm ci
npm run dev
```

运行 `npm run build` 构建，`npm run preview` 预览。GitHub Actions 会在 main 分支的文档变更、相关 PR 或手动触发时构建站点，并上传 `docs-site` 产物。使用说明见 `docs/guide/`，文档开发流程见 `docs/development.md`。
