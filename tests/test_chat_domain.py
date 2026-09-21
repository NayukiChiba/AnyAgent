"""Round-trip serialization tests for the chat domain model."""

from dataclasses import asdict

import pytest

from anyagent.core.domain.chat import Message, ToolCall


def test_tool_message_round_trip() -> None:
    message = Message(
        "tool",
        "42",
        tool_call_id="call-1",
        name="calculate",
    )
    restored = Message(**asdict(message))
    assert restored == message


def test_assistant_message_with_tool_calls_round_trip() -> None:
    message = Message(
        "assistant",
        "先计算",
        tool_calls=(ToolCall("call-1", "calculate", {"a": 1, "b": 2}),),
    )
    restored = Message(**asdict(message))
    assert restored == message
    assert restored.tool_calls[0].arguments == {"a": 1, "b": 2}


def test_tool_message_requires_tool_call_id() -> None:
    with pytest.raises(ValueError, match="tool_call_id"):
        Message("tool", "result")


def test_plain_user_message_still_defaults() -> None:
    message = Message("user", "你好")
    assert message.tool_calls == ()
    assert message.tool_call_id is None
    assert message.name is None
