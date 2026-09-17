from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from anyagent.api.app import build_app
from anyagent.configs import config
from anyagent.utils.logger import logger


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

    return build_app(lifespan=lifespan)
