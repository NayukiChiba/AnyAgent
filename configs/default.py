"""Default configuration values and centralized runtime configuration paths."""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIGS_DIR = DATA_DIR / "configs"
LEGACY_CONFIG_FILE = DATA_DIR / "config.json"
LOGS_DIR = DATA_DIR / "logs"

DEFAULT_CMD_CONFIG = {
    "paths": {"data_dir": "data"},
    "server": {"host": "127.0.0.1", "port": 8000},
}
DEFAULT_LOGGING_CONFIG = {
    "level": "INFO",
    "file_path": "data/logs/anyagent.log",
    "max_bytes": 10485760,
    "backup_count": 5,
}
DEFAULT_CONFIGS = {
    "cmd_config": DEFAULT_CMD_CONFIG,
    "logging_config": DEFAULT_LOGGING_CONFIG,
}


def get_config_path(name: str) -> Path:
    """Resolve a configuration name to a JSON file under data/configs.

    Args:
        name: Lowercase configuration name without an extension or directories.

    Returns:
        The configuration filename.

    Raises:
        ValueError: The name or resolved path leaves the configuration directory.
    """
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(
            "Configuration names must use lowercase letters, digits and underscores"
        )
    path = CONFIGS_DIR / f"{name}.json"
    if not path.resolve().is_relative_to(CONFIGS_DIR.resolve()):
        raise ValueError("Configuration files must stay inside data/configs")
    return path


def create_default_config(name: str = "cmd_config", values: dict | None = None) -> Path:
    """Create one default configuration without overwriting an existing file.

    Args:
        name: Configuration name without its JSON extension.
        values: Defaults for this file; omitted for built-in configuration types.

    Returns:
        The runtime configuration filename.

    Raises:
        OSError: The directory or configuration file cannot be created.
        ValueError: The configuration name is invalid.
        KeyError: An unknown configuration name has no supplied defaults.
    """
    path = get_config_path(name)
    values = DEFAULT_CONFIGS[name] if values is None else values
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump(values, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return path
