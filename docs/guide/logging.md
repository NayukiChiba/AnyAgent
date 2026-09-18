# 日志

独立模块 `anyagent.utils.logger` 为外层模块提供统一日志入口：

```python
from anyagent.utils.logger import logger

logger.info("Task started: %s", task_id)

try:
    execute_task()
except Exception:
    logger.exception("Task execution failed")
    raise
```

源码中的日志内容使用英文。异常日志保留堆栈，文件采用 UTF-8 编码，支持中文数据。

## 输出与配置

通过 `main.py` 启动时，日志同时输出到控制台和 `data/logs/anyagent.log`，格式包含时间、级别、模块名和源码位置。项目日志和达到依赖门槛的标准 `logging` 日志统一进入写入队列。默认过滤 Uvicorn、HTTP 客户端、事件循环等依赖的 DEBUG/INFO，保留其警告和错误；main.py 关闭 HTTP 请求访问日志。

文件参数来自 `data/configs/logging_config.json`：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `level` | `INFO` | 支持 DEBUG、INFO、WARNING、ERROR、CRITICAL |
| `third_party_level` | `WARNING` | 依赖日志的额外最低级别，仍受 level 限制；网页日志高级设置可调整 |
| `file_path` | `data/logs/anyagent.log` | 日志文件，必须在根目录 data/logs/ 内 |
| `max_bytes` | `10485760` | 当前文件达到约 10 MiB 后轮转 |
| `backup_count` | `5` | 最多保留五个轮转备份 |

轮转文件依次为 `anyagent.log.1`、`anyagent.log.2` 等，当前文件与备份均在 `data/logs/` 内。

## INFO 与 DEBUG

INFO 展示项目启动、SQLite 连接、Agent 执行开始/完成/取消和服务退出。执行记录包含会话标识、耗时、输出长度和工具次数，便于对应操作；不输出聊天正文、工具参数、模型密钥或 SDK 异常正文。执行失败与超时使用 WARNING。

DEBUG 补充会话创建/删除、上下文消息数、Runner 创建、工具调用次数与历史提交阶段。选择 DEBUG 不会默认放开依赖日志；需要定位依赖问题时单独调整 third_party_level。数据库驱动、SQLAlchemy 引擎以及 OpenAI/HTTP 客户端低于 WARNING 的日志始终过滤，避免 SQL 参数、请求载荷与密钥进入日志。

参考 AstrBot 的[日志模块](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/log.py)对噪声依赖单独设门槛的做法，AnyAgent 通过自己的队列处理器过滤，不修改其他日志处理器。core 继续使用标准库模块日志。

## 生命周期

`LogManager.configure(logging_config)` 在服务启动前配置输出；`LogManager.shutdown()` 在退出时清空队列并关闭本模块的处理器。重复配置会替换本模块的输出处理器，避免重复写入，其他模块安装的处理器保持原样。

直接调用 `create_app()` 时，宿主程序负责配置和关闭日志。日志文件属于运行数据，不提交 Git。迁移时可根据需要保留或清理历史日志。
