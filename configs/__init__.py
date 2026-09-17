"""Shared, independently loaded configurations under data/configs."""

from . import paths
from .load import (
    CmdConfig,
    LoggingSettings,
    ServerSettings,
    load_cmd_config,
    load_config,
    load_logging_config,
    migrate_legacy_config,
)

migrate_legacy_config()
cmd_config = load_cmd_config()
logging_config = load_logging_config()
config = cmd_config

__all__ = [
    "CmdConfig",
    "LoggingSettings",
    "ServerSettings",
    "cmd_config",
    "config",
    "load_cmd_config",
    "load_config",
    "load_logging_config",
    "logging_config",
    "paths",
]
