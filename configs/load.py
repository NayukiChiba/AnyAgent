"""Load and validate the current runtime JSON configuration."""

import json
import logging
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import default

logger = logging.getLogger(__name__)


class PathSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = (
        default.DEFAULT_CONFIG["logging"]["level"]
    )
    file_path: Path = default.DEFAULT_CONFIG["logging"]["file_path"]
    max_bytes: int = Field(
        default.DEFAULT_CONFIG["logging"]["max_bytes"], ge=1, strict=True
    )
    backup_count: int = Field(
        default.DEFAULT_CONFIG["logging"]["backup_count"], ge=1, strict=True
    )


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: PathSettings
    server: ServerSettings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def load_config() -> Config:
    """Load data/config.json, creating defaults if its contents cannot be loaded.

    Returns:
        Validated configuration with an absolute data path.

    Raises:
        OSError: Configuration cannot be read, backed up, or created.
    """
    try:
        with default.CONFIG_FILE.open(encoding="utf-8-sig") as file:
            config = Config.model_validate(json.load(file))
        data_dir = (default.PROJECT_ROOT / config.paths.data_dir).resolve()
        if not data_dir.is_relative_to(default.DATA_DIR.resolve()):
            raise ValueError("paths.data_dir must stay inside the data directory")
        log_path = (default.PROJECT_ROOT / config.logging.file_path).resolve()
        if log_path == default.LOGS_DIR.resolve() or not log_path.is_relative_to(
            default.LOGS_DIR.resolve()
        ):
            raise ValueError("logging.file_path must be a file inside data/logs")
    except FileNotFoundError:
        default.create_default_config()
        return load_config()
    except ValueError:
        backup_path = default.CONFIG_FILE.with_name(
            f"{default.CONFIG_FILE.name}.{time.time_ns()}.bak"
        )
        default.CONFIG_FILE.rename(backup_path)
        logger.warning(
            "Invalid configuration backed up to %s; restoring defaults", backup_path
        )
        default.create_default_config()
        return load_config()

    return Config(
        paths=PathSettings(data_dir=data_dir),
        server=config.server,
        logging=config.logging.model_copy(update={"file_path": log_path}),
    )
