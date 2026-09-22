"""HTTP, HTTP streaming and WebSocket access to the same chat service."""

import asyncio
import json
from contextlib import aclosing
from dataclasses import asdict
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


def http_error(error: ChatError) -> HTTPException:
    status = {
        "session_not_found": 404,
        "session_busy": 409,
        "session_not_running": 409,
        "invalid_message": 422,
        "capacity_exceeded": 429,
        "session_limit": 429,
        "model_not_configured": 503,
        "run_timeout": 504,
        "storage_unavailable": 503,
    }.get(error.code, 502)
    return HTTPException(status, detail=error_data(error)["data"])


def service(request: Request | WebSocket) -> ChatService:
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


@router.post("/api/v1/sessions/{session_id}/stream", tags=["agent"])
async def stream_message(
    session_id: str, body: MessageInput, request: Request
) -> StreamingResponse:
    try:
        await service(request).repository.get(session_id)
        service(request).validate_message(body.content)
    except ChatError as error:
        raise http_error(error) from error

    async def stream():
        try:
            async with aclosing(
                service(request).stream(session_id, body.content)
            ) as events:
                async for event in events:
                    yield f"event: {event.type}\ndata: {json.dumps(asdict(event), ensure_ascii=False)}\n\n"
        except ChatError as error:
            yield f"event: error\ndata: {json.dumps(error_data(error), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws/sessions/{session_id}")
async def chat_socket(websocket: WebSocket, session_id: str) -> None:
    origin = websocket.headers.get("origin")
    if origin and urlsplit(origin).netloc != websocket.headers.get("host"):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    running: asyncio.Task | None = None

    async def execute(content: str):
        try:
            async with aclosing(
                service(websocket).stream(session_id, content)
            ) as events:
                async for event in events:
                    await websocket.send_json(asdict(event))
        except ChatError as error:
            await websocket.send_json(error_data(error))

    try:
        await service(websocket).repository.get(session_id)
        while True:
            try:
                payload = await websocket.receive_json()
                if not isinstance(payload, dict):
                    raise ValueError("Invalid message")
                if payload.get("type") == "cancel":
                    if running and not running.done():
                        running.cancel()
                        await asyncio.gather(running, return_exceptions=True)
                        await websocket.send_json({"type": "cancelled", "data": {}})
                    continue
                if payload.get("type") != "message":
                    raise ValueError("Unknown message type")
                body = MessageInput.model_validate(
                    {key: value for key, value in payload.items() if key != "type"}
                )
                if running and not running.done():
                    await websocket.send_json(
                        error_data(
                            ChatError("session_busy", "请等待当前回复或先停止生成")
                        )
                    )
                    continue
                running = asyncio.create_task(execute(body.content))
            except (ValueError, ValidationError):
                await websocket.send_json(
                    error_data(ChatError("invalid_message", "请发送有效的消息内容"))
                )
    except ChatError as error:
        await websocket.send_json(error_data(error))
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        if running is not None:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
