"""Load and validate the current runtime JSON configuration."""

import json
import logging
import time
from pathlib import Path

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


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: PathSettings
    server: ServerSettings


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

    return Config(paths=PathSettings(data_dir=data_dir), server=config.server)
