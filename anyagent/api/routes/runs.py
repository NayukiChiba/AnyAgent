"""Run API：创建、查询、事件订阅与取消。

Run 是执行的一等公民：创建后独立运行，事件经 SSE 订阅
（Last-Event-ID 断点重连），订阅断开不停止执行。归属边界为
创建时绑定的会话；本地单用户形态下不引入平台级鉴权（见 M1 计划 D7）。
"""

import json
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from anyagent.api.routes.chat import error_data, http_error, service
from anyagent.core.domain.chat import ChatError, Message
from anyagent.core.domain.run import Run

router = APIRouter()


class RunCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 携带 session_id 时会话执行并提交历史；缺省为无会话执行
    session_id: str | None = None
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


def run_data(run: Run) -> dict:
    """Run 的 API 快照：状态、结果与错误，不回放完整输入消息。"""
    return {
        "id": run.id,
        "session_id": run.session_id,
        "profile_id": run.profile_id,
        "status": run.status,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "result": run.result,
        "error": asdict(run.error) if run.error else None,
        "truncated": run.input.truncated,
        "config_snapshot": run.config_snapshot,
    }


@router.post("/api/v1/runs", status_code=201, tags=["runs"])
async def create_run(body: RunCreateInput, request: Request) -> dict:
    runs = service(request).runs
    try:
        if body.session_id is not None:
            run = await runs.create_session_run(
                session_id=body.session_id, content=body.content
            )
        else:
            run = await runs.create_stateless_run((Message("user", body.content),))
        return run_data(run)
    except ChatError as error:
        raise http_error(error) from error


@router.get("/api/v1/runs/{run_id}", tags=["runs"])
async def get_run(run_id: str, request: Request) -> dict:
    try:
        return run_data(await service(request).runs.get_run(run_id))
    except ChatError as error:
        raise http_error(error) from error


@router.post("/api/v1/runs/{run_id}/cancel", tags=["runs"])
async def cancel_run(run_id: str, request: Request) -> dict:
    try:
        return run_data(service(request).runs.request_cancel(run_id))
    except ChatError as error:
        raise http_error(error) from error


@router.get("/api/v1/runs/{run_id}/events", tags=["runs"])
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE 事件订阅：id 为事件序号，支持 Last-Event-ID 断点续传。"""
    runs = service(request).runs
    since = request.headers.get("last-event-id", "-1")
    try:
        since_seq = int(since)
    except ValueError:
        since_seq = -1

    async def stream():
        try:
            async for event in runs.subscribe(run_id, since_seq=since_seq):
                payload = json.dumps(
                    {"seq": event.seq, "type": event.type, "data": event.data},
                    ensure_ascii=False,
                )
                yield f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n"
        except ChatError as error:
            yield f"event: error\ndata: {json.dumps(error_data(error), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
