"""RunnerProfile 模型校验与 ProfileStore 读写/切换/兼容模式验证。"""

import json

import pytest
from pydantic import ValidationError

from anyagent.configs import paths
from anyagent.configs.profiles import LEGACY_PROFILE_ID, ProfileStore, RunnerProfile
from anyagent.core.domain.chat import ChatError


def make_profile(**overrides) -> RunnerProfile:
    values = {
        "name": "测试档案",
        "type": "langchain",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key": "sk-test",
    }
    return RunnerProfile(**(values | overrides))


def test_profile_required_fields_by_type():
    # 本地引擎与 pi 必须填写模型名称
    with pytest.raises(ValidationError, match="模型名称"):
        make_profile(model="")
    # 平台引擎无需模型名称
    assert make_profile(type="dify", model="").model == ""
    # coze 必须有 bot_id
    with pytest.raises(ValidationError, match="Bot ID"):
        make_profile(type="coze", model="")
    assert make_profile(type="coze", model="", bot_id="bot-1").bot_id == "bot-1"
    # api_key 必填
    with pytest.raises(ValidationError, match="API Key"):
        make_profile(api_key="")
    # base_url 校验与模型连接一致
    with pytest.raises(ValidationError):
        make_profile(base_url="ftp://example.com")
    assert make_profile(base_url="https://api.dify.ai/v1/").base_url.endswith("/v1")


def test_profile_as_model_settings():
    profile = make_profile(temperature=0.2, timeout_seconds=30)
    settings = profile.as_model_settings()
    assert settings.enabled is True
    assert settings.model == "gpt-4.1-mini"
    assert settings.api_key.get_secret_value() == "sk-test"
    assert settings.temperature == 0.2
    # 平台引擎以类型名占位模型名称
    assert make_profile(type="dify", model="").as_model_settings().model == "dify"


def test_store_crud_and_activate(tmp_path, runtime_paths):
    store = ProfileStore(tmp_path / "runner_profiles.json")
    assert store.list() == []
    assert store.active() is None
    assert store.legacy_mode is True

    first = store.create(make_profile(name="一号"))
    assert store.active_id() == first.id  # 首个档案自动启用
    assert store.legacy_mode is False
    second = store.create(make_profile(name="二号", type="dify", model=""))
    assert store.active_id() == first.id  # 后续创建不抢占启用位

    store.activate(second.id)
    assert store.active().name == "二号"

    updated = store.update(
        second.model_copy(update={"name": "二号改", "base_url": "https://x.ai/v1"})
    )
    assert updated.name == "二号改"
    assert store.get(second.id).base_url == "https://x.ai/v1"

    store.delete(second.id)
    assert store.active_id() == first.id  # 删除活动档案回落到剩余首个
    store.delete(first.id)
    assert store.list() == []
    assert store.active() is None
    with pytest.raises(ChatError) as missing:
        store.get(first.id)
    assert missing.value.code == "profile_not_found"


def test_store_persists_secret_and_reloads(tmp_path, runtime_paths):
    path = tmp_path / "runner_profiles.json"
    store = ProfileStore(path)
    profile = store.create(make_profile())
    # 落盘的是真实密钥而非遮蔽值
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["profiles"][0]["api_key"] == "sk-test"
    reloaded = ProfileStore(path)
    assert reloaded.active().api_key.get_secret_value() == "sk-test"
    assert reloaded.get(profile.id).name == "测试档案"


def test_store_recovers_from_corrupted_file(tmp_path, runtime_paths):
    path = tmp_path / "runner_profiles.json"
    path.write_text("not json", encoding="utf-8")
    store = ProfileStore(path)
    assert store.list() == []
    assert store.legacy_mode is True
    backups = list(tmp_path.glob("runner_profiles.broken-*.json"))
    assert len(backups) == 1


def test_legacy_mode_derives_active_profile_from_model_config(runtime_paths):
    paths.get_configs_dir().mkdir(parents=True)
    paths.get_config_path("model_config").write_text(
        json.dumps(
            {
                "enabled": True,
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4.1-mini",
                "api_key": "sk-legacy",
            }
        ),
        encoding="utf-8",
    )
    store = ProfileStore()
    assert store.legacy_mode is True
    legacy = store.active()
    assert legacy.id == LEGACY_PROFILE_ID
    assert legacy.model == "gpt-4.1-mini"
    assert legacy.api_key.get_secret_value() == "sk-legacy"
    # 兼容模式下创建档案：旧配置以 legacy 档案落盘，不丢失
    created = store.create(make_profile(name="新档案"))
    store.activate(created.id)
    assert store.legacy_mode is False
    ids = [profile.id for profile in store.list()]
    assert LEGACY_PROFILE_ID in ids and created.id in ids
    assert store.active_id() == created.id


def test_legacy_mode_inactive_when_model_disabled(runtime_paths):
    store = ProfileStore()
    assert store.active() is None
    assert store.list() == []
