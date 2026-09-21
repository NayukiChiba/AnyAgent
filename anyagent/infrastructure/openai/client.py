"""OpenAI-compatible model client implementation."""

from openai import AsyncOpenAI, OpenAIError

from anyagent.configs.agent import ModelSettings
from anyagent.core.domain.chat import ChatError, Message
from anyagent.core.ports.model import ChatChunk, ChatResult
from anyagent.tools import ToolSet


class OpenAIClient:
    """Thin wrapper around AsyncOpenAI for OpenAI-compatible providers."""

    def __init__(self, settings: ModelSettings):
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )

    async def complete(
        self,
        messages: tuple[Message, ...],
        tools: ToolSet | None = None,
    ) -> ChatResult:
        kwargs: dict = {
            "model": self._settings.model,
            "messages": [self._to_openai(m) for m in messages],
            "temperature": self._settings.temperature,
        }
        if tools:
            kwargs["tools"] = tools.to_openai_schema()
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        return ChatResult(
            content=choice.message.content or "",
            tool_calls=tuple(
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in (choice.message.tool_calls or [])
            ),
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )

    async def stream(
        self,
        messages: tuple[Message, ...],
        tools: ToolSet | None = None,
    ):
        kwargs: dict = {
            "model": self._settings.model,
            "messages": [self._to_openai(m) for m in messages],
            "temperature": self._settings.temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools.to_openai_schema()
        if self._settings.stream_usage:
            kwargs["stream_options"] = {"include_usage": True}

        tool_calls_acc: dict[int, dict] = {}
        usage = None
        async for chunk in await self._client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield ChatChunk(delta=delta.content)
            for tc in delta.tool_calls or []:
                acc = tool_calls_acc.setdefault(
                    tc.index, {"id": "", "name": "", "arguments": ""}
                )
                if tc.id:
                    acc["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        acc["name"] = tc.function.name
                    if tc.function.arguments:
                        acc["arguments"] += tc.function.arguments

        yield ChatResult(
            content="",
            tool_calls=tuple(tool_calls_acc.values()),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def test(self) -> None:
        """Connectivity check: one configured call and one streaming call.

        The first call uses the saved streaming flag so the probe reflects
        the actual configuration. The second is always streaming to verify
        the endpoint supports it regardless of the saved setting.
        """
        try:
            await self._client.chat.completions.create(
                model=self._settings.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                stream=self._settings.streaming,
            )
            async for _ in await self._client.chat.completions.create(
                model=self._settings.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                stream=True,
            ):
                pass
        except OpenAIError as exc:
            raise ChatError(
                "model_unavailable", "模型连接失败，请检查配置和网络"
            ) from exc

    async def aclose(self) -> None:
        await self._client.close()

    @staticmethod
    def _to_openai(message: Message) -> dict:
        result: dict = {"role": message.role, "content": message.content}
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": str(tc.arguments)},
                }
                for tc in message.tool_calls
            ]
        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id
        if message.name:
            result["name"] = message.name
        return result
