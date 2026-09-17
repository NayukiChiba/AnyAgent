# 配置管理

运行配置按类型组织在根目录 `data/configs/`，不提交 Git：

| 文件 | 内容 | 导出对象 |
| --- | --- | --- |
| `cmd_config.json` | 主配置：数据路径、服务监听参数 | `cmd_config`，别名 `config` |
| `logging_config.json` | 日志级别、文件路径、轮转参数 | `logging_config` |

配置代码位于 `anyagent/configs/`，属于应用的外层支撑模块。`base.py` 定义共享校验规则，`models.py` 定义具体配置模型，`default.py` 定义默认值并创建 JSON，`paths.py` 集中处理路径，`load.py` 加载、校验和恢复分类 JSON，`__init__.py` 导出共享对象。实际 JSON 和日志始终保存在项目根目录 data，不随代码迁入应用包。启动入口、runtime 和需要配置的外层模块直接获取所需配置；核心应用通过注入的运行快照使用配置值：

```python
from anyagent.configs import cmd_config, logging_config

host = cmd_config.server.host
log_file = logging_config.file_path
```

模块导入时加载当前配置，修改 JSON 后需要重启服务。共享配置对象不可直接修改。

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

`get_project_root()`、`get_data_dir()`、`get_configs_dir()` 和 `get_logs_dir()` 返回固定部署目录；`get_log_path()` 获取默认日志文件，也可传入配置路径进行校验。当前使用的配置数据目录和日志文件分别以 `config.paths.data_dir` 和 `logging_config.file_path` 为准。旧配置和备份路径也由 paths 模块提供，其他代码不硬编码或自行拼接运行路径。路径函数只计算和校验，不创建目录或文件。

## 独立扩展配置

新增配置类型通过文件名、校验模型和独立默认值接入，不往 cmd_config 添加其他应用模块的全部配置。示例：

```python
from anyagent.configs import BaseSettings, load_config


class FeatureConfig(BaseSettings):
    enabled: bool


feature_config = load_config("feature_config", FeatureConfig, {"enabled": False})
```

该调用仅加载或创建 `data/configs/feature_config.json`。名称使用小写字母、数字及下划线，不包含扩展名或目录。后续 MCP、RAG、Runner 配置采用同样方式按职责分文件；当前不预先创建这些功能的空配置。

## 缺失与无效配置

- 某个文件缺失时，只创建该类型的默认 JSON。
- 编码、格式、字段或路径无效时，先备份为 `data/configs/<文件名>.<时间戳>.bak`，再恢复该类型默认值，不修改其他文件。
- 读取、备份或创建过程中的文件系统权限错误直接报告。
- 开发者传入的默认值无效时直接报错，不据此覆盖现有配置。

## 旧配置迁移

首次加载发现 `data/config.json` 时，将路径和服务参数迁移到 cmd_config.json，将 logging 内容拆分到 logging_config.json。旧配置没有日志字段时使用日志默认值。

已有新配置文件优先，迁移不覆盖其内容。完成后旧文件原样备份在 `data/configs/config.json.<时间戳>.bak`。旧文件内容无法加载时也先备份，再分别创建缺失的默认文件；发生权限等文件系统错误时保留错误并中止。再次启动不会重复迁移已归档的旧文件。
