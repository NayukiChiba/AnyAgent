import pytest

from anyagent.configs import load_settings


def test_config_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    expected = load_settings()
    monkeypatch.chdir(tmp_path)

    assert load_settings() == expected
    assert load_settings("configs/app.toml") == expected
    assert expected.paths.data_dir.is_absolute()


def test_custom_config_and_command_line_overrides(tmp_path):
    config = tmp_path / "custom.toml"
    config.write_text(
        '[paths]\ndata_dir = "data/custom"\n'
        '[server]\nhost = "localhost"\nport = 9000\n',
        encoding="utf-8",
    )

    settings = load_settings(config)
    assert settings.server.host == "localhost"
    assert settings.server.port == 9000
    assert settings.paths.data_dir == load_settings().paths.data_dir / "custom"
    assert not settings.paths.data_dir.exists()

    overridden = load_settings(config, host="0.0.0.0", port=8080)
    assert overridden.server.host == "0.0.0.0"
    assert overridden.server.port == 8080
    assert overridden.paths == settings.paths


@pytest.mark.parametrize("data_dir", ["../outside", "."])
def test_invalid_data_path_is_rejected(tmp_path, data_dir):
    config = tmp_path / "invalid.toml"
    config.write_text(
        f'[paths]\ndata_dir = "{data_dir}"\n'
        '[server]\nhost = "localhost"\nport = 8000\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inside the project root"):
        load_settings(config)


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_command_line_port_is_rejected(port):
    with pytest.raises(ValueError):
        load_settings(port=port)


def test_missing_config_is_not_replaced_with_defaults(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.toml")


def test_unknown_config_key_is_rejected(tmp_path):
    config = tmp_path / "unknown.toml"
    config.write_text(
        '[paths]\ndata_dir = "data"\ndtaa_dir = "wrong"\n'
        '[server]\nhost = "localhost"\nport = 8000\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="dtaa_dir"):
        load_settings(config)
