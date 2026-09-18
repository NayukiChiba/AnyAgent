# 日志

独立模块 `anyagent.utils.logger` 为包括 core 在内的所有项目模块提供自定义 `AnyAgentLogger` 日志入口：

```python
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)

logger.info("Task started: %s", task_id)

try:
    execute_task()
except Exception:
    logger.exception("Task execution failed")
    raise
```

共享入口可使用 `from anyagent.utils.logger import logger`；模块入口使用 `get_logger(__name__)`，名称须属于 `anyagent` 命名空间。接口只提供 debug、info、warning、error、critical、exception 方法及只读名称，不提供原生 Logger 的 Handler 或级别修改能力。业务代码禁止直接导入 logging、调用 logging.getLogger 或自行配置输出。

原生 logging 仅在 utils/logger 内部承接队列、文件输出和第三方兼容。日志模块导入不加载配置、不创建文件或线程；LogManager.configure 显式接收已校验配置，避免配置 loader 与日志相互引用。core 依赖该通用接口是明确的跨层日志例外，不依赖其他 utils 实现。

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

INFO 展示项目启动、SQLite 连接、用户输入、完整模型最终回复、工具调用名称/标识/参数/结果，以及执行开始/完成/取消和服务退出。业务内容默认进入控制台和文件；记录会话标识、耗时和数量以关联操作。模型回复在校验后记录，历史提交单独记录，因此数据库写入失败时也能看到已生成的回复。执行失败与超时使用 WARNING。

DEBUG 补充 LangChain 每轮模型响应（含工具请求）、会话创建/删除、上下文消息数、Runner 创建、工具调用次数与历史提交阶段。流式 delta 不逐 token 写入日志，正常轮次最终回复在 INFO 完整记录一次。选择 DEBUG 不会默认放开依赖日志；需要定位依赖问题时单独调整 third_party_level。数据库驱动、SQLAlchemy 引擎以及 OpenAI/HTTP 客户端低于 WARNING 的日志始终过滤，避免 SQL 参数、请求载荷与密钥进入日志。

AnyAgentLogger 将字典、列表等结构化参数输出为保留中文的单行 JSON，转义正文换行，避免伪造日志行。嵌套字段和可解析的 JSON 字符串中的 api_key、Authorization、password、access_token 等认证字段替换为 `[REDACTED]`，保留普通正文和参数；原始事件与会话内容不变。自由文本中的任意凭据无法仅凭字段名自动识别，调用方不得把连接配置、模型 API Key、认证头或整个 SDK 响应/异常正文传入日志。

AstrBot 的[工具循环](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/agent/runners/tool_loop_agent_runner.py)在 INFO 记录工具名称、参数和结果，[回复阶段](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/pipeline/respond/stage.py)在 INFO 记录发送内容，[OpenAI Provider](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/provider/sources/openai_source.py)在 DEBUG 记录 completion。基础日志模块主要负责等级、格式、输出、插件分级和独立 trace 通道，没有统一禁止模型回复/工具参数，也未发现通用正文脱敏器；内容由业务调用点决定。AnyAgent 保留自己的自定义入口和认证字段保护，不引入插件日志或额外 trace 系统。

参考 AstrBot 的[日志模块](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/log.py)对噪声依赖单独设门槛的做法，AnyAgent 通过自己的队列处理器过滤，不修改其他日志处理器。core 统一使用项目日志接口。

## 生命周期

`LogManager.configure(logging_config)` 在服务启动前配置输出；`LogManager.shutdown()` 在退出时清空队列并关闭本模块的处理器。重复配置会替换本模块的输出处理器，避免重复写入，其他模块安装的处理器保持原样。

直接调用 `create_app()` 时，宿主程序负责配置和关闭日志。日志文件属于运行数据，不提交 Git。迁移时可根据需要保留或清理历史日志。
