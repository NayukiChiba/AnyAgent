import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI

from anyagent.adapters.runners.coze.runner import CozeRunnerFactory
from anyagent.adapters.runners.deerflow.runner import DeerFlowRunnerFactory
from anyagent.adapters.runners.dify.runner import DifyRunnerFactory
from anyagent.adapters.runners.langchain.runner import LangChainRunnerFactory
from anyagent.adapters.runners.langgraph.runner import LangGraphRunnerFactory
from anyagent.adapters.runners.loop.runner import LoopRunnerFactory
from anyagent.adapters.runners.pi.runner import PiRunnerFactory
from anyagent.api.app import build_app
from anyagent.api.frontend import install_frontend
from anyagent.configs import (
    config,
    load_database_config,
    load_frontend_config,
    load_langchain_config,
    load_model_config,
    paths,
)
from anyagent.configs.agent import LangChainSettings
from anyagent.configs.management import ConfigurationManager
from anyagent.core.domain.chat import ChatError
from anyagent.core.ports.chat import RunnerFactory
from anyagent.core.ports.model import ChatClient
from anyagent.core.services.chat import ChatService
from anyagent.infrastructure.openai.client import OpenAIClient
from anyagent.infrastructure.sqlite.sessions import SQLiteSessionRepository
from anyagent.runtime.restart import RestartController
from anyagent.tools import build_tool_set
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


def _openai_client_loader() -> ChatClient:
    """每次调用重读模型连接配置并创建客户端，支撑连接热更新。"""
    connection = load_model_config()
    if not connection.enabled:
        raise ChatError(
            "model_not_configured",
            "请在 data/configs/model_config.json 配置并启用模型",
        )
    return OpenAIClient(connection)


def _build_factory(
    settings: LangChainSettings,
    tool_set,
) -> RunnerFactory:
    """按配置的 runner 名称装配对应 factory。"""
    match settings.runner:
        case "langgraph":
            return LangGraphRunnerFactory(settings, tool_set)
        case "loop":
            return LoopRunnerFactory(
                _openai_client_loader,
                tool_set,
                system_prompt=settings.system_prompt,
                max_steps=settings.max_steps,
            )
        case "dify":
            return DifyRunnerFactory()
        case "coze":
            return CozeRunnerFactory(settings.coze_bot_id)
        case "pi":
            return PiRunnerFactory(_openai_client_loader)
        case "deerflow":
            return DeerFlowRunnerFactory()
        case _:
            return LangChainRunnerFactory(settings, tool_set)


def create_app(
    *,
    runner_factory: RunnerFactory | None = None,
    agent_settings: LangChainSettings | None = None,
    restart_controller: RestartController | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config.paths.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.data_dir = config.paths.data_dir
        app.state.config = config
        settings = agent_settings or load_langchain_config()
        load_model_config()
        load_frontend_config()
        app.state.configuration_manager = ConfigurationManager()
        tool_set = build_tool_set()
        factory = runner_factory or _build_factory(settings, tool_set)
        database = load_database_config()
        repository = SQLiteSessionRepository(
            database.file_path,
            max_sessions=settings.max_sessions,
            busy_timeout_seconds=database.busy_timeout_seconds,
        )
        async with AsyncExitStack() as resources:
            resources.push_async_callback(repository.aclose)
            await repository.initialize()
            logger.info("Session storage connected: backend=sqlite")
            logger.debug(
                "Agent limits loaded: max_sessions=%d max_history_messages=%d max_concurrent_runs=%d",
                settings.max_sessions,
                settings.max_history_messages,
                settings.max_concurrent_runs,
            )
            app.state.chat_service = ChatService(
                repository,
                factory,
                timeout_seconds=settings.run_timeout_seconds,
                max_history_messages=settings.max_history_messages,
                max_concurrent_runs=settings.max_concurrent_runs,
                max_input_chars=settings.max_input_chars,
                max_output_chars=settings.max_output_chars,
                max_event_chars=settings.max_event_chars,
                cleanup_timeout_seconds=settings.cleanup_timeout_seconds,
            )

            probe_lock = asyncio.Lock()

            async def test_model() -> None:
                if probe_lock.locked():
                    raise ChatError(
                        "probe_busy", "已有模型连接测试正在进行，请稍后重试"
                    )
                async with probe_lock:
                    connection = load_model_config()
                    if not connection.enabled:
                        raise ChatError(
                            "model_not_configured",
                            "请在 data/configs/model_config.json 配置并启用模型",
                        )
                    client = OpenAIClient(connection)
                    try:
                        await client.test()
                    finally:
                        await client.aclose()

            app.state.test_model = test_model

            def agent_info() -> dict:
                connection = load_model_config()
                return {
                    "runner": settings.runner,
                    "configured": connection.enabled,
                    "model": connection.model,
                    "base_url": connection.base_url,
                    "streaming": connection.streaming,
                    "limits": {"max_input_chars": settings.max_input_chars},
                    "frontend": load_frontend_config().model_dump(),
                    "storage": "sqlite",
                    "transports": ["http", "websocket", "sse"],
                    "tools": [t.name for t in tool_set.tools],
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
    app.state.restart_controller = restart_controller
    app.state.instance_id = (
        restart_controller.instance_id if restart_controller else uuid4().hex
    )
    install_frontend(
        app,
        index_file=paths.get_frontend_index_path(),
        assets_dir=paths.get_frontend_assets_dir(),
    )
    return app
