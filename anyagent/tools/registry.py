"""Tool registry for collecting all available tools."""

from anyagent.tools.function_tool import FunctionTool

tool_registry: dict[str, FunctionTool] = {}
