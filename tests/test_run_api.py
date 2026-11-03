"""Run API 的 HTTP 层验证：创建、查询、SSE 订阅与取消。

验收语义：创建后执行与订阅解耦——无订阅者执行仍完成（创建后仅
轮询查询的用例即覆盖）；SSE 帧携带事件序号，Last-Event-ID 支持
断点重连，终态后可重放。

注意：starlette TestClient 会把响应完整缓冲后才返回（handle_request
等待应用协程结束），无法验证"执行中实时推送"。实时订阅由服务层
测试覆盖（tests/test_run_service.py），端到端实时性由前端 e2e
（真实服务进程）验收。
"""

import asyncio
import json
import time

from fastapi.testclient import TestClient

from anyagent.runtime.bootstrap import create_app
from tests.mock_runner import MockRunnerFactory


def wait_run_status(client, run_id, status, timeout=5.0):
    """轮询直到 Run 到达目标状态，返回最新快照。"""
    deadline = time.monotonic() + timeout
    snapshot = {}
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/v1/runs/{run_id}").json()
        if snapshot["status"] == status:
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f"Run 未在 {timeout}s 内进入 {status}: {snapshot}")


def frame_iter(response):
    """逐帧解析 SSE 流，产出 (event, payload, event_id)；event_id 可能为 None。"""
    event = data = event_id = None
    for line in response.iter_lines():
        if not line:
            if event is not None:
                yield event, json.loads(data), event_id
                event = data = event_id = None
            continue
        field, _, value = line.partition(": ")
        if field == "event":
            event = value
        elif field == "data":
            data = value
        elif field == "id":
            event_id = int(value)


def read_frames(response, count):
    """读取 count 个 SSE 帧（适用于会自然结束的流）。

    httpx 的响应流只允许消费一次，需要在读取中途执行动作的用例
    应直接使用 frame_iter 保持同一个迭代器。
    """
    frames = frame_iter(response)
    return [next(frames) for _ in range(count)]


def create_session_run(client, content="你好"):
    session = client.post("/api/v1/sessions").json()
    response = client.post(
        "/api/v1/runs", json={"session_id": session["id"], "content": content}
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "queued"
    assert run["session_id"] == session["id"]
    return session, run


def test_run_create_query_and_terminal_replay(runtime_paths):
    factory = MockRunnerFactory(
        [
            ("event", "delta", {"content": "部分"}),
            ("event", "result", {"content": "完成"}),
        ]
    )
    with TestClient(create_app(runner_factory=factory)) as client:
        session, run = create_session_run(client)
        assert run["profile_id"] == "mock"
        assert run["config_snapshot"]["profile_id"] == "mock"

        snapshot = wait_run_status(client, run["id"], "succeeded")
        assert snapshot["result"] == "完成"
        assert snapshot["finished_at"] is not None
        # 成功后历史已提交
        detail = client.get(f"/api/v1/sessions/{session['id']}").json()
        assert [message["role"] for message in detail["messages"]] == [
            "user",
            "assistant",
        ]

        # 终态后订阅：缓冲重放完整事件序列，序号单调
        with client.stream("GET", f"/api/v1/runs/{run['id']}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            frames = read_frames(response, 5)
        assert [frame[0] for frame in frames] == [
            "status",
            "status",
            "delta",
            "result",
            "status",
        ]
        assert [frame[2] for frame in frames] == [0, 1, 2, 3, 4]
        assert [frame[1]["seq"] for frame in frames] == [0, 1, 2, 3, 4]
        assert frames[-1][1]["data"]["status"] == "succeeded"
        assert frames[3][1]["data"]["content"] == "完成"

        # Last-Event-ID 断点续传：只补发序号之后的事件
        with client.stream(
            "GET",
            f"/api/v1/runs/{run['id']}/events",
            headers={"Last-Event-ID": "2"},
        ) as response:
            frames = read_frames(response, 2)
        assert [frame[2] for frame in frames] == [3, 4]
        assert frames[0][0] == "result"


def test_run_cancel_flow(runtime_paths):
    gate = asyncio.Event()
    factory = MockRunnerFactory([("wait", gate)])
    with TestClient(create_app(runner_factory=factory)) as client:
        session, run = create_session_run(client)
        wait_run_status(client, run["id"], "running")

        cancelled = client.post(f"/api/v1/runs/{run['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        snapshot = client.get(f"/api/v1/runs/{run['id']}").json()
        assert snapshot["status"] == "cancelled"
        assert snapshot["finished_at"] is not None
        assert snapshot["error"] is None
        # 取消不提交半轮历史
        assert client.get(f"/api/v1/sessions/{session['id']}").json()["messages"] == []
        assert client.get("/api/v1/stats").json()["runs_cancelled"] == 1

        # 终态后重复取消
        again = client.post(f"/api/v1/runs/{run['id']}/cancel")
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "invalid_state"


def test_stateless_run(runtime_paths):
    factory = MockRunnerFactory([("event", "result", {"content": "完成"})])
    with TestClient(create_app(runner_factory=factory)) as client:
        response = client.post("/api/v1/runs", json={"content": "你好"})
        assert response.status_code == 201
        run = response.json()
        assert run["session_id"] is None

        snapshot = wait_run_status(client, run["id"], "succeeded")
        assert snapshot["result"] == "完成"
        # 无会话执行不创建会话
        assert client.get("/api/v1/sessions").json() == []


def test_run_session_busy(runtime_paths):
    gate = asyncio.Event()
    factory = MockRunnerFactory([("wait", gate)])
    with TestClient(create_app(runner_factory=factory)) as client:
        session, run = create_session_run(client)
        wait_run_status(client, run["id"], "running")

        busy = client.post(
            "/api/v1/runs", json={"session_id": session["id"], "content": "再来"}
        )
        assert busy.status_code == 409
        assert busy.json()["detail"]["code"] == "session_busy"

        assert client.post(f"/api/v1/runs/{run['id']}/cancel").status_code == 200


def test_run_api_errors(runtime_paths):
    with TestClient(create_app(runner_factory=MockRunnerFactory())) as client:
        # 查询与取消不存在的 Run
        missing = client.get("/api/v1/runs/missing")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "run_not_found"
        cancel_missing = client.post("/api/v1/runs/missing/cancel")
        assert cancel_missing.status_code == 404

        # 绑定不存在的会话
        orphan = client.post(
            "/api/v1/runs", json={"session_id": "missing", "content": "你好"}
        )
        assert orphan.status_code == 404
        assert orphan.json()["detail"]["code"] == "session_not_found"

        # 输入校验：空白、空串、缺字段、未知字段、超长
        assert client.post("/api/v1/runs", json={"content": "   "}).status_code == 422
        assert client.post("/api/v1/runs", json={"content": ""}).status_code == 422
        assert client.post("/api/v1/runs", json={}).status_code == 422
        assert (
            client.post(
                "/api/v1/runs", json={"content": "你好", "extra": 1}
            ).status_code
            == 422
        )
        too_long = client.post("/api/v1/runs", json={"content": "字" * 8001})
        assert too_long.status_code == 422
        assert too_long.json()["detail"]["code"] == "invalid_message"

        # 订阅不存在的 Run：连接建立后以错误帧结束（沿用既有 SSE 错误格式）
        with client.stream("GET", "/api/v1/runs/missing/events") as response:
            assert response.status_code == 200
            frames = read_frames(response, 1)
        assert frames[0][0] == "error"
        assert frames[0][1]["data"]["code"] == "run_not_found"
