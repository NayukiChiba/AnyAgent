"""实时日志推送：快照回放、跨线程实时投递、断线补发与 SSE 帧格式验证。

长连接流在 ASGITransport/TestClient 下会被整体缓冲，因此 HTTP 层用
once=true 的快照模式验证，实时投递在应用事件循环内直接验证。
"""

import asyncio
import json
import time

from fastapi.testclient import TestClient

from anyagent.runtime.bootstrap import create_app
from anyagent.utils.logbroker import broker


def make_entry(message: str, level: str = "INFO") -> dict:
    """构造一条规范的日志条目；id 由 broker 发布时统一分配。"""
    return {
        "level": level,
        "time": time.time(),
        "logger": "anyagent.test",
        "message": message,
    }


def test_logs_stream_once_replays_snapshot(runtime_paths):
    marker = f"snapshot-marker-{time.time_ns()}"
    with TestClient(create_app()) as client:
        broker.publish(make_entry(marker))
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
        # 帧带单调 id，供断线重连后的 Last-Event-ID 补发
        assert matched[0]["id"] > 0


def test_broker_delivers_live_across_threads(runtime_paths):
    """从测试线程发布的日志经 call_soon_threadsafe 投递到应用事件循环。"""
    live = f"live-entry-{time.time_ns()}"
    with TestClient(create_app()) as client:
        queue = client.portal.call(broker.subscribe)
        try:
            broker.publish(make_entry(live, level="WARNING"))

            async def receive() -> dict:
                return await asyncio.wait_for(queue.get(), timeout=5)

            entry = client.portal.call(receive)
            assert entry["message"] == live
            assert entry["level"] == "WARNING"
            assert entry["logger"] == "anyagent.test"
        finally:
            broker.unsubscribe(queue)


def test_broker_stream_replays_only_after_since_id(runtime_paths):
    """断线重连：since_id 之前的缓存条目不重发，之后的不遗漏。"""
    marker = f"resume-marker-{time.time_ns()}"
    with TestClient(create_app()) as client:
        broker.publish(make_entry(f"{marker}-old"))

        async def collect() -> list[dict]:
            collected = []
            stream = broker.stream()
            # 先拿到全量快照，确定分界 id
            async for entry in stream:
                collected.append(entry)
                if entry["message"] == f"{marker}-old":
                    break
            boundary = collected[-1]["id"]
            broker.publish(make_entry(f"{marker}-new-1"))
            broker.publish(make_entry(f"{marker}-new-2"))
            resumed = []
            async for entry in broker.stream(since_id=boundary):
                resumed.append(entry)
                if len(resumed) == 2:
                    break
            await stream.aclose()
            return resumed

        resumed = client.portal.call(collect)
        messages = [entry["message"] for entry in resumed]
        assert messages == [f"{marker}-new-1", f"{marker}-new-2"]


def test_logs_tail_and_stream_coexist(runtime_paths):
    with TestClient(create_app()) as client:
        tail = client.get("/api/v1/logs/tail")
        assert tail.status_code == 200
        assert "lines" in tail.json()
