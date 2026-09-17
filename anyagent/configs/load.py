"""Load independent runtime JSON configurations and migrate legacy settings."""

import json
import logging
import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from anyagent.configs import default, paths
from anyagent.configs.models import CmdConfig, LoggingSettings

logger = logging.getLogger(__name__)
Model = TypeVar("Model", bound=BaseModel)


def _backup_config(path: Path) -> Path:
    backup = paths.get_config_backup_path(path, time.time_ns())
    backup.parent.mkdir(parents=True, exist_ok=True)
    path.rename(backup)
    logger.warning("Configuration backed up to %s", backup)
    return backup


def load_config(name: str, schema: type[Model], defaults: dict) -> Model:
    """Load one configuration, recovering only this file when its data is invalid.

    Args:
        name: Configuration name without its extension.
        schema: Validation model for this configuration type.
        defaults: Default JSON values used for missing or invalid files.

    Returns:
        The validated configuration object.

    Raises:
        OSError: Configuration cannot be read, backed up, or created.
        ValueError: The name or developer-supplied defaults are invalid.
    """
    path = paths.get_config_path(name)
    fallback = schema.model_validate(defaults)
    try:
        with path.open(encoding="utf-8-sig") as file:
            return schema.model_validate(json.load(file))
    except FileNotFoundError:
        default.create_default_config(name, defaults)
    except ValueError:
        _backup_config(path)
        default.create_default_config(name, defaults)
    return fallback


def load_cmd_config() -> CmdConfig:
    return load_config("cmd_config", CmdConfig, default.DEFAULT_CMD_CONFIG)


def load_logging_config() -> LoggingSettings:
    return load_config(
        "logging_config", LoggingSettings, default.DEFAULT_LOGGING_CONFIG
    )


def migrate_legacy_config() -> None:
    """Split legacy data/config.json without overwriting newer configuration files.

    Raises:
        OSError: The legacy file cannot be read, migrated, or backed up.
    """
    legacy = paths.get_legacy_config_path()
    if not legacy.exists():
        return
    try:
        with legacy.open(encoding="utf-8-sig") as file:
            values = json.load(file)
        if not isinstance(values, dict):
            raise ValueError("Legacy configuration must be an object")
        cmd_values = {key: value for key, value in values.items() if key != "logging"}
        logging_values = values.get("logging", default.DEFAULT_LOGGING_CONFIG)
        pending = []
        if not paths.get_config_path("cmd_config").exists():
            CmdConfig.model_validate(cmd_values)
            pending.append(("cmd_config", cmd_values))
        if not paths.get_config_path("logging_config").exists():
            LoggingSettings.model_validate(logging_values)
            pending.append(("logging_config", logging_values))
    except ValueError:
        _backup_config(legacy)
        return
    for name, contents in pending:
        default.create_default_config(name, contents)
    _backup_config(legacy)
