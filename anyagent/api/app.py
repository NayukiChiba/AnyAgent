"""Build the HTTP application with its supplied resource lifecycle."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from anyagent import __version__
from anyagent.api.routes.health import router as health_router


def build_app(
    *, lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]]
) -> FastAPI:
    app = FastAPI(
        title="AnyAgent",
        description="An application platform for multiple Agent Runners.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.ready = False
    app.include_router(health_router)
    return app
