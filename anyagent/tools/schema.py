"""Function calling tool schema with construction-time validation."""

import jsonschema
from pydantic import Field, model_validator
from pydantic.dataclasses import dataclass


@dataclass
class ToolSchema:
    """JSON Schema description of a callable tool."""

    name: str
    description: str
    parameters: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_parameters(self) -> "ToolSchema":
        jsonschema.validate(
            self.parameters,
            jsonschema.Draft202012Validator.META_SCHEMA,
        )
        return self
