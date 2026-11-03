"""会话与对话的 HTTP 接口；实时事件订阅由 Run API 的 SSE 承担。"""

from contextlib import aclosing
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from anyagent.core.domain.chat import ChatError
from anyagent.core.services.chat import ChatService

router = APIRouter()


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


class SessionRenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=60)


def error_data(error: ChatError) -> dict:
    return {"type": "error", "data": {"code": error.code, "message": error.message}}


# ChatError 业务码到 HTTP 状态码的映射，供平台路由与 OpenAI 兼容路由共用
ERROR_STATUS = {
    "session_not_found": 404,
    "session_busy": 409,
    "session_not_running": 409,
    "invalid_message": 422,
    "capacity_exceeded": 429,
    "session_limit": 429,
    "model_not_configured": 503,
    "model_missing": 503,
    "model_incomplete": 503,
    "run_timeout": 504,
    "storage_unavailable": 503,
    "run_not_found": 404,
    "invalid_state": 409,
    "run_cancelled": 409,
}


def http_error(error: ChatError) -> HTTPException:
    status = ERROR_STATUS.get(error.code, 502)
    return HTTPException(status, detail=error_data(error)["data"])


def service(request: Request) -> ChatService:
    return request.app.state.chat_service


@router.get("/api/v1/agent", tags=["agent"])
async def agent_status(request: Request) -> dict:
    return request.app.state.agent_info()


@router.get("/api/v1/sessions", tags=["sessions"])
async def list_sessions(request: Request) -> list[dict]:
    try:
        return [
            {
                "id": session.id,
                "title": session.title,
                "created_at": session.created_at,
                "message_count": len(session.messages),
            }
            for session in await service(request).repository.list()
        ]
    except ChatError as error:
        raise http_error(error) from error


@router.post("/api/v1/sessions", status_code=201, tags=["sessions"])
async def create_session(request: Request) -> dict:
    try:
        return asdict(await service(request).create_session())
    except ChatError as error:
        raise http_error(error) from error


@router.get("/api/v1/sessions/{session_id}", tags=["sessions"])
async def get_session(session_id: str, request: Request) -> dict:
    try:
        return asdict(await service(request).repository.get(session_id))
    except ChatError as error:
        raise http_error(error) from error


@router.delete("/api/v1/sessions/{session_id}", status_code=204, tags=["sessions"])
async def delete_session(session_id: str, request: Request) -> None:
    try:
        await service(request).delete_session(session_id)
    except ChatError as error:
        raise http_error(error) from error


@router.patch("/api/v1/sessions/{session_id}", tags=["sessions"])
async def rename_session(
    session_id: str, body: SessionRenameInput, request: Request
) -> dict:
    try:
        return asdict(await service(request).rename_session(session_id, body.title))
    except ChatError as error:
        raise http_error(error) from error


@router.post("/api/v1/sessions/{session_id}/cancel", tags=["agent"])
async def cancel_run(session_id: str, request: Request) -> dict:
    """停止会话当前的生成（与 WebSocket cancel 等价）。"""
    try:
        service(request).cancel(session_id)
    except ChatError as error:
        raise http_error(error) from error
    return {"message": "已停止生成"}


@router.post("/api/v1/sessions/{session_id}/messages", tags=["agent"])
async def send_message(session_id: str, body: MessageInput, request: Request) -> dict:
    events = []
    try:
        async with aclosing(
            service(request).stream(session_id, body.content)
        ) as stream:
            async for event in stream:
                events.append(asdict(event))
        return {
            "session_id": session_id,
            "content": events[-1]["data"]["content"],
            "events": events,
        }
    except ChatError as error:
        raise http_error(error) from error
