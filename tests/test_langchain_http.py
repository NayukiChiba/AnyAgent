"""Exercise the SDK/tool loop against a local OpenAI-compatible protocol fixture."""

import json

import pytest
from fastapi.testclient import TestClient

from anyagent.configs import paths
from anyagent.runtime.bootstrap import create_app
from tests.model_fixture import open_model_endpoint


@pytest.fixture
def model_endpoint():
    with open_model_endpoint() as endpoint:
        yield endpoint


@pytest.fixture
def configured_app(tmp_path, monkeypatch, model_endpoint):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "CONFIGS_DIR", tmp_path / "data/configs")
    paths.get_configs_dir().mkdir(parents=True)
    connection = {
        "enabled": True,
        "base_url": model_endpoint[0],
        "model": "fixture-model",
        "api_key": "fixture-secret",
    }
    paths.get_config_path("model_config").write_text(json.dumps(connection))
    yield create_app(), connection


def test_real_sdk_tool_loop_http_sse_websocket_and_hot_reload(
    configured_app, model_endpoint
):
    app, connection = configured_app
    upstream = model_endpoint[1]
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions").json()
        url = f"/api/v1/sessions/{session['id']}"
        assert "fixture-secret" not in client.get("/api/v1/agent").text
        response = client.post(f"{url}/messages", json={"content": "计算 2+3"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["content"] == "结果是 5"
        assert [event["type"] for event in result["events"]] == [
            "tool_call",
            "tool_result",
            "delta",
            "delta",
            "result",
        ]
        assert result["events"][1]["data"]["content"] == "5.0"
        assert len(upstream) == 2
        assert upstream[1]["body"]["messages"][-1]["role"] == "tool"
        assert upstream[0]["path"] == "/v1/chat/completions"
        assert upstream[0]["authorization"] == "Bearer fixture-secret"
        connection.update(model="reloaded-model", api_key="reloaded-secret")
        paths.get_config_path("model_config").write_text(json.dumps(connection))
        assert client.get("/api/v1/agent").json()["model"] == "reloaded-model"
        response = client.post(f"{url}/stream", json={"content": "再计算一次"})
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: result" in response.text
        assert upstream[2]["body"]["model"] == "reloaded-model"
        assert upstream[2]["authorization"] == "Bearer reloaded-secret"
        assert [message["role"] for message in upstream[2]["body"]["messages"]] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
        with client.websocket_connect(f"/ws/sessions/{session['id']}") as socket:
            socket.send_json({"type": "message", "content": "第三次"})
            events = []
            while not events or events[-1]["type"] not in {"result", "error"}:
                events.append(socket.receive_json())
            assert events[-1]["type"] == "result", events
            assert events[-1]["data"]["content"] == "结果是 5"
        history = client.get(url).json()["messages"]
        assert len(history) == 6
        assert client.post(f"{url}/messages", json={"content": " "}).status_code == 422
        assert client.delete(url).status_code == 204
        assert client.get(url).status_code == 404
        assert client.get("/api/v1/agent").json()["storage"] == "memory"
    with TestClient(app) as client:
        assert client.get("/api/v1/sessions").json() == []
    assert not list(paths.get_data_dir().rglob("*.sqlite*"))


def test_disabled_model_returns_public_error_without_saving_turn(configured_app):
    app, connection = configured_app
    connection["enabled"] = False
    paths.get_config_path("model_config").write_text(json.dumps(connection))
    with TestClient(app) as client:
        session = client.post("/api/v1/sessions").json()
        url = f"/api/v1/sessions/{session['id']}"
        result = client.post(f"{url}/messages", json={"content": "你好"})
        assert result.status_code == 503
        assert result.json()["detail"]["code"] == "model_not_configured"
        assert client.get(url).json()["messages"] == []
        assert (
            "event: error"
            in client.post(f"{url}/stream", json={"content": "你好"}).text
        )
