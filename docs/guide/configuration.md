# 配置管理

实际配置保存在根目录 `data/config.json`，不提交 Git。根目录 `configs/` 只保存 Python 配置代码：

| 模块 | 职责 |
| --- | --- |
| `default.py` | 定义默认值和统一路径，创建默认 JSON |
| `load.py` | 加载、校验和解析当前配置 |
| `__init__.py` | 导出共享 `config` |

启动入口和 `src` 模块使用同一份配置：

```python
from configs import config

host = config.server.host
log_file = config.logging.file_path
```

导入模块时加载配置，修改 JSON 后需要重启服务。配置对象不可直接修改。

## 配置示例

```json
{
  "paths": {
    "data_dir": "data"
  },
  "server": {
    "host": "127.0.0.1",
    "port": 8000
  },
  "logging": {
    "level": "INFO",
    "file_path": "data/logs/anyagent.log",
    "max_bytes": 10485760,
    "backup_count": 5
  }
}
```

相对路径以项目根目录为基准解析。数据路径必须位于 `data/` 内，日志文件必须位于 `data/logs/` 内；解析后导出的路径为绝对路径。

## 缺失与无效配置

- 文件缺失时自动创建默认 JSON。
- 编码、JSON 格式、配置字段或路径无效时，先备份到 `data/config.json.<时间戳>.bak`，再创建默认配置。
- 文件读取、备份和创建过程中出现权限等文件系统错误时，直接报告错误。
- 已有 JSON 未包含 `logging` 时，加载默认日志参数，保留原文件和已有服务配置。

未知字段会视为无效配置。停止服务后修改配置，确认字段名和数值正确，再重新启动。
