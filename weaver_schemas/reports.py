from __future__ import annotations

import typing as typ

import msgspec as ms

from .diagnostics import Diagnostic  # ruff: ignore[typing-only-first-party-import]


class ImpactReport(ms.Struct, frozen=True):
    """Result of analysing a proposed change."""

    diagnostics: tuple[Diagnostic, ...]
    type: typ.Literal["impact"] = "impact"


class TestResult(ms.Struct, frozen=True):
    """Outcome of a project test run."""

    name: str
    status: typ.Literal["passed", "failed", "error", "skipped"]
    output: str | None = None
    type: typ.Literal["test-result"] = "test-result"


class OnboardingReport(ms.Struct, frozen=True):
    """Information gathered during project onboarding."""

    details: str
    type: typ.Literal["onboarding"] = "onboarding"


__all__ = ["ImpactReport", "OnboardingReport", "TestResult"]
