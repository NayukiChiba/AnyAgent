"""LangGraph StateGraph runner：显式构建 ReAct 循环，支持 checkpoint。

与 LangChainRunner（把循环委托给 create_agent）不同，本 runner 直接构图：
agent 节点 → tool 节点 → 条件边回到 agent。显式控制状态流转，
为后续 interrupt/resume 能力留出接入点。
"""

from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

from anyagent.adapters.runners.langchain.model import build_chat_model
from anyagent.adapters.runners.langchain.tooling import to_langchain_tools
from anyagent.configs import load_model_config
from anyagent.configs.agent import LangChainSettings, ModelSettings
from anyagent.core.domain.chat import ChatError, Event, Message
from anyagent.tools import ToolSet
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


def _text_content(content: str | list) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block if isinstance(block, str) else block.get("text", "")
        for block in content
        if isinstance(block, str)
        or (isinstance(block, dict) and block.get("type") == "text")
    )


def _build_graph(
    model: Any,
    tools: list,
    system_prompt: str,
) -> CompiledStateGraph:
    """编译最小 ReAct 图：agent → tools → agent → ... → END。"""
    model_with_tools = model.bind_tools(tools)

    async def agent_node(state: MessagesState) -> dict:
        messages = state["messages"]
        if system_prompt:
            from langchain_core.messages import SystemMessage

            messages = [SystemMessage(content=system_prompt)] + messages
        response = await model_with_tools.ainvoke(messages)
        return {"messages": [response]}

    async def tool_node(state: MessagesState) -> dict:
        from langgraph.prebuilt import ToolNode

        node = ToolNode(tools)
        return await node.ainvoke(state)

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")
    return graph.compile()


class LangGraphRunner:
    def __init__(
        self,
        model: Any,
        settings: LangChainSettings,
        tool_set: ToolSet,
        *,
        streaming: bool,
        clients: tuple = (),
    ):
        self.graph = _build_graph(
            model,
            to_langchain_tools(tool_set),
            settings.system_prompt,
        )
        self.max_steps = settings.max_steps
        self.clients = clients
        self.streaming = streaming

    async def stream(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]:
        final = ""
        config = RunnableConfig(recursion_limit=self.max_steps)
        input_messages = [{"role": m.role, "content": m.content} for m in messages]
        source = self.graph.astream(
            {"messages": input_messages},
            config=config,
            stream_mode=["messages", "updates"] if self.streaming else ["updates"],
        )
        async with aclosing(source):
            async for mode, payload in source:
                if mode == "messages":
                    chunk, metadata = payload
                    if metadata.get("langgraph_node") == "agent":
                        text = _text_content(chunk.content)
                        if text:
                            yield Event("delta", {"content": text})
                elif mode == "updates":
                    for update in payload.values():
                        if not isinstance(update, dict):
                            continue
                        for message in update.get("messages", []):
                            if isinstance(message, AIMessage):
                                logger.debug(
                                    "LangGraph model response: data=%s",
                                    {
                                        "content": _text_content(message.content),
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
                                    final = _text_content(message.content)
                            elif isinstance(message, ToolMessage):
                                yield Event(
                                    "tool_result",
                                    {
                                        "id": message.tool_call_id,
                                        "name": message.name,
                                        "content": _text_content(message.content),
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


class LangGraphRunnerFactory:
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

    async def create(self) -> LangGraphRunner:
        connection = self.model_loader()
        if not connection.enabled:
            raise ChatError(
                "model_not_configured",
                "请在 data/configs/model_config.json 配置并启用模型",
            )
        model, async_client, sync_client = build_chat_model(connection)
        try:
            return LangGraphRunner(
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
