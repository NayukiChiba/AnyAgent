"""Immutable chat snapshots and public execution events."""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        # asdict() 会把嵌套的 ToolCall 变成 dict，构造时强制转回来
        object.__setattr__(
            self,
            "tool_calls",
            tuple(
                call if isinstance(call, ToolCall) else ToolCall(**call)
                for call in self.tool_calls
            ),
        )


@dataclass(frozen=True)
class Session:
    id: str
    title: str
    created_at: str
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True)
class Event:
    type: Literal["delta", "tool_call", "tool_result", "result"]
    data: dict


class ChatError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
