"""Tests for CozeRunner event mapping."""

from anyagent.adapters.runners.coze.runner import CozeRunner


def _make_runner() -> CozeRunner:
    return CozeRunner(
        base_url="http://localhost:9999",
        api_key="test-key",
        bot_id="bot-123",
        streaming=True,
    )


def test_map_message_delta_event() -> None:
    runner = _make_runner()
    event = runner._map_event(
        {
            "event": "conversation.message.delta",
            "data": {"content": "你好", "type": "answer"},
        }
    )
    assert event is not None
    assert event.type == "delta"
    assert event.data["content"] == "你好"


def test_map_message_delta_non_answer_ignored() -> None:
    runner = _make_runner()
    event = runner._map_event(
        {
            "event": "conversation.message.delta",
            "data": {"content": "思考中", "type": "verbose"},
        }
    )
    assert event is None


def test_map_message_completed_event() -> None:
    runner = _make_runner()
    event = runner._map_event(
        {
            "event": "conversation.message.completed",
            "data": {"content": "最终回复", "type": "answer"},
        }
    )
    assert event is not None
    assert event.type == "result"
    assert event.data["content"] == "最终回复"


def test_map_chat_failed_raises() -> None:
    import pytest

    from anyagent.core.domain.chat import ChatError

    runner = _make_runner()
    with pytest.raises(ChatError) as exc_info:
        runner._map_event(
            {
                "event": "conversation.chat.failed",
                "data": {"last_error": {"msg": "bot 不存在"}},
            }
        )
    assert exc_info.value.code == "coze_error"


def test_map_unknown_event_returns_none() -> None:
    runner = _make_runner()
    event = runner._map_event({"event": "conversation.chat.created", "data": {}})
    assert event is None


def test_coze_package_has_no_framework_imports() -> None:
    """adapters/runners/coze/ 只允许 import httpx，不允许框架 SDK。"""
    import pathlib

    pkg_dir = pathlib.Path("anyagent/adapters/runners/coze")
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for forbidden in ("langchain", "langgraph", "openai"):
            assert forbidden not in content, f"{py_file} imports {forbidden}"
