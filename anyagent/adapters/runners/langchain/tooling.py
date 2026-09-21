"""Convert ToolSet tools into LangChain StructuredTool instances."""

from langchain_core.tools import StructuredTool

from anyagent.tools import ToolSet


def to_langchain_tools(tool_set: ToolSet) -> list[StructuredTool]:
    """Translate every tool in the set to a LangChain StructuredTool.

    The handler's signature must be type-annotated so that
    StructuredTool can infer the args schema automatically.
    """
    return [
        StructuredTool.from_function(
            func=tool.handler,
            name=tool.name,
            description=tool.description,
        )
        for tool in tool_set.tools
    ]
