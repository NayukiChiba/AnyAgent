"""OpenAI 兼容网关的协议验证。"""

import json

from fastapi.testclient import TestClient

from anyagent.runtime.bootstrap import create_app
from tests.test_chat_service import Factory


def test_models_listing(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        data = client.get("/v1/models").json()
        assert data["object"] == "list"
        assert data["data"][0]["id"] == "anyagent"
        assert data["data"][0]["object"] == "model"


def test_chat_completion_non_stream(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "anyagent",
                "messages": [
                    {"role": "system", "content": "助手"},
                    {"role": "user", "content": "你好"},
                ],
                # 额外字段应被忽略而非拒绝
                "temperature": 0.5,
                "top_p": 0.9,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["object"] == "chat.completion"
        assert data["id"].startswith("chatcmpl-")
        assert data["model"] == "anyagent"
        choice = data["choices"][0]
        assert choice["message"] == {"role": "assistant", "content": "回复"}
        assert choice["finish_reason"] == "stop"
        # 无状态：网关调用不产生会话
        assert client.get("/api/v1/sessions").json() == []


def test_chat_completion_stream(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "你好"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [
            line for line in response.text.splitlines() if line.startswith("data:")
        ]
        assert lines[-1] == "data: [DONE]"
        chunks = [json.loads(line[5:].strip()) for line in lines[:-1]]
        assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
        assert chunks[0]["object"] == "chat.completion.chunk"
        contents = [c["choices"][0]["delta"].get("content", "") for c in chunks]
        assert "回复" in contents
        assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_chat_completion_rejects_invalid_sequence(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "assistant", "content": "先说话"}]},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_message"
        # 空消息列表与不合法 role 由请求模型拒绝
        assert (
            client.post("/v1/chat/completions", json={"messages": []}).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "root", "content": "你好"}]},
            ).status_code
            == 422
        )


def test_chat_completion_model_not_configured(runtime_paths):
    from tests.test_chat_service import Runner

    factory = Factory()
    factory.next = Runner(fail=True)
    with TestClient(create_app(runner_factory=factory)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "你好"}]},
        )
        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "runner_failed"
        # SDK 异常细节不泄漏
        assert "secret" not in response.text
