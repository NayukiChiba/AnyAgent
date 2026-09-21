"""Tests for PiRunner."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from anyagent.adapters.runners.pi.runner import PiRunner
from anyagent.core.domain.chat import Event, Message
from anyagent.core.ports.model import ChatChunk, ChatResult


def _make_client(chunks: list) -> MagicMock:
    client = MagicMock()

    async def fake_stream(messages, tools=None):
        for chunk in chunks:
            yield chunk

    client.stream = fake_stream
    client.aclose = AsyncMock()
    return client


def test_pi_runner_streams_delta_and_result() -> None:
    chunks = [
        ChatChunk(delta="你好"),
        ChatChunk(delta="，世界"),
        ChatResult(content="你好，世界"),
    ]
    client = _make_client(chunks)
    runner = PiRunner(client)

    async def check() -> list[Event]:
        events = []
        async for event in runner.stream((Message("user", "你好"),)):
            events.append(event)
        return events

    events = asyncio.run(check())
    types = [e.type for e in events]
    assert types == ["delta", "delta", "result"]
    assert events[-1].data["content"] == "你好，世界"


def test_pi_runner_ignores_tool_calls() -> None:
    """Pi 不支持工具调用，tool_calls 应被静默忽略。"""
    chunks = [
        ChatResult(
            content="回复",
            tool_calls=({"id": "c1", "name": "calc", "arguments": "{}"},),
        ),
    ]
    client = _make_client(chunks)
    runner = PiRunner(client)

    async def check() -> list[Event]:
        events = []
        async for event in runner.stream((Message("user", "hi"),)):
            events.append(event)
        return events

    events = asyncio.run(check())
    assert all(e.type != "tool_call" for e in events)


def test_pi_package_has_no_framework_imports() -> None:
    """adapters/runners/pi/ 只允许 import core.ports，不允许框架 SDK。"""
    import pathlib

    pkg_dir = pathlib.Path("anyagent/adapters/runners/pi")
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for forbidden in ("langchain", "langgraph", "openai"):
            assert forbidden not in content, f"{py_file} imports {forbidden}"
