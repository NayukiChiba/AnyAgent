import json

import pytest

from configs import default, load_config


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(default, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(default, "DATA_DIR", data_dir)
    monkeypatch.setattr(default, "CONFIG_FILE", data_dir / "config.json")
    return default.CONFIG_FILE


def test_missing_config_creates_json_in_data(config_file):
    loaded = load_config()

    assert loaded.paths.data_dir == config_file.parent
    assert json.loads(config_file.read_text()) == default.DEFAULT_CONFIG
    assert not list(default.PROJECT_ROOT.glob("*.json"))


def test_valid_config_is_loaded_without_rewriting(config_file):
    default.create_default_config()
    values = json.loads(config_file.read_text())
    values["server"] = {"host": "localhost", "port": 9000}
    values["paths"]["data_dir"] = "data/custom"
    original = json.dumps(values)
    config_file.write_text(original)

    loaded = load_config()

    assert loaded.server.host == "localhost"
    assert loaded.server.port == 9000
    assert loaded.paths.data_dir == config_file.parent / "custom"
    assert not loaded.paths.data_dir.exists()
    assert config_file.read_text() == original


@pytest.mark.parametrize(
    "contents",
    [
        b"{broken JSON",
        b"\xff",
        b"[]",
        b'{"paths": {"data_dir": "data"}, "server": {"host": "localhost", "port": 0}}',
        b'{"paths": {"data_dir": "../outside"}, "server": {"host": "localhost", "port": 8000}}',
    ],
)
def test_unloadable_config_is_backed_up_and_replaced(config_file, contents):
    config_file.parent.mkdir()
    config_file.write_bytes(contents)

    loaded = load_config()

    assert loaded.server.port == default.DEFAULT_CONFIG["server"]["port"]
    assert json.loads(config_file.read_text()) == default.DEFAULT_CONFIG
    backups = list(config_file.parent.glob("config.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == contents


def test_paths_are_independent_of_working_directory(config_file, tmp_path, monkeypatch):
    loaded = load_config()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert load_config() == loaded
    assert not (elsewhere / "data").exists()


def test_default_creation_does_not_overwrite_current_config(config_file):
    default.create_default_config()
    original = config_file.read_bytes()

    with pytest.raises(FileExistsError):
        default.create_default_config()

    assert config_file.read_bytes() == original


def test_read_permission_error_is_not_treated_as_invalid_json(config_file, monkeypatch):
    def deny_read(*args, **kwargs):
        raise PermissionError("Cannot read configuration")

    monkeypatch.setattr(type(config_file), "open", deny_read)
    with pytest.raises(PermissionError):
        load_config()
    assert not config_file.exists()
