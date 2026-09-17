import json

import pytest
from pydantic import BaseModel, ConfigDict

from configs import default, load_cmd_config, load_config, load_logging_config
from configs.load import migrate_legacy_config


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(default, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(default, "DATA_DIR", data_dir)
    monkeypatch.setattr(default, "LOGS_DIR", data_dir / "logs")
    monkeypatch.setattr(default, "CONFIGS_DIR", data_dir / "configs")
    monkeypatch.setattr(default, "LEGACY_CONFIG_FILE", data_dir / "config.json")
    return default.CONFIGS_DIR


def test_missing_configs_create_separate_json_files(config_dir):
    cmd = load_cmd_config()
    logs = load_logging_config()

    assert cmd.paths.data_dir == config_dir.parent
    assert logs.file_path == default.LOGS_DIR / "anyagent.log"
    assert (
        json.loads((config_dir / "cmd_config.json").read_text())
        == default.DEFAULT_CMD_CONFIG
    )
    assert (
        json.loads((config_dir / "logging_config.json").read_text())
        == default.DEFAULT_LOGGING_CONFIG
    )
    assert not default.LEGACY_CONFIG_FILE.exists()


def test_valid_config_is_loaded_without_rewriting(config_dir):
    path = default.create_default_config()
    values = json.loads(path.read_text())
    values["server"] = {"host": "localhost", "port": 9000}
    values["paths"]["data_dir"] = "data/custom"
    original = json.dumps(values)
    path.write_text(original)

    loaded = load_cmd_config()

    assert loaded.server.port == 9000
    assert loaded.paths.data_dir == config_dir.parent / "custom"
    assert not loaded.paths.data_dir.exists()
    assert path.read_text() == original


@pytest.mark.parametrize(
    "contents", [b"{broken JSON", b"\xff", b"[]", b'{"server":{}}']
)
def test_invalid_cmd_is_backed_up_without_changing_logging(config_dir, contents):
    load_logging_config()
    logs_path = config_dir / "logging_config.json"
    original_logs = logs_path.read_bytes()
    path = config_dir / "cmd_config.json"
    path.write_bytes(contents)

    loaded = load_cmd_config()

    assert loaded.server.port == 8000
    backups = list(config_dir.glob("cmd_config.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == contents
    assert logs_path.read_bytes() == original_logs


def test_paths_are_independent_of_working_directory(config_dir, tmp_path, monkeypatch):
    cmd, logs = load_cmd_config(), load_logging_config()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_cmd_config() == cmd
    assert load_logging_config() == logs
    assert not (elsewhere / "data").exists()


def test_default_creation_does_not_overwrite_existing_config(config_dir):
    path = default.create_default_config()
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        default.create_default_config()
    assert path.read_bytes() == original


def test_permissions_are_not_treated_as_invalid_json(config_dir, monkeypatch):
    def deny_read(*args, **kwargs):
        raise PermissionError("Cannot read configuration")

    monkeypatch.setattr(type(config_dir), "open", deny_read)
    with pytest.raises(PermissionError):
        load_cmd_config()
    assert not config_dir.exists()


def test_invalid_log_path_only_recovers_logging_config(config_dir):
    load_cmd_config()
    cmd_path = config_dir / "cmd_config.json"
    original_cmd = cmd_path.read_bytes()
    path = default.create_default_config("logging_config")
    values = json.loads(path.read_text())
    values["file_path"] = "data/outside.log"
    path.write_text(json.dumps(values))

    assert load_logging_config().file_path == default.LOGS_DIR / "anyagent.log"
    assert cmd_path.read_bytes() == original_cmd
    assert len(list(config_dir.glob("logging_config.json.*.bak"))) == 1


def test_independent_extension_config(config_dir):
    class ExtensionConfig(BaseModel):
        model_config = ConfigDict(extra="forbid")
        enabled: bool

    defaults = {"enabled": False}
    assert not load_config("extension_config", ExtensionConfig, defaults).enabled
    path = config_dir / "extension_config.json"
    path.write_text('{"enabled":true}')
    assert load_config("extension_config", ExtensionConfig, defaults).enabled
    assert not (config_dir / "cmd_config.json").exists()


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "nested/config", "config.json"]
)
def test_config_name_cannot_leave_configs_directory(config_dir, name):
    with pytest.raises(ValueError):
        default.get_config_path(name)
    assert not config_dir.exists()


def test_legacy_migration_preserves_values_and_original_bytes(config_dir):
    default.DATA_DIR.mkdir()
    values = {
        "paths": {"data_dir": "data/custom"},
        "server": {"host": "localhost", "port": 9000},
        "logging": {**default.DEFAULT_LOGGING_CONFIG, "level": "DEBUG"},
    }
    original = json.dumps(values).encode()
    default.LEGACY_CONFIG_FILE.write_bytes(original)

    migrate_legacy_config()

    assert load_cmd_config().server.port == 9000
    assert load_logging_config().level == "DEBUG"
    assert "logging" not in json.loads((config_dir / "cmd_config.json").read_text())
    assert not default.LEGACY_CONFIG_FILE.exists()
    assert next(config_dir.glob("config.json.*.bak")).read_bytes() == original


def test_legacy_migration_keeps_newer_config_files(config_dir):
    cmd = default.create_default_config()
    original = cmd.read_bytes()
    default.LEGACY_CONFIG_FILE.write_text(
        '{"paths":{"data_dir":"data"},"server":{"host":"localhost","port":9000}}'
    )
    migrate_legacy_config()
    assert cmd.read_bytes() == original
    assert load_logging_config().level == "INFO"
    migrate_legacy_config()
    assert len(list(config_dir.glob("config.json.*.bak"))) == 1


def test_corrupt_legacy_is_backed_up_before_defaults(config_dir):
    default.DATA_DIR.mkdir()
    default.LEGACY_CONFIG_FILE.write_bytes(b"broken")
    migrate_legacy_config()
    assert load_cmd_config().server.port == 8000
    assert next(config_dir.glob("config.json.*.bak")).read_bytes() == b"broken"
