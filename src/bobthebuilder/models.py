"""Data models for bobthebuilder."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Ecosystem(str, Enum):
    NODE = "node"
    PYTHON = "python"
    GO = "go"
    RUST = "rust"
    DOCKER = "docker"
    MAKE = "make"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MarkerFile(BaseModel):
    path: str
    ecosystem: Ecosystem
    description: str


class ProjectContext(BaseModel):
    """Everything we know about a project from scanning its directory."""

    root: str
    ecosystems: list[Ecosystem] = Field(default_factory=list)
    marker_files: list[MarkerFile] = Field(default_factory=list)
    readme_content: str | None = None
    env_example_files: list[str] = Field(default_factory=list)
    has_docker_compose: bool = False
    makefile_targets: list[str] = Field(default_factory=list)
    # Node-specific
    node_package_manager: str | None = None
    node_scripts: list[str] = Field(default_factory=list)
    # Python-specific
    python_tool: str | None = None  # uv, poetry, pipenv, pip


class BuildStep(BaseModel):
    """A single step in the build plan."""

    name: str
    command: list[str]  # argv-style for subprocess
    description: str
    ecosystem: Ecosystem
    risk_level: RiskLevel = RiskLevel.LOW
    working_dir: str | None = None


class BuildPlan(BaseModel):
    """The full plan for setting up a project."""

    steps: list[BuildStep] = Field(default_factory=list)

    def add(self, step: BuildStep) -> None:
        self.steps.append(step)

    def is_empty(self) -> bool:
        return len(self.steps) == 0
