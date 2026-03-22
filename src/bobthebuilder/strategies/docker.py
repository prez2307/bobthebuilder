"""Docker Compose setup strategy."""

from __future__ import annotations

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel


def get_steps(ctx: ProjectContext, docker: bool = False) -> list[BuildStep]:
    if not ctx.has_docker_compose or not docker:
        return []

    return [
        BuildStep(
            name="docker-up",
            command=["docker", "compose", "up", "-d"],
            description="Start Docker Compose services",
            ecosystem=Ecosystem.DOCKER,
            risk_level=RiskLevel.MEDIUM,
        ),
    ]
