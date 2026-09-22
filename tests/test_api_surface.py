"""会话管理增强、能力清单与可观测性接口的 HTTP 层验证。"""

import asyncio
from contextlib import aclosing

from fastapi.testclient import TestClient

from anyagent.configs import load_logging_config
from anyagent.runtime.bootstrap import create_app
from tests.test_chat_service import Factory, Runner


def test_session_rename_via_api(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        session = client.post("/api/v1/sessions").json()
        url = f"/api/v1/sessions/{session['id']}"
        response = client.patch(url, json={"title": "  新标题  "})
        assert response.status_code == 200
        assert response.json()["title"] == "新标题"
        assert client.get(url).json()["title"] == "新标题"
        # 空白标题经服务层校验拒绝，超长或缺字段由请求模型拒绝
        assert client.patch(url, json={"title": "   "}).status_code == 422
        assert client.patch(url, json={"title": "x" * 61}).status_code == 422
        assert client.patch(url, json={"title": 1}).status_code == 422
        assert client.patch(url, json={}).status_code == 422
        missing = client.patch("/api/v1/sessions/missing", json={"title": "标题"})
        assert missing.status_code == 404


def test_session_cancel_via_api(runtime_paths):
    gate = asyncio.Event()
    factory = Factory()
    factory.next = Runner(gate=gate)
    with TestClient(create_app(runner_factory=factory)) as client:
        session = client.post("/api/v1/sessions").json()
        url = f"/api/v1/sessions/{session['id']}"
        idle = client.post(f"{url}/cancel")
        assert idle.status_code == 409
        assert idle.json()["detail"]["code"] == "session_not_running"

        # TestClient 会缓冲流式响应，改为在 app 事件循环内直接发起 run
        service = client.app.state.chat_service

        async def consume():
            async with aclosing(service.stream(session["id"], "你好")) as stream:
                async for _ in stream:
                    pass

        client.portal.start_task_soon(consume)
        client.portal.call(asyncio.sleep, 0.1)
        assert client.get("/api/v1/stats").json()["active_runs"] == 1

        response = client.post(f"{url}/cancel")
        assert response.status_code == 200
        client.portal.call(asyncio.sleep, 0.1)
        stats = client.get("/api/v1/stats").json()
        assert stats["active_runs"] == 0
        assert stats["runs_cancelled"] == 1
        # 取消后历史不提交
        assert client.get(url).json()["messages"] == []


def test_tools_listing(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        tools = client.get("/api/v1/tools").json()
        names = [tool["name"] for tool in tools]
        assert "calculate" in names
        calculate = next(tool for tool in tools if tool["name"] == "calculate")
        assert calculate["description"]
        assert calculate["parameters"]["type"] == "object"


def test_runners_listing(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        data = client.get("/api/v1/runners").json()
        assert data["current"] == "langchain"
        ids = [runner["id"] for runner in data["runners"]]
        assert ids == [
            "langchain",
            "langgraph",
            "loop",
            "dify",
            "coze",
            "pi",
            "deerflow",
        ]
        for runner in data["runners"]:
            assert runner["kind"] in ("local", "remote")
            assert isinstance(runner["tools"], bool)
            assert runner["label"] and runner["description"]


def test_stats_via_api(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        session = client.post("/api/v1/sessions").json()
        url = f"/api/v1/sessions/{session['id']}/messages"
        assert client.post(url, json={"content": "你好"}).status_code == 200
        stats = client.get("/api/v1/stats").json()
        assert stats["runs_started"] == 1
        assert stats["runs_completed"] == 1
        assert stats["runs_failed"] == 0
        assert stats["active_runs"] == 0
        assert stats["sessions"] == 1
        assert stats["runner"] == "langchain"


def test_logs_tail_via_api(runtime_paths):
    log_path = load_logging_config().file_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(f"line-{index}" for index in range(10)), encoding="utf-8"
    )
    with TestClient(create_app(runner_factory=Factory())) as client:
        response = client.get("/api/v1/logs/tail?lines=3")
        assert response.status_code == 200
        assert response.json()["lines"] == ["line-7", "line-8", "line-9"]
        assert client.get("/api/v1/logs/tail?lines=0").status_code == 422
        assert client.get("/api/v1/logs/tail?lines=1001").status_code == 422


def test_logs_tail_missing_file_returns_empty(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        assert client.get("/api/v1/logs/tail").json()["lines"] == []
