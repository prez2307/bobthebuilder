"""Python setup strategy."""

from __future__ import annotations

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel


def get_steps(ctx: ProjectContext) -> list[BuildStep]:
    if Ecosystem.PYTHON not in ctx.root_ecosystems:
        return []

    tool = ctx.python_tool
    if not tool:
        return []

    if tool == "uv":
        return [
            BuildStep(
                name="install-deps",
                command=["uv", "sync"],
                description="Install Python dependencies with uv",
                ecosystem=Ecosystem.PYTHON,
                risk_level=RiskLevel.LOW,
            )
        ]

    if tool == "poetry":
        return [
            BuildStep(
                name="install-deps",
                command=["poetry", "install"],
                description="Install Python dependencies with Poetry",
                ecosystem=Ecosystem.PYTHON,
                risk_level=RiskLevel.LOW,
            )
        ]

    if tool == "pipenv":
        return [
            BuildStep(
                name="install-deps",
                command=["pipenv", "install"],
                description="Install Python dependencies with Pipenv",
                ecosystem=Ecosystem.PYTHON,
                risk_level=RiskLevel.LOW,
            )
        ]

    # pip fallback
    has_requirements = any(m.path == "requirements.txt" for m in ctx.marker_files)
    has_pyproject = any(m.path == "pyproject.toml" for m in ctx.marker_files)

    if has_requirements:
        return [
            BuildStep(
                name="install-deps",
                command=["pip", "install", "-r", "requirements.txt"],
                description="Install Python dependencies from requirements.txt",
                ecosystem=Ecosystem.PYTHON,
                risk_level=RiskLevel.LOW,
            )
        ]

    if has_pyproject:
        return [
            BuildStep(
                name="install-deps",
                command=["pip", "install", "-e", "."],
                description="Install Python project in editable mode",
                ecosystem=Ecosystem.PYTHON,
                risk_level=RiskLevel.LOW,
            )
        ]

    return []
