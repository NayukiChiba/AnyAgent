from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from configs import config

from .logger import logger


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config.paths.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.data_dir = config.paths.data_dir
        app.state.config = config
        app.state.ready = True
        logger.info("Application ready")
        try:
            yield
        finally:
            app.state.ready = False
            logger.info("Application shutdown complete")

    app = FastAPI(
        title="AnyAgent",
        description="An application platform for multiple Agent Runners.",
        version=version("anyagent"),
        lifespan=lifespan,
    )
    app.state.ready = False

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/health/ready", tags=["health"], responses={503: {"description": "Not ready"}}
    )
    async def ready(request: Request) -> JSONResponse:
        is_ready = request.app.state.ready
        return JSONResponse(
            {"status": "ready" if is_ready else "not_ready"},
            status_code=200 if is_ready else 503,
        )

    return app
