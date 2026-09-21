"""Tests for the tools package."""

import asyncio

import pytest

from anyagent.tools.decorator import tool
from anyagent.tools.function_tool import FunctionTool
from anyagent.tools.tool_set import ToolSet


def _run(coro):
    return asyncio.run(coro)


def test_tool_decorator_generates_schema_from_annotations() -> None:
    @tool
    def add_for_schema(a: int, b: int) -> str:
        """Add two numbers."""
        return str(a + b)

    assert add_for_schema.name == "add_for_schema"
    assert add_for_schema.description == "Add two numbers."
    assert add_for_schema.parameters["type"] == "object"
    assert set(add_for_schema.parameters["properties"].keys()) == {"a", "b"}
    assert add_for_schema.parameters["required"] == ["a", "b"]


def test_tool_decorator_with_custom_name() -> None:
    @tool(name="custom_add")
    def add_custom(a: int, b: int) -> str:
        """Add two numbers."""
        return str(a + b)

    assert add_custom.name == "custom_add"


def test_tool_call_sync_handler() -> None:
    @tool
    def greet_sync(name: str) -> str:
        """Greet someone."""
        return f"Hello, {name}!"

    result = _run(greet_sync.call(name="world"))
    assert result == "Hello, world!"


def test_tool_call_async_handler() -> None:
    @tool
    async def fetch_async(url: str) -> str:
        """Fetch a URL."""
        return f"content of {url}"

    result = _run(fetch_async.call(url="https://example.com"))
    assert result == "content of https://example.com"


def test_tool_call_invalid_args_returns_error() -> None:
    @tool
    def add_invalid(a: int, b: int) -> str:
        """Add two numbers."""
        return str(a + b)

    result = _run(add_invalid.call(a="not_a_number", b=2))
    assert result.startswith("Error: invalid arguments.")


def test_tool_call_handler_exception_returns_error() -> None:
    @tool
    def fail_always() -> str:
        """Always fail."""
        raise RuntimeError("boom")

    result = _run(fail_always.call())
    assert result.startswith("Error: ")


def test_tool_set_add_get_remove() -> None:
    @tool
    def alpha_tool(x: int) -> str:
        """Alpha."""
        return str(x)

    ts = ToolSet()
    ts.add_tool(alpha_tool)
    assert ts.get_tool("alpha_tool") is alpha_tool

    ts.remove_tool("alpha_tool")
    assert ts.get_tool("alpha_tool") is None


def test_tool_set_dedup_replaces_old() -> None:

    first = FunctionTool(
        name="dup",
        description="First.",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "first",
    )
    second = FunctionTool(
        name="dup",
        description="Second.",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "second",
    )

    ts = ToolSet()
    ts.add_tool(first)
    ts.add_tool(second)
    assert ts.get_tool("dup") is second


def test_tool_set_to_openai_schema() -> None:
    @tool
    def ping_tool(host: str) -> str:
        """Ping a host."""
        return "pong"

    ts = ToolSet()
    ts.add_tool(ping_tool)
    schemas = ts.to_openai_schema()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "ping_tool"


def test_tool_schema_jsonschema_validated() -> None:
    from anyagent.tools.schema import ToolSchema

    with pytest.raises(Exception):
        ToolSchema(
            name="bad",
            description="bad",
            parameters={"type": "invalid_jsonschema_type"},
        )


def test_tools_package_has_no_framework_imports() -> None:
    """tools/ must not import langchain, langgraph, or openai."""
    import pathlib

    import anyagent.tools as tools_pkg

    pkg_dir = pathlib.Path(tools_pkg.__file__).parent
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for forbidden in ("import langchain", "import langgraph", "import openai"):
            assert forbidden not in content, f"{py_file} imports {forbidden}"
