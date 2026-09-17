"""Shared logging with queued console output and rotating UTF-8 files."""

import logging
import sys
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from queue import Queue

from configs.load import LoggingSettings

logger = logging.getLogger("anyagent")


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
        cls._listener = QueueListener(
            queue, console_handler, file_handler, respect_handler_level=True
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
