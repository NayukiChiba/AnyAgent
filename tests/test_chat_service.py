import asyncio
from contextlib import aclosing

import pytest

from anyagent.core.domain.chat import ChatError, Event
from anyagent.core.services.chat import ChatService
from anyagent.infrastructure.memory.sessions import MemorySessionRepository


class Runner:
    def __init__(self, *, fail=False, gate=None):
        self.fail = fail
        self.gate = gate
        self.closed = False
        self.seen = ()

    async def stream(self, messages):
        self.seen = messages
        yield Event("delta", {"content": "回复"})
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("secret upstream credential")
        yield Event("result", {"content": "回复"})

    async def aclose(self):
        self.closed = True


class Factory:
    def __init__(self):
        self.next = Runner()

    async def create(self):
        return self.next


def configured_service(repository, factory, **overrides):
    limits = {
        "timeout_seconds": 120,
        "max_concurrent_runs": 4,
        "max_history_messages": 40,
        "max_input_chars": 8000,
        "max_output_chars": 32000,
        "max_event_chars": 64000,
        "cleanup_timeout_seconds": 5,
    }
    return ChatService(repository, factory, **(limits | overrides))


async def collect(service, session_id, content="你好"):
    async with aclosing(service.stream(session_id, content)) as events:
        return [event async for event in events]


def test_success_failure_isolation_and_history_window():
    async def check():
        repository = MemorySessionRepository(max_sessions=2)
        factory = Factory()
        service = configured_service(repository, factory, max_history_messages=4)
        session = await service.create_session()
        other = await service.create_session()
        with pytest.raises(ChatError, match="会话数量"):
            await service.create_session()
        events = await collect(service, session.id)
        assert events[-1].type == "result"
        assert factory.next.closed
        assert len((await repository.get(session.id)).messages) == 2
        assert (await repository.get(other.id)).messages == ()
        factory.next = Runner(fail=True)
        with pytest.raises(ChatError) as failure:
            await collect(service, session.id)
        assert "secret" not in str(failure.value)
        assert len((await repository.get(session.id)).messages) == 2
        for content in ["第二轮", "第三轮"]:
            factory.next = Runner()
            await collect(service, session.id, content)
        history = (await repository.get(session.id)).messages
        assert [message.content for message in history] == [
            "第二轮",
            "回复",
            "第三轮",
            "回复",
        ]
        assert (await repository.get(session.id)).title == "你好"

    asyncio.run(check())


def test_busy_cancel_timeout_and_cleanup():
    async def check():
        repository = MemorySessionRepository()
        factory = Factory()
        factory.next = Runner(gate=asyncio.Event())
        service = configured_service(
            repository, factory, max_concurrent_runs=1, timeout_seconds=0.05
        )
        session = await service.create_session()
        other = await service.create_session()
        task = asyncio.create_task(collect(service, session.id))
        await asyncio.sleep(0)
        with pytest.raises(ChatError) as busy:
            await collect(service, session.id)
        assert busy.value.code == "session_busy"
        with pytest.raises(ChatError) as capacity:
            await collect(service, other.id)
        assert capacity.value.code == "capacity_exceeded"
        with pytest.raises(ChatError):
            await service.delete_session(session.id)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert factory.next.closed
        assert (await repository.get(session.id)).messages == ()
        factory.next = Runner(gate=asyncio.Event())
        with pytest.raises(ChatError) as timeout:
            await collect(service, session.id)
        assert timeout.value.code == "run_timeout"
        assert factory.next.closed
        assert (await repository.get(session.id)).messages == ()
        factory.next = Runner()
        await collect(service, session.id)
        await service.delete_session(session.id)
        with pytest.raises(ChatError) as missing:
            await repository.get(session.id)
        assert missing.value.code == "session_not_found"

    asyncio.run(check())


def test_disconnect_during_cleanup_keeps_owned_disposal_alive():
    async def check():
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowCloseRunner(Runner):
            async def aclose(self):
                started.set()
                await release.wait()
                self.closed = True

        factory = Factory()
        factory.next = SlowCloseRunner()
        service = configured_service(MemorySessionRepository(), factory)
        session = await service.create_session()
        task = asyncio.create_task(collect(service, session.id))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not factory.next.closed
        release.set()
        await service.shutdown()
        assert factory.next.closed
        assert not service._active
        assert not service._closing

    asyncio.run(check())


def test_cleanup_failure_does_not_replace_successful_result():
    async def check():
        class FailedCloseRunner(Runner):
            async def aclose(self):
                raise RuntimeError("secret in SDK cleanup")

        factory = Factory()
        factory.next = FailedCloseRunner()
        repository = MemorySessionRepository()
        service = configured_service(repository, factory)
        session = await service.create_session()
        assert (await collect(service, session.id))[-1].type == "result"
        assert len((await repository.get(session.id)).messages) == 2

    asyncio.run(check())


@pytest.mark.parametrize("limits", [{"max_output_chars": 1}, {"max_event_chars": 1}])
def test_injected_output_limits_prevent_history_commit(limits):
    async def check():
        repository = MemorySessionRepository()
        factory = Factory()
        service = configured_service(repository, factory, **limits)
        session = await service.create_session()
        with pytest.raises(ChatError) as failure:
            await collect(service, session.id)
        assert failure.value.code == "output_limit"
        assert (await repository.get(session.id)).messages == ()
        assert factory.next.closed

    asyncio.run(check())


def test_run_logs_identify_phases_without_message_or_exception_content(caplog):
    import logging

    async def check():
        repository = MemorySessionRepository(max_sessions=1)
        factory = Factory()
        service = configured_service(repository, factory)
        session = await service.create_session()
        await collect(service, session.id, "private-user-message")
        factory.next = Runner(fail=True)
        with pytest.raises(ChatError):
            await collect(service, session.id, "private-user-message")
        await service.shutdown()
        return session.id

    with caplog.at_level(logging.DEBUG, logger="anyagent.core.services.chat"):
        session_id = asyncio.run(check())
    content = caplog.text
    assert session_id in content
    assert "Agent run started" in content
    assert "Agent run completed" in content
    assert "Agent context loaded" in content
    assert "Agent history committed" in content
    assert "Agent execution failed" in content
    assert "private-user-message" not in content
    assert "secret" not in content
