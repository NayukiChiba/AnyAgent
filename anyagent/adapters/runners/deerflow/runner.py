"""DeerFlow runner：通过 DeerFlow Gateway 的 LangGraph 兼容 API 执行对话。

DeerFlow 2.0 对外暴露 LangGraph Server 兼容的 REST 接口：
- POST /api/langgraph/threads  创建会话线程
- POST /api/langgraph/threads/{thread_id}/runs/stream  流式执行

事件协议为 LangGraph SSE：event 字段为消息类型，data 字段为 JSON。
"""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from anyagent.configs import load_model_config
from anyagent.configs.agent import ModelSettings
from anyagent.core.domain.chat import ChatError, Event, Message
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


class DeerFlowRunner:
    """DeerFlow Gateway runner：通过 LangGraph 兼容 API 调用。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        streaming: bool = True,
        timeout_seconds: int = 120,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._streaming = streaming
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def stream(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]:
        thread_id = await self._create_thread()
        logger.debug("DeerFlow thread created: %s", thread_id)

        payload: dict[str, Any] = {
            "assistant_id": "lead_agent",
            "input": {
                "messages": [
                    {"role": m.role, "content": m.content}
                    for m in messages
                    if m.role in ("user", "assistant", "system")
                ]
            },
            "stream_mode": ["messages", "updates"],
        }
        url = f"{self._base_url}/api/langgraph/threads/{thread_id}/runs/stream"

        async with self._client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise ChatError(
                    "deerflow_error",
                    f"DeerFlow 请求失败: {response.status_code} {body[:200]}",
                )
            async for event in self._parse_sse(response):
                yield event

    async def _create_thread(self) -> str:
        response = await self._client.post(
            f"{self._base_url}/api/langgraph/threads", json={}
        )
        if response.status_code not in (200, 201):
            raise ChatError(
                "deerflow_error",
                f"DeerFlow 创建线程失败: {response.status_code}",
            )
        return response.json()["thread_id"]

    async def _parse_sse(self, response: httpx.Response) -> AsyncIterator[Event]:
        """解析 LangGraph SSE 事件流。"""
        event_type = ""
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                event = self._map_event(event_type, data)
                if event is not None:
                    yield event

    def _map_event(self, event_type: str, data: Any) -> Event | None:
        match event_type:
            case "messages/partial" | "messages/complete":
                # data 是消息列表，取最后一条
                if isinstance(data, list) and data:
                    msg = data[-1]
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = "".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                    if msg.get("type") == "ai" and content:
                        if event_type == "messages/partial":
                            return Event("delta", {"content": content})
                        return Event("result", {"content": content})
            case "updates":
                if isinstance(data, dict):
                    for node_output in data.values():
                        if not isinstance(node_output, dict):
                            continue
                        for msg in node_output.get("messages", []):
                            if msg.get("type") == "ai":
                                for tc in msg.get("tool_calls", []):
                                    return Event(
                                        "tool_call",
                                        {
                                            "id": tc.get("id", ""),
                                            "name": tc.get("name", ""),
                                            "arguments": tc.get("args", {}),
                                        },
                                    )
                            elif msg.get("type") == "tool":
                                return Event(
                                    "tool_result",
                                    {
                                        "id": msg.get("tool_call_id", ""),
                                        "name": msg.get("name", ""),
                                        "content": str(msg.get("content", "")),
                                    },
                                )
        return None

    async def aclose(self) -> None:
        await self._client.aclose()


class DeerFlowRunnerFactory:
    """按配置创建 DeerFlowRunner 实例。

    连接信息读取自模型连接配置（base_url 指向 Gateway 地址），
    每次创建时重读以支持热更新；本地无认证的 Gateway 密钥可填 local。
    """

    def __init__(
        self,
        model_loader: Callable[[], ModelSettings] = load_model_config,
    ):
        self._model_loader = model_loader

    async def create(self) -> DeerFlowRunner:
        connection = self._model_loader()
        api_key = connection.api_key.get_secret_value()
        if not connection.enabled or not api_key:
            raise ChatError(
                "model_not_configured",
                "请在模型连接设置中配置并启用 DeerFlow 的 Gateway 地址与密钥",
            )
        return DeerFlowRunner(
            connection.base_url,
            api_key,
            streaming=connection.streaming,
            timeout_seconds=connection.timeout_seconds,
        )
