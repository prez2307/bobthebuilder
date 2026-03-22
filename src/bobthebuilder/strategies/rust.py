"""Rust setup strategy."""

from __future__ import annotations

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel


def get_steps(ctx: ProjectContext) -> list[BuildStep]:
    if Ecosystem.RUST not in ctx.root_ecosystems:
        return []

    return [
        BuildStep(
            name="build",
            command=["cargo", "build"],
            description="Build Rust project with Cargo",
            ecosystem=Ecosystem.RUST,
            risk_level=RiskLevel.LOW,
        ),
    ]
