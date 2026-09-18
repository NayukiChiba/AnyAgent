"""Typed schemas for independently loaded JSON configurations."""

import ipaddress
import re
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
        return paths.resolve_data_directory(value)


class ServerSettings(BaseSettings):
    model_config = ConfigDict(strict=True)

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            labels = value.rstrip(".").split(".")
            if len(value) > 253 or not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in labels
            ):
                raise ValueError(
                    "Server host must be an IP address or hostname"
                ) from None
        return value


class LoggingSettings(BaseSettings):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = (
        default.DEFAULT_LOGGING_CONFIG["level"]
    )
    third_party_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = (
        default.DEFAULT_LOGGING_CONFIG["third_party_level"]
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


class DatabaseSettings(BaseSettings):
    file_path: Path = default.DEFAULT_DATABASE_CONFIG["file_path"]
    busy_timeout_seconds: int = Field(
        default=default.DEFAULT_DATABASE_CONFIG["busy_timeout_seconds"],
        ge=1,
        le=60,
        strict=True,
    )

    @field_validator("file_path")
    @classmethod
    def resolve_file_path(cls, value: Path) -> Path:
        return paths.get_database_path(value)
