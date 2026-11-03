"""数据库版本化迁移：新库建表、存量库接管、幂等升级与失败恢复。"""

import sqlite3

import pytest

from anyagent.configs import paths
from anyagent.infrastructure.sqlite.migrate import INITIAL_REVISION, migrate_database


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """把 data 目录指向临时位置，返回其中的数据库路径。"""
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir()
    return tmp_path / "data" / "test.db"


def _tables(path):
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def _revision(path):
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    return {row[0] for row in rows}


def _insert_session(path, session_id):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO anyagent_chat_sessions "
            "(session_id, title, created_at, messages) VALUES (?, ?, ?, ?)",
            (session_id, "标题", "2026-11-03", "[]"),
        )


def _fetch_session(path, session_id):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT title FROM anyagent_chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()


def test_fresh_database_migrates_to_head(db_path):
    migrate_database(db_path)
    assert "anyagent_chat_sessions" in _tables(db_path)
    assert _revision(db_path) == {INITIAL_REVISION}


def test_legacy_create_all_database_is_stamped_without_data_loss(db_path):
    """create_all 时代的存量库：schema 不变、数据保留、只补登版本。"""
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE anyagent_chat_sessions ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id VARCHAR(32) UNIQUE NOT NULL, "
            "title VARCHAR(255) NOT NULL, "
            "created_at VARCHAR(40) NOT NULL, "
            "messages JSON NOT NULL)"
        )
    _insert_session(db_path, "legacy-1")

    migrate_database(db_path)

    assert _revision(db_path) == {INITIAL_REVISION}
    assert _fetch_session(db_path, "legacy-1") == ("标题",)


def test_migration_is_idempotent(db_path):
    migrate_database(db_path)
    _insert_session(db_path, "keep-1")
    migrate_database(db_path)
    assert _revision(db_path) == {INITIAL_REVISION}
    assert _fetch_session(db_path, "keep-1") == ("标题",)


def test_failed_migration_restores_backup(db_path, monkeypatch):
    """迁移中途失败：从备份恢复，已有数据不丢，备份文件保留备查。"""
    migrate_database(db_path)
    _insert_session(db_path, "safe-1")
    original = db_path.read_bytes()

    def boom(config, revision):
        raise RuntimeError("模拟迁移脚本执行失败")

    monkeypatch.setattr("anyagent.infrastructure.sqlite.migrate.command.upgrade", boom)
    with pytest.raises(RuntimeError, match="模拟迁移脚本失败|模拟迁移"):
        migrate_database(db_path)

    assert _fetch_session(db_path, "safe-1") == ("标题",)
    backups = list(db_path.parent.glob("test.db.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_failed_fresh_migration_leaves_no_partial_file(db_path, monkeypatch):
    """空库升级失败时删除半成品文件，下次启动可干净重试。"""

    def boom(config, revision):
        raise RuntimeError("模拟建表失败")

    monkeypatch.setattr("anyagent.infrastructure.sqlite.migrate.command.upgrade", boom)
    with pytest.raises(RuntimeError):
        migrate_database(db_path)
    assert not db_path.exists()


def test_repository_initialize_uses_migration(db_path):
    """仓储入口验收：initialize 后表结构与版本就位，可正常读写。"""
    import asyncio

    from anyagent.core.domain.chat import Message, Session
    from anyagent.infrastructure.sqlite.sessions import SQLiteSessionRepository

    async def check():
        repository = SQLiteSessionRepository(
            db_path, max_sessions=4, busy_timeout_seconds=1
        )
        try:
            await repository.initialize()
            await repository.save(
                Session("s-1", "迁移后写入", "2026-11-03", (Message("user", "你好"),))
            )
            assert (await repository.get("s-1")).title == "迁移后写入"
        finally:
            await repository.aclose()

    asyncio.run(check())
    assert _revision(db_path) == {INITIAL_REVISION}
