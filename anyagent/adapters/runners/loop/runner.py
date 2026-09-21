"""Self-driving loop runner with no agent framework dependency.

Drives its own tool loop using only ChatClient, ToolSet and Message.
"""

from collections.abc import AsyncIterator, Callable

from anyagent.core.domain.chat import Event, Message, ToolCall
from anyagent.core.ports.model import ChatChunk, ChatClient, ChatResult
from anyagent.tools import ToolSet
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


class LoopRunner:
    """Minimal agent loop: stream → tool calls → repeat until done."""

    def __init__(
        self,
        client: ChatClient,
        tool_set: ToolSet,
        *,
        system_prompt: str = "",
        max_steps: int = 10,
    ):
        self._client = client
        self._tool_set = tool_set
        self._system_prompt = system_prompt
        self._max_steps = max_steps

    async def stream(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]:
        history = list(messages)
        final = ""

        for step in range(self._max_steps):
            logger.debug("LoopRunner step %d: messages=%d", step, len(history))
            result, delta_events = await self._collect_step(tuple(history))
            for delta_event in delta_events:
                yield delta_event

            if not result.tool_calls:
                final = result.content
                break

            # Append assistant message with tool calls
            parsed_calls = result.parsed_tool_calls()
            assistant = Message(
                "assistant",
                result.content,
                tool_calls=tuple(
                    ToolCall(tc["id"], tc["name"], tc["arguments"])
                    for tc in parsed_calls
                ),
            )
            history.append(assistant)

            # Execute each tool call
            for tc in assistant.tool_calls:
                yield Event(
                    "tool_call",
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                )
                tool = self._tool_set.get_tool(tc.name)
                if tool is None:
                    tool_result = f"Error: unknown tool '{tc.name}'."
                else:
                    tool_result = await tool.call(**tc.arguments)
                yield Event(
                    "tool_result",
                    {"id": tc.id, "name": tc.name, "content": tool_result},
                )
                history.append(
                    Message(
                        "tool",
                        tool_result,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
        else:
            logger.warning("LoopRunner reached max_steps=%d", self._max_steps)

        yield Event("result", {"content": final})

    async def _collect_step(
        self, messages: tuple[Message, ...]
    ) -> tuple[ChatResult, list[Event]]:
        """Run one model call and return the final result plus delta events."""
        if self._system_prompt:
            messages = (Message("system", self._system_prompt),) + messages

        content_parts: list[str] = []
        delta_events: list[Event] = []
        final_result: ChatResult | None = None

        async for chunk in self._client.stream(messages, tools=self._tool_set):
            if isinstance(chunk, ChatResult):
                final_result = chunk
            elif isinstance(chunk, ChatChunk):
                content_parts.append(chunk.delta)
                delta_events.append(Event("delta", {"content": chunk.delta}))

        result = ChatResult(
            content="".join(content_parts)
            or (final_result.content if final_result else ""),
            tool_calls=final_result.tool_calls if final_result else (),
            input_tokens=final_result.input_tokens if final_result else 0,
            output_tokens=final_result.output_tokens if final_result else 0,
        )
        return result, delta_events

    async def aclose(self) -> None:
        await self._client.aclose()


class LoopRunnerFactory:
    """Creates LoopRunner instances from injected dependencies.

    client_loader is invoked per create() so model connection
    changes apply to the next run without a restart.
    """

    def __init__(
        self,
        client_loader: Callable[[], ChatClient],
        tool_set: ToolSet,
        *,
        system_prompt: str = "",
        max_steps: int = 10,
    ):
        self._client_loader = client_loader
        self._tool_set = tool_set
        self._system_prompt = system_prompt
        self._max_steps = max_steps

    async def create(self) -> LoopRunner:
        return LoopRunner(
            self._client_loader(),
            self._tool_set,
            system_prompt=self._system_prompt,
            max_steps=self._max_steps,
        )
