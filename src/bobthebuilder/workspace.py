"""Workspace management - bob.yaml creation and loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .detector import detect_project
from .models import Ecosystem


@dataclass
class WorkspaceRepo:
    path: str
    url: str | None = None
    detected_ecosystem: str | None = None
    detected_package_manager: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"path": self.path}
        if self.url:
            d["url"] = self.url
        detected: dict = {}
        if self.detected_ecosystem:
            detected["ecosystem"] = self.detected_ecosystem
        if self.detected_package_manager:
            detected["package_manager"] = self.detected_package_manager
        if detected:
            d["detected"] = detected
        return d

    @classmethod
    def from_dict(cls, data: dict) -> WorkspaceRepo:
        detected = data.get("detected", {})
        return cls(
            path=data["path"],
            url=data.get("url"),
            detected_ecosystem=detected.get("ecosystem"),
            detected_package_manager=detected.get("package_manager"),
        )


@dataclass
class Workspace:
    name: str
    repos: list[WorkspaceRepo] = field(default_factory=list)

    def save(self, path: Path) -> None:
        data = {
            "workspace": self.name,
            "repos": [r.to_dict() for r in self.repos],
        }
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    def to_dict(self) -> dict:
        return {
            "workspace": self.name,
            "repos": [r.to_dict() for r in self.repos],
        }


def _ecosystem_to_pm(ctx) -> str | None:
    """Get the detected package manager name from a ProjectContext."""
    if Ecosystem.NODE in ctx.ecosystems:
        return ctx.node_package_manager
    if Ecosystem.PYTHON in ctx.ecosystems:
        return ctx.python_tool
    return None


def _primary_ecosystem(ctx) -> str | None:
    """Get the primary ecosystem name from a ProjectContext."""
    if ctx.ecosystems:
        return ctx.ecosystems[0].value
    return None


def create_workspace(root: Path, repo_paths: list[Path]) -> Workspace:
    """Create a workspace by detecting each repo."""
    repos: list[WorkspaceRepo] = []

    for repo_path in repo_paths:
        ctx = detect_project(repo_path)
        try:
            rel = str(repo_path.relative_to(root))
        except ValueError:
            rel = str(repo_path)

        repos.append(
            WorkspaceRepo(
                path=f"./{rel}",
                detected_ecosystem=_primary_ecosystem(ctx),
                detected_package_manager=_ecosystem_to_pm(ctx),
            )
        )

    return Workspace(name=root.name, repos=repos)


def load_workspace(path: Path) -> Workspace:
    """Load a workspace from a bob.yaml file."""
    data = yaml.safe_load(path.read_text())
    return Workspace(
        name=data["workspace"],
        repos=[WorkspaceRepo.from_dict(r) for r in data.get("repos", [])],
    )
