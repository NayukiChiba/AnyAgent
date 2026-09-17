"""Default configuration values and runtime configuration creation."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "paths": {"data_dir": "data"},
    "server": {"host": "127.0.0.1", "port": 8000},
}


def create_default_config() -> Path:
    """Create the default JSON configuration without overwriting an existing file.

    Returns:
        The runtime configuration filename under the data directory.

    Raises:
        OSError: The directory or configuration file cannot be created.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("x", encoding="utf-8") as file:
        json.dump(DEFAULT_CONFIG, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return CONFIG_FILE
