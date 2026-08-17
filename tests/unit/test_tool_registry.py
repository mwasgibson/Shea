from __future__ import annotations

import pytest

from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.registry import (
    ToolAlreadyRegisteredError,
    ToolDeclaration,
    ToolNotFoundError,
    ToolRegistry,
)


def echo_handler(request: ToolRequest) -> ToolResponse:
    return ToolResponse(success=True, data=request.arguments)


def test_register_and_get_declaration() -> None:
    registry = ToolRegistry()
    declaration = ToolDeclaration(name="echo", capabilities=frozenset({"weather.lookup"}))

    registry.register(declaration, echo_handler)

    assert registry.get_declaration("echo") is declaration


def test_register_and_get_handler() -> None:
    registry = ToolRegistry()
    declaration = ToolDeclaration(name="echo", capabilities=frozenset())

    registry.register(declaration, echo_handler)

    assert registry.get_handler("echo") is echo_handler


def test_duplicate_registration_raises() -> None:
    registry = ToolRegistry()
    declaration = ToolDeclaration(name="echo", capabilities=frozenset())
    registry.register(declaration, echo_handler)

    with pytest.raises(ToolAlreadyRegisteredError):
        registry.register(declaration, echo_handler)


def test_unknown_tool_raises_on_declaration_lookup() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get_declaration("does-not-exist")


def test_unknown_tool_raises_on_handler_lookup() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get_handler("does-not-exist")


def test_list_tools_returns_all_declarations() -> None:
    registry = ToolRegistry()
    a = ToolDeclaration(name="a", capabilities=frozenset())
    b = ToolDeclaration(name="b", capabilities=frozenset())
    registry.register(a, echo_handler)
    registry.register(b, echo_handler)

    names = {declaration.name for declaration in registry.list_tools()}
    assert names == {"a", "b"}
