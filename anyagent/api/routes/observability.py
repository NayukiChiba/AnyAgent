"""运行统计与日志查看：只读统计、日志文件回看与实时日志推送。"""

import json
from pathlib import Path

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


def _read_tail(path: Path, max_lines: int, block_size: int = 8192) -> list[str]:
    """从文件尾部反向分块读取，凑够行数即停，避免整文件加载。

    块边界可能切断多字节字符，decode 时丢弃残片，
    因此最旧的一行可能以替换符开头，属可接受的近似。
    """
    with path.open("rb") as file:
        file.seek(0, 2)
        position = file.tell()
        buffer = b""
        while position > 0 and buffer.count(b"\n") <= max_lines:
            step = min(block_size, position)
            position -= step
            file.seek(position)
            buffer = file.read(step) + buffer
    return buffer.decode("utf-8", errors="replace").splitlines()[-max_lines:]


@router.get("/logs/tail")
async def tail_logs(lines: int = Query(default=200, ge=1, le=1000)) -> dict:
    """读取日志文件末尾若干行；文件不存在时返回空列表。"""
    path = load_logging_config().file_path
    if not path.is_file():
        return {"lines": [], "path": str(path)}
    return {"lines": _read_tail(path, lines), "path": str(path)}


def _sse_frame(entry: dict) -> str:
    """编码一条 SSE 帧；PING 心跳不带 id，避免污染客户端的 Last-Event-ID。"""
    lines = []
    if entry.get("level") != "PING":
        lines.append(f"id: {entry['id']}")
    lines.append("event: log")
    lines.append(f"data: {json.dumps(entry, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


@router.get("/logs/stream")
async def stream_logs(request: Request, once: bool = False) -> StreamingResponse:
    """实时日志推送：先回放内存缓存的最近日志，再持续推送新日志。

    once=true 时只回放快照后立即关闭，供只需要历史日志的调用方使用。
    心跳以 PING 级别下发，前端据此维持连接而不渲染空行。
    EventSource 断线重连时自动携带 Last-Event-ID 头，
    服务端据此只补发遗漏的日志，不重复推送已收到的条目。
    """
    broker = request.app.state.log_broker
    last_event_id = request.headers.get("last-event-id", "")
    since_id = int(last_event_id) if last_event_id.isdigit() else None

    async def stream():
        if once:
            for entry in broker.snapshot():
                yield _sse_frame(entry)
            return
        async for entry in broker.stream(since_id=since_id):
            yield _sse_frame(entry)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
