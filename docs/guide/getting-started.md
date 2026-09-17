# 快速开始

## 环境准备

运行服务需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。Node.js 仅用于开发和构建本站文档。

## 启动服务

```bash
git clone https://github.com/NayukiChiba/AnyAgent.git
cd AnyAgent
uv sync --locked
uv run main.py
```

首次启动会创建 `data/configs/cmd_config.json`，服务默认监听 `127.0.0.1:8000`，日志写入 `data/logs/anyagent.log`。

访问 <http://127.0.0.1:8000/docs> 查看交互式 API 文档。

## 覆盖监听参数

```bash
uv run main.py --host 0.0.0.0 --port 8080
```

命令行覆盖只对本次启动生效，不修改保存的配置。已经安装项目依赖时，也可使用虚拟环境的 `python main.py` 启动。

路径以项目根目录为基准解析。从其他工作目录使用虚拟环境 Python 执行 `main.py` 的绝对路径时，配置和日志位置保持一致。

## 停止服务

按 `Ctrl+C`。服务完成退出后，日志模块清空待写队列并关闭文件句柄。

下一步可阅读[配置管理](./configuration.md)和[健康检查](./health.md)。
