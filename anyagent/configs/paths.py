"""Centralized runtime paths and containment checks."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CONFIGS_DIR = DATA_DIR / "configs"
LOGS_DIR = DATA_DIR / "logs"
LEGACY_CONFIG_FILE = DATA_DIR / "config.json"


def get_frontend_dist_dir() -> Path:
    """Return compiled frontend assets, which are source build artifacts."""
    return get_project_root() / "frontend" / "dist"


def get_frontend_index_path() -> Path:
    return get_frontend_dist_dir() / "index.html"


def get_frontend_assets_dir() -> Path:
    return get_frontend_dist_dir() / "assets"


def get_project_root() -> Path:
    """Return the absolute project root, independently of the working directory."""
    return PROJECT_ROOT.resolve()


def get_data_dir() -> Path:
    """Return the absolute runtime data directory."""
    return DATA_DIR.resolve()


def as_project_relative(path: Path) -> str:
    """Serialize a project path for portable JSON configuration values."""
    return path.relative_to(get_project_root()).as_posix()


def resolve_data_path(value: str | Path) -> Path:
    """Resolve a project-relative path within the runtime data directory.

    Args:
        value: A project-relative or absolute runtime path.

    Returns:
        The validated absolute path; no directories are created.

    Raises:
        ValueError: The path or its symlink target leaves the data directory.
    """
    path = (get_project_root() / value).resolve()
    if not path.is_relative_to(get_data_dir()):
        raise ValueError("Runtime paths must stay inside the data directory")
    return path


def get_configs_dir() -> Path:
    """Return the configuration directory, rejecting symlinks outside data."""
    return resolve_data_path(CONFIGS_DIR)


def get_logs_dir() -> Path:
    """Return the logging directory, rejecting symlinks outside data."""
    return resolve_data_path(LOGS_DIR)


def get_log_path(value: str | Path | None = None) -> Path:
    """Resolve a configured log filename or return the default log filename.

    Args:
        value: A project-relative or absolute filename; None selects the default.

    Returns:
        The validated absolute log filename.

    Raises:
        ValueError: The path is the log directory or leaves it after resolution.
    """
    directory = get_logs_dir()
    path = resolve_data_path(directory / "anyagent.log" if value is None else value)
    if path == directory or not path.is_relative_to(directory):
        raise ValueError("Logging files must stay inside the logging directory")
    return path


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
    directory = get_configs_dir()
    path = directory / f"{name}.json"
    if not path.resolve().is_relative_to(directory):
        raise ValueError(
            "Configuration files must stay inside the configuration directory"
        )
    return path


def get_legacy_config_path() -> Path:
    """Return the former single configuration path within the data directory."""
    resolve_data_path(LEGACY_CONFIG_FILE)
    return LEGACY_CONFIG_FILE


def get_config_backup_path(path: Path, timestamp: int) -> Path:
    """Build a configuration backup filename inside the configuration directory.

    Args:
        path: The original configuration filename.
        timestamp: The nanosecond timestamp used to distinguish backups.

    Returns:
        The backup filename, without creating or moving any files.

    Raises:
        ValueError: The resolved backup leaves the configuration directory.
    """
    directory = get_configs_dir()
    backup = directory / f"{path.name}.{timestamp}.bak"
    if not backup.resolve().is_relative_to(directory):
        raise ValueError(
            "Configuration backups must stay inside the configuration directory"
        )
    return backup
