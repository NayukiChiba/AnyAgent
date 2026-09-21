"""Coze runner：通过字节跳动 Coze 平台 API 执行对话。

Coze 使用专有协议（POST /v3/chat，SSE 流式响应），
需要先在平台侧创建 Bot 并获取 Bot ID 与 API Token。
事件类型：conversation.message.delta / conversation.message.completed /
conversation.chat.completed / conversation.chat.failed。
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

_COZE_CHAT_PATH = "/v3/chat"


class CozeRunner:
    """Coze 平台 runner：纯 HTTP 调用，无本地循环。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        bot_id: str,
        *,
        streaming: bool = True,
        timeout_seconds: int = 60,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._bot_id = bot_id
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
            "bot_id": self._bot_id,
            "user_id": "anyagent",
            "stream": self._streaming,
            "auto_save_history": True,
            "additional_messages": [
                {
                    "role": "user",
                    "content": user_message.content,
                    "content_type": "text",
                }
            ],
        }
        url = f"{self._base_url}{_COZE_CHAT_PATH}"
        logger.debug("Coze request: url=%s query=%s", url, user_message.content)

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
                    "coze_error",
                    f"Coze 请求失败: {response.status_code} {body[:200]}",
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
                "coze_error",
                f"Coze 请求失败: {response.status_code} {response.text[:200]}",
            )
        data = response.json()
        # 非流式响应：messages 列表中找 type=answer 的最后一条
        messages = data.get("messages", [])
        answer = next(
            (m["content"] for m in reversed(messages) if m.get("type") == "answer"),
            "",
        )
        yield Event("result", {"content": answer})

    def _map_event(self, data: dict) -> Event | None:
        event_type = data.get("event", "")
        msg = data.get("data", {})
        match event_type:
            case "conversation.message.delta":
                content = msg.get("content", "")
                if content and msg.get("type") == "answer":
                    return Event("delta", {"content": content})
            case "conversation.message.completed":
                if msg.get("type") == "answer":
                    return Event("result", {"content": msg.get("content", "")})
            case "conversation.chat.failed":
                raise ChatError(
                    "coze_error",
                    f"Coze 执行失败: {msg.get('last_error', {}).get('msg', '')}",
                )
        return None

    async def aclose(self) -> None:
        await self._client.aclose()


class CozeRunnerFactory:
    """按配置创建 CozeRunner 实例。

    bot_id 来自 Agent 行为设置（重启生效）；连接信息读取自模型连接配置，
    每次创建时重读以支持热更新。
    """

    def __init__(
        self,
        bot_id: str,
        model_loader: Callable[[], ModelSettings] = load_model_config,
    ):
        self._bot_id = bot_id
        self._model_loader = model_loader

    async def create(self) -> CozeRunner:
        connection = self._model_loader()
        api_key = connection.api_key.get_secret_value()
        if not connection.enabled or not api_key:
            raise ChatError(
                "model_not_configured",
                "请在模型连接设置中配置并启用 Coze 的接口地址与 API Key",
            )
        if not self._bot_id:
            raise ChatError(
                "model_not_configured",
                "请在 Agent 行为设置中填写 Coze Bot ID",
            )
        return CozeRunner(
            connection.base_url,
            api_key,
            self._bot_id,
            streaming=connection.streaming,
            timeout_seconds=connection.timeout_seconds,
        )
