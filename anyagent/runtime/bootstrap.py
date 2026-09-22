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
from anyagent.configs.profiles import ProfileStore, RunnerProfile
from anyagent.core.domain.chat import ChatError
from anyagent.core.ports.chat import AgentRunner, RunnerFactory
from anyagent.core.services.chat import ChatService
from anyagent.infrastructure.openai.client import OpenAIClient
from anyagent.infrastructure.sqlite.sessions import SQLiteSessionRepository
from anyagent.runtime.restart import RestartController
from anyagent.tools import build_tool_set
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)

# 支持连接测试的引擎（走 OpenAI 兼容协议）
TESTABLE_TYPES = ("langchain", "langgraph", "loop", "pi")


def _runner_for(
    profile: RunnerProfile,
    settings: LangChainSettings,
    tool_set,
) -> RunnerFactory:
    """按档案类型构建对应 runner；档案即连接，互不共享状态。"""
    model_loader = lambda: profile.as_model_settings()  # noqa: E731
    client_loader = lambda: OpenAIClient(profile.as_model_settings())  # noqa: E731
    match profile.type:
        case "langgraph":
            factory = LangGraphRunnerFactory(
                settings, tool_set, model_loader=model_loader
            )
        case "loop":
            factory = LoopRunnerFactory(
                client_loader,
                tool_set,
                system_prompt=settings.system_prompt,
                max_steps=settings.max_steps,
            )
        case "dify":
            factory = DifyRunnerFactory(model_loader=model_loader)
        case "coze":
            factory = CozeRunnerFactory(profile.bot_id, model_loader=model_loader)
        case "pi":
            factory = PiRunnerFactory(client_loader)
        case "deerflow":
            factory = DeerFlowRunnerFactory(model_loader=model_loader)
        case _:
            factory = LangChainRunnerFactory(
                settings, tool_set, model_loader=model_loader
            )
    return factory


class ProfileRunnerFactory:
    """每次创建时读取活动档案并按其类型委托对应工厂，支撑热切换。"""

    def __init__(self, store: ProfileStore, settings: LangChainSettings, tool_set):
        self._store = store
        self._settings = settings
        self._tool_set = tool_set

    async def create(self) -> AgentRunner:
        profile = self._store.active()
        if profile is None:
            raise ChatError(
                "model_not_configured",
                "请先在 Runner 页面创建并启用一个 Runner",
            )
        factory = _runner_for(profile, self._settings, self._tool_set)
        return await factory.create()


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
        profile_store = ProfileStore()
        app.state.profile_store = profile_store
        tool_set = build_tool_set()
        app.state.tool_set = tool_set
        factory = runner_factory or ProfileRunnerFactory(
            profile_store, settings, tool_set
        )
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
                    profile = profile_store.active()
                    if profile is None:
                        raise ChatError(
                            "model_not_configured",
                            "请先创建并启用一个 Runner",
                        )
                    if profile.type not in TESTABLE_TYPES:
                        raise ChatError(
                            "unsupported",
                            "该平台引擎由服务端托管，无需连接测试",
                        )
                    client = OpenAIClient(profile.as_model_settings())
                    try:
                        await client.test()
                    finally:
                        await client.aclose()

            app.state.test_model = test_model

            def agent_info() -> dict:
                profile = profile_store.active()
                return {
                    "runner": profile.type if profile else None,
                    "profile": (
                        {
                            "id": profile.id,
                            "name": profile.name,
                            "type": profile.type,
                        }
                        if profile
                        else None
                    ),
                    "configured": profile is not None,
                    "model": profile.model if profile else "",
                    "base_url": profile.base_url if profile else "",
                    "streaming": profile.streaming if profile else False,
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
