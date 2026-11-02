"""统一日志门面：stdlib logging 作前端 API，loguru 作后端 sink 引擎。

三层结构（参考 AstrBot 的日志链条）：
1. AnyAgentLogger 门面：业务代码唯一入口，Ruff 禁用直接 import logging/loguru；
2. _InterceptHandler：把 stdlib 记录桥进 loguru，console 与文件 sink 由
   loguru 统一管理（enqueue 异步写出、rotation 轮转、retention 保留）；
3. LogBroker 广播：loguru sink 把记录推给广播器，SSE 订阅者实时接收。

业务代码只应使用本模块导出的 get_logger()/logger/log_context()。
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from loguru import logger as _raw_loguru

if TYPE_CHECKING:
    from anyagent.configs.models import LoggingSettings

from anyagent.utils.logbroker import broker

__all__ = ["AnyAgentLogger", "LogManager", "get_logger", "log_context", "logger"]


_CREDENTIAL_FIELDS = frozenset(
    {
        "apikey",
        "authorization",
        "proxyauthorization",
        "password",
        "passwd",
        "secret",
        "clientsecret",
        "accesstoken",
        "refreshtoken",
        "token",
        "privatekey",
        "secretkey",
        "credentials",
    }
)


def _redact_payload(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if str(key).replace("_", "").replace("-", "").casefold()
            in _CREDENTIAL_FIELDS
            else _redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            structured = json.loads(value)
        except (ValueError, RecursionError):
            return value
        if isinstance(structured, (dict, list)):
            redacted = _redact_payload(structured)
            if redacted == structured:
                return value
            return json.dumps(redacted, ensure_ascii=False)
    return value


def _format_argument(value: object) -> object:
    if not isinstance(value, (dict, list, tuple)):
        return value
    try:
        return json.dumps(_redact_payload(value), ensure_ascii=False, default=str)
    except (TypeError, ValueError, RecursionError):
        # 负载序列化失败不允许中断 Agent 执行
        return "[UNSERIALIZABLE PAYLOAD]"


class AnyAgentLogger:
    """项目日志门面：只暴露固定级别方法，不泄露后端引擎配置。"""

    def __init__(self, name: str = "anyagent"):
        if name != "anyagent" and not name.startswith("anyagent."):
            raise ValueError(
                "Project logger names must belong to the anyagent namespace"
            )
        self._backend = logging.getLogger(name)

    @property
    def name(self) -> str:
        return self._backend.name

    def _emit(
        self,
        level: int,
        message: str,
        args: tuple[object, ...],
        *,
        exception: bool = False,
    ) -> None:
        if not self._backend.isEnabledFor(level):
            return
        formatted = tuple(_format_argument(value) for value in args)
        self._backend.log(level, message, *formatted, exc_info=exception, stacklevel=3)

    def debug(self, message: str, *args: object) -> None:
        self._emit(logging.DEBUG, message, args)

    def info(self, message: str, *args: object) -> None:
        self._emit(logging.INFO, message, args)

    def warning(self, message: str, *args: object) -> None:
        self._emit(logging.WARNING, message, args)

    def error(self, message: str, *args: object) -> None:
        self._emit(logging.ERROR, message, args)

    def critical(self, message: str, *args: object) -> None:
        self._emit(logging.CRITICAL, message, args)

    def exception(self, message: str, *args: object) -> None:
        self._emit(logging.ERROR, message, args, exception=True)


def get_logger(name: str = "anyagent") -> AnyAgentLogger:
    """创建项目日志门面；不加载配置、不打开任何资源。

    Args:
        name: 项目命名空间，或以 anyagent. 开头的完整模块名。

    Returns:
        固定级别、保持调用方归属的受控日志门面。

    Raises:
        ValueError: 名称不属于 anyagent 命名空间。
    """
    return AnyAgentLogger(name)


logger = get_logger()


# 执行上下文字段（如 run/session 标识），随 ContextVar 在协程与线程间传播
_log_context: ContextVar[dict[str, str]] = ContextVar(
    "anyagent_log_context", default={}
)


@contextmanager
def log_context(**fields: str) -> Iterator[None]:
    """在 with 块内为所有日志注入上下文字段（如 run_id/session_id）。

    空值字段被忽略；嵌套使用时内层字段覆盖同名外层字段，
    退出 with 块后自动还原。
    """
    merged = {**_log_context.get(), **{k: v for k, v in fields.items() if v}}
    token = _log_context.set(merged)
    try:
        yield
    finally:
        _log_context.reset(token)


def _render_context(fields: dict[str, str]) -> str:
    """把上下文字典渲染成行内片段；空上下文渲染为空串。"""
    if not fields:
        return ""
    return " [" + " ".join(f"{key}={value}" for key, value in fields.items()) + "]"


def _patch_record(record: dict) -> None:
    """给每条 loguru 记录补齐默认 extra，格式串可放心引用。"""
    extra = record["extra"]
    extra.setdefault("std_name", record["name"] or "")
    extra.setdefault("std_file", record["file"].name if record["file"] else "")
    extra.setdefault("std_line", record["line"])
    extra.setdefault("log_context", "")


# 全局统一的 patched logger：所有 sink 共享同一份 extra 补齐逻辑
_loguru = _raw_loguru.patch(_patch_record)


class _ApplicationLogFilter(logging.Filter):
    """入桥前的统一门槛：项目日志按配置级别，第三方按独立级别。

    数据库驱动与 SDK 的调试记录可能携带凭据与报文内容，
    无论配置如何都压到 WARNING 以上。
    """

    def __init__(self, third_party_level: str):
        super().__init__()
        self.third_party_level = logging.getLevelNamesMapping()[third_party_level]

    def filter(self, record: logging.LogRecord) -> bool:
        sensitive = any(
            record.name == name or record.name.startswith(name + ".")
            for name in (
                "aiosqlite",
                "sqlalchemy.engine",
                "openai",
                "httpx",
                "httpcore",
            )
        )
        project = record.name == "anyagent" or record.name.startswith("anyagent.")
        minimum = 0 if project else self.third_party_level
        if sensitive:
            minimum = max(minimum, logging.WARNING)
        return record.levelno >= minimum


class _InterceptHandler(logging.Handler):
    """把 stdlib 记录桥进 loguru：归属信息走 extra，消息不再二次格式化。"""

    def emit(self, record: logging.LogRecord) -> None:
        # stdlib 存在 loguru 未注册的级别名时按数值记录
        try:
            level: str | int = _loguru.level(record.levelname).name
        except ValueError:
            level = record.levelno
        payload = {
            "std_name": record.name,
            "std_file": record.filename,
            "std_line": record.lineno,
            "log_context": _render_context(_log_context.get()),
        }
        try:
            _loguru.bind(**payload).opt(exception=record.exc_info).log(
                level, record.getMessage()
            )
        except Exception:
            self.handleError(record)


def _broker_sink(message) -> None:
    """loguru 函数 sink：把记录规范化后推给广播器。"""
    record = message.record
    exception = record["exception"]
    exception_text = None
    if exception is not None:
        exception_text = f"{exception.type.__name__}: {exception.value}"
    broker.publish(
        {
            "level": record["level"].name,
            "time": record["time"].timestamp(),
            "logger": record["extra"]["std_name"],
            "message": record["message"],
            "context": record["extra"]["log_context"].strip(" []"),
            "file": record["extra"]["std_file"],
            "line": record["extra"]["std_line"],
            "exception": exception_text,
        }
    )


class LogManager:
    """日志引擎装配器：按配置安装 loguru sink 与 stdlib 桥，支持重复装配。"""

    _intercept: _InterceptHandler | None = None
    _sink_ids: list[int] = []
    _previous_root_level: int | None = None

    @classmethod
    def configure(cls, settings: LoggingSettings) -> None:
        """按配置装配日志输出；重复调用先回收旧装配，不产生重复记录。

        Args:
            settings: 已校验的日志配置，file_path 必须是绝对路径。

        Raises:
            OSError: 日志目录或文件无法创建。
        """
        cls.shutdown()
        settings.file_path.parent.mkdir(parents=True, exist_ok=True)

        # 清掉 loguru 默认 sink 与历史残留，只保留本次装配的三个 sink
        _loguru.remove()
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> <level>[{level}]</level> "
            "<cyan>{extra[std_name]}</cyan> "
            "[{extra[std_file]}:{extra[std_line]}]{extra[log_context]} "
            "<level>{message}</level>"
        )
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} [{level}] {extra[std_name]} "
            "[{extra[std_file]}:{extra[std_line]}]{extra[log_context]} {message}"
        )
        cls._sink_ids = [
            _loguru.add(
                sys.stderr,
                level=settings.level,
                format=console_format,
                # None 表示自动检测：tty 上色，重定向到文件时输出纯文本
                colorize=None,
                enqueue=True,
            ),
            _loguru.add(
                settings.file_path,
                level=settings.level,
                format=file_format,
                encoding="utf-8",
                rotation=settings.max_bytes,
                retention=settings.backup_count,
                enqueue=True,
            ),
            # 广播 sink 只做内存扇出，不经过格式化与异步写队列
            _loguru.add(_broker_sink, level="DEBUG", format=""),
        ]

        root = logging.getLogger()
        cls._previous_root_level = root.level
        root.setLevel(settings.level)
        cls._intercept = _InterceptHandler()
        cls._intercept.setLevel(settings.level)
        cls._intercept.addFilter(_ApplicationLogFilter(settings.third_party_level))
        root.addHandler(cls._intercept)

    @classmethod
    def shutdown(cls) -> None:
        """回收本项目装配的 handler 与 sink，冲刷队列并恢复 root 级别。"""
        root = logging.getLogger()
        if cls._intercept is not None:
            root.removeHandler(cls._intercept)
            cls._intercept.close()
            cls._intercept = None
        for sink_id in cls._sink_ids:
            try:
                # remove 会等待 enqueue 队列清空后再返回
                _loguru.remove(sink_id)
            except ValueError:
                # sink 已被 remove() 全清时忽略
                pass
        cls._sink_ids = []
        if cls._previous_root_level is not None:
            root.setLevel(cls._previous_root_level)
            cls._previous_root_level = None
