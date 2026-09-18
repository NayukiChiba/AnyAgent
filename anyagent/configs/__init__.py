"""Shared, independently loaded configurations under data/configs."""

from anyagent.configs import paths
from anyagent.configs.agent import LangChainSettings, ModelSettings
from anyagent.configs.base import BaseSettings
from anyagent.configs.load import (
    load_cmd_config,
    load_config,
    load_langchain_config,
    load_logging_config,
    load_model_config,
    migrate_legacy_config,
)
from anyagent.configs.models import CmdConfig, LoggingSettings, ServerSettings

migrate_legacy_config()
cmd_config = load_cmd_config()
logging_config = load_logging_config()
config = cmd_config

__all__ = [
    "BaseSettings",
    "LangChainSettings",
    "ModelSettings",
    "CmdConfig",
    "LoggingSettings",
    "ServerSettings",
    "cmd_config",
    "config",
    "load_cmd_config",
    "load_config",
    "load_logging_config",
    "load_model_config",
    "load_langchain_config",
    "logging_config",
    "paths",
]
