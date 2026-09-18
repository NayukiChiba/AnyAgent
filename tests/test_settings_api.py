"""Accept configuration edits while preserving credentials and valid files."""

import json
import stat

import pytest
from fastapi.testclient import TestClient

from anyagent.configs import paths
from anyagent.configs.catalog import GROUPS, form_fields
from anyagent.configs.default import DEFAULT_CONFIGS
from anyagent.runtime.bootstrap import create_app
from tests.model_fixture import open_model_endpoint


@pytest.fixture
def settings_client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "CONFIGS_DIR", tmp_path / "data/configs")
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "data/logs")
    monkeypatch.setattr(paths, "LEGACY_CONFIG_FILE", tmp_path / "data/config.json")
    with TestClient(create_app()) as client:
        yield client


def group(client, name):
    return next(
        item
        for item in client.get("/api/v1/settings").json()["groups"]
        if item["name"] == name
    )


def save(client, name, values, **kwargs):
    payload = {"revision": group(client, name)["revision"], "values": values, **kwargs}
    return client.put(f"/api/v1/settings/{name}", json=payload)


def test_catalog_covers_every_configuration_field(settings_client):
    response = settings_client.get("/api/v1/settings")
    assert response.status_code == 200
    assert set(GROUPS) == set(DEFAULT_CONFIGS)
    assert {item["name"] for item in response.json()["groups"]} == set(GROUPS)
    for name, entry in GROUPS.items():
        public = group(settings_client, name)

        def leaf_paths(values, prefix=""):
            for key, value in values.items():
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    yield from leaf_paths(value, path)
                else:
                    yield path

        assert set(leaf_paths(public["values"])) == {
            field["path"] for field in form_fields(entry)
        }
        assert not public["restart_required"]
        assert paths.get_config_path(name).is_file()


def test_secret_retention_clear_and_model_hot_reload(settings_client):
    client = settings_client
    values = {"enabled": True, "model": "my-model", "api_key": "super-secret"}
    result = save(client, "model_config", values)
    assert result.status_code == 200
    assert "super-secret" not in result.text
    assert result.json()["has_api_key"]
    assert (
        result.json()["values"]["api_key"] == result.json()["defaults"]["api_key"] == ""
    )
    assert "super-secret" not in client.get("/api/v1/settings").text
    assert client.get("/api/v1/agent").json()["model"] == "my-model"
    path = paths.get_config_path("model_config")
    path.chmod(0o600)
    result = save(client, "model_config", {"api_key": "", "streaming": False})
    assert result.status_code == 200
    assert json.loads(path.read_text())["api_key"] == "super-secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert client.get("/api/v1/agent").json()["streaming"] is False
    original = path.read_bytes()
    rejected = save(client, "model_config", {}, clear_api_key=True)
    assert rejected.status_code == 422
    assert "api_key" in rejected.json()["detail"]["fields"]
    assert path.read_bytes() == original
    result = save(client, "model_config", {"enabled": False}, clear_api_key=True)
    assert result.status_code == 200
    assert not result.json()["has_api_key"]
    assert json.loads(path.read_text())["api_key"] == ""


@pytest.mark.parametrize(
    ("name", "values", "field"),
    [
        ("cmd_config", {"server": {"port": 0}}, "server.port"),
        ("cmd_config", {"server": {"host": "http://oops"}}, "server.host"),
        ("cmd_config", {"paths": {"data_dir": "../escape"}}, "paths.data_dir"),
        ("logging_config", {"file_path": "data/outside.log"}, "file_path"),
        (
            "model_config",
            {"base_url": "https://example.com/v1/chat/completions"},
            "base_url",
        ),
        ("model_config", {"base_url": "https://example.com:bad/v1"}, "base_url"),
        ("model_config", {"streaming": "false"}, "streaming"),
        ("model_config", {"api_key": 42}, "api_key"),
        ("langchain_config", {"max_steps": 1}, "max_steps"),
        ("frontend_config", {"default_transport": "tcp"}, "default_transport"),
        ("frontend_config", {"unknown": True}, "unknown"),
    ],
)
def test_invalid_edit_preserves_file(settings_client, name, values, field):
    path = paths.get_config_path(name)
    original = path.read_bytes()
    response = save(settings_client, name, values)
    assert response.status_code == 422, response.text
    assert field in response.json()["detail"]["fields"]
    assert path.read_bytes() == original


def test_conflicts_nested_updates_and_restart_notice(settings_client):
    client = settings_client
    current = group(client, "cmd_config")
    result = save(client, "cmd_config", {"server": {"port": 9000}})
    assert result.status_code == 200
    assert result.json()["restart_required"]
    assert (
        result.json()["values"]["server"]["host"] == current["values"]["server"]["host"]
    )
    stale = client.put(
        "/api/v1/settings/cmd_config",
        json={"revision": current["revision"], "values": {"server": {"port": 9999}}},
    )
    assert stale.status_code == 409
    assert group(client, "cmd_config")["values"]["server"]["port"] == 9000
    unchanged = group(client, "logging_config")
    assert (
        save(client, "logging_config", unchanged["values"]).json()["revision"]
        == unchanged["revision"]
    )
    assert not group(client, "logging_config")["restart_required"]
    assert (
        save(client, "frontend_config", {"default_transport": "http"}).status_code
        == 200
    )
    assert client.get("/api/v1/agent").json()["frontend"]["default_transport"] == "http"


def test_request_errors_do_not_echo_secrets_and_reject_cross_origin(settings_client):
    client = settings_client
    response = client.put(
        "/api/v1/settings/model_config", json={"values": {"api_key": "do-not-echo"}}
    )
    assert response.status_code == 422
    assert "do-not-echo" not in response.text
    payload = {"values": {}, "revision": group(client, "model_config")["revision"]}
    for headers in [
        {"Origin": "https://other.invalid"},
        {"Sec-Fetch-Site": "cross-site"},
    ]:
        assert (
            client.put(
                "/api/v1/settings/model_config", json=payload, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/settings/model_config/test", headers=headers
            ).status_code
            == 403
        )
    assert client.put("/api/v1/settings/unregistered", json=payload).status_code == 404


def test_write_failure_retains_original(settings_client, monkeypatch):
    def denied(*_):
        raise PermissionError("not writable")

    from anyagent.configs import management

    monkeypatch.setattr(management, "_save_update", denied)
    path = paths.get_config_path("frontend_config")
    original = path.read_bytes()
    response = save(settings_client, "frontend_config", {"default_transport": "http"})
    assert response.status_code == 503
    assert path.read_bytes() == original


@pytest.mark.parametrize("streaming", [True, False])
def test_connection_probe_uses_saved_sdk_config_without_chat_history(
    settings_client, streaming
):
    client = settings_client
    with open_model_endpoint() as (base_url, requests):
        result = save(
            client,
            "model_config",
            {
                "enabled": True,
                "base_url": base_url,
                "model": "probe-fixture",
                "api_key": "probe-secret",
                "streaming": streaming,
            },
        )
        assert result.status_code == 200
        response = client.post("/api/v1/settings/model_config/test")
        assert response.status_code == 200, response.text
        assert len(requests) == 2
        assert requests[0]["authorization"] == "Bearer probe-secret"
        assert requests[0]["body"].get("stream", False) is streaming
        assert client.get("/api/v1/sessions").json() == []
    # The model endpoint is now closed: errors remain actionable and sanitized.
    response = client.post("/api/v1/settings/model_config/test")
    assert response.status_code == 503
    assert "probe-secret" not in response.text
    assert client.get("/api/v1/sessions").json() == []


def test_existing_file_and_directory_paths_are_rejected(settings_client):
    path = paths.get_config_path("cmd_config")
    original = path.read_bytes()
    for invalid in [
        "data/configs/cmd_config.json",
        "data/configs/cmd_config.json/child",
    ]:
        response = save(settings_client, "cmd_config", {"paths": {"data_dir": invalid}})
        assert response.status_code == 422
        assert path.read_bytes() == original
    logs = paths.get_logs_dir()
    nested = logs / "existing-directory"
    nested.mkdir(parents=True)
    path = paths.get_config_path("logging_config")
    original = path.read_bytes()
    for invalid in [
        "data/logs/existing-directory",
        "data/logs/existing-directory/log.txt/child.log",
    ]:
        if invalid.endswith("child.log"):
            (nested / "log.txt").write_text("existing log")
        response = save(settings_client, "logging_config", {"file_path": invalid})
        assert response.status_code == 422
        assert path.read_bytes() == original
