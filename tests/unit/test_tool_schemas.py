from __future__ import annotations

import pytest

from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.executor import ToolExecutor
from shea.tools.registry import ToolDeclaration, ToolRegistry
from shea.tools.schema import (
    ToolSchema,
    ToolSchemaValidationError,
    boolean_arg,
    enum_arg,
    integer_arg,
    string_arg,
)


def make_request(tool: str = "test.tool", **arguments: object) -> ToolRequest:
    return ToolRequest(request_id="req-1", tool=tool, action="do_thing", arguments=arguments)

def test_string_arg_validation():
    """Test string argument schema validation."""
    schema = string_arg("name", required=True, min_length=3, max_length=10)

    # Valid
    is_valid, error = schema.validate("hello")
    assert is_valid
    assert error == ""

    # Too short
    is_valid, error = schema.validate("hi")
    assert not is_valid
    assert "length >= 3" in error

    # Too long
    is_valid, error = schema.validate("hello world")
    assert not is_valid
    assert "length <= 10" in error

def test_integer_arg_validation():
    """Test integer argument schema validation."""
    schema = integer_arg("count", required=True, min_value=0, max_value=100)

    # Valid
    is_valid, error = schema.validate(50)
    assert is_valid

    # Too low
    is_valid, error = schema.validate(-1)
    assert not is_valid
    assert ">=" in error

    # Too high
    is_valid, error = schema.validate(101)
    assert not is_valid
    assert "<=" in error

    # Wrong type
    is_valid, error = schema.validate("50")
    assert not is_valid
    assert "type" in error

def test_boolean_arg_validation():
    """Test boolean argument schema validation."""
    schema = boolean_arg("enabled", required=True)

    # Valid
    is_valid, _ = schema.validate(True)
    assert is_valid

    is_valid, _ = schema.validate(False)
    assert is_valid

    # Wrong type
    is_valid, _ = schema.validate(1)
    assert not is_valid

def test_enum_arg_validation():
    """Test enum argument schema validation."""
    schema = enum_arg("action", ["create", "read", "update", "delete"])

    # Valid
    is_valid, error = schema.validate("create")
    assert is_valid

    # Invalid
    is_valid, error = schema.validate("delete_all")
    assert not is_valid
    assert "one of" in error

def test_tool_schema_validation():
    """Test complete tool schema validation."""
    schema = ToolSchema(
        name="file.operate",
        description="File operations",
        required_capabilities=frozenset({"filesystem.write"}),
        arguments={
            "path": string_arg("path", required=True, min_length=1),
            "action": enum_arg("action", ["read", "write", "delete"]),
            "recursive": boolean_arg("recursive", required=False, default=False),
            "max_depth": integer_arg("max_depth", required=False, min_value=0, max_value=100),
        },
    )

    # Valid request
    request = make_request(
        "file.operate",
        path="/tmp/test.txt",
        action="write",
    )
    is_valid, errors = schema.validate_request(request)
    assert is_valid
    assert errors == []

    # Missing required argument
    request = make_request("file.operate", action="write")
    is_valid, errors = schema.validate_request(request)
    assert not is_valid
    assert "Missing required argument: path" in errors

    # Invalid enum value
    request = make_request("file.operate", path="/tmp/test.txt", action="execute")
    is_valid, errors = schema.validate_request(request)
    assert not is_valid
    assert "one of" in errors[0]

    # Unknown argument
    request = make_request("file.operate", path="/tmp/test.txt", action="write", unknown="value")
    is_valid, errors = schema.validate_request(request)
    assert not is_valid
    assert "Unknown argument: unknown" in errors

def test_tool_executor_with_schema_validation():
    """Test that ToolExecutor validates arguments before execution."""
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True, data="ok")

    registry = ToolRegistry()
    registry.register(
        ToolDeclaration(
            name="test.tool",
            capabilities=frozenset({"test.capability"}),
            argument_schema={
                "name": {"type": "string", "required": True, "min_length": 3},
                "count": {"type": "integer", "required": False, "min_value": 0},
            },
        ),
        handler,
    )

    executor = ToolExecutor(registry, allow_unsafe_execution=True)

    # Valid request
    result = executor.execute(
        make_request("test.tool", name="valid", count=5),
        authorized_capabilities=frozenset({"test.capability"}),
    )
    assert result.outcome.name == "SUCCESS"
    assert len(calls) == 1

    # Invalid request - missing required argument
    with pytest.raises(ToolSchemaValidationError) as exc_info:
        executor.execute(
            make_request("test.tool", count=5),
            authorized_capabilities=frozenset({"test.capability"}),
        )
    assert "name" in str(exc_info.value)
    assert len(calls) == 1  # Previous call still happened

    # Invalid request - wrong type
    with pytest.raises(ToolSchemaValidationError) as exc_info:
        executor.execute(
            make_request("test.tool", name=123),
            authorized_capabilities=frozenset({"test.capability"}),
        )
    assert "type" in str(exc_info.value)

def test_tool_executor_without_schema():
    """Test that tools without schemas still work."""
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True, data="ok")

    registry = ToolRegistry()
    registry.register(
        ToolDeclaration(
            name="test.tool",
            capabilities=frozenset({"test.capability"}),
            # No argument_schema
        ),
        handler,
    )

    executor = ToolExecutor(registry, allow_unsafe_execution=True)

    # Should work without validation
    result = executor.execute(
        make_request("test.tool", unknown_arg="anything"),
        authorized_capabilities=frozenset({"test.capability"}),
    )
    assert result.outcome.name == "SUCCESS"
    assert len(calls) == 1

def test_schema_with_defaults():
    """Test that default values are applied correctly."""
    schema = ToolSchema(
        name="test.tool",
        arguments={
            "required_arg": string_arg("required_arg", required=True),
            "optional_arg": string_arg("optional_arg", required=False, default="default_value"),
        },
    )

    # Request without optional arg
    request = make_request("test.tool", required_arg="test")
    validated = schema.get_validated_arguments(request)
    assert validated["required_arg"] == "test"
    assert validated["optional_arg"] == "default_value"

    # Request with optional arg
    request = make_request("test.tool", required_arg="test", optional_arg="custom")
    validated = schema.get_validated_arguments(request)
    assert validated["optional_arg"] == "custom"

def test_register_with_schema():
    """Test the convenience method for registering tools with schemas."""
    registry = ToolRegistry()

    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True)

    registry.register_with_schema(
        name="test.tool",
        capabilities=frozenset({"test.capability"}),
        handler=handler,
        description="A test tool",
        argument_schema={
            "arg1": {"type": "string", "required": True},
            "arg2": {"type": "integer", "required": False, "default": 42},
        },
    )

    declaration = registry.get_declaration("test.tool")
    assert declaration.name == "test.tool"
    assert declaration.argument_schema is not None
    assert "arg1" in declaration.argument_schema
    assert "arg2" in declaration.argument_schema