# 开发指南

## Python 检查

在项目根目录运行：

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

配置测试覆盖创建、加载、错误恢复及路径行为；日志测试覆盖队列清空、异常堆栈、第三方日志、重复配置和轮转。

## 源码分层

包根 anyagent 仅保留 __init__.py。当前 main.py 通过 anyagent.runtime.bootstrap.create_app 装配应用，api/app.py 构造 FastAPI，api/routes/health.py 提供健康检查，utils/logger.py 管理日志。

当前 core/domain、core/ports 和 core/services 已实现会话闭环；adapters/runners/langchain 实现真实 SDK，infrastructure/memory 提供会话仓储。后续 pipeline、Provider、MCP、检索和持久仓储随用例扩展。core 只依赖领域与端口，不导入外层模块、全局 configs、FastAPI、ORM 或厂商 SDK。runtime 获取配置、显式注册实现并注入应用服务；HTTP 类型和错误转换留在 api。

配置代码位于 anyagent/configs，JSON 位于根目录 data/configs。BaseSettings 只统一配置值校验，不作为领域、Port 或 Service 的公共父类；core 使用 runtime 注入的必要配置值。

| 概念 | 职责 |
| --- | --- |
| Port | 应用依赖的可替换能力边界，放在 core/ports |
| Protocol | 表达 Port 的结构化类型契约，实现无需显式继承 |
| Service | 注入端口、组织业务用例与应用能力 |
| Stage | 按 pipeline 顺序处理请求，可拒绝或中止后续阶段 |
| Middleware | 通过 call_next 包裹下游，管理前后处理和清理 |

责任链描述执行顺序，洋葱分层描述代码依赖，两者分别验收。Protocol 不保证 SDK 的运行语义，公共契约测试与真实执行负责验证；Python 类型机制见[官方文档](https://docs.python.org/3/library/typing.html#typing.Protocol)。当前 Runner、Factory、SessionRepository 采用 Protocol，ChatService 注入这些端口；完整阶段 pipeline 尚未实现。

utils 不存放业务策略。包入口不创建数据库、Manager 或网络任务；configs 的共享 JSON 初始化是现有配置约定的例外。尚未进入实施阶段的目录不提前建空壳，新增 Runner 不修改通用 pipeline 或专门新增厂商路由。

## Vue 3 前端开发

前端源码和依赖位于 `frontend/`，使用 Vue 3 和 Vite。先运行 Python 后端，再启动开发服务器：

```bash
cd frontend
npm ci
npm run dev
```

Vite 将 `/api` 和 `/ws` 代理到 `127.0.0.1:8000`。`npm run build` 输出到 `frontend/dist/`，由 FastAPI 同源提供；所有 Python 静态资源路径来自 configs/paths.py。

验证流式解析与真实浏览器操作：

```bash
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

浏览器测试启动 `tests.e2e_server`，使用临时配置和本地 OpenAI 兼容协议夹具，不需要云端密钥。Python 和前端依赖都需提前安装。SDK 测试同样使用该夹具，检查工具调用交回模型、配置热重载和多轮历史；夹具成功不代表真实服务已验收。

## 文档开发

文档使用 [VitePress 1.6](https://vuejs.github.io/vitepress/v1/guide/getting-started)，需要 Node.js 22+。`package.json`、锁文件和依赖安装均位于 `docs/` 中：

```bash
cd docs
npm ci
npm run dev
```

构建与预览：

```bash
npm run build
npm run preview
```

默认输出到 `docs/.vitepress/dist/`，构建产物、缓存和 `node_modules` 不提交 Git。`docs/package-lock.json` 必须随文档依赖修改一起提交。

站点默认使用根路径 `/`；部署到子目录时，通过 `DOCS_BASE` 指定前缀：

```bash
DOCS_BASE=/AnyAgent/ npm run build
```

## 自动构建

`.github/workflows/docs.yml` 在 main 分支的文档变更、相关 PR 和手动触发时执行：

1. 准备 Node.js 22，并按 docs 内的锁文件恢复 npm 缓存。
2. 在 docs 内运行 `npm ci` 和 `npm run build`。
3. 将静态站点上传为 `docs-site` 构建产物，可在 Actions 运行页面下载。

工作流只需仓库读取权限。发布到静态托管服务时，可使用构建产物，并按部署位置设置 `DOCS_BASE`。构建与部署方式可参考 [VitePress 官方部署指南](https://vuejs.github.io/vitepress/v1/guide/deploy)。

## 提交与运行数据

遵守根目录 [AGENTS.md](https://github.com/NayukiChiba/AnyAgent/blob/main/AGENTS.md)：按独立改动拆分提交，type、scope 使用英文，标题描述和正文使用中文，正文记录原因、改动与实际验证。

`plans/` 是本地临时规划目录；实际配置、日志及其他运行数据统一保存在 `data/`。这些内容不进入文档构建或 Git 提交。
