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
from anyagent.configs.model_profiles import ModelProfile, ModelProfileStore
from anyagent.configs.profiles import MODEL_REQUIRED_TYPES, ProfileStore, RunnerProfile
from anyagent.core.domain.chat import ChatError
from anyagent.core.ports.chat import AgentRunner, RunnerFactory
from anyagent.core.services.chat import ChatService
from anyagent.infrastructure.openai.client import OpenAIClient
from anyagent.infrastructure.sqlite.sessions import SQLiteSessionRepository
from anyagent.runtime.restart import RestartController
from anyagent.tools import build_tool_set
from anyagent.utils.logbroker import broker as log_broker
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)

# 支持连接测试的引擎（走 OpenAI 兼容协议）
TESTABLE_TYPES = ("langchain", "langgraph", "loop", "pi")


def _resolve_model(
    profile: RunnerProfile, model_store: ModelProfileStore
) -> ModelProfile:
    """解析 Runner 引用的模型连接；引用失效或信息不全时给出可操作的提示。"""
    try:
        model = model_store.get(profile.model_id)
    except ChatError:
        raise ChatError(
            "model_missing",
            "该 Runner 引用的模型连接已被删除，请在 Runner 页面重新选择",
        ) from None
    if profile.type in MODEL_REQUIRED_TYPES and not model.model.strip():
        raise ChatError(
            "model_incomplete", "该模型连接未填写模型名称，请在模型页面补全"
        )
    return model


def _runner_for(
    profile: RunnerProfile,
    model: ModelProfile,
    settings: LangChainSettings,
    tool_set,
) -> RunnerFactory:
    """按档案类型构建对应 runner；连接信息来自引用的模型连接。"""
    # 远端平台引擎不填模型名，用引擎类型占位满足连接配置的校验
    model_loader = lambda: model.as_model_settings(profile.type)  # noqa: E731
    client_loader = lambda: OpenAIClient(model.as_model_settings(profile.type))  # noqa: E731
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

    def __init__(
        self,
        store: ProfileStore,
        model_store: ModelProfileStore,
        settings: LangChainSettings,
        tool_set,
    ):
        self._store = store
        self._model_store = model_store
        self._settings = settings
        self._tool_set = tool_set

    async def create(self) -> AgentRunner:
        profile = self._store.active()
        if profile is None:
            raise ChatError(
                "model_not_configured",
                "请先在 Runner 页面创建并启用一个 Runner",
            )
        model = _resolve_model(profile, self._model_store)
        factory = _runner_for(profile, model, self._settings, self._tool_set)
        return await factory.create()


def create_app(
    *,
    runner_factory: RunnerFactory | None = None,
    agent_settings: LangChainSettings | None = None,
    restart_controller: RestartController | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log_broker.attach_loop(asyncio.get_running_loop())
        app.state.log_broker = log_broker
        config.paths.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.data_dir = config.paths.data_dir
        app.state.config = config
        settings = agent_settings or load_langchain_config()
        load_model_config()
        load_frontend_config()
        app.state.configuration_manager = ConfigurationManager()
        model_store = ModelProfileStore()
        app.state.model_store = model_store
        profile_store = ProfileStore(model_store=model_store)
        app.state.profile_store = profile_store
        tool_set = build_tool_set()
        app.state.tool_set = tool_set
        factory = runner_factory or ProfileRunnerFactory(
            profile_store, model_store, settings, tool_set
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
                    model = _resolve_model(profile, model_store)
                    client = OpenAIClient(model.as_model_settings(profile.type))
                    try:
                        await client.test()
                    finally:
                        await client.aclose()

            app.state.test_model = test_model

            def agent_info() -> dict:
                profile = profile_store.active()
                model = None
                if profile is not None:
                    try:
                        model = _resolve_model(profile, model_store)
                    except ChatError:
                        model = None
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
                    "model_profile": (
                        {"id": model.id, "name": model.name} if model else None
                    ),
                    "configured": profile is not None and model is not None,
                    "model": model.model if model else "",
                    "base_url": model.base_url if model else "",
                    "streaming": model.streaming if model else False,
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
                log_broker.detach_loop()
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
