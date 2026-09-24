"""日志广播器：把运行日志分发给 Web 界面的实时订阅者。

参考 AstrBot 的 LogBroker 模式：
- logging.Handler 在任意线程调用 publish()，写入固定容量的缓存队列；
- SSE 订阅者在事件循环中持有 asyncio.Queue，通过
  loop.call_soon_threadsafe 跨线程投递，避免在日志线程里操作事件循环；
- 新订阅者先收到缓存快照，再接收实时日志，保证打开页面即可看到最近日志。
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator


class LogBroker:
    """日志消息的缓存与扇出中心；线程安全的发布 + 协程安全的订阅。"""

    def __init__(self, capacity: int = 500):
        self._cache: deque[dict] = deque(maxlen=capacity)
        self._subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定事件循环；服务启动时调用一次，之后日志线程据此投递。"""
        self._loop = loop

    def detach_loop(self) -> None:
        self._loop = None

    def publish(self, record: logging.LogRecord) -> None:
        """接收日志记录：写入缓存并投递给所有订阅者。"""
        entry = {
            "level": record.levelname,
            "time": record.created,
            "logger": record.name,
            "message": record.getMessage(),
        }
        self._cache.append(entry)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        for queue in list(self._subscribers):
            loop.call_soon_threadsafe(self._deliver, queue, entry)

    def snapshot(self) -> list[dict]:
        """返回缓存的日志快照，供新订阅者回放。"""
        return list(self._cache)

    def subscribe(self) -> asyncio.Queue:
        """注册一个订阅者队列；容量略大于缓存，消化快照 + 实时洪峰。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._cache.maxlen + 10)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    @staticmethod
    def _deliver(queue: asyncio.Queue, entry: dict) -> None:
        """在事件循环线程内投递；队列满时丢弃最旧的，避免拖垮日志线程。"""
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(entry)

    async def stream(self) -> AsyncIterator[dict]:
        """异步迭代器：先回放快照，再持续产出实时日志。"""
        queue = self.subscribe()
        try:
            for entry in self.snapshot():
                yield entry
            while True:
                try:
                    # 超时让调用方有机会发送心跳，检测连接存活
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield {
                        "level": "PING",
                        "time": time.time(),
                        "logger": "",
                        "message": "",
                    }
        finally:
            self.unsubscribe(queue)


# 进程级单例：logging 配置与 API 路由共享同一个广播器
broker = LogBroker()


class BrokerHandler(logging.Handler):
    """把日志记录转发给广播器；本身不输出，只扇出。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            broker.publish(record)
        except Exception:
            self.handleError(record)
