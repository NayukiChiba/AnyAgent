"""Callable function tool wrapping a JSON schema and an async handler."""

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import Field, ValidationError, create_model
from pydantic.dataclasses import dataclass

from anyagent.tools.schema import ToolSchema
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _build_args_model(func: Callable) -> type:
    """Generate a pydantic model from a function's type-annotated signature."""
    hints = inspect.get_annotations(func, eval_str=True)
    fields: dict[str, Any] = {}
    for name, param in inspect.signature(func).parameters.items():
        annotation = hints.get(name, str)
        if param.default is param.empty:
            fields[name] = (annotation, ...)
        else:
            fields[name] = (annotation, param.default)
    return create_model(f"{func.__name__}_args", **fields)


def _to_json_schema(model: type) -> dict:
    schema = model.model_json_schema()
    properties = {
        k: {kk: vv for kk, vv in v.items() if kk != "title"}
        for k, v in schema.get("properties", {}).items()
    }
    return {
        "type": "object",
        "properties": properties,
        "required": schema.get("required", []),
    }


@dataclass
class FunctionTool(ToolSchema):
    """A tool with a handler that can be invoked by the model."""

    handler: Callable | None = Field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.handler is not None:
            self.args_model = _build_args_model(self.handler)
            self.parameters = _to_json_schema(self.args_model)

    async def call(self, **kwargs: Any) -> str:
        """Execute the tool and return the result as a string.

        Handler exceptions are caught and returned as "Error: ..." so the
        model can read and recover from failures.
        """
        if self.handler is None:
            return "Error: no handler registered."
        try:
            validated = self.args_model(**kwargs)
        except ValidationError as exc:
            return f"Error: invalid arguments. {exc.errors()[0]['msg']}"
        try:
            result = self.handler(**validated.model_dump())
            if inspect.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as exc:
            logger.warning("Tool %s execution failed: %s", self.name, exc)
            return f"Error: {exc}"
