"""Go setup strategy."""

from __future__ import annotations

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel


def get_steps(ctx: ProjectContext) -> list[BuildStep]:
    if Ecosystem.GO not in ctx.ecosystems:
        return []

    return [
        BuildStep(
            name="install-deps",
            command=["go", "mod", "download"],
            description="Download Go module dependencies",
            ecosystem=Ecosystem.GO,
            risk_level=RiskLevel.LOW,
        ),
        BuildStep(
            name="build",
            command=["go", "build", "./..."],
            description="Build Go project",
            ecosystem=Ecosystem.GO,
            risk_level=RiskLevel.LOW,
        ),
    ]
