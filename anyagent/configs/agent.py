"""Independent model connection and LangChain application settings."""

from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator

from anyagent.configs.base import BaseSettings


class ModelSettings(BaseSettings):
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    api_key: SecretStr = SecretStr("")
    temperature: float = Field(default=0.7, ge=0, le=2)
    timeout_seconds: int = Field(default=60, ge=1, le=600, strict=True)

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
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_enabled_model(self) -> "ModelSettings":
        if self.enabled and (
            not self.model.strip() or not self.api_key.get_secret_value().strip()
        ):
            raise ValueError("Enabled models require a model name and API key")
        return self


class LangChainSettings(BaseSettings):
    system_prompt: str = (
        "You are a helpful assistant. Use the calculate tool for arithmetic."
    )
    max_steps: int = Field(default=12, ge=2, le=100, strict=True)
    max_sessions: int = Field(default=64, ge=1, le=10000, strict=True)
    max_history_messages: int = Field(default=40, ge=2, le=200, strict=True)
    max_concurrent_runs: int = Field(default=4, ge=1, le=64, strict=True)
    run_timeout_seconds: int = Field(default=120, ge=1, le=1200, strict=True)
