"""Pi Agent runner：通过 Inflection AI 的 OpenAI 兼容 API 执行对话。

Pi 使用 OpenAI 兼容协议，直接复用 OpenAIClient，
不支持工具调用（Pi 是对话模型，无 function calling 能力）。
"""

from collections.abc import AsyncIterator, Callable

from anyagent.core.domain.chat import Event, Message
from anyagent.core.ports.model import ChatChunk, ChatClient, ChatResult
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


class PiRunner:
    """Pi Agent runner：纯对话，无工具调用。"""

    def __init__(self, client: ChatClient):
        self._client = client

    async def stream(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]:
        content_parts: list[str] = []
        async for chunk in self._client.stream(messages):
            if isinstance(chunk, ChatResult):
                if chunk.tool_calls:
                    logger.warning("Pi 不支持工具调用，忽略 tool_calls")
            elif isinstance(chunk, ChatChunk):
                content_parts.append(chunk.delta)
                yield Event("delta", {"content": chunk.delta})
        yield Event("result", {"content": "".join(content_parts)})

    async def aclose(self) -> None:
        await self._client.aclose()


class PiRunnerFactory:
    """按配置创建 PiRunner 实例。

    client_loader 每次创建时调用并返回新的 ChatClient，
    由装配层注入，以支持模型连接配置的热更新。
    """

    def __init__(self, client_loader: Callable[[], ChatClient]):
        self._client_loader = client_loader

    async def create(self) -> PiRunner:
        return PiRunner(self._client_loader())
