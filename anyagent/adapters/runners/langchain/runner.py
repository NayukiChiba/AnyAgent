"""Normalize a real LangChain agent graph into platform execution events."""

from collections.abc import AsyncIterator, Callable
from contextlib import aclosing

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from anyagent.adapters.runners.langchain.model import build_chat_model
from anyagent.adapters.runners.langchain.tooling import to_langchain_tools
from anyagent.configs import load_model_config
from anyagent.configs.agent import LangChainSettings, ModelSettings
from anyagent.core.domain.chat import ChatError, Event, Message
from anyagent.tools import ToolSet
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


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
        tool_set: ToolSet,
        *,
        streaming: bool,
        clients: tuple = (),
    ):
        self.agent = create_agent(
            model,
            tools=to_langchain_tools(tool_set),
            system_prompt=settings.system_prompt,
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
        tool_set: ToolSet,
        *,
        model_loader: Callable[[], ModelSettings] = load_model_config,
    ):
        self.settings = settings
        self.tool_set = tool_set
        self.model_loader = model_loader

    async def create(self) -> LangChainRunner:
        # A fresh immutable snapshot hot-reloads connections without changing active runs.
        connection = self.model_loader()
        if not connection.enabled:
            raise ChatError(
                "model_not_configured",
                "请在 data/configs/model_config.json 配置并启用模型",
            )
        model, async_client, sync_client = build_chat_model(connection)
        try:
            return LangChainRunner(
                model,
                self.settings,
                self.tool_set,
                streaming=connection.streaming,
                clients=(async_client, sync_client),
            )
        except BaseException:
            try:
                await async_client.aclose()
            finally:
                sync_client.close()
            raise
