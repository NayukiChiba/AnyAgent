"""Independent model connection and LangChain application settings."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator

from anyagent.configs.base import BaseSettings
from anyagent.configs.default import (
    DEFAULT_FRONTEND_CONFIG,
    DEFAULT_LANGCHAIN_CONFIG,
    DEFAULT_MODEL_CONFIG,
)


class ModelSettings(BaseSettings):
    enabled: bool = DEFAULT_MODEL_CONFIG["enabled"]
    streaming: bool = Field(default=DEFAULT_MODEL_CONFIG["streaming"], strict=True)
    base_url: str = DEFAULT_MODEL_CONFIG["base_url"]
    model: str = DEFAULT_MODEL_CONFIG["model"]
    api_key: SecretStr = SecretStr(DEFAULT_MODEL_CONFIG["api_key"])
    temperature: float = Field(default=DEFAULT_MODEL_CONFIG["temperature"], ge=0, le=2)
    timeout_seconds: int = Field(
        default=DEFAULT_MODEL_CONFIG["timeout_seconds"], ge=1, le=600, strict=True
    )
    max_retries: int = Field(
        default=DEFAULT_MODEL_CONFIG["max_retries"], ge=0, le=5, strict=True
    )
    stream_usage: bool = Field(
        default=DEFAULT_MODEL_CONFIG["stream_usage"], strict=True
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Model base URL must be an HTTP or HTTPS address")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "Model base URL cannot contain credentials, query or fragment"
            )
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Model URL port must be between 1 and 65535")
        if value.rstrip("/").endswith("/chat/completions"):
            raise ValueError("Model URL must be a base URL, not a completion endpoint")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_enabled_model(self) -> "ModelSettings":
        if self.enabled and (
            not self.model.strip() or not self.api_key.get_secret_value().strip()
        ):
            raise ValueError("Enabled models require a model name and API key")
        return self


class LangChainSettings(BaseSettings):
    system_prompt: str = DEFAULT_LANGCHAIN_CONFIG["system_prompt"]
    max_steps: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["max_steps"], ge=2, le=100, strict=True
    )
    max_sessions: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["max_sessions"], ge=1, le=10000, strict=True
    )
    max_history_messages: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["max_history_messages"],
        ge=2,
        le=200,
        strict=True,
    )
    max_concurrent_runs: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["max_concurrent_runs"],
        ge=1,
        le=64,
        strict=True,
    )
    run_timeout_seconds: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["run_timeout_seconds"],
        ge=1,
        le=1200,
        strict=True,
    )
    max_input_chars: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["max_input_chars"],
        ge=1,
        le=100000,
        strict=True,
    )
    max_output_chars: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["max_output_chars"],
        ge=1,
        le=1000000,
        strict=True,
    )
    max_event_chars: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["max_event_chars"],
        ge=1,
        le=2000000,
        strict=True,
    )
    cleanup_timeout_seconds: int = Field(
        default=DEFAULT_LANGCHAIN_CONFIG["cleanup_timeout_seconds"],
        ge=1,
        le=60,
        strict=True,
    )


class FrontendSettings(BaseSettings):
    default_transport: Literal["websocket", "http"] = DEFAULT_FRONTEND_CONFIG[
        "default_transport"
    ]
    cancel_timeout_ms: int = Field(
        default=DEFAULT_FRONTEND_CONFIG["cancel_timeout_ms"],
        ge=100,
        le=30000,
        strict=True,
    )

    restart_poll_interval_ms: int = Field(
        default=DEFAULT_FRONTEND_CONFIG["restart_poll_interval_ms"],
        ge=250,
        le=10000,
        strict=True,
    )
    restart_wait_timeout_seconds: int = Field(
        default=DEFAULT_FRONTEND_CONFIG["restart_wait_timeout_seconds"],
        ge=10,
        le=600,
        strict=True,
    )
