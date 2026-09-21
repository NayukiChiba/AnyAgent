"""Dify runner：通过 Dify 平台 API 执行对话。

Dify 使用专有协议（POST /v1/chat-messages，SSE 流式响应），
不走 OpenAI 兼容格式。事件类型：message / agent_message / message_end /
tool_call / tool_result / error。
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

_DIFY_CHAT_PATH = "/v1/chat-messages"


class DifyRunner:
    """Dify 平台 runner：纯 HTTP 调用，无本地循环。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        streaming: bool = True,
        timeout_seconds: int = 60,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._streaming = streaming
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def stream(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]:
        user_message = next((m for m in reversed(messages) if m.role == "user"), None)
        if user_message is None:
            raise ChatError("invalid_input", "消息列表中没有用户消息")

        payload: dict[str, Any] = {
            "inputs": {},
            "query": user_message.content,
            "response_mode": "streaming" if self._streaming else "blocking",
            "user": "anyagent",
        }
        url = f"{self._base_url}{_DIFY_CHAT_PATH}"
        logger.debug("Dify request: url=%s query=%s", url, user_message.content)

        if self._streaming:
            async for event in self._stream_sse(url, payload):
                yield event
        else:
            async for event in self._blocking(url, payload):
                yield event

    async def _stream_sse(self, url: str, payload: dict) -> AsyncIterator[Event]:
        async with self._client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise ChatError(
                    "dify_error", f"Dify 请求失败: {response.status_code} {body[:200]}"
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event_data = json.loads(data)
                except json.JSONDecodeError:
                    continue
                event = self._map_event(event_data)
                if event is not None:
                    yield event

    async def _blocking(self, url: str, payload: dict) -> AsyncIterator[Event]:
        response = await self._client.post(url, json=payload)
        if response.status_code != 200:
            raise ChatError(
                "dify_error",
                f"Dify 请求失败: {response.status_code} {response.text[:200]}",
            )
        data = response.json()
        answer = data.get("answer", "")
        yield Event("result", {"content": answer})

    def _map_event(self, data: dict) -> Event | None:
        event_type = data.get("event", "")
        match event_type:
            case "message" | "agent_message":
                text = data.get("answer", "")
                if text:
                    return Event("delta", {"content": text})
            case "message_end":
                return Event("result", {"content": data.get("answer", "")})
            case "tool_call":
                return Event(
                    "tool_call",
                    {
                        "id": data.get("tool_call_id", ""),
                        "name": data.get("tool_name", ""),
                        "arguments": data.get("tool_input", {}),
                    },
                )
            case "tool_result":
                return Event(
                    "tool_result",
                    {
                        "id": data.get("tool_call_id", ""),
                        "name": data.get("tool_name", ""),
                        "content": data.get("result", ""),
                    },
                )
            case "error":
                raise ChatError("dify_error", f"Dify 错误: {data.get('message', '')}")
        return None

    async def aclose(self) -> None:
        await self._client.aclose()


class DifyRunnerFactory:
    """按配置创建 DifyRunner 实例。

    连接信息读取自模型连接配置，每次创建时重读以支持热更新；
    Dify 不使用模型名称，仅需接口地址与 API Key。
    """

    def __init__(
        self,
        model_loader: Callable[[], ModelSettings] = load_model_config,
    ):
        self._model_loader = model_loader

    async def create(self) -> DifyRunner:
        connection = self._model_loader()
        api_key = connection.api_key.get_secret_value()
        if not connection.enabled or not api_key:
            raise ChatError(
                "model_not_configured",
                "请在模型连接设置中配置并启用 Dify 的接口地址与 API Key",
            )
        return DifyRunner(
            connection.base_url,
            api_key,
            streaming=connection.streaming,
            timeout_seconds=connection.timeout_seconds,
        )
