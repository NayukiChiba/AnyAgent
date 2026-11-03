"""RunService：执行编排、订阅重放、取消竞态、背压与注册表行为。"""

import asyncio
from contextlib import aclosing

import pytest

from anyagent.core.domain.chat import ChatError, Message, Session
from anyagent.core.services import run as run_module
from anyagent.core.services.run import SUBSCRIBER_QUEUE_SIZE, RunService
from anyagent.infrastructure.memory.sessions import MemorySessionRepository
from tests.mock_runner import MockRunnerFactory

LIMITS = {
    "timeout_seconds": 5,
    "max_concurrent_runs": 2,
    "max_history_messages": 40,
    "max_input_chars": 8000,
    "max_output_chars": 32000,
    "max_event_chars": 64000,
    "cleanup_timeout_seconds": 5,
}

GOOD_SCRIPT = [
    ("event", "delta", {"content": "你"}),
    ("event", "delta", {"content": "好"}),
    ("event", "result", {"content": "你好"}),
]


def make_service(factory, repository=None, **overrides):
    return RunService(
        repository or MemorySessionRepository(), factory, **(LIMITS | overrides)
    )


async def make_session(repository, session_id="s-1"):
    session = Session(session_id, "测试", "2026-11-03", ())
    await repository.save(session)
    return session


async def collect(service, run_id, *, since_seq=-1):
    async with aclosing(service.subscribe(run_id, since_seq=since_seq)) as events:
        return [event async for event in events]


def test_run_executes_and_publishes_events_with_monotonic_seq():
    async def check():
        factory = MockRunnerFactory(GOOD_SCRIPT)
        service = make_service(factory)
        repository = service.repository
        session = await make_session(repository)

        run = await service.create_session_run(session_id=session.id, content="你好")
        assert run.status == "queued"
        assert run.config_snapshot["profile_id"] == "mock"

        events = await collect(service, run.id)
        await service.wait_finished(run.id)

        kinds = [event.type for event in events]
        assert kinds == ["status", "status", "delta", "delta", "result", "status"]
        statuses = [e.data["status"] for e in events if e.type == "status"]
        assert statuses == ["queued", "running", "succeeded"]
        seqs = [event.seq for event in events]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

        final = await service.get_run(run.id)
        assert final.status == "succeeded" and final.result == "你好"
        assert final.finished_at is not None
        assert service.stats["runs_completed"] == 1
        # 会话历史已提交
        history = (await repository.get(session.id)).messages
        assert [m.content for m in history] == ["你好", "你好"]
        assert factory.created[0].closed

    asyncio.run(check())


def test_subscribe_after_completion_replays_full_event_log():
    async def check():
        factory = MockRunnerFactory(GOOD_SCRIPT)
        service = make_service(factory)
        session = await make_session(service.repository)
        run = await service.create_session_run(session_id=session.id, content="你好")
        await service.wait_finished(run.id)

        events = await collect(service, run.id)
        assert events[0].data["status"] == "queued"
        assert events[-1].data["status"] == "succeeded"

        # since_seq 去重：只重放之后的事件
        replay = await collect(service, run.id, since_seq=events[2].seq)
        assert replay == events[3:]

    asyncio.run(check())


def test_subscribe_disconnect_does_not_stop_run():
    async def check():
        gate = asyncio.Event()
        factory = MockRunnerFactory(
            [
                ("event", "delta", {"content": "第一段"}),
                ("wait", gate),
                ("event", "result", {"content": "完整回复"}),
            ]
        )
        service = make_service(factory)
        session = await make_session(service.repository)
        run = await service.create_session_run(session_id=session.id, content="你好")

        received = []
        async with aclosing(service.subscribe(run.id)) as events:
            async for event in events:
                received.append(event)
                if event.type == "delta":
                    break  # 订阅断开
        assert (await service.get_run(run.id)).status == "running"

        gate.set()
        await service.wait_finished(run.id)
        assert (await service.get_run(run.id)).status == "succeeded"

        # 重订阅只补发断开期间错过的事件，不重复
        last_seq = received[-1].seq
        missed = await collect(service, run.id, since_seq=last_seq)
        assert [event.type for event in missed] == ["result", "status"]
        assert missed[0].data["content"] == "完整回复"

    asyncio.run(check())


def test_slow_subscriber_is_marked_lagged_and_never_blocks_run():
    async def check():
        gate = asyncio.Event()
        # 事件数远超订阅者队列容量
        script = (
            [("wait", gate)]
            + [
                ("event", "delta", {"content": f"段{i}"})
                for i in range(SUBSCRIBER_QUEUE_SIZE + 20)
            ]
            + [("event", "result", {"content": "完"})]
        )
        factory = MockRunnerFactory(script)
        service = make_service(factory)
        session = await make_session(service.repository)
        run = await service.create_session_run(session_id=session.id, content="你好")

        subscription = service.subscribe(run.id)
        # 消费到订阅者登记完成（重放耗尽、转入实时等待）
        while not service._runs[run.id].subscribers:
            await asyncio.wait_for(subscription.__anext__(), 1)
        gate.set()

        # 不再读取：执行不被慢订阅者阻塞，正常跑到终态
        await service.wait_finished(run.id)
        assert (await service.get_run(run.id)).status == "succeeded"

        # 恢复读取：收到溢出标记后订阅终止
        remaining = [event async for event in subscription]
        assert remaining[-1].type == "error"
        assert remaining[-1].data["code"] == "subscription_lagged"

    asyncio.run(check())


def test_request_cancel_transitions_and_terminal_is_final():
    async def check():
        factory = MockRunnerFactory([("block",)])
        service = make_service(factory)
        session = await make_session(service.repository)
        run = await service.create_session_run(session_id=session.id, content="你好")
        while (await service.get_run(run.id)).status != "running":
            await asyncio.sleep(0)

        cancelled = service.request_cancel(run.id)
        assert cancelled.status == "cancelled"
        await service.wait_finished(run.id)

        events = await collect(service, run.id)
        statuses = [e.data["status"] for e in events if e.type == "status"]
        assert statuses == ["queued", "running", "cancelling", "cancelled"]
        assert service.stats["runs_cancelled"] == 1
        assert factory.created[0].closed

        # 终态后再取消：拒绝且不产生新事件
        with pytest.raises(ChatError) as excinfo:
            service.request_cancel(run.id)
        assert excinfo.value.code == "invalid_state"
        again = await collect(service, run.id)
        assert [e.seq for e in again] == [e.seq for e in events]

        # 占用已释放，可立即开始新执行
        factory.script = GOOD_SCRIPT
        rerun = await service.create_session_run(session_id=session.id, content="再来")
        await service.wait_finished(rerun.id)
        assert (await service.get_run(rerun.id)).status == "succeeded"

    asyncio.run(check())


def test_runner_error_ends_failed_without_history_commit():
    async def check():
        factory = MockRunnerFactory(
            [
                ("event", "delta", {"content": "半句"}),
                ("raise", RuntimeError("secret upstream credential")),
            ]
        )
        service = make_service(factory)
        session = await make_session(service.repository)
        run = await service.create_session_run(session_id=session.id, content="你好")
        await service.wait_finished(run.id)

        final = await service.get_run(run.id)
        assert final.status == "failed"
        assert final.error.code == "runner_failed"
        assert "secret" not in final.error.message
        assert (await service.repository.get(session.id)).messages == ()
        assert service.stats["runs_failed"] == 1

        events = await collect(service, run.id)
        assert events[-1].data == {
            "status": "failed",
            "error": {"code": "runner_failed", "message": final.error.message},
        }

    asyncio.run(check())


def test_empty_result_and_timeout_end_failed():
    async def check():
        # 空结果
        factory = MockRunnerFactory([("event", "delta", {"content": "只有增量"})])
        service = make_service(factory)
        session = await make_session(service.repository)
        run = await service.create_session_run(session_id=session.id, content="你好")
        await service.wait_finished(run.id)
        assert (await service.get_run(run.id)).error.code == "runner_failed"

        # 超时
        factory = MockRunnerFactory([("block",)])
        service = make_service(factory, timeout_seconds=0.05)
        session = await make_session(service.repository, "s-2")
        run = await service.create_session_run(session_id=session.id, content="你好")
        await service.wait_finished(run.id)
        final = await service.get_run(run.id)
        assert final.status == "failed" and final.error.code == "run_timeout"
        assert factory.created[0].closed

    asyncio.run(check())


def test_occupancy_and_capacity_rejections():
    async def check():
        factory = MockRunnerFactory([("block",)])
        service = make_service(factory, max_concurrent_runs=1)
        repository = service.repository
        session = await make_session(repository, "s-1")
        other = await make_session(repository, "s-2")
        run = await service.create_session_run(session_id=session.id, content="你好")
        while (await service.get_run(run.id)).status != "running":
            await asyncio.sleep(0)

        with pytest.raises(ChatError) as busy:
            await service.create_session_run(session_id=session.id, content="又一句")
        assert busy.value.code == "session_busy"
        with pytest.raises(ChatError) as capacity:
            await service.create_session_run(session_id=other.id, content="你好")
        assert capacity.value.code == "capacity_exceeded"

        with pytest.raises(ChatError) as missing:
            await service.create_session_run(session_id="missing", content="你好")
        assert missing.value.code == "session_not_found"

        service.request_cancel(run.id)
        await service.wait_finished(run.id)

    asyncio.run(check())


def test_stateless_run_skips_persistence_and_session_occupancy():
    async def check():
        factory = MockRunnerFactory(GOOD_SCRIPT)
        service = make_service(factory)
        run = await service.create_stateless_run(
            (Message("system", "助手"), Message("user", "你好"))
        )
        assert run.session_id is None
        events = await collect(service, run.id)
        assert events[-1].data["status"] == "succeeded"
        assert await service.repository.list() == ()
        assert [m.content for m in factory.created[0].seen] == ["助手", "你好"]

    asyncio.run(check())


def test_terminal_records_are_pruned_beyond_retention(monkeypatch):
    async def check():
        monkeypatch.setattr(run_module, "MAX_RETAINED_TERMINAL_RUNS", 2)
        factory = MockRunnerFactory(GOOD_SCRIPT)
        service = make_service(factory)
        session = await make_session(service.repository)
        runs = []
        for _ in range(4):
            run = await service.create_session_run(
                session_id=session.id, content="你好"
            )
            await service.wait_finished(run.id)
            runs.append(run)
        with pytest.raises(ChatError) as missing:
            await service.get_run(runs[0].id)
        assert missing.value.code == "run_not_found"
        assert (await service.get_run(runs[-1].id)).status == "succeeded"

    asyncio.run(check())


def test_subscribe_unknown_run_rejected():
    async def check():
        service = make_service(MockRunnerFactory(GOOD_SCRIPT))
        with pytest.raises(ChatError) as missing:
            async for _ in service.subscribe("missing"):
                pass
        assert missing.value.code == "run_not_found"
        with pytest.raises(ChatError):
            service.request_cancel("missing")

    asyncio.run(check())
