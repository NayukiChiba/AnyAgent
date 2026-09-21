"""Tests for LoopRunner using the local model fixture."""

import asyncio

from anyagent.adapters.runners.loop.runner import LoopRunner, LoopRunnerFactory
from anyagent.core.domain.chat import Event, Message
from anyagent.infrastructure.openai.client import OpenAIClient
from anyagent.tools import build_tool_set
from tests.model_fixture import open_model_endpoint


def _make_settings(base_url: str, streaming: bool = True):
    from pydantic import SecretStr

    from anyagent.configs.agent import ModelSettings

    return ModelSettings(
        enabled=True,
        streaming=streaming,
        base_url=base_url,
        model="test-model",
        api_key=SecretStr("sk-test"),
        temperature=0.0,
        timeout_seconds=10,
        max_retries=0,
        stream_usage=False,
    )


def test_loop_runner_produces_expected_event_sequence() -> None:
    """LoopRunner must emit delta/tool_call/tool_result/result events."""

    async def check() -> None:
        with open_model_endpoint() as (base_url, _):
            settings = _make_settings(base_url)
            client = OpenAIClient(settings)
            tool_set = build_tool_set()
            runner = LoopRunner(client, tool_set)

            events: list[Event] = []
            async for event in runner.stream((Message("user", "计算 2+3"),)):
                events.append(event)

            types = [e.type for e in events]
            assert "tool_call" in types
            assert "tool_result" in types
            assert types[-1] == "result"

            tool_result = next(e for e in events if e.type == "tool_result")
            assert tool_result.data["content"] == "5.0"

            final = events[-1]
            assert final.data["content"] == "结果是 5"

            await runner.aclose()

    asyncio.run(check())


def test_loop_runner_factory_creates_runner() -> None:
    async def check() -> None:
        with open_model_endpoint() as (base_url, _):
            settings = _make_settings(base_url)
            client = OpenAIClient(settings)
            tool_set = build_tool_set()
            factory = LoopRunnerFactory(client, tool_set)
            runner = await factory.create()
            assert isinstance(runner, LoopRunner)

    asyncio.run(check())


def test_loop_runner_package_has_no_framework_imports() -> None:
    """adapters/runners/loop/ must not import any agent framework."""
    import pathlib

    pkg_dir = pathlib.Path("anyagent/adapters/runners/loop")
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for forbidden in ("langchain", "langgraph", "openai"):
            assert forbidden not in content, f"{py_file} imports {forbidden}"
