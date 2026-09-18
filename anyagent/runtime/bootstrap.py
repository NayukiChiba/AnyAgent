from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from anyagent.adapters.runners.langchain.runner import LangChainRunnerFactory
from anyagent.api.app import build_app
from anyagent.api.frontend import install_frontend
from anyagent.configs import (
    config,
    load_frontend_config,
    load_langchain_config,
    load_model_config,
    paths,
)
from anyagent.configs.agent import LangChainSettings
from anyagent.core.ports.chat import RunnerFactory
from anyagent.core.services.chat import ChatService
from anyagent.infrastructure.memory.sessions import MemorySessionRepository
from anyagent.utils.logger import logger


def create_app(
    *,
    runner_factory: RunnerFactory | None = None,
    agent_settings: LangChainSettings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config.paths.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.data_dir = config.paths.data_dir
        app.state.config = config
        settings = agent_settings or load_langchain_config()
        load_model_config()
        load_frontend_config()
        repository = MemorySessionRepository(max_sessions=settings.max_sessions)
        app.state.chat_service = ChatService(
            repository,
            runner_factory or LangChainRunnerFactory(settings),
            timeout_seconds=settings.run_timeout_seconds,
            max_history_messages=settings.max_history_messages,
            max_concurrent_runs=settings.max_concurrent_runs,
            max_input_chars=settings.max_input_chars,
            max_output_chars=settings.max_output_chars,
            max_event_chars=settings.max_event_chars,
            cleanup_timeout_seconds=settings.cleanup_timeout_seconds,
        )

        def agent_info() -> dict:
            connection = load_model_config()
            return {
                "runner": "langchain",
                "configured": connection.enabled,
                "model": connection.model,
                "base_url": connection.base_url,
                "streaming": connection.streaming,
                "limits": {"max_input_chars": settings.max_input_chars},
                "frontend": load_frontend_config().model_dump(),
                "storage": "memory",
                "transports": ["http", "websocket", "sse"],
                "tools": ["calculate"],
            }

        app.state.agent_info = agent_info
        app.state.ready = True
        logger.info("Application ready")
        try:
            yield
        finally:
            app.state.ready = False
            await app.state.chat_service.shutdown()
            logger.info("Application shutdown complete")

    app = build_app(lifespan=lifespan)
    install_frontend(
        app,
        index_file=paths.get_frontend_index_path(),
        assets_dir=paths.get_frontend_assets_dir(),
    )
    return app
