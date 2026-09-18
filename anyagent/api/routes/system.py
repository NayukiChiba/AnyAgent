"""Expose the explicitly supplied process lifecycle capability."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from anyagent.api.routes.settings import ensure_same_origin

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("")
async def system_status(request: Request) -> JSONResponse:
    controller = request.app.state.restart_controller
    # Only public readiness metadata is readable across ports after a port change.
    return JSONResponse(
        {
            "instance_id": request.app.state.instance_id,
            "restart_available": controller is not None,
            "restarting": controller.requested if controller else False,
            "ready": request.app.state.ready,
        },
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
    )


@router.post("/restart", status_code=202)
async def restart(request: Request, background: BackgroundTasks) -> dict:
    ensure_same_origin(request)
    controller = request.app.state.restart_controller
    if controller is None:
        raise HTTPException(
            503,
            detail={"message": "当前启动方式不支持网页重启，请通过 main.py 启动服务"},
        )
    try:
        port = controller.request()
    except (OSError, ValueError):
        raise HTTPException(
            503,
            detail={
                "message": "无法读取重启配置，请检查设置和配置目录权限；当前服务继续运行"
            },
        ) from None
    except RuntimeError:
        raise HTTPException(
            409, detail={"message": "服务正在重启，请等待完成"}
        ) from None
    background.add_task(controller.stop_server)
    return {
        "message": "正在重启服务，内存会话将清空",
        "instance_id": controller.instance_id,
        "port": port,
    }
