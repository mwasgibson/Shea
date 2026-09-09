from __future__ import annotations

import pytest

from shea.contracts.models import ToolResponse
from shea.tools.registry import SchemaRequiredError, ToolDeclaration, ToolRegistry


def test_elevated_capability_requires_schema() -> None:
    registry = ToolRegistry()
    with pytest.raises(SchemaRequiredError):
        registry.register(
            ToolDeclaration(
                name="shell",
                capabilities=frozenset({"process.execute"}),
            ),
            lambda r: ToolResponse(success=True),
        )