"""Build the HTTP application with its supplied resource lifecycle."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from anyagent import __version__
from anyagent.api.routes.chat import router as chat_router
from anyagent.api.routes.health import router as health_router
from anyagent.api.routes.settings import router as settings_router


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
    app.include_router(chat_router)
    app.include_router(settings_router)
    return app
