"""Service liveness and readiness HTTP endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", responses={503: {"description": "Not ready"}})
async def ready(request: Request) -> JSONResponse:
    is_ready = request.app.state.ready
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready"},
        status_code=200 if is_ready else 503,
    )
