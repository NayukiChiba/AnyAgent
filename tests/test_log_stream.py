"""实时日志推送：快照回放、跨线程实时投递与 SSE 帧格式验证。

长连接流在 ASGITransport/TestClient 下会被整体缓冲，因此 HTTP 层用
once=true 的快照模式验证，实时投递在应用事件循环内直接验证。
"""

import asyncio
import json
import time

from fastapi.testclient import TestClient

from anyagent.runtime.bootstrap import create_app
from anyagent.utils.logbroker import broker


class FakeRecord:
    """publish() 只依赖四个属性，用鸭子类型避免直接引入 logging。"""

    def __init__(self, message: str, levelname: str = "INFO"):
        self.message = message
        self.levelname = levelname
        self.created = time.time()
        self.name = "anyagent.test"

    def getMessage(self) -> str:
        return self.message


def test_logs_stream_once_replays_snapshot(runtime_paths):
    marker = f"snapshot-marker-{time.time_ns()}"
    with TestClient(create_app()) as client:
        broker.publish(FakeRecord(marker))
        response = client.get("/api/v1/logs/stream", params={"once": "true"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = [
            json.loads(line.removeprefix("data:").strip())
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        assert all(frame["level"] != "PING" for frame in frames)  # 快照模式无心跳
        matched = [frame for frame in frames if frame["message"] == marker]
        assert matched and matched[0]["level"] == "INFO"
        assert matched[0]["logger"] == "anyagent.test"


def test_broker_delivers_live_across_threads(runtime_paths):
    """从测试线程发布的日志经 call_soon_threadsafe 投递到应用事件循环。"""
    live = f"live-entry-{time.time_ns()}"
    with TestClient(create_app()) as client:
        queue = client.portal.call(broker.subscribe)
        try:
            broker.publish(FakeRecord(live, levelname="WARNING"))

            async def receive() -> dict:
                return await asyncio.wait_for(queue.get(), timeout=5)

            entry = client.portal.call(receive)
            assert entry["message"] == live
            assert entry["level"] == "WARNING"
            assert entry["logger"] == "anyagent.test"
        finally:
            broker.unsubscribe(queue)


def test_logs_tail_and_stream_coexist(runtime_paths):
    with TestClient(create_app()) as client:
        tail = client.get("/api/v1/logs/tail")
        assert tail.status_code == 200
        assert "lines" in tail.json()
