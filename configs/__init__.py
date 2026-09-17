"""Shared configuration loaded from the project's data directory."""

from .load import Config, ServerSettings, load_config

config = load_config()

__all__ = ["Config", "ServerSettings", "config", "load_config"]
