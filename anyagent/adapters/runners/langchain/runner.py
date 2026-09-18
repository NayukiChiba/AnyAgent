"""Normalize a real LangChain agent graph into platform execution events."""

import math
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Literal

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from openai import DefaultAsyncHttpxClient, DefaultHttpxClient

from anyagent.configs import load_model_config
from anyagent.configs.agent import LangChainSettings, ModelSettings
from anyagent.core.domain.chat import ChatError, Event, Message
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


@tool
def calculate(
    operation: Literal["add", "subtract", "multiply", "divide"], a: float, b: float
) -> str:
    """Calculate one arithmetic operation on two finite numbers."""
    if not math.isfinite(a) or not math.isfinite(b):
        return "Error: operands must be finite numbers."
    match operation:
        case "add":
            result = a + b
        case "subtract":
            result = a - b
        case "multiply":
            result = a * b
        case "divide":
            if b == 0:
                return "Error: division by zero."
            result = a / b
        case _:
            return "Error: unsupported operation."
    return str(result) if math.isfinite(result) else "Error: result is not finite."


def text_content(content: str | list) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block if isinstance(block, str) else block.get("text", "")
        for block in content
        if isinstance(block, str)
        or (isinstance(block, dict) and block.get("type") == "text")
    )


class LangChainRunner:
    def __init__(
        self,
        model: BaseChatModel,
        settings: LangChainSettings,
        *,
        streaming: bool,
        clients: tuple = (),
    ):
        self.agent = create_agent(
            model, tools=[calculate], system_prompt=settings.system_prompt
        )
        self.max_steps = settings.max_steps
        self.clients = clients
        self.streaming = streaming

    async def stream(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]:
        final = ""
        source = self.agent.astream(
            {
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ]
            },
            config={"recursion_limit": self.max_steps},
            stream_mode=["messages", "updates"] if self.streaming else ["updates"],
        )
        async with aclosing(source):
            async for mode, payload in source:
                if mode == "messages":
                    chunk, metadata = payload
                    if metadata.get("langgraph_node") == "model":
                        text = text_content(chunk.content)
                        if text:
                            yield Event("delta", {"content": text})
                elif mode == "updates":
                    for update in payload.values():
                        if not isinstance(update, dict):
                            continue
                        for message in update.get("messages", []):
                            if isinstance(message, AIMessage):
                                logger.debug(
                                    "LangChain model response: data=%s",
                                    {
                                        "content": text_content(message.content),
                                        "tool_calls": message.tool_calls,
                                    },
                                )
                                for call in message.tool_calls:
                                    yield Event(
                                        "tool_call",
                                        {
                                            "id": call["id"],
                                            "name": call["name"],
                                            "arguments": call["args"],
                                        },
                                    )
                                if not message.tool_calls:
                                    final = text_content(message.content)
                            elif isinstance(message, ToolMessage):
                                yield Event(
                                    "tool_result",
                                    {
                                        "id": message.tool_call_id,
                                        "name": message.name,
                                        "content": text_content(message.content),
                                    },
                                )
        yield Event("result", {"content": final})

    async def aclose(self) -> None:
        try:
            for client in self.clients:
                if hasattr(client, "aclose"):
                    await client.aclose()
        finally:
            for client in self.clients:
                if not hasattr(client, "aclose"):
                    client.close()


class LangChainRunnerFactory:
    def __init__(
        self,
        settings: LangChainSettings,
        *,
        model_loader: Callable[[], ModelSettings] = load_model_config,
    ):
        self.settings = settings
        self.model_loader = model_loader

    async def create(self) -> LangChainRunner:
        # A fresh immutable snapshot hot-reloads connections without changing active runs.
        connection = self.model_loader()
        if not connection.enabled:
            raise ChatError(
                "model_not_configured",
                "请在 data/configs/model_config.json 配置并启用模型",
            )
        sync_client = DefaultHttpxClient()
        async_client = DefaultAsyncHttpxClient()
        try:
            model = ChatOpenAI(
                model=connection.model,
                base_url=connection.base_url,
                api_key=connection.api_key.get_secret_value(),
                temperature=connection.temperature,
                timeout=connection.timeout_seconds,
                max_retries=connection.max_retries,
                streaming=connection.streaming,
                disable_streaming=not connection.streaming,
                stream_usage=connection.stream_usage,
                use_responses_api=False,
                http_client=sync_client,
                http_async_client=async_client,
            )
            return LangChainRunner(
                model,
                self.settings,
                streaming=connection.streaming,
                clients=(async_client, sync_client),
            )
        except BaseException:
            try:
                await async_client.aclose()
            finally:
                sync_client.close()
            raise
