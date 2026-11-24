from __future__ import annotations

import pytest

from weaverd.serena_tools import (
    SerenaTool,
    UnknownSerenaToolError,
    _is_serena_related_error,
    _resolve_string_tool_name,
    _resolve_tool_name,
)


@pytest.mark.parametrize(
    ("input_name", "expected"),
    [
        ("onboarding", "OnboardingTool"),
        ("OnboardingTool", "OnboardingTool"),
        ("list_references", "ListReferencesTool"),
        ("ListReferencesTool", "ListReferencesTool"),
    ],
)
def test_resolve_string_tool_name_success(input_name: str, expected: str) -> None:
    assert _resolve_string_tool_name(input_name) == expected


def test_resolve_string_tool_name_unknown() -> None:
    with pytest.raises(UnknownSerenaToolError, match="Unknown Serena tool 'Nope'"):
        _resolve_string_tool_name("Nope")


def test_resolve_tool_name_type_error() -> None:
    with pytest.raises(TypeError):
        _resolve_tool_name(123)  # ty: ignore[invalid-argument-type] -- deliberately wrong type


def test_resolve_tool_name_from_enum() -> None:
    assert _resolve_tool_name(SerenaTool.ONBOARDING) == "OnboardingTool"


def test_is_serena_related_error_by_module_name() -> None:
    exc = ModuleNotFoundError()
    assert _is_serena_related_error("serena.fake", exc) is True


def test_is_serena_related_error_by_exc_name() -> None:
    exc = ModuleNotFoundError()
    exc.name = "serena.fake"
    assert _is_serena_related_error("other", exc) is True


def test_is_serena_related_error_false() -> None:
    exc = ModuleNotFoundError()
    exc.name = "other"
    assert _is_serena_related_error("random", exc) is False
