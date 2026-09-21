"""Ordered collection of tools with deduplication and OpenAI export."""

from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass

from anyagent.tools.function_tool import FunctionTool
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolSet:
    """A named collection of tools."""

    tools: list[FunctionTool] = Field(default_factory=list)

    def add_tool(self, tool: FunctionTool) -> None:
        """Add a tool; a newer tool with the same name replaces the old one."""
        for i, existing in enumerate(self.tools):
            if existing.name == tool.name:
                logger.debug("Tool '%s' replaced in set", tool.name)
                self.tools[i] = tool
                return
        self.tools.append(tool)

    def get_tool(self, name: str) -> FunctionTool | None:
        """Return the tool with the given name, or None."""
        for t in self.tools:
            if t.name == name:
                return t
        return None

    def remove_tool(self, name: str) -> None:
        """Remove the tool with the given name; silently ignored if absent."""
        self.tools = [t for t in self.tools if t.name != name]

    def to_openai_schema(self) -> list[dict[str, Any]]:
        """Export all tools in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self.tools
        ]
