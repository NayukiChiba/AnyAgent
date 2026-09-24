"""模型连接与 Runner 档案 API：CRUD、密钥保护、引用约束与热切换验证。"""

import json

from fastapi.testclient import TestClient

from anyagent.configs import paths
from anyagent.runtime.bootstrap import create_app
from tests.model_fixture import open_model_endpoint


def model_payload(**overrides) -> dict:
    values = {
        "name": "测试连接",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key": "sk-test",
    }
    return values | overrides


def profile_payload(model_id: str, **overrides) -> dict:
    values = {"name": "测试档案", "type": "langchain", "model_id": model_id}
    return values | overrides


def create_model(client, **overrides) -> dict:
    response = client.post("/api/v1/models", json=model_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_models_crud_and_secret_protection(runtime_paths):
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/models").json() == {"models": []}

        created = create_model(client)
        assert created["has_api_key"] is True
        assert "api_key" not in created  # 密钥不回显
        assert created["referenced_by"] == []

        # 更新：留空密钥保持不变
        updated = client.put(
            f"/api/v1/models/{created['id']}",
            json=model_payload(name="改名", api_key=""),
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "改名"
        stored = json.loads(
            paths.get_config_path("model_profiles").read_text(encoding="utf-8")
        )
        assert stored["profiles"][0]["api_key"] == "sk-test"

        missing = "/api/v1/models/not-exist"
        assert client.put(missing, json=model_payload()).status_code == 404
        assert client.delete(missing).status_code == 404
        assert client.post(f"{missing}/test").status_code == 404

        assert client.delete(f"/api/v1/models/{created['id']}").status_code == 204
        assert client.get("/api/v1/models").json() == {"models": []}


def test_models_validation(runtime_paths):
    with TestClient(create_app()) as client:
        # 缺密钥；响应不回显提交内容
        response = client.post("/api/v1/models", json=model_payload(api_key=""))
        assert response.status_code == 422
        assert "sk-test" not in response.text
        # 非法 base_url
        assert (
            client.post(
                "/api/v1/models", json=model_payload(base_url="ftp://x")
            ).status_code
            == 422
        )
        # 未填写模型名称的连接无法测试
        empty_model = create_model(client, model="")
        response = client.post(f"/api/v1/models/{empty_model['id']}/test")
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "model_incomplete"


def test_model_delete_blocked_when_referenced(runtime_paths):
    with TestClient(create_app()) as client:
        model = create_model(client)
        profile = client.post(
            "/api/v1/profiles", json=profile_payload(model["id"])
        ).json()
        listed = client.get("/api/v1/models").json()["models"][0]
        assert listed["referenced_by"] == ["测试档案"]
        response = client.delete(f"/api/v1/models/{model['id']}")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "model_in_use"
        # 删除 Runner 后放行
        assert client.delete(f"/api/v1/profiles/{profile['id']}").status_code == 204
        assert client.delete(f"/api/v1/models/{model['id']}").status_code == 204


def test_model_connection_test_against_endpoint(runtime_paths):
    with open_model_endpoint() as (base_url, upstream):
        with TestClient(create_app()) as client:
            model = create_model(client, base_url=base_url, api_key="probe-key")
            response = client.post(f"/api/v1/models/{model['id']}/test")
            assert response.status_code == 200, response.text
            assert upstream[-1]["authorization"] == "Bearer probe-key"
            # 连接不可达时返回 503 且不泄露密钥
            bad = create_model(
                client,
                name="坏连接",
                base_url="http://127.0.0.1:1/v1",
                api_key="unreachable-key",
            )
            response = client.post(f"/api/v1/models/{bad['id']}/test")
            assert response.status_code == 503
            assert "unreachable-key" not in response.text


def test_profiles_crud_and_activate(runtime_paths):
    with TestClient(create_app()) as client:
        empty = client.get("/api/v1/profiles").json()
        assert empty == {"active": None, "profiles": []}
        model = create_model(client)

        created = client.post("/api/v1/profiles", json=profile_payload(model["id"]))
        assert created.status_code == 201
        first = created.json()
        assert first["active"] is True  # 首个档案自动启用
        assert first["model"]["id"] == model["id"]
        assert first["model"]["model"] == "gpt-4.1-mini"

        second = client.post(
            "/api/v1/profiles",
            json=profile_payload(model["id"], name="二号", type="dify"),
        ).json()
        assert second["active"] is False  # 后续创建不抢占启用位

        updated = client.put(
            f"/api/v1/profiles/{second['id']}",
            json=profile_payload(model["id"], name="二号改", type="dify"),
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "二号改"

        # 切换与删除回落
        client.post(f"/api/v1/profiles/{second['id']}/activate")
        data = client.get("/api/v1/profiles").json()
        assert data["active"] == second["id"]
        assert client.delete(f"/api/v1/profiles/{second['id']}").status_code == 204
        assert client.get("/api/v1/profiles").json()["active"] == first["id"]

        # 404 路径
        missing = "/api/v1/profiles/not-exist"
        assert client.post(f"{missing}/activate").status_code == 404
        assert client.delete(missing).status_code == 404
        assert client.put(missing, json=profile_payload(model["id"])).status_code == 404


def test_profiles_validation(runtime_paths):
    with TestClient(create_app()) as client:
        model = create_model(client)
        # 引用的模型连接不存在
        response = client.post("/api/v1/profiles", json=profile_payload("missing"))
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "model_missing"
        # 本地引擎要求模型连接填写模型名称
        unnamed = create_model(client, name="未命名模型", model="")
        response = client.post("/api/v1/profiles", json=profile_payload(unnamed["id"]))
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "model_incomplete"
        # 远端平台引擎不要求模型名称
        response = client.post(
            "/api/v1/profiles",
            json=profile_payload(unnamed["id"], name="Dify", type="dify"),
        )
        assert response.status_code == 201
        # coze 缺 bot_id
        response = client.post(
            "/api/v1/profiles", json=profile_payload(model["id"], type="coze")
        )
        assert response.status_code == 422
        assert "Bot ID" in response.json()["detail"]["message"]


def test_profiles_reject_cross_site_mutation(runtime_paths):
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/profiles",
            json=profile_payload("any"),
            headers={"sec-fetch-site": "cross-site"},
        )
        assert response.status_code == 403
        assert client.get("/api/v1/profiles").json()["profiles"] == []
        response = client.post(
            "/api/v1/models",
            json=model_payload(),
            headers={"sec-fetch-site": "cross-site"},
        )
        assert response.status_code == 403
        assert client.get("/api/v1/models").json() == {"models": []}


def test_hot_switch_changes_next_run_connection(runtime_paths):
    """启用另一个档案后，下一次对话立即使用新连接，无需重启。"""
    with open_model_endpoint() as (base_url, upstream):
        with TestClient(create_app()) as client:
            session = client.post("/api/v1/sessions").json()
            url = f"/api/v1/sessions/{session['id']}/messages"

            first_model = create_model(client, base_url=base_url, api_key="first-key")
            first = client.post(
                "/api/v1/profiles",
                json=profile_payload(first_model["id"], name="一号"),
            ).json()
            response = client.post(url, json={"content": "计算 2+3"})
            assert response.status_code == 200, response.text
            assert upstream[-1]["authorization"] == "Bearer first-key"

            second_model = create_model(
                client,
                name="二号连接",
                base_url=base_url,
                model="switched-model",
                api_key="second-key",
            )
            second = client.post(
                "/api/v1/profiles",
                json=profile_payload(second_model["id"], name="二号"),
            ).json()
            client.post(f"/api/v1/profiles/{second['id']}/activate")
            response = client.post(url, json={"content": "再算一次"})
            assert response.status_code == 200, response.text
            assert upstream[-1]["authorization"] == "Bearer second-key"
            assert upstream[-1]["body"]["model"] == "switched-model"

            # agent 信息反映活动档案与其模型连接
            info = client.get("/api/v1/agent").json()
            assert info["profile"]["id"] == second["id"]
            assert info["model_profile"]["id"] == second_model["id"]
            assert info["runner"] == "langchain"
            assert info["model"] == "switched-model"
            assert "second-key" not in client.get("/api/v1/agent").text


def test_chat_with_dangling_model_reference_returns_public_error(runtime_paths):
    """Runner 引用的模型连接被外力删除后，对话返回可操作的错误提示。"""
    with TestClient(create_app()) as client:
        model = create_model(client)
        client.post("/api/v1/profiles", json=profile_payload(model["id"]))
        # 绕过 API 直接删文件内容，模拟引用失效
        paths.get_config_path("model_profiles").write_text(
            json.dumps({"profiles": []}), encoding="utf-8"
        )
        session = client.post("/api/v1/sessions").json()
        response = client.post(
            f"/api/v1/sessions/{session['id']}/messages", json={"content": "你好"}
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "model_missing"
        # agent 信息标记为未配置，引导用户修复
        info = client.get("/api/v1/agent").json()
        assert info["configured"] is False
        assert info["model_profile"] is None


def test_chat_without_profile_returns_public_error(runtime_paths):
    with TestClient(create_app()) as client:
        session = client.post("/api/v1/sessions").json()
        response = client.post(
            f"/api/v1/sessions/{session['id']}/messages", json={"content": "你好"}
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "model_not_configured"
