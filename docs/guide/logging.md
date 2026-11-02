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

日志链条分三层，参考 AstrBot 的日志模块设计：业务代码只接触 AnyAgentLogger 门面（标准 logging API）；`_InterceptHandler` 把标准 logging 记录桥接进 loguru，由 loguru 统一管理控制台与文件 sink（enqueue 异步写出、rotation 轮转、retention 保留）；loguru 的广播 sink 把记录推给 `LogBroker`，Web 实时日志订阅者经 SSE 接收。原生 logging 与 loguru 均仅限 utils/logger.py 内部使用，业务模块禁止直接导入。日志模块导入不加载配置、不创建文件或线程；LogManager.configure 显式接收已校验配置，避免配置 loader 与日志相互引用。core 依赖该通用接口是明确的跨层日志例外，不依赖其他 utils 实现。

源码中的日志内容使用英文。异常日志保留堆栈，文件采用 UTF-8 编码，支持中文数据。

## 输出与配置

通过 `main.py` 启动时，日志同时输出到控制台和 `data/logs/anyagent.log`，格式包含时间、级别、模块名和源码位置；控制台输出在终端内按级别着色，重定向时自动输出纯文本。项目日志和达到依赖门槛的标准 `logging` 日志统一桥接进 loguru，经异步队列写出。默认过滤 Uvicorn、HTTP 客户端、事件循环等依赖的 DEBUG/INFO，保留其警告和错误；main.py 关闭 HTTP 请求访问日志。

文件参数来自 `data/configs/logging_config.json`：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `level` | `INFO` | 支持 DEBUG、INFO、WARNING、ERROR、CRITICAL |
| `third_party_level` | `WARNING` | 依赖日志的额外最低级别，仍受 level 限制；网页日志高级设置可调整 |
| `file_path` | `data/logs/anyagent.log` | 日志文件，必须在根目录 data/logs/ 内 |
| `max_bytes` | `10485760` | 当前文件达到约 10 MiB 后轮转 |
| `backup_count` | `5` | 最多保留五个轮转备份 |

达到 `max_bytes` 后当前文件轮转为 `anyagent.<时间戳>.log`（loguru 命名规则），最多保留 `backup_count` 份，当前文件与备份均在 `data/logs/` 内。

## INFO 与 DEBUG

INFO 展示项目启动、SQLite 连接、用户输入、完整模型最终回复、工具调用名称/标识/参数/结果，以及执行开始/完成/取消和服务退出。业务内容默认进入控制台和文件；记录会话标识、耗时和数量以关联操作。模型回复在校验后记录，历史提交单独记录，因此数据库写入失败时也能看到已生成的回复。执行失败与超时使用 WARNING。

DEBUG 补充 LangChain 每轮模型响应（含工具请求）、会话创建/删除、上下文消息数、Runner 创建、工具调用次数与历史提交阶段。流式 delta 不逐 token 写入日志，正常轮次最终回复在 INFO 完整记录一次。选择 DEBUG 不会默认放开依赖日志；需要定位依赖问题时单独调整 third_party_level。数据库驱动、SQLAlchemy 引擎以及 OpenAI/HTTP 客户端低于 WARNING 的日志始终过滤，避免 SQL 参数、请求载荷与密钥进入日志。

AnyAgentLogger 将字典、列表等结构化参数输出为保留中文的单行 JSON，转义正文换行，避免伪造日志行。嵌套字段和可解析的 JSON 字符串中的 api_key、Authorization、password、access_token 等认证字段替换为 `[REDACTED]`，保留普通正文和参数；原始事件与会话内容不变。自由文本中的任意凭据无法仅凭字段名自动识别，调用方不得把连接配置、模型 API Key、认证头或整个 SDK 响应/异常正文传入日志。

AstrBot 的[工具循环](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/agent/runners/tool_loop_agent_runner.py)在 INFO 记录工具名称、参数和结果，[回复阶段](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/pipeline/respond/stage.py)在 INFO 记录发送内容，[OpenAI Provider](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/provider/sources/openai_source.py)在 DEBUG 记录 completion。基础日志模块主要负责等级、格式、输出、插件分级和独立 trace 通道，没有统一禁止模型回复/工具参数，也未发现通用正文脱敏器；内容由业务调用点决定。AnyAgent 保留自己的自定义入口和认证字段保护，不引入插件日志或额外 trace 系统。

参考 AstrBot 的[日志模块](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/log.py)对噪声依赖单独设门槛的做法，AnyAgent 在入桥前的拦截过滤器上实现门槛，不修改其他日志处理器。core 统一使用项目日志接口。

## 执行上下文

`log_context` 以 ContextVar 方式给 with 块内的所有日志附加字段，适合标记一次执行链路：

```python
from anyagent.utils.logger import log_context

with log_context(run=run_id):
    # 本块内（含 runner、工具层）产生的日志都带 [run=...] 标签
    ...
```

字段渲染为行内 `[run=xxx session=yyy]` 片段，嵌套使用时内层覆盖同名字段，退出后自动还原。ChatService 已为每次 Agent 执行注入 run 标识，下游模块无需显式传参。

## 实时日志推送

`LogBroker`（utils/logbroker.py）是进程级发布-订阅广播器：日志引擎经广播 sink 写入固定容量（500 条）的内存缓存，并为每条日志分配单调递增 id；SSE 订阅者各持有一条有界 asyncio.Queue，跨线程投递经 `loop.call_soon_threadsafe`，队列满时丢弃最旧条目，慢订阅者不阻塞日志线程。

- `GET /api/v1/logs/stream`：先回放缓存快照，再持续推送实时日志；SSE 帧携带条目 id，EventSource 断线重连时自动带上 Last-Event-ID 头，服务端据此只补发遗漏条目，快照与实时段重叠部分按 id 去重；PING 心跳帧不带 id。`once=true` 时仅回放快照后关闭。
- `GET /api/v1/logs/tail?lines=200`：从日志文件尾部反向分块读取，不整文件加载。

## 生命周期

`LogManager.configure(logging_config)` 在服务启动前配置输出；`LogManager.shutdown()` 在退出时移除本项目装配的 sink（loguru 在移除时冲刷异步队列）并恢复 root 级别。重复配置会先回收旧装配，避免重复写入，其他模块安装的处理器保持原样。

直接调用 `create_app()` 时，宿主程序负责配置和关闭日志。日志文件属于运行数据，不提交 Git。迁移时可根据需要保留或清理历史日志。
