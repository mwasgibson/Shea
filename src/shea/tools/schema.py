from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from shea.contracts.models import ToolRequest


class ArgumentType(Enum):
    """Supported argument types for tool schema validation."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    ANY = "any"

@dataclass(frozen=True)
class ArgumentSchema:
    """Schema definition for a single tool argument.

    Supports type checking, required/optional, default values, and
    custom validators for complex constraints.
    """

    name: str
    type: ArgumentType
    description: str = ""
    required: bool = True
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    enum: list[Any] | None = None
    custom_validator: Callable[[Any], bool] | None = None
    custom_validator_message: str = "Validation failed"

    def validate(self, value: Any) -> tuple[bool, str]:
        """Validate a value against this schema.

        Returns:
            tuple: (is_valid, error_message)
        """
        # Check required
        if value is None and self.required and self.default is None:
            return False, f"Argument '{self.name}' is required"

        # Use default if value is None
        if value is None and self.default is not None:
            value = self.default

        # Check type
        if not self._check_type(value):
            return False, f"Argument '{self.name}' must be of type {self.type.value}"

        # Check numeric bounds
        if self.type in (ArgumentType.INTEGER, ArgumentType.FLOAT):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"Argument '{self.name}' must be of type {self.type.value}"
            if self.min_value is not None and value < self.min_value:
                return False, f"Argument '{self.name}' must be >= {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"Argument '{self.name}' must be <= {self.max_value}"

        # Check string bounds
        if self.type == ArgumentType.STRING:
            if not isinstance(value, str):
                return False, f"Argument '{self.name}' must be of type {self.type.value}"
            if self.min_length is not None and len(value) < self.min_length:
                return False, f"Argument '{self.name}' must have length >= {self.min_length}"
            if self.max_length is not None and len(value) > self.max_length:
                return False, f"Argument '{self.name}' must have length <= {self.max_length}"
            if self.pattern is not None:
                import re
                if not re.match(self.pattern, value):
                    return False, f"Argument '{self.name}' must match pattern {self.pattern}"

        # Check enum
        if self.enum is not None and value not in self.enum:
            return False, f"Argument '{self.name}' must be one of {self.enum}"

        # Custom validator
        if self.custom_validator is not None and not self.custom_validator(value):
            return False, self.custom_validator_message

        return True, ""

    def _check_type(self, value: Any) -> bool:
        """Check if value matches the expected type."""
        if self.type == ArgumentType.ANY:
            return True
        if self.type == ArgumentType.STRING:
            return isinstance(value, str)
        if self.type == ArgumentType.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool)
        if self.type == ArgumentType.FLOAT:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if self.type == ArgumentType.BOOLEAN:
            return isinstance(value, bool)
        if self.type == ArgumentType.ARRAY:
            return isinstance(value, list)
        if self.type == ArgumentType.OBJECT:
            return isinstance(value, dict)
        return False

@dataclass(frozen=True)
class ToolSchema:
    """Complete schema definition for a tool.

    Includes argument schemas, required capabilities, and metadata
    for validation and documentation.
    """

    name: str
    description: str = ""
    arguments: dict[str, ArgumentSchema] = field(
        default_factory=lambda: dict[str, ArgumentSchema]()
    )
    required_capabilities: frozenset[str] = frozenset()
    baseline_risk: str = "UNKNOWN"
    isolation_required: bool = True
    audit_required: bool = True

    def __contains__(self, argument_name: str) -> bool:
        """Return whether an argument is defined by this schema."""
        return argument_name in self.arguments

    def validate_request(self, request: ToolRequest) -> tuple[bool, list[str]]:
        """Validate a ToolRequest against this schema.

        Returns:
            tuple: (is_valid, list_of_error_messages)
        """
        errors: list[str] = []

        # Check all required arguments are present
        for arg_name, schema in self.arguments.items():
            if schema.required:
                if arg_name not in request.arguments:
                    if schema.default is None:
                        errors.append(f"Missing required argument: {arg_name}")
                # Else: default will be used, no error

        # Check all provided arguments are valid
        for arg_name, value in request.arguments.items():
            if arg_name not in self.arguments:
                errors.append(f"Unknown argument: {arg_name}")
                continue

            schema = self.arguments[arg_name]
            is_valid, error_msg = schema.validate(value)
            if not is_valid:
                errors.append(error_msg)

        return len(errors) == 0, errors

    def get_validated_arguments(self, request: ToolRequest) -> dict[str, Any]:
        """Validate request and return arguments with defaults applied.

        Raises:
            ToolSchemaValidationError: If validation fails
        """
        is_valid, errors = self.validate_request(request)
        if not is_valid:
            raise ToolSchemaValidationError(self.name, errors)

        # Apply defaults
        validated_args = dict(request.arguments)
        for arg_name, schema in self.arguments.items():
            if arg_name not in validated_args and schema.default is not None:
                validated_args[arg_name] = schema.default

        return validated_args

class ToolSchemaValidationError(Exception):
    """Raised when tool argument validation fails."""

    def __init__(self, tool_name: str, errors: list[str]) -> None:
        self.tool_name = tool_name
        self.errors = errors
        super().__init__(
            f"Tool {tool_name!r} argument validation failed: {', '.join(errors)}"
        )

# Convenience functions for common schema patterns
def string_arg(
    name: str,
    description: str = "",
    required: bool = True,
    default: str | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    pattern: str | None = None,
) -> ArgumentSchema:
    """Create a string argument schema."""
    return ArgumentSchema(
        name=name,
        type=ArgumentType.STRING,
        description=description,
        required=required,
        default=default,
        min_length=min_length,
        max_length=max_length,
        pattern=pattern,
    )

def integer_arg(
    name: str,
    description: str = "",
    required: bool = True,
    default: int | None = None,
    min_value: int | None = None,
    max_value: int | None = None,
) -> ArgumentSchema:
    """Create an integer argument schema."""
    return ArgumentSchema(
        name=name,
        type=ArgumentType.INTEGER,
        description=description,
        required=required,
        default=default,
        min_value=min_value,
        max_value=max_value,
    )

def boolean_arg(
    name: str,
    description: str = "",
    required: bool = True,
    default: bool | None = None,
) -> ArgumentSchema:
    """Create a boolean argument schema."""
    return ArgumentSchema(
        name=name,
        type=ArgumentType.BOOLEAN,
        description=description,
        required=required,
        default=default,
    )

def enum_arg(
    name: str,
    allowed_values: list[Any],
    description: str = "",
    required: bool = True,
    default: Any | None = None,
) -> ArgumentSchema:
    """Create an enum argument schema."""
    return ArgumentSchema(
        name=name,
        type=ArgumentType.ANY,
        description=description,
        required=required,
        default=default,
        enum=allowed_values,
    )