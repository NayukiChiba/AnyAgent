"""ModelProfile/RunnerProfile 校验与两个档案存储的读写/切换/迁移验证。"""

import json

import pytest
from pydantic import ValidationError

from anyagent.configs import paths
from anyagent.configs.model_profiles import (
    LEGACY_MODEL_ID,
    ModelProfile,
    ModelProfileStore,
)
from anyagent.configs.profiles import LEGACY_PROFILE_ID, ProfileStore, RunnerProfile
from anyagent.core.domain.chat import ChatError


def make_model(**overrides) -> ModelProfile:
    values = {
        "name": "测试连接",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key": "sk-test",
    }
    return ModelProfile(**(values | overrides))


def make_profile(model_id: str = "m1", **overrides) -> RunnerProfile:
    values = {"name": "测试档案", "type": "langchain", "model_id": model_id}
    return RunnerProfile(**(values | overrides))


def make_stores(tmp_path) -> tuple[ModelProfileStore, ProfileStore]:
    model_store = ModelProfileStore(tmp_path / "model_profiles.json")
    return model_store, ProfileStore(
        tmp_path / "runner_profiles.json", model_store=model_store
    )


def test_model_required_fields():
    # api_key 必填（本地免密服务可填 local 占位）
    with pytest.raises(ValidationError, match="API Key"):
        make_model(api_key="")
    # base_url 必须是 http(s)
    with pytest.raises(ValidationError):
        make_model(base_url="ftp://example.com")
    assert make_model(base_url="https://api.dify.ai/v1/").base_url.endswith("/v1")
    # 模型名称允许留空（远端平台引擎不需要）
    assert make_model(model="").model == ""


def test_model_as_model_settings():
    model = make_model(temperature=0.2, timeout_seconds=30)
    settings = model.as_model_settings()
    assert settings.enabled is True
    assert settings.model == "gpt-4.1-mini"
    assert settings.api_key.get_secret_value() == "sk-test"
    assert settings.temperature == 0.2
    # 模型名留空时由调用方占位（远端平台引擎传类型名）
    assert make_model(model="").as_model_settings("dify").model == "dify"


def test_profile_required_fields():
    # coze 必须有 bot_id
    with pytest.raises(ValidationError, match="Bot ID"):
        make_profile(type="coze")
    assert make_profile(type="coze", bot_id="bot-1").bot_id == "bot-1"
    # model_id 必填
    with pytest.raises(ValidationError):
        make_profile(model_id="")


def test_model_store_crud_and_secret(tmp_path, runtime_paths):
    model_store, _ = make_stores(tmp_path)
    assert model_store.list() == []

    profile = model_store.create(make_model())
    assert model_store.get(profile.id).name == "测试连接"
    # 落盘的是真实密钥而非遮蔽值
    path = tmp_path / "model_profiles.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["profiles"][0]["api_key"] == "sk-test"
    reloaded = ModelProfileStore(path)
    assert reloaded.get(profile.id).api_key.get_secret_value() == "sk-test"

    model_store.update(profile.model_copy(update={"name": "改名"}))
    assert model_store.get(profile.id).name == "改名"
    model_store.delete(profile.id)
    assert model_store.list() == []
    with pytest.raises(ChatError) as missing:
        model_store.get(profile.id)
    assert missing.value.code == "model_profile_not_found"


def test_store_crud_and_activate(tmp_path, runtime_paths):
    model_store, store = make_stores(tmp_path)
    model = model_store.create(make_model())
    assert store.list() == []
    assert store.active() is None
    assert store.legacy_mode is True

    first = store.create(make_profile(model.id, name="一号"))
    assert store.active_id() == first.id  # 首个档案自动启用
    assert store.legacy_mode is False
    second = store.create(make_profile(model.id, name="二号", type="dify"))
    assert store.active_id() == first.id  # 后续创建不抢占启用位

    store.activate(second.id)
    assert store.active().name == "二号"

    updated = store.update(second.model_copy(update={"name": "二号改"}))
    assert updated.name == "二号改"
    assert store.get(second.id).model_id == model.id

    store.delete(second.id)
    assert store.active_id() == first.id  # 删除活动档案回落到剩余首个
    store.delete(first.id)
    assert store.list() == []
    assert store.active() is None
    with pytest.raises(ChatError) as missing:
        store.get(first.id)
    assert missing.value.code == "profile_not_found"


def test_store_recovers_from_corrupted_file(tmp_path, runtime_paths):
    path = tmp_path / "runner_profiles.json"
    path.write_text("not json", encoding="utf-8")
    _, store = make_stores(tmp_path)
    store._path = path
    assert store.list() == []
    backups = list(tmp_path.glob("runner_profiles.broken-*.json"))
    assert len(backups) == 1


def test_inline_connections_migrate_to_model_profiles(tmp_path, runtime_paths):
    """旧版档案内联的连接信息在读取时自动拆分为模型连接 + 引用。"""
    model_store, store = make_stores(tmp_path)
    (tmp_path / "runner_profiles.json").write_text(
        json.dumps(
            {
                "active": "old1",
                "profiles": [
                    {
                        "id": "old1",
                        "name": "旧 Dify",
                        "type": "dify",
                        "base_url": "https://api.dify.ai/v1",
                        "api_key": "app-old",
                        "model": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    profiles = store.list()
    models = model_store.list()
    assert len(models) == 1
    assert models[0].base_url == "https://api.dify.ai/v1"
    assert models[0].api_key.get_secret_value() == "app-old"
    assert profiles[0].model_id == models[0].id
    assert profiles[0].type == "dify"
    # 迁移结果已落盘，再次读取不重复拆分
    reloaded = json.loads(
        (tmp_path / "runner_profiles.json").read_text(encoding="utf-8")
    )
    assert "base_url" not in reloaded["profiles"][0]
    assert reloaded["profiles"][0]["model_id"] == models[0].id


def test_legacy_mode_derives_profiles_from_model_config(runtime_paths):
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
    model_store = ModelProfileStore()
    store = ProfileStore(model_store=model_store)
    assert store.legacy_mode is True
    legacy = store.active()
    assert legacy.id == LEGACY_PROFILE_ID
    assert legacy.model_id == LEGACY_MODEL_ID
    legacy_model = model_store.get(LEGACY_MODEL_ID)
    assert legacy_model.model == "gpt-4.1-mini"
    assert legacy_model.api_key.get_secret_value() == "sk-legacy"
    # 兼容模式下创建档案：旧配置以 legacy 档案落盘，不丢失
    created = store.create(make_profile(LEGACY_MODEL_ID, name="新档案"))
    store.activate(created.id)
    assert store.legacy_mode is False
    ids = [profile.id for profile in store.list()]
    assert LEGACY_PROFILE_ID in ids and created.id in ids
    assert store.active_id() == created.id


def test_legacy_mode_inactive_when_model_disabled(runtime_paths):
    model_store = ModelProfileStore()
    store = ProfileStore(model_store=model_store)
    assert store.active() is None
    assert store.list() == []
    assert model_store.list() == []
