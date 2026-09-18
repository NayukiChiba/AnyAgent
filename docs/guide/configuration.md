# 配置管理

日常使用请打开工作台的“设置”，无需手动编辑 JSON；首次连接步骤见 [网页设置](./settings.md)。

运行配置按类型组织在根目录 `data/configs/`，不提交 Git：

| 文件 | 内容 | 导出对象 |
| --- | --- | --- |
| `cmd_config.json` | 主配置：数据路径、服务监听参数 | `cmd_config`，别名 `config` |
| `logging_config.json` | 日志级别、文件路径、轮转参数 | `logging_config` |
| `model_config.json` | OpenAI 兼容模型连接与密钥 | `load_model_config()`，新执行热重载 |
| `langchain_config.json` | Agent prompt、历史与执行预算 | `load_langchain_config()`，启动时读取 |
| `database_config.json` | SQLite 文件位置、数据库锁等待时限 | `load_database_config()`，启动时读取 |
| `frontend_config.json` | 默认连接、取消确认与重启检查等待参数 | `load_frontend_config()`，状态刷新时读取 |

配置代码位于 `anyagent/configs/`，属于应用的外层支撑模块。`base.py` 定义共享校验规则，`models.py` 定义基础配置模型，`agent.py` 定义模型连接与 LangChain 配置，`default.py` 定义默认值并创建 JSON，`paths.py` 集中处理路径，`load.py` 加载、校验和恢复分类 JSON，`catalog.py` 登记网页分组和字段信息，`management.py` 提供密钥隐藏、校验保存和版本冲突检查，`__init__.py` 导出共享对象。实际 JSON 和日志始终保存在项目根目录 data，不随代码迁入应用包。启动入口、runtime 和需要配置的外层模块直接获取所需配置；核心应用通过注入的运行快照使用配置值：

```python
from anyagent.configs import cmd_config, logging_config

host = cmd_config.server.host
log_file = logging_config.file_path
```

主配置与日志配置在模块导入时加载，修改后重启。LangChain 与数据库配置在启动时读取；模型连接配置每次新执行重新加载，无需重启，正在执行的请求使用自己的快照。共享配置对象不可直接修改。配置示例见 [LangChain Agent](./agent.md)。

配置模型统一继承项目自己的 `BaseSettings`，基于 Pydantic BaseModel，拒绝未知字段、禁止字段重新赋值并校验默认值。它只处理配置值，不自动读取环境变量、dotenv 或文件；分类 JSON 的加载与恢复由 loader 完成。`frozen` 不递归冻结 list/dict，未来含集合的运行快照需要显式隔离。Pydantic 的配置继承机制见[官方文档](https://docs.pydantic.dev/latest/concepts/config/#change-behaviour-globally)。

## 主配置

`data/configs/cmd_config.json`：

```json
{
  "paths": {"data_dir": "data"},
  "server": {"host": "127.0.0.1", "port": 8000}
}
```

## 日志配置

`data/configs/logging_config.json`：

```json
{
  "level": "INFO",
  "third_party_level": "WARNING",
  "file_path": "data/logs/anyagent.log",
  "max_bytes": 10485760,
  "backup_count": 5
}
```

相对路径以项目根目录为基准解析。数据路径必须位于 data/ 内，日志文件必须位于 data/logs/ 内，导出的路径为绝对路径。

需要获取运行文件或目录时，统一使用路径模块：

```python
from anyagent.configs import paths

config_file = paths.get_config_path("cmd_config")
logs_dir = paths.get_logs_dir()
```

`get_project_root()`、`get_data_dir()`、`get_configs_dir()` 和 `get_logs_dir()` 返回固定部署目录；`get_database_path()` 获取并校验 SQLite 文件路径；`get_log_path()` 获取默认日志文件，也可传入配置路径进行校验。当前使用的配置数据目录和日志文件分别以 `config.paths.data_dir` 和 `logging_config.file_path` 为准。旧配置和备份路径也由 paths 模块提供，其他代码不硬编码或自行拼接运行路径。路径函数只计算和校验，不创建目录或文件。

## 会话数据库

`data/configs/database_config.json`：

```json
{
  "file_path": "data/anyagent.db",
  "busy_timeout_seconds": 5
}
```

`DatabaseSettings` 校验 SQLite 文件路径必须位于 `data/` 内，扩展名为 `.db`、`.sqlite` 或 `.sqlite3`；锁等待时限为 1–60 秒。网页“会话存储”可修改这些值，保存后重启生效。更换路径会打开另一数据库，不搬迁旧会话。

数据库由 runtime 在启动时连接，使用 SQLAlchemy 异步仓储保存会话与已完成的历史窗口；连接测试仍使用隔离内存仓储。退出时完成执行清理并关闭连接池。损坏数据库不会触发 JSON 配置的备份恢复逻辑，也不会被覆盖为空库。

迁移或备份时先停止服务，再完整复制 `data/`，包括存在的 SQLite 辅助文件。旧版本的内存会话没有持久存档可以迁移。

## 独立扩展配置

新增配置类型通过文件名、校验模型和独立默认值接入，不往 cmd_config 添加其他应用模块的全部配置。示例：

```python
from anyagent.configs import BaseSettings, load_config


class FeatureConfig(BaseSettings):
    enabled: bool


feature_config = load_config("feature_config", FeatureConfig, {"enabled": False})
```

该调用仅加载或创建 `data/configs/feature_config.json`。名称使用小写字母、数字及下划线，不包含扩展名或目录。后续 MCP、RAG、Runner 配置采用同样方式按职责分文件；当前不预先创建这些功能的空配置。

## 网页保存与手动加载

网页保存先校验整组设置；无效输入仅返回字段提示，原文件不变。保存需携带载入时的 `revision`，多个页面产生冲突时需重新载入。有效修改通过原子替换写回 JSON，并保留文件权限；密钥留空保留，清除需要显式选择。

下面的备份恢复规则用于 loader 读取缺失或损坏文件，不会用来处理网页表单的错误输入。

## 缺失与无效配置

- 某个文件缺失时，只创建该类型的默认 JSON。
- 已有有效配置缺少新增默认项时，递归补齐并原子写回 JSON，保留原值、密钥和文件权限；完整配置不重复写入。缺失必填字段或现有值无效时仍按错误恢复规则处理。
- 编码、格式、字段或路径无效时，先备份为 `data/configs/<文件名>.<时间戳>.bak`，再恢复该类型默认值，不修改其他文件。
- 读取、备份或创建过程中的文件系统权限错误直接报告。
- 开发者传入的默认值无效时直接报错，不据此覆盖现有配置。

## 旧配置迁移

首次加载发现 `data/config.json` 时，将路径和服务参数迁移到 cmd_config.json，将 logging 内容拆分到 logging_config.json。旧配置没有日志字段时使用日志默认值。

已有新配置文件优先，迁移不覆盖其内容。完成后旧文件原样备份在 `data/configs/config.json.<时间戳>.bak`。旧文件内容无法加载时也先备份，再分别创建缺失的默认文件；发生权限等文件系统错误时保留错误并中止。再次启动不会重复迁移已归档的旧文件。
