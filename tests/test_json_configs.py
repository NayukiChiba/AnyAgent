import json
import sys

import pytest
from pydantic import Field

from anyagent.configs import (
    BaseSettings,
    default,
    load_cmd_config,
    load_config,
    load_logging_config,
    paths,
)
from anyagent.configs.load import migrate_legacy_config


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "LOGS_DIR", data_dir / "logs")
    monkeypatch.setattr(paths, "CONFIGS_DIR", data_dir / "configs")
    monkeypatch.setattr(paths, "LEGACY_CONFIG_FILE", data_dir / "config.json")
    return paths.CONFIGS_DIR


def test_missing_configs_create_separate_json_files(config_dir):
    cmd = load_cmd_config()
    logs = load_logging_config()

    assert cmd.paths.data_dir == config_dir.parent
    assert logs.file_path == paths.LOGS_DIR / "anyagent.log"
    assert (
        json.loads((config_dir / "cmd_config.json").read_text())
        == default.DEFAULT_CMD_CONFIG
    )
    assert (
        json.loads((config_dir / "logging_config.json").read_text())
        == default.DEFAULT_LOGGING_CONFIG
    )
    assert not paths.LEGACY_CONFIG_FILE.exists()


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

    assert load_logging_config().file_path == paths.LOGS_DIR / "anyagent.log"
    assert cmd_path.read_bytes() == original_cmd
    assert len(list(config_dir.glob("logging_config.json.*.bak"))) == 1


def test_independent_extension_config(config_dir):
    class ExtensionConfig(BaseSettings):
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
        paths.get_config_path(name)
    assert not config_dir.exists()


@pytest.mark.parametrize("resolver", [paths.resolve_data_path, paths.get_log_path])
@pytest.mark.parametrize("absolute", [False, True])
def test_runtime_paths_reject_escape(config_dir, resolver, absolute):
    value = paths.PROJECT_ROOT / "outside" if absolute else "data/../outside"
    with pytest.raises(ValueError):
        resolver(value)
    assert not config_dir.exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlink creation requires elevated privileges on Windows",
)
def test_config_symlink_cannot_modify_file_outside_configs(config_dir):
    outside = paths.PROJECT_ROOT / "outside.json"
    outside.write_text('{"keep":true}')
    config_dir.mkdir(parents=True)
    (config_dir / "cmd_config.json").symlink_to(outside)

    with pytest.raises(ValueError):
        load_cmd_config()

    assert outside.read_text() == '{"keep":true}'
    assert not list(config_dir.glob("*.bak"))


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlink creation requires elevated privileges on Windows",
)
def test_log_symlink_cannot_leave_logs_directory(config_dir):
    outside = paths.DATA_DIR / "outside.log"
    paths.get_logs_dir().mkdir(parents=True)
    outside.write_text("Keep this file")
    logfile = paths.get_logs_dir() / "linked.log"
    logfile.symlink_to(outside)

    with pytest.raises(ValueError):
        paths.get_log_path(logfile)

    assert outside.read_text() == "Keep this file"


def test_log_filename_cannot_be_the_logs_directory(config_dir):
    with pytest.raises(ValueError):
        paths.get_log_path(paths.get_logs_dir())


def test_legacy_migration_preserves_values_and_original_bytes(config_dir):
    paths.DATA_DIR.mkdir()
    values = {
        "paths": {"data_dir": "data/custom"},
        "server": {"host": "localhost", "port": 9000},
        "logging": {**default.DEFAULT_LOGGING_CONFIG, "level": "DEBUG"},
    }
    original = json.dumps(values).encode()
    paths.LEGACY_CONFIG_FILE.write_bytes(original)

    migrate_legacy_config()

    assert load_cmd_config().server.port == 9000
    assert load_logging_config().level == "DEBUG"
    assert "logging" not in json.loads((config_dir / "cmd_config.json").read_text())
    assert not paths.LEGACY_CONFIG_FILE.exists()
    assert next(config_dir.glob("config.json.*.bak")).read_bytes() == original


def test_legacy_migration_keeps_newer_config_files(config_dir):
    cmd = default.create_default_config()
    original = cmd.read_bytes()
    paths.LEGACY_CONFIG_FILE.write_text(
        '{"paths":{"data_dir":"data"},"server":{"host":"localhost","port":9000}}'
    )
    migrate_legacy_config()
    assert cmd.read_bytes() == original
    assert load_logging_config().level == "INFO"
    migrate_legacy_config()
    assert len(list(config_dir.glob("config.json.*.bak"))) == 1


def test_corrupt_legacy_is_backed_up_before_defaults(config_dir):
    paths.DATA_DIR.mkdir()
    paths.LEGACY_CONFIG_FILE.write_bytes(b"broken")
    migrate_legacy_config()
    assert load_cmd_config().server.port == 8000
    assert next(config_dir.glob("config.json.*.bak")).read_bytes() == b"broken"


def test_invalid_extension_defaults_do_not_create_a_config_file(config_dir):
    class ExtensionConfig(BaseSettings):
        limit: int = Field(default=0, ge=1)

    with pytest.raises(ValueError):
        load_config("extension_config", ExtensionConfig, {})

    assert not config_dir.exists()


def test_optional_defaults_are_written_without_overwriting_values(config_dir):
    class NestedSettings(BaseSettings):
        enabled: bool = False
        limit: int = 10

    class ExtensionConfig(BaseSettings):
        nested: NestedSettings
        streaming: bool = True
        api_key: str = ""

    config_dir.mkdir(parents=True)
    file = config_dir / "extension_config.json"
    original = {
        "nested": {"enabled": True},
        "api_key": "keep-local-secret",
        "streaming": False,
    }
    file.write_text(json.dumps(original))
    file.chmod(0o600)
    defaults = {
        "nested": {"enabled": False, "limit": 10},
        "api_key": "",
        "streaming": True,
    }
    loaded = load_config("extension_config", ExtensionConfig, defaults)
    assert loaded.nested.enabled
    assert not loaded.streaming
    assert json.loads(file.read_text()) == {
        **original,
        "nested": {"enabled": True, "limit": 10},
    }
    if sys.platform != "win32":
        # POSIX 权限位在 Windows 上无意义，跳过断言
        assert file.stat().st_mode & 0o777 == 0o600
    assert not list(config_dir.glob("*.bak"))
    assert not list(config_dir.glob(".*.tmp"))
    unchanged = file.read_bytes()
    load_config("extension_config", ExtensionConfig, defaults)
    assert file.read_bytes() == unchanged


def test_default_update_failure_preserves_original_config(config_dir, monkeypatch):
    class ExtensionConfig(BaseSettings):
        enabled: bool = False

    config_dir.mkdir(parents=True)
    file = config_dir / "extension_config.json"
    file.write_text("{}")

    def deny_replace(*args):
        raise PermissionError("Cannot replace configuration")

    monkeypatch.setattr(type(file), "replace", deny_replace)
    with pytest.raises(PermissionError):
        load_config("extension_config", ExtensionConfig, {"enabled": False})
    assert file.read_text() == "{}"
    assert not list(config_dir.glob("*.bak"))
    assert not list(config_dir.glob(".*.tmp"))


def test_filled_values_are_used_in_the_same_load(config_dir):
    class ExtensionConfig(BaseSettings):
        enabled: bool = False

    config_dir.mkdir(parents=True)
    file = config_dir / "extension_config.json"
    file.write_text("{}")
    loaded = load_config("extension_config", ExtensionConfig, {"enabled": True})
    assert loaded.enabled
    assert json.loads(file.read_text()) == {"enabled": True}
