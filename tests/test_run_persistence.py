"""Run 持久化：创建/终态落库、重启回源、残留标记中断。"""

import asyncio

import pytest

from anyagent.core.domain.chat import ChatError, Message
from anyagent.core.domain.run import Run, RunError, prepare_input
from anyagent.core.services.run import RunService
from anyagent.infrastructure.memory.runs import InMemoryRunRepository
from anyagent.infrastructure.sqlite.migrate import migrate_database
from anyagent.infrastructure.sqlite.runs import SQLiteRunRepository
from anyagent.infrastructure.sqlite.sessions import SQLiteSessionRepository
from tests.mock_runner import MockRunnerFactory
from tests.test_run_service import GOOD_SCRIPT, LIMITS, make_session


def make_persistent_service(factory, run_repository, session_repository, **overrides):
    return RunService(
        session_repository,
        factory,
        run_repository=run_repository,
        **(LIMITS | overrides),
    )


def test_create_and_terminal_states_are_persisted():
    async def check():
        from anyagent.infrastructure.memory.sessions import MemorySessionRepository

        sessions = MemorySessionRepository()
        runs = InMemoryRunRepository()
        service = make_persistent_service(
            MockRunnerFactory(GOOD_SCRIPT), runs, sessions
        )
        session = await make_session(sessions)

        run = await service.create_session_run(session_id=session.id, content="你好")
        await service.wait_finished(run.id)
        await asyncio.gather(*tuple(service._persisting))

        stored = await runs.get(run.id)
        assert stored.status == "succeeded"
        assert stored.result == "你好"
        assert stored.finished_at is not None
        assert stored.input.messages[-1].content == "你好"
        assert stored.config_snapshot["profile_id"] == "mock"

    asyncio.run(check())


def test_get_and_subscribe_fall_back_to_repository_after_restart():
    async def check():
        from anyagent.infrastructure.memory.sessions import MemorySessionRepository

        sessions = MemorySessionRepository()
        runs = InMemoryRunRepository()
        first = make_persistent_service(MockRunnerFactory(GOOD_SCRIPT), runs, sessions)
        session = await make_session(sessions)
        run = await first.create_session_run(session_id=session.id, content="你好")
        await first.wait_finished(run.id)
        await asyncio.gather(*tuple(first._persisting))

        # 模拟重启：新服务实例共享同一仓储，内存注册表为空
        second = make_persistent_service(MockRunnerFactory(GOOD_SCRIPT), runs, sessions)
        stored = await second.get_run(run.id)
        assert stored.status == "succeeded" and stored.result == "你好"

        events = [event async for event in second.subscribe(run.id)]
        assert [event.type for event in events] == ["result", "status"]
        assert events[0].data["content"] == "你好"
        assert events[1].data["status"] == "succeeded"

        with pytest.raises(ChatError) as missing:
            await second.get_run("unknown")
        assert missing.value.code == "run_not_found"

    asyncio.run(check())


def test_interrupted_runs_are_marked_failed_on_startup():
    async def check():
        from anyagent.infrastructure.memory.sessions import MemorySessionRepository

        sessions = MemorySessionRepository()
        runs = InMemoryRunRepository()
        # 直接落两条非终态记录，模拟进程崩溃后的残留
        prepared = prepare_input(
            (Message("user", "你好"),), max_input_chars=100, max_history_messages=40
        )
        for run_id, status in (("r-running", "running"), ("r-queued", "queued")):
            await runs.save(
                Run(
                    id=run_id,
                    profile_id="mock",
                    status=status,
                    input=prepared,
                    config_snapshot={},
                    created_at="2026-11-03",
                    session_id="s-1",
                )
            )
        await runs.save(
            Run(
                id="r-done",
                profile_id="mock",
                status="succeeded",
                input=prepared,
                config_snapshot={},
                created_at="2026-11-03",
                session_id="s-1",
                result="已完成",
                finished_at="2026-11-03",
            )
        )

        service = make_persistent_service(
            MockRunnerFactory(GOOD_SCRIPT), runs, sessions
        )
        assert await service.recover_interrupted() == 2

        for run_id in ("r-running", "r-queued"):
            marked = await runs.get(run_id)
            assert marked.status == "failed"
            assert marked.error == RunError("run_interrupted", "服务重启，执行被中断")
            assert marked.finished_at is not None
        # 已终态记录不受影响
        assert (await runs.get("r-done")).status == "succeeded"
        # 幂等：再次扫描无残留
        assert await service.recover_interrupted() == 0

    asyncio.run(check())


def test_persistence_failure_does_not_break_execution(caplog):
    """落库失败只记日志，执行链路不受影响（存储降级而非阻断）。"""

    class BrokenRunRepository(InMemoryRunRepository):
        async def save(self, run):
            raise RuntimeError("disk full")

    async def check():
        from anyagent.infrastructure.memory.sessions import MemorySessionRepository

        sessions = MemorySessionRepository()
        service = make_persistent_service(
            MockRunnerFactory(GOOD_SCRIPT), BrokenRunRepository(), sessions
        )
        session = await make_session(sessions)
        run = await service.create_session_run(session_id=session.id, content="你好")
        await service.wait_finished(run.id)
        await service.shutdown()
        assert (await service.get_run(run.id)).status == "succeeded"

    with caplog.at_level("ERROR", logger="anyagent.core.services.run"):
        asyncio.run(check())
    assert "Run persistence failed" in caplog.text


def test_sqlite_run_repository_roundtrip_and_migration(tmp_path):
    """真实 SQLite：迁移建表（0001→0002）、读写回环、残留扫描口径。"""

    async def check():
        db_path = tmp_path / "data" / "test.db"
        sessions = SQLiteSessionRepository(
            db_path, max_sessions=4, busy_timeout_seconds=1
        )
        try:
            await sessions.initialize()
            runs = SQLiteRunRepository(db_path, busy_timeout_seconds=1)
            try:
                await runs.initialize()
                prepared = prepare_input(
                    (Message("user", "你好"),),
                    max_input_chars=100,
                    max_history_messages=40,
                )
                run = Run(
                    id="r-1",
                    profile_id="mock",
                    status="running",
                    input=prepared,
                    config_snapshot={"profile_id": "mock"},
                    created_at="2026-11-03",
                    session_id="s-1",
                )
                await runs.save(run)
                assert (await runs.list_nonterminal())[0].id == "r-1"

                from anyagent.core.domain.run import transition

                done = transition(
                    run, "failed", at="2026-11-03T01", error=RunError("x", "y")
                )
                await runs.save(done)
                loaded = await runs.get("r-1")
                assert loaded.status == "failed" and loaded.error.code == "x"
                assert await runs.list_nonterminal() == ()
            finally:
                await runs.aclose()
        finally:
            await sessions.aclose()

    asyncio.run(check())


def test_sqlite_migration_upgrades_existing_0001_database(tmp_path):
    """存量 0001 库升级到 0002：会话数据保留，runs 表出现。"""
    import sqlite3

    db_path = tmp_path / "data" / "test.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE anyagent_chat_sessions ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id VARCHAR(32) UNIQUE NOT NULL, "
            "title VARCHAR(255) NOT NULL, "
            "created_at VARCHAR(40) NOT NULL, "
            "messages JSON NOT NULL)"
        )
        connection.execute(
            "INSERT INTO anyagent_chat_sessions "
            "(session_id, title, created_at, messages) VALUES ('s-1', '旧会话', '2026-11-03', '[]')"
        )

    migrate_database(db_path)

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "anyagent_runs" in tables
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("0002",)
        assert connection.execute(
            "SELECT title FROM anyagent_chat_sessions WHERE session_id='s-1'"
        ).fetchone() == ("旧会话",)
