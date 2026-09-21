"""Tool protocol types: schema, function tool, and tool set."""

from anyagent.tools.function_tool import FunctionTool
from anyagent.tools.registry import tool_registry
from anyagent.tools.schema import ToolSchema
from anyagent.tools.tool_set import ToolSet


def build_tool_set() -> ToolSet:
    """Collect all registered tools into a fresh ToolSet.

    Triggers lazy import of built-in tools so they are registered.
    """
    import anyagent.tools.builtin  # noqa: F401

    return ToolSet(tools=list(tool_registry.values()))


__all__ = ["FunctionTool", "ToolSchema", "ToolSet", "build_tool_set", "tool_registry"]
