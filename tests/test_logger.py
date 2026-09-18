import asyncio
import logging

import pytest

from anyagent.configs import LoggingSettings, paths
from anyagent.core.domain.chat import Message, Session
from anyagent.infrastructure.sqlite.sessions import SQLiteSessionRepository
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


def test_database_debug_logs_do_not_include_chat_content(log_settings):
    settings = log_settings.model_copy(update={"level": "DEBUG"})
    LogManager.configure(settings)
    marker = "private-chat-content-must-not-be-logged"

    async def check():
        store = SQLiteSessionRepository(
            paths.get_database_path(), max_sessions=1, busy_timeout_seconds=1
        )
        try:
            await store.initialize()
            await store.save(
                Session("one", marker, "2026-09-18", (Message("user", marker),))
            )
            assert (await store.get("one")).title == marker
        finally:
            await store.aclose()

    asyncio.run(check())
    logger.debug("Visible application debug")
    logging.getLogger("sqlalchemy.engine.Engine").info("SQL parameters: %s", marker)
    logging.getLogger("aiosqlite").warning("Visible database warning")
    LogManager.shutdown()
    content = settings.file_path.read_text()
    assert marker not in content
    assert "Visible application debug" in content
    assert "Visible database warning" in content


@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
def test_project_logs_exclude_dependency_chatter_and_keep_failures(log_settings, level):
    settings = log_settings.model_copy(update={"level": level})
    LogManager.configure(settings)
    logger.info("Project lifecycle info")
    logger.debug("Project execution debug")
    logging.getLogger("anyagent.core.services.chat").info("Project agent info")
    for name in (
        "uvicorn.access",
        "uvicorn.error",
        "httpx",
        "httpcore",
        "asyncio",
        "openai",
        "anyagent_extra",
    ):
        dependency = logging.getLogger(name)
        previous = dependency.level
        dependency.setLevel(logging.DEBUG)
        try:
            dependency.debug("Hidden dependency debug")
            dependency.info("Hidden dependency info")
            dependency.warning("Retained dependency warning")
            dependency.error("Retained dependency error")
        finally:
            dependency.setLevel(previous)
    LogManager.shutdown()
    content = settings.file_path.read_text()
    assert "Project lifecycle info" in content
    assert "Project agent info" in content
    assert ("Project execution debug" in content) == (level == "DEBUG")
    assert "Hidden dependency" not in content
    assert "Retained dependency warning" in content
    assert "Retained dependency error" in content


def test_dependency_threshold_is_configurable_and_database_parameters_stay_private(
    log_settings,
):
    settings = log_settings.model_copy(
        update={"level": "DEBUG", "third_party_level": "DEBUG"}
    )
    LogManager.configure(settings)
    logging.getLogger("external.client").debug("Explicit dependency debug")
    logging.getLogger("aiosqlite").debug("Private database parameter")
    for name in ("openai", "httpx", "httpcore"):
        logging.getLogger(name).debug("Private SDK request payload")
        logging.getLogger(name).info("Private HTTP request info")
    logging.getLogger("sqlalchemy.engine.Engine").info("Private query parameter")
    LogManager.shutdown()
    content = settings.file_path.read_text()
    assert "Explicit dependency debug" in content
    assert "Private" not in content
