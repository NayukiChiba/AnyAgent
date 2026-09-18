"""Verify persistence, atomic snapshots and the existing repository contract."""

import asyncio
from contextlib import aclosing
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from anyagent.configs import paths
from anyagent.core.domain.chat import ChatError, Message, Session
from anyagent.infrastructure.sqlite.sessions import SQLiteSessionRepository
from anyagent.runtime.bootstrap import create_app
from tests.test_chat_service import Factory, Runner, configured_service


def repository(path, **limits):
    return SQLiteSessionRepository(
        path, max_sessions=limits.get("max_sessions", 64), busy_timeout_seconds=1
    )


def snapshot(identifier, messages=()):
    return Session(identifier, "中文会话", "2026-09-18T00:00:00+00:00", messages)


def test_reopen_preserves_snapshots_order_and_deletions(tmp_path):
    async def check():
        file = tmp_path / "history.db"
        first = repository(file)
        await first.initialize()
        saved = snapshot(
            "one", (Message("user", "你好🙂"), Message("assistant", "你好"))
        )
        await first.save(saved)
        await first.save(snapshot("two"))
        updated = replace(saved, title="新标题")
        await first.save(updated)
        assert [session.id for session in await first.list()] == ["two", "one"]
        await first.aclose()
        reopened = repository(file)
        await reopened.initialize()
        assert await reopened.get("one") == updated
        assert (await reopened.get("one")).messages == saved.messages
        await reopened.delete("two")
        with pytest.raises(ChatError) as missing:
            await reopened.delete("two")
        assert missing.value.code == "session_not_found"
        await reopened.aclose()
        final = repository(file)
        await final.initialize()
        assert await final.list() == (updated,)
        await final.aclose()

    asyncio.run(check())


def test_capacity_is_atomic_across_independent_connections(tmp_path):
    async def check():
        file = tmp_path / "concurrent.db"
        first, second = (
            repository(file, max_sessions=1),
            repository(file, max_sessions=1),
        )
        await first.initialize()
        await second.initialize()
        result = await asyncio.gather(
            first.save(snapshot("one")),
            second.save(snapshot("two")),
            return_exceptions=True,
        )
        assert sum(value is None for value in result) == 1
        failure = next(value for value in result if isinstance(value, ChatError))
        assert failure.code == "session_limit"
        sessions = await first.list()
        assert len(sessions) == 1
        await second.save(replace(sessions[0], title="容量满时仍可更新"))
        assert (await first.get(sessions[0].id)).title == "容量满时仍可更新"
        await first.aclose()
        await second.aclose()

    asyncio.run(check())


def test_failed_database_commit_rolls_back_without_exposing_content(tmp_path):
    async def check():
        file = tmp_path / "rollback.db"
        store = repository(file)
        await store.initialize()
        original = snapshot("one")
        await store.save(original)

        def deny_write(connection, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith("UPDATE"):
                raise OperationalError(
                    statement, parameters, RuntimeError("private content")
                )

        event.listen(store.engine.sync_engine, "before_cursor_execute", deny_write)
        with pytest.raises(ChatError) as failure:
            await store.save(
                replace(
                    original,
                    title="secret content",
                    messages=(
                        Message("user", "secret content"),
                        Message("assistant", "answer"),
                    ),
                )
            )
        assert failure.value.code == "storage_unavailable"
        assert "secret" not in str(failure.value)
        event.remove(store.engine.sync_engine, "before_cursor_execute", deny_write)
        await store.aclose()
        reopened = repository(file)
        await reopened.initialize()
        assert await reopened.get("one") == original
        await reopened.aclose()

    asyncio.run(check())


def test_cancel_and_runner_failure_leave_persisted_history_unchanged(tmp_path):
    async def check():
        file = tmp_path / "cancel.db"
        store = repository(file)
        await store.initialize()
        factory = Factory()
        service = configured_service(store, factory)
        session = await service.create_session()

        async def run():
            async with aclosing(service.stream(session.id, "问题")) as stream:
                return [event async for event in stream]

        await run()
        baseline = await store.get(session.id)
        factory.next = Runner(fail=True)
        with pytest.raises(ChatError):
            await run()
        factory.next = Runner(gate=asyncio.Event())
        reached = asyncio.Event()

        async def cancelable():
            async with aclosing(service.stream(session.id, "取消的问题")) as stream:
                async for _ in stream:
                    reached.set()

        task = asyncio.create_task(cancelable())
        await reached.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await service.shutdown()
        await store.aclose()
        reopened = repository(file)
        await reopened.initialize()
        assert await reopened.get(session.id) == baseline
        await reopened.aclose()

    asyncio.run(check())


def test_app_restart_preserves_chat_and_runner_context(runtime_paths):
    factory = Factory()
    with TestClient(create_app(runner_factory=factory)) as client:
        saved = client.post("/api/v1/sessions").json()
        url = f"/api/v1/sessions/{saved['id']}"
        assert (
            client.post(f"{url}/messages", json={"content": "第一轮"}).status_code
            == 200
        )
        before = client.get(url).json()
        assert client.get("/api/v1/agent").json()["storage"] == "sqlite"
    factory.next = Runner()
    with TestClient(create_app(runner_factory=factory)) as client:
        assert client.get("/api/v1/sessions").json()[0]["id"] == saved["id"]
        assert client.get(url).json() == before
        assert (
            client.post(f"{url}/messages", json={"content": "第二轮"}).status_code
            == 200
        )
        assert [message.content for message in factory.next.seen] == [
            "第一轮",
            "回复",
            "第二轮",
        ]
        assert len(client.get(url).json()["messages"]) == 4
        assert client.delete(url).status_code == 204
    with TestClient(create_app(runner_factory=factory)) as client:
        assert client.get("/api/v1/sessions").json() == []
    assert paths.get_database_path().is_file()


def test_corrupted_database_is_not_replaced(tmp_path):
    async def check():
        file = tmp_path / "broken.db"
        contents = b"not a sqlite database"
        file.write_bytes(contents)
        store = repository(file)
        try:
            with pytest.raises(SQLAlchemyError):
                await store.initialize()
        finally:
            await store.aclose()
        assert file.read_bytes() == contents

    asyncio.run(check())


def test_storage_failure_returns_safe_service_unavailable(runtime_paths):
    with TestClient(create_app(runner_factory=Factory())) as client:
        store = client.app.state.chat_service.repository

        def deny_read(connection, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith("SELECT"):
                raise OperationalError(
                    statement, parameters, RuntimeError("private database details")
                )

        event.listen(store.engine.sync_engine, "before_cursor_execute", deny_read)
        try:
            response = client.get("/api/v1/sessions")
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "storage_unavailable"
            assert "private" not in response.text
            assert "SELECT" not in response.text
        finally:
            event.remove(store.engine.sync_engine, "before_cursor_execute", deny_read)
