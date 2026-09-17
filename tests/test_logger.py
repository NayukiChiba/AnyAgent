import logging

import pytest

from anyagent.configs import paths
from anyagent.configs.load import LoggingSettings
from anyagent.utils.logger import LogManager, logger


@pytest.fixture
def log_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "data/logs")
    settings = LoggingSettings(file_path=tmp_path / "data/logs/test.log")
    yield settings
    LogManager.shutdown()


def test_shared_logging_flushes_exceptions_and_external_records(log_settings):
    LogManager.configure(log_settings)
    logger.info("Unicode message: 中文")
    logging.getLogger("external.client").warning("External warning")
    try:
        raise ValueError("Example error")
    except ValueError:
        logger.exception("Operation failed")
    LogManager.shutdown()

    content = log_settings.file_path.read_text(encoding="utf-8")
    assert "Unicode message: 中文" in content
    assert "external.client" in content
    assert "External warning" in content
    assert "Traceback" in content
    assert "ValueError: Example error" in content


def test_reconfiguration_does_not_duplicate_records(log_settings):
    LogManager.configure(log_settings)
    logger.info("First record")
    LogManager.configure(log_settings)
    logger.info("Second record")
    LogManager.shutdown()

    content = log_settings.file_path.read_text()
    assert content.count("First record") == 1
    assert content.count("Second record") == 1


def test_log_rotation_limits_retained_files(log_settings):
    settings = log_settings.model_copy(update={"max_bytes": 512, "backup_count": 2})
    LogManager.configure(settings)
    for index in range(20):
        logger.info("Record %s: %s", index, "x" * 200)
    LogManager.shutdown()

    files = list(settings.file_path.parent.glob("test.log*"))
    assert len(files) == 3
    assert "Record 19:" in settings.file_path.read_text()


def test_log_level_and_other_handlers_are_preserved(log_settings):
    root = logging.getLogger()
    previous_level = root.level
    other_handler = logging.NullHandler()
    root.addHandler(other_handler)
    try:
        LogManager.configure(log_settings)
        logger.debug("Filtered debug record")
        logger.info("Visible info record")
        LogManager.shutdown()
        assert other_handler in root.handlers
        assert root.level == previous_level
    finally:
        root.removeHandler(other_handler)

    content = log_settings.file_path.read_text()
    assert "Filtered debug record" not in content
    assert "Visible info record" in content
