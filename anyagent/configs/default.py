"""Default configuration values and exclusive JSON creation."""

import json
from pathlib import Path

from anyagent.configs import paths

DEFAULT_CMD_CONFIG = {
    "paths": {"data_dir": paths.as_project_relative(paths.get_data_dir())},
    "server": {"host": "127.0.0.1", "port": 8000},
}
DEFAULT_LOGGING_CONFIG = {
    "level": "INFO",
    "file_path": paths.as_project_relative(paths.get_log_path()),
    "max_bytes": 10485760,
    "backup_count": 5,
}
DEFAULT_CONFIGS = {
    "cmd_config": DEFAULT_CMD_CONFIG,
    "logging_config": DEFAULT_LOGGING_CONFIG,
}

DEFAULT_MODEL_CONFIG = {
    "enabled": False,
    "base_url": "https://api.openai.com/v1",
    "model": "",
    "api_key": "",
    "temperature": 0.7,
    "timeout_seconds": 60,
}
DEFAULT_LANGCHAIN_CONFIG = {
    "system_prompt": "You are a helpful assistant. Use the calculate tool for arithmetic.",
    "max_steps": 12,
    "max_sessions": 64,
    "max_history_messages": 40,
    "max_concurrent_runs": 4,
    "run_timeout_seconds": 120,
}
DEFAULT_CONFIGS.update(
    model_config=DEFAULT_MODEL_CONFIG, langchain_config=DEFAULT_LANGCHAIN_CONFIG
)


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
    path = paths.get_config_path(name)
    values = DEFAULT_CONFIGS[name] if values is None else values
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump(values, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return path
