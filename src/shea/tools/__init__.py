from shea.tools.provider import ToolProvider, load_tools

from .boundary import UnsafeExecutionBoundary
from .executor import (
    CapabilityNotAuthorizedError,
    ExecutionResult,
    ToolExecutor,
    UnknownOutcomeError,
    UnsafeExecutionNotAllowedError,
)
from .registry import (
    ToolAlreadyRegisteredError,
    ToolDeclaration,
    ToolHandler,
    ToolNotFoundError,
    ToolRegistry,
)
from .schema import (
    ArgumentSchema,
    ArgumentType,
    ToolSchema,
    ToolSchemaValidationError,
    boolean_arg,
    enum_arg,
    integer_arg,
    string_arg,
)

__all__ = [
    "UnsafeExecutionBoundary",
    "CapabilityNotAuthorizedError",
    "ExecutionResult",
    "ToolExecutor",
    "UnknownOutcomeError",
    "UnsafeExecutionNotAllowedError",
    "ToolAlreadyRegisteredError",
    "ToolDeclaration",
    "ToolHandler",
    "ToolNotFoundError",
    "ToolRegistry",
    "ArgumentSchema",
    "ArgumentType",
    "ToolSchema",
    "ToolSchemaValidationError",
    "boolean_arg",
    "enum_arg",
    "integer_arg",
    "string_arg",
    "ToolProvider",
    "load_tools",
]