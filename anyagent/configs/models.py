"""Typed schemas for independently loaded JSON configurations."""

from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from anyagent.configs import default, paths
from anyagent.configs.base import BaseSettings


class PathSettings(BaseSettings):
    data_dir: Path

    @field_validator("data_dir")
    @classmethod
    def resolve_data_dir(cls, value: Path) -> Path:
        return paths.resolve_data_path(value)


class ServerSettings(BaseSettings):
    model_config = ConfigDict(strict=True)

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class LoggingSettings(BaseSettings):
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
        return paths.get_log_path(value)


class CmdConfig(BaseSettings):
    paths: PathSettings
    server: ServerSettings
