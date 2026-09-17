"""Shared validation policy for project configuration values."""

from pydantic import BaseModel, ConfigDict


class BaseSettings(BaseModel):
    """Validate settings values without automatic environment or file loading.

    Fields cannot be reassigned; mutable collections are not deeply frozen.
    JSON loading and recovery belong to the configuration loader.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
