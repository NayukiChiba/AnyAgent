"""Centralized configuration loading and path resolution."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class PathSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: PathSettings
    server: ServerSettings


def load_settings(
    config_path: str | Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> Settings:
    """Load startup settings and resolve paths without creating runtime files.

    Args:
        config_path: Optional TOML file; relative filenames use the project root.
        host: Optional command-line override for the configured server host.
        port: Optional command-line override for the configured server port.

    Returns:
        Validated settings with an absolute runtime data path.

    Raises:
        OSError: The configuration file cannot be read.
        ValueError: Settings are invalid or the data path leaves the project root.
    """
    project_root = Path(__file__).resolve().parents[3]
    path = Path(config_path) if config_path is not None else Path("configs/app.toml")
    if not path.is_absolute():
        path = project_root / path
    with path.open("rb") as file:
        values = tomllib.load(file)

    settings = Settings.model_validate(values)
    server = ServerSettings(
        host=host if host is not None else settings.server.host,
        port=port if port is not None else settings.server.port,
    )
    data_dir = (project_root / settings.paths.data_dir).resolve()
    if data_dir == project_root or not data_dir.is_relative_to(project_root):
        raise ValueError("paths.data_dir must be a directory inside the project root")
    return Settings(paths=PathSettings(data_dir=data_dir), server=server)
