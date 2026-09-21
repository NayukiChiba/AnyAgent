"""Tests for the OpenAI-compatible ChatClient implementation."""

from unittest.mock import AsyncMock, MagicMock

from anyagent.core.domain.chat import Message, ToolCall
from anyagent.core.ports.model import ChatChunk, ChatResult
from anyagent.infrastructure.openai.client import OpenAIClient


def _make_settings(**overrides):
    from pydantic import SecretStr

    from anyagent.configs.agent import ModelSettings

    defaults = {
        "enabled": True,
        "streaming": True,
        "base_url": "https://api.example.com",
        "model": "test-model",
        "api_key": SecretStr("sk-test"),
        "temperature": 0.7,
        "timeout_seconds": 30,
        "max_retries": 1,
        "stream_usage": True,
    }
    return ModelSettings(**{**defaults, **overrides})


def test_complete_returns_chat_result() -> None:
    import asyncio

    async def check() -> None:
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="hello",
                    tool_calls=None,
                )
            )
        ]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        client = OpenAIClient(_make_settings())
        client._client = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await client.complete((Message("user", "hi"),))
        assert result.content == "hello"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.tool_calls == ()

    asyncio.run(check())


def test_stream_yields_chunks_then_final_result() -> None:
    import asyncio

    async def check() -> None:
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="Hello", tool_calls=None))]
        chunk1.usage = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content=" world", tool_calls=None))]
        chunk2.usage = None

        chunk3 = MagicMock()
        chunk3.choices = []
        chunk3.usage.prompt_tokens = 8
        chunk3.usage.completion_tokens = 4

        async def fake_stream(**kwargs):
            for c in [chunk1, chunk2, chunk3]:
                yield c

        client = OpenAIClient(_make_settings())
        client._client = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=fake_stream())

        events = []
        async for event in client.stream((Message("user", "hi"),)):
            events.append(event)

        assert isinstance(events[0], ChatChunk) and events[0].delta == "Hello"
        assert isinstance(events[1], ChatChunk) and events[1].delta == " world"
        assert isinstance(events[2], ChatResult)
        assert events[2].input_tokens == 8

    asyncio.run(check())


def test_stream_accumulates_tool_calls() -> None:
    import asyncio

    async def check() -> None:
        tc = MagicMock()
        tc.index = 0
        tc.id = "call-1"
        tc.function.name = "calculate"
        tc.function.arguments = '{"a":1,"b":2}'

        chunk = MagicMock()
        chunk.choices = [MagicMock(delta=MagicMock(content=None, tool_calls=[tc]))]
        chunk.usage = None

        async def fake_stream(**kwargs):
            yield chunk

        client = OpenAIClient(_make_settings())
        client._client = MagicMock()
        client._client.chat.completions.create = AsyncMock(return_value=fake_stream())

        events = []
        async for event in client.stream((Message("user", "hi"),)):
            events.append(event)

        result = events[-1]
        assert isinstance(result, ChatResult)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "calculate"

    asyncio.run(check())


def test_to_openai_converts_tool_call_message() -> None:
    message = Message(
        "tool",
        "5",
        tool_call_id="call-1",
        name="calculate",
    )
    result = OpenAIClient._to_openai(message)
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call-1"
    assert result["name"] == "calculate"


def test_to_openai_converts_assistant_tool_calls() -> None:
    message = Message(
        "assistant",
        "计算中",
        tool_calls=(ToolCall("call-1", "calculate", {"a": 1}),),
    )
    result = OpenAIClient._to_openai(message)
    assert result["tool_calls"][0]["function"]["name"] == "calculate"


def test_openai_import_only_in_infrastructure() -> None:
    """openai SDK must only be imported inside infrastructure/openai/."""
    import pathlib

    root = pathlib.Path("anyagent")
    for py_file in root.rglob("*.py"):
        if "infrastructure/openai" in str(py_file).replace("\\", "/"):
            continue
        content = py_file.read_text(encoding="utf-8")
        assert "import openai" not in content, f"{py_file} imports openai"
