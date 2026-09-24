"""运行统计与日志查看：只读统计、日志文件回看与实时日志推送。"""

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from anyagent.configs import load_logging_config

router = APIRouter(prefix="/api/v1", tags=["observability"])


@router.get("/stats")
async def runtime_stats(request: Request) -> dict:
    """运行统计：内存计数（重启清零）加上存储中的会话数。"""
    service = request.app.state.chat_service
    sessions = await service.repository.list()
    return {
        **service.stats,
        "sessions": len(sessions),
        "runner": request.app.state.agent_info()["runner"],
    }


@router.get("/logs/tail")
async def tail_logs(lines: int = Query(default=200, ge=1, le=1000)) -> dict:
    """读取日志文件末尾若干行；文件不存在时返回空列表。"""
    path = load_logging_config().file_path
    if not path.is_file():
        return {"lines": [], "path": str(path)}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"lines": content.splitlines()[-lines:], "path": str(path)}


@router.get("/logs/stream")
async def stream_logs(request: Request, once: bool = False) -> StreamingResponse:
    """实时日志推送：先回放内存缓存的最近日志，再持续推送新日志。

    once=true 时只回放快照后立即关闭，供只需要历史日志的调用方使用。
    心跳以 PING 级别下发，前端据此维持连接而不渲染空行。
    """
    broker = request.app.state.log_broker

    async def stream():
        if once:
            for entry in broker.snapshot():
                yield f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
            return
        async for entry in broker.stream():
            yield f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
