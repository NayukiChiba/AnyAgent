"""Tool decorator for registering functions as callable tools."""

import inspect
from collections.abc import Callable

from anyagent.tools.function_tool import FunctionTool


def tool(func: Callable | None = None, *, name: str | None = None) -> Callable:
    """Register a function as a tool.

    Can be used bare (``@tool``) or with an explicit name
    (``@tool(name="...")``).

    The docstring's first paragraph becomes the tool description.
    Parameters must have type annotations; they drive JSON Schema generation.
    """

    def decorator(f: Callable) -> FunctionTool:
        doc = inspect.getdoc(f) or ""
        description = doc.split("\n\n")[0].strip() if doc else f.__name__
        ft = FunctionTool(
            name=name or f.__name__,
            description=description,
            parameters={},
            handler=f,
        )
        _register(ft)
        return ft

    if func is not None:
        return decorator(func)
    return decorator


def _register(ft: FunctionTool) -> None:
    from anyagent.tools.registry import tool_registry

    if ft.name in tool_registry:
        raise ValueError(f"Tool '{ft.name}' already registered.")
    tool_registry[ft.name] = ft
