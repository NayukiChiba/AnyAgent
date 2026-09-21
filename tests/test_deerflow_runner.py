"""Tests for DeerFlowRunner event mapping."""

from anyagent.adapters.runners.deerflow.runner import DeerFlowRunner


def _make_runner() -> DeerFlowRunner:
    return DeerFlowRunner(
        base_url="http://localhost:9999",
        api_key="test-key",
        streaming=True,
    )


def test_map_messages_partial_produces_delta() -> None:
    runner = _make_runner()
    event = runner._map_event(
        "messages/partial",
        [{"type": "ai", "content": "你好"}],
    )
    assert event is not None
    assert event.type == "delta"
    assert event.data["content"] == "你好"


def test_map_messages_complete_produces_result() -> None:
    runner = _make_runner()
    event = runner._map_event(
        "messages/complete",
        [{"type": "ai", "content": "最终回复"}],
    )
    assert event is not None
    assert event.type == "result"
    assert event.data["content"] == "最终回复"


def test_map_updates_produces_tool_call() -> None:
    runner = _make_runner()
    event = runner._map_event(
        "updates",
        {
            "agent": {
                "messages": [
                    {
                        "type": "ai",
                        "tool_calls": [
                            {"id": "c1", "name": "calculate", "args": {"a": 1}}
                        ],
                    }
                ]
            }
        },
    )
    assert event is not None
    assert event.type == "tool_call"
    assert event.data["name"] == "calculate"


def test_map_updates_produces_tool_result() -> None:
    runner = _make_runner()
    event = runner._map_event(
        "updates",
        {
            "tools": {
                "messages": [
                    {
                        "type": "tool",
                        "tool_call_id": "c1",
                        "name": "calculate",
                        "content": "3",
                    }
                ]
            }
        },
    )
    assert event is not None
    assert event.type == "tool_result"
    assert event.data["content"] == "3"


def test_map_unknown_event_returns_none() -> None:
    runner = _make_runner()
    event = runner._map_event("metadata", {"run_id": "abc"})
    assert event is None


def test_deerflow_package_has_no_framework_imports() -> None:
    """adapters/runners/deerflow/ 只允许 import httpx，不允许框架 SDK。"""
    import pathlib
    import re

    # 只匹配真实 import 语句，避免误判 docstring/URL 中出现的框架名
    pattern = re.compile(r"^(?:from|import)\s+(langchain|langgraph|openai)", re.M)
    pkg_dir = pathlib.Path("anyagent/adapters/runners/deerflow")
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        match = pattern.search(content)
        assert match is None, f"{py_file} imports {match.group(1)}"
