"""Runner 契约测试：同一场景集施加到 MockRunner 与 LoopRunner。

验证任何接入 RunService 的 runner 外部行为一致：终态唯一且正确、
事件序号连续、错误不泄漏内部文本、失败/取消不提交历史。
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from anyagent.core.domain.chat import Session
from anyagent.core.services.run import RunService
from anyagent.infrastructure.memory.sessions import MemorySessionRepository
from tests.contract.runner_contract import SCENARIOS, factory_for

LIMITS = {
    "timeout_seconds": 5,
    "max_concurrent_runs": 2,
    "max_history_messages": 10,
    "max_input_chars": 1000,
    "max_output_chars": 1000,
    "max_event_chars": 1000,
    "cleanup_timeout_seconds": 1,
}


@pytest.mark.parametrize("runner_kind", ["mock", "loop"])
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_runner_contract(scenario, runner_kind):
    if scenario.mock_only and runner_kind != "mock":
        pytest.skip("该场景仅脚本驱动 runner 可构造")

    async def check():
        factory = factory_for(runner_kind, scenario)
        repository = MemorySessionRepository(max_sessions=4)
        service = RunService(repository, factory, **(LIMITS | scenario.overrides))
        session = Session(uuid4().hex, "契约", datetime.now(UTC).isoformat())
        await repository.save(session)

        run = await service.create_session_run(session_id=session.id, content="你好")
        events = []
        async for event in service.subscribe(run.id):
            events.append(event)
            if (
                scenario.cancel_when_running
                and event.type == "status"
                and event.data["status"] == "running"
            ):
                service.request_cancel(run.id)
        await service.wait_finished(run.id)

        # 事件序号从 0 连续递增，最后一个事件是唯一终态
        assert [event.seq for event in events] == list(range(len(events)))
        assert events[-1].type == "status"
        assert events[-1].data["status"] == scenario.expect_status
        assert (
            sum(
                event.type == "status"
                and event.data["status"] in {"succeeded", "failed", "cancelled"}
                for event in events
            )
            == 1
        )

        terminal = events[-1].data
        if scenario.expect_error is not None:
            assert terminal["error"]["code"] == scenario.expect_error
            # 错误消息不得泄漏 runner 内部异常文本
            assert "secret" not in terminal["error"]["message"]
        if scenario.expect_status == "succeeded":
            results = [event for event in events if event.type == "result"]
            assert results[-1].data["content"] == scenario.expect_result

        stored = await repository.get(session.id)
        if scenario.expect_committed:
            assert [message.role for message in stored.messages] == [
                "user",
                "assistant",
            ]
        else:
            assert stored.messages == ()

        await service.shutdown()

    asyncio.run(check())
