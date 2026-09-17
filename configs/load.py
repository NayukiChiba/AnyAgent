"""Load independent runtime JSON configurations and migrate legacy settings."""

import json
import logging
import time
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import default

logger = logging.getLogger(__name__)
Model = TypeVar("Model", bound=BaseModel)


class PathSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path

    @field_validator("data_dir")
    @classmethod
    def resolve_data_dir(cls, value: Path) -> Path:
        path = (default.PROJECT_ROOT / value).resolve()
        if not path.is_relative_to(default.DATA_DIR.resolve()):
            raise ValueError("paths.data_dir must stay inside the data directory")
        return path


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = (
        default.DEFAULT_LOGGING_CONFIG["level"]
    )
    file_path: Path = default.DEFAULT_LOGGING_CONFIG["file_path"]
    max_bytes: int = Field(
        default.DEFAULT_LOGGING_CONFIG["max_bytes"], ge=1, strict=True
    )
    backup_count: int = Field(
        default.DEFAULT_LOGGING_CONFIG["backup_count"], ge=1, strict=True
    )

    @field_validator("file_path")
    @classmethod
    def resolve_log_path(cls, value: Path) -> Path:
        path = (default.PROJECT_ROOT / value).resolve()
        if path == default.LOGS_DIR.resolve() or not path.is_relative_to(
            default.LOGS_DIR.resolve()
        ):
            raise ValueError("Logging files must stay inside data/logs")
        return path


class CmdConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: PathSettings
    server: ServerSettings


def _backup_config(path: Path) -> Path:
    default.CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    backup = default.CONFIGS_DIR / f"{path.name}.{time.time_ns()}.bak"
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
    path = default.get_config_path(name)
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
    legacy = default.LEGACY_CONFIG_FILE
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
        if not default.get_config_path("cmd_config").exists():
            CmdConfig.model_validate(cmd_values)
            pending.append(("cmd_config", cmd_values))
        if not default.get_config_path("logging_config").exists():
            LoggingSettings.model_validate(logging_values)
            pending.append(("logging_config", logging_values))
    except ValueError:
        _backup_config(legacy)
        return
    for name, contents in pending:
        default.create_default_config(name, contents)
    _backup_config(legacy)
