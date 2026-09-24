"""Shared logging with queued console output and rotating UTF-8 files."""

from __future__ import annotations

import json
import logging
import sys
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from queue import Queue
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyagent.configs.models import LoggingSettings


from anyagent.utils.logbroker import BrokerHandler

__all__ = ["AnyAgentLogger", "LogManager", "get_logger", "logger"]


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
        # Logging unsupported payloads must not interrupt agent execution.
        return "[UNSERIALIZABLE PAYLOAD]"


class AnyAgentLogger:
    """Expose project messages without exposing backend logger configuration."""

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
    """Create a project logger without loading configuration or opening resources.

    Args:
        name: Project namespace or full module name starting with anyagent.

    Returns:
        Controlled logging facade with fixed levels and caller attribution.

    Raises:
        ValueError: The logger name belongs to an external namespace.
    """
    return AnyAgentLogger(name)


logger = get_logger()


class _ApplicationLogFilter(logging.Filter):
    def __init__(self, third_party_level: str):
        super().__init__()
        self.third_party_level = logging.getLevelNamesMapping()[third_party_level]

    def filter(self, record: logging.LogRecord) -> bool:
        # Driver and SDK debug records can include credentials and message content.
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


class LogManager:
    _listener: QueueListener | None = None
    _queue_handler: QueueHandler | None = None
    _previous_root_level: int | None = None

    @classmethod
    def configure(cls, settings: LoggingSettings) -> None:
        """Configure shared output, replacing only this module's own handlers.

        Args:
            settings: Validated logging settings with an absolute file path.

        Raises:
            OSError: The log directory or file cannot be created.
        """
        cls.shutdown()
        settings.file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.file_path,
            maxBytes=settings.max_bytes,
            backupCount=settings.backup_count,
            encoding="utf-8",
        )
        console_handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s "
            "[%(filename)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        for handler in (console_handler, file_handler):
            handler.setFormatter(formatter)
            handler.setLevel(settings.level)

        queue: Queue = Queue()
        cls._queue_handler = QueueHandler(queue)
        cls._queue_handler.setLevel(settings.level)
        cls._queue_handler.addFilter(_ApplicationLogFilter(settings.third_party_level))
        # 广播处理器不做格式化输出，只把日志扇出给 Web 实时日志订阅者；
        # 入队前的级别与过滤已生效，这里接收全部通过过滤的记录。
        cls._listener = QueueListener(
            queue,
            console_handler,
            file_handler,
            BrokerHandler(),
            respect_handler_level=True,
        )
        root = logging.getLogger()
        cls._previous_root_level = root.level
        root.setLevel(settings.level)
        cls._listener.start()
        root.addHandler(cls._queue_handler)

    @classmethod
    def shutdown(cls) -> None:
        """Flush pending records and close owned handlers without affecting others."""
        if cls._listener is None:
            return
        root = logging.getLogger()
        root.removeHandler(cls._queue_handler)
        cls._listener.stop()
        for handler in cls._listener.handlers:
            handler.close()
        cls._queue_handler.close()
        root.setLevel(cls._previous_root_level)
        cls._listener = None
        cls._queue_handler = None
        cls._previous_root_level = None
