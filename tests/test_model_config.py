import json

import pytest
from pydantic import ValidationError

from anyagent.configs import paths
from anyagent.configs.agent import ModelSettings
from anyagent.configs.load import load_langchain_config, load_model_config


def test_model_connections_reload_and_recover_independently(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "CONFIGS_DIR", tmp_path / "data/configs")
    settings = load_langchain_config()
    first = load_model_config()
    assert not first.enabled
    file = paths.get_config_path("model_config")
    values = {
        "enabled": True,
        "model": "custom-model",
        "base_url": "http://localhost:1234/v1",
        "api_key": "local-test-key",
    }
    file.write_text(json.dumps(values))
    second = load_model_config()
    assert second.model == "custom-model"
    assert second.api_key.get_secret_value() == "local-test-key"
    assert "local-test-key" not in repr(second)
    assert not first.enabled
    file.write_text("broken-json")
    assert not load_model_config().enabled
    assert load_langchain_config() == settings
    assert len(list(paths.get_configs_dir().glob("model_config.json.*.bak"))) == 1


@pytest.mark.parametrize(
    "values",
    [
        {"enabled": True},
        {"base_url": "file:///tmp/model"},
        {"base_url": "https://user:password@example.com/v1"},
        {"unknown_option": True},
    ],
)
def test_invalid_model_config_is_rejected(values):
    with pytest.raises(ValidationError):
        ModelSettings.model_validate(values)


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_streaming_switch_requires_json_boolean(value):
    with pytest.raises(ValidationError):
        ModelSettings(streaming=value)
