"""Runner 档案 API：CRUD、密钥保护、同源校验与热切换验证。"""

import json

from fastapi.testclient import TestClient

from anyagent.configs import paths
from anyagent.runtime.bootstrap import create_app
from tests.model_fixture import open_model_endpoint


def profile_payload(**overrides) -> dict:
    values = {
        "name": "测试档案",
        "type": "langchain",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key": "sk-test",
    }
    return values | overrides


def test_profiles_crud_and_activate(runtime_paths):
    with TestClient(create_app()) as client:
        empty = client.get("/api/v1/profiles").json()
        assert empty == {"active": None, "profiles": []}

        created = client.post("/api/v1/profiles", json=profile_payload())
        assert created.status_code == 201
        first = created.json()
        assert first["active"] is True  # 首个档案自动启用
        assert first["has_api_key"] is True
        assert "api_key" not in first  # 密钥不回显

        second = client.post(
            "/api/v1/profiles",
            json=profile_payload(
                name="二号", type="dify", model="", base_url="https://api.dify.ai/v1"
            ),
        ).json()
        assert second["active"] is False  # 后续创建不抢占启用位

        # 更新：留空密钥保持不变
        updated = client.put(
            f"/api/v1/profiles/{second['id']}",
            json=profile_payload(
                name="二号改", type="dify", model="", base_url="https://api.dify.ai/v1"
            ),
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "二号改"
        stored = json.loads(
            paths.get_config_path("runner_profiles").read_text(encoding="utf-8")
        )
        assert stored["profiles"][1]["api_key"] == "sk-test"

        # 切换与删除回落
        client.post(f"/api/v1/profiles/{second['id']}/activate")
        data = client.get("/api/v1/profiles").json()
        assert data["active"] == second["id"]
        assert client.delete(f"/api/v1/profiles/{second['id']}").status_code == 204
        assert client.get("/api/v1/profiles").json()["active"] == first["id"]

        # 404 路径
        assert client.get("/api/v1/profiles").json()["profiles"][0]["id"] == first["id"]
        missing = "/api/v1/profiles/not-exist"
        assert client.post(f"{missing}/activate").status_code == 404
        assert client.delete(missing).status_code == 404
        assert client.put(missing, json=profile_payload()).status_code == 404


def test_profiles_validation(runtime_paths):
    with TestClient(create_app()) as client:
        # 本地引擎缺模型名称
        response = client.post("/api/v1/profiles", json=profile_payload(model=""))
        assert response.status_code == 422
        assert "模型名称" in response.json()["detail"]["message"]
        # coze 缺 bot_id
        response = client.post(
            "/api/v1/profiles", json=profile_payload(type="coze", model="")
        )
        assert response.status_code == 422
        assert "Bot ID" in response.json()["detail"]["message"]
        # 缺密钥；响应不回显提交内容
        response = client.post("/api/v1/profiles", json=profile_payload(api_key=""))
        assert response.status_code == 422
        assert "sk-test" not in response.text
        # 非法 base_url
        assert (
            client.post(
                "/api/v1/profiles", json=profile_payload(base_url="ftp://x")
            ).status_code
            == 422
        )


def test_profiles_reject_cross_site_mutation(runtime_paths):
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/profiles",
            json=profile_payload(),
            headers={"sec-fetch-site": "cross-site"},
        )
        assert response.status_code == 403
        assert client.get("/api/v1/profiles").json()["profiles"] == []


def test_hot_switch_changes_next_run_connection(runtime_paths):
    """启用另一个档案后，下一次对话立即使用新连接，无需重启。"""
    with open_model_endpoint() as (base_url, upstream):
        with TestClient(create_app()) as client:
            session = client.post("/api/v1/sessions").json()
            url = f"/api/v1/sessions/{session['id']}/messages"

            first = client.post(
                "/api/v1/profiles",
                json=profile_payload(
                    name="一号", base_url=base_url, api_key="first-key"
                ),
            ).json()
            response = client.post(url, json={"content": "计算 2+3"})
            assert response.status_code == 200, response.text
            assert upstream[-1]["authorization"] == "Bearer first-key"

            second = client.post(
                "/api/v1/profiles",
                json=profile_payload(
                    name="二号",
                    base_url=base_url,
                    model="switched-model",
                    api_key="second-key",
                ),
            ).json()
            client.post(f"/api/v1/profiles/{second['id']}/activate")
            response = client.post(url, json={"content": "再算一次"})
            assert response.status_code == 200, response.text
            assert upstream[-1]["authorization"] == "Bearer second-key"
            assert upstream[-1]["body"]["model"] == "switched-model"

            # agent 信息反映活动档案
            info = client.get("/api/v1/agent").json()
            assert info["profile"]["id"] == second["id"]
            assert info["runner"] == "langchain"
            assert info["model"] == "switched-model"
            assert "second-key" not in client.get("/api/v1/agent").text


def test_chat_without_profile_returns_public_error(runtime_paths):
    with TestClient(create_app()) as client:
        session = client.post("/api/v1/sessions").json()
        response = client.post(
            f"/api/v1/sessions/{session['id']}/messages", json={"content": "你好"}
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "model_not_configured"
