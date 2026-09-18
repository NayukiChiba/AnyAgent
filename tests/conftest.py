"""Isolate runtime storage from the developer's data directory."""

import pytest

from anyagent.configs import paths


@pytest.fixture
def runtime_paths(tmp_path, monkeypatch):
    source_root = paths.get_project_root()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "CONFIGS_DIR", tmp_path / "data/configs")
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "data/logs")
    monkeypatch.setattr(paths, "LEGACY_CONFIG_FILE", tmp_path / "data/config.json")
    return source_root
