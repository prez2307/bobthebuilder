"""Env file template strategy."""

from __future__ import annotations

from pathlib import Path

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel


def get_steps(ctx: ProjectContext) -> list[BuildStep]:
    steps: list[BuildStep] = []
    root = Path(ctx.root)

    for template in ctx.env_example_files:
        target = ".env"
        if (root / target).exists():
            continue
        steps.append(
            BuildStep(
                name="copy-env",
                command=["cp", template, target],
                description=f"Copy {template} to {target}",
                ecosystem=Ecosystem.NODE,  # cross-cutting, but needs a value
                risk_level=RiskLevel.LOW,
            )
        )
        break  # only copy the first template found

    return steps
