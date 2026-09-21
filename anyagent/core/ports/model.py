"""Model client contract for self-driving runners."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from anyagent.core.domain.chat import Message
from anyagent.tools import ToolSet


@dataclass(frozen=True)
class ChatChunk:
    """One increment in a streaming response."""

    delta: str


@dataclass(frozen=True)
class ChatResult:
    """Complete result of a model call.

    In streaming mode this is yielded as the final item after all
    ChatChunk increments, carrying accumulated tool calls and usage.
    """

    content: str
    tool_calls: tuple = ()
    input_tokens: int = 0
    output_tokens: int = 0


class ChatClient(Protocol):
    """Minimal model client for runners that drive their own loop."""

    async def complete(
        self,
        messages: tuple[Message, ...],
        tools: ToolSet | None = None,
    ) -> ChatResult: ...

    def stream(
        self,
        messages: tuple[Message, ...],
        tools: ToolSet | None = None,
    ) -> AsyncIterator[ChatChunk | ChatResult]: ...

    async def test(self) -> None: ...

    async def aclose(self) -> None: ...
