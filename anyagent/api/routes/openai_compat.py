"""OpenAI 兼容网关：/v1/models 与 /v1/chat/completions。

第三方客户端将 base_url 指向本服务即可使用当前配置的执行引擎。
网关无状态：历史由客户端携带，经 ChatService.run_stateless 执行，不落库；
temperature 等 OpenAI 扩展字段一律忽略。工具调用在服务端内部完成，
对客户端只呈现文本增量。
"""

import json
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from anyagent.api.routes.chat import ERROR_STATUS
from anyagent.core.domain.chat import ChatError, Message

router = APIRouter(prefix="/v1", tags=["openai"])

MODEL_ID = "anyagent"


class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_call_id: str | None = None


class ChatCompletionInput(BaseModel):
    # OpenAI 客户端会携带 temperature 等额外字段，必须忽略而非拒绝
    model_config = ConfigDict(extra="ignore")
    model: str = MODEL_ID
    messages: list[OpenAIMessage] = Field(min_length=1)
    stream: bool = False


def to_domain(messages: list[OpenAIMessage]) -> tuple[Message, ...]:
    """OpenAI 消息映射为领域消息；assistant 的 tool_calls 数组丢弃。"""
    result = []
    for message in messages:
        content = message.content or ""
        if message.role == "tool":
            result.append(
                Message("tool", content, tool_call_id=message.tool_call_id or "unknown")
            )
        else:
            result.append(Message(message.role, content))
    return tuple(result)


def openai_error(error: ChatError) -> JSONResponse:
    """ChatError 映射为 OpenAI 错误格式。"""
    return JSONResponse(
        {
            "error": {
                "message": error.message,
                "type": "server_error",
                "code": error.code,
            }
        },
        status_code=ERROR_STATUS.get(error.code, 502),
    )


@router.get("/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "anyagent"}
        ],
    }


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionInput, request: Request):
    service = request.app.state.chat_service
    messages = to_domain(body.messages)
    if body.stream:
        return _stream_response(service, messages, body.model)
    content = ""
    try:
        async with aclosing(service.run_stateless(messages)) as events:
            async for event in events:
                if event.type == "result":
                    content = event.data["content"]
    except ChatError as error:
        return openai_error(error)
    return {
        "id": f"chatcmpl-{uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _stream_response(service, messages: tuple[Message, ...], model: str):
    completion_id = f"chatcmpl-{uuid4().hex[:24]}"
    created = int(time.time())

    def chunk(delta: dict, finish: str | None = None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def stream() -> AsyncIterator[str]:
        yield chunk({"role": "assistant"})
        try:
            async with aclosing(service.run_stateless(messages)) as events:
                async for event in events:
                    if event.type == "delta":
                        yield chunk({"content": event.data.get("content", "")})
        except ChatError as error:
            payload = {
                "error": {
                    "message": error.message,
                    "type": "server_error",
                    "code": error.code,
                }
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        yield chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
