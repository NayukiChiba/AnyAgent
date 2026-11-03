"""Runner 契约共享场景：任何 AgentRunner 接入 RunService 后外部行为一致。

场景以统一期望描述（终态、错误码、历史提交），由 test_runner_contract.py
参数化施加到 MockRunner（脚本驱动）与 LoopRunner（内置循环 + 桩
ChatClient）。mock_only 场景用于只有脚本驱动才能构造的非法序列。
"""

import asyncio
from dataclasses import dataclass, field

from anyagent.adapters.runners.loop.runner import LoopRunnerFactory
from anyagent.core.ports.model import ChatChunk, ChatResult
from anyagent.tools import ToolSet
from tests.mock_runner import MockRunnerFactory


class StubChatClient:
    """桩 ChatClient：按脚本产出增量/结果，支持挂起与抛错。

    脚本步骤：("chunk", 文本)、("result", 内容)、("raise", 异常)、("block",)。
    """

    def __init__(self, script):
        self.script = script
        self.closed = False

    async def stream(self, messages, tools=None):
        for step in self.script:
            kind = step[0]
            if kind == "chunk":
                yield ChatChunk(step[1])
            elif kind == "result":
                yield ChatResult(content=step[1])
            elif kind == "raise":
                raise step[1]
            elif kind == "block":
                await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def loop_factory(script):
    """LoopRunner 工厂：每次创建使用新的桩客户端与空工具集。"""
    return LoopRunnerFactory(lambda: StubChatClient(script), ToolSet())


def factory_for(runner_kind: str, scenario: "Scenario"):
    """按 runner 种类构造场景对应的工厂。"""
    if runner_kind == "mock":
        return MockRunnerFactory(scenario.mock_script)
    return loop_factory(scenario.stub_script)


@dataclass(frozen=True)
class Scenario:
    """一个契约场景：两种 runner 的触发脚本与统一的外部期望。"""

    name: str
    mock_script: tuple = ()
    stub_script: tuple = ()
    expect_status: str = "succeeded"
    expect_error: str | None = None  # failed 终态的错误码
    expect_result: str | None = None  # succeeded 时的结果内容
    expect_committed: bool = True  # 是否提交会话历史
    cancel_when_running: bool = False  # 进入 running 后立即请求取消
    overrides: dict = field(default_factory=dict)  # RunService 限额覆盖
    mock_only: bool = False  # 仅脚本驱动可构造的场景（如非法事件序列）


SCENARIOS = [
    Scenario(
        name="normal_stream",
        mock_script=(
            ("event", "delta", {"content": "回"}),
            ("event", "result", {"content": "回复"}),
        ),
        # LoopRunner 语义：增量拼接即最终内容（ChatResult 仅携带工具与用量）
        stub_script=(("chunk", "回"), ("chunk", "复")),
        expect_result="回复",
    ),
    Scenario(
        name="cancel_blocked",
        mock_script=(("block",),),
        stub_script=(("block",),),
        expect_status="cancelled",
        expect_committed=False,
        cancel_when_running=True,
    ),
    Scenario(
        name="error_raised",
        mock_script=(("raise", RuntimeError("secret upstream token")),),
        stub_script=(("raise", RuntimeError("secret upstream token")),),
        expect_status="failed",
        expect_error="runner_failed",
        expect_committed=False,
    ),
    Scenario(
        name="empty_result",
        # 无结果事件：mock 直接结束流；loop 桩无 ChatResult 时结果为空串
        expect_status="failed",
        expect_error="runner_failed",
        expect_committed=False,
    ),
    Scenario(
        name="result_then_events_tolerated",
        # 非法序列：result 之后仍有事件。RunService 容错消费到底并提交结果。
        mock_script=(
            ("event", "result", {"content": "回复"}),
            ("event", "delta", {"content": "迟到"}),
        ),
        expect_result="回复",
        mock_only=True,
    ),
    Scenario(
        name="timeout",
        mock_script=(("block",),),
        stub_script=(("block",),),
        expect_status="failed",
        expect_error="run_timeout",
        expect_committed=False,
        overrides={"timeout_seconds": 0.05},
    ),
    Scenario(
        name="output_limit",
        mock_script=(
            ("event", "delta", {"content": "xxxxxxxxxx"}),
            ("event", "delta", {"content": "yyyyyyyyyy"}),
        ),
        stub_script=(("chunk", "xxxxxxxxxx"), ("chunk", "yyyyyyyyyy")),
        expect_status="failed",
        expect_error="output_limit",
        expect_committed=False,
        overrides={"max_event_chars": 10},
    ),
]
