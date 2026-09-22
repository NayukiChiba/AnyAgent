"""运行统计与日志查看的只读接口。"""

from fastapi import APIRouter, Query, Request

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
