"""Tests for LangGraphRunner using the local model fixture."""

import asyncio

from anyagent.adapters.runners.langchain.model import build_chat_model
from anyagent.adapters.runners.langgraph.runner import LangGraphRunner
from anyagent.core.domain.chat import Event, Message
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


def _make_langchain_settings():
    from anyagent.configs.agent import LangChainSettings

    return LangChainSettings(
        system_prompt="",
        max_steps=10,
        max_sessions=64,
        max_history_messages=40,
        max_concurrent_runs=4,
        run_timeout_seconds=60,
        max_input_chars=4000,
        max_output_chars=8000,
        max_event_chars=100000,
        cleanup_timeout_seconds=5,
    )


def test_langgraph_runner_produces_expected_event_sequence() -> None:
    """LangGraphRunner must emit tool_call/tool_result/result events."""

    async def check() -> None:
        with open_model_endpoint() as (base_url, _):
            model_settings = _make_settings(base_url)
            lc_settings = _make_langchain_settings()
            tool_set = build_tool_set()
            model, async_client, sync_client = build_chat_model(model_settings)
            runner = LangGraphRunner(
                model,
                lc_settings,
                tool_set,
                streaming=True,
                clients=(async_client, sync_client),
            )

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


def test_langgraph_runner_no_framework_leak() -> None:
    """adapters/runners/langgraph/ may import langgraph but not openai directly."""
    import pathlib

    pkg_dir = pathlib.Path("anyagent/adapters/runners/langgraph")
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "import openai" not in content, f"{py_file} imports openai directly"
