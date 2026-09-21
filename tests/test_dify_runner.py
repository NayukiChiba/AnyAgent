"""Tests for DifyRunner event mapping."""

from anyagent.adapters.runners.dify.runner import DifyRunner


def _make_runner() -> DifyRunner:
    return DifyRunner(
        base_url="http://localhost:9999",
        api_key="test-key",
        streaming=True,
    )


def test_map_message_event() -> None:
    runner = _make_runner()
    event = runner._map_event({"event": "message", "answer": "你好"})
    assert event is not None
    assert event.type == "delta"
    assert event.data["content"] == "你好"


def test_map_agent_message_event() -> None:
    runner = _make_runner()
    event = runner._map_event({"event": "agent_message", "answer": "计算结果"})
    assert event is not None
    assert event.type == "delta"


def test_map_message_end_event() -> None:
    runner = _make_runner()
    event = runner._map_event({"event": "message_end", "answer": "最终回复"})
    assert event is not None
    assert event.type == "result"
    assert event.data["content"] == "最终回复"


def test_map_tool_call_event() -> None:
    runner = _make_runner()
    event = runner._map_event(
        {
            "event": "tool_call",
            "tool_call_id": "call-1",
            "tool_name": "calculate",
            "tool_input": {"a": 1, "b": 2},
        }
    )
    assert event is not None
    assert event.type == "tool_call"
    assert event.data["name"] == "calculate"


def test_map_tool_result_event() -> None:
    runner = _make_runner()
    event = runner._map_event(
        {
            "event": "tool_result",
            "tool_call_id": "call-1",
            "tool_name": "calculate",
            "result": "3",
        }
    )
    assert event is not None
    assert event.type == "tool_result"
    assert event.data["content"] == "3"


def test_map_unknown_event_returns_none() -> None:
    runner = _make_runner()
    event = runner._map_event({"event": "workflow_started"})
    assert event is None


def test_dify_package_has_no_framework_imports() -> None:
    """adapters/runners/dify/ 只允许 import httpx，不允许框架 SDK。"""
    import pathlib

    pkg_dir = pathlib.Path("anyagent/adapters/runners/dify")
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for forbidden in ("langchain", "langgraph", "openai"):
            assert forbidden not in content, f"{py_file} imports {forbidden}"
