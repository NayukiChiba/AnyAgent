# 日志

独立模块 `anyagent.logger` 提供统一日志入口：

```python
from anyagent.logger import logger

logger.info("Task started: %s", task_id)

try:
    execute_task()
except Exception:
    logger.exception("Task execution failed")
    raise
```

源码中的日志内容使用英文。异常日志保留堆栈，文件采用 UTF-8 编码，支持中文数据。

## 输出与配置

通过 `main.py` 启动时，日志同时输出到控制台和 `data/logs/anyagent.log`，格式包含时间、级别、模块名和源码位置。应用日志、向上传播的标准 `logging` 日志及 Uvicorn 服务和访问日志统一进入写入队列。

文件参数来自 `data/configs/logging_config.json`：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `level` | `INFO` | 支持 DEBUG、INFO、WARNING、ERROR、CRITICAL |
| `file_path` | `data/logs/anyagent.log` | 日志文件，必须在根目录 data/logs/ 内 |
| `max_bytes` | `10485760` | 当前文件达到约 10 MiB 后轮转 |
| `backup_count` | `5` | 最多保留五个轮转备份 |

轮转文件依次为 `anyagent.log.1`、`anyagent.log.2` 等，当前文件与备份均在 `data/logs/` 内。

## 生命周期

`LogManager.configure(logging_config)` 在服务启动前配置输出；`LogManager.shutdown()` 在退出时清空队列并关闭本模块的处理器。重复配置会替换本模块的输出处理器，避免重复写入，其他模块安装的处理器保持原样。

直接调用 `create_app()` 时，宿主程序负责配置和关闭日志。日志文件属于运行数据，不提交 Git。迁移时可根据需要保留或清理历史日志。
