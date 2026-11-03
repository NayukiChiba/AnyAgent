"""data 目录进程互斥：OS 级文件锁，进程退出由内核自动释放。

同一部署根只允许一个服务进程：启动时锁定 data/anyagent.lock，
第二个进程获取失败并明确退出，避免两个实例并发写同一
SQLite 数据库与日志文件。锁随文件描述符生命周期存在，
进程异常退出（包括崩溃）后内核回收描述符、自动释放，
不存在残留的"死锁文件"问题。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import BinaryIO

from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


class DataLockError(RuntimeError):
    """data 目录已被另一个 AnyAgent 进程占用。"""


class DataDirectoryLock:
    """对锁文件的跨平台排他锁（Windows msvcrt / POSIX fcntl）。"""

    def __init__(self, path: Path):
        self._path = path
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        """获取排他锁；已被占用时抛出 DataLockError。

        同进程重复调用是幂等的，直接复用已有锁。
        """
        if self._file is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                # LK_NBLCK 非阻塞锁定首字节，失败立即抛 OSError；
                # 追加模式打开时指针在末尾，先回到文件头再锁
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise DataLockError(
                f"另一个 AnyAgent 进程正在使用数据目录 {self._path.parent}；"
                "请先停止该进程，或确认没有残留实例后重试"
            ) from error
        self._file = handle
        logger.debug("已获取数据目录锁: %s", self._path.name)

    def release(self) -> None:
        """释放锁并关闭文件；未持锁时调用安全。"""
        if self._file is None:
            return
        if os.name == "nt":
            import msvcrt

            # Windows 的锁必须显式解锁；POSIX 的 flock 随 close 自动释放
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        self._file.close()
        self._file = None

    def __enter__(self) -> DataDirectoryLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def exit_if_locked(path: Path) -> DataDirectoryLock:
    """获取 data 目录锁；失败时打印中文提示并以退出码 1 结束进程。

    供入口在日志系统配置之前调用，此时只能写 stderr。
    """
    lock = DataDirectoryLock(path)
    try:
        lock.acquire()
    except DataLockError as error:
        print(f"❌ 启动失败：{error}", file=sys.stderr)
        sys.exit(1)
    return lock
