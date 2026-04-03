"""Workspace management - bob.yaml creation and loading."""

from __future__ import annotations

import subprocess
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
    custom_build_steps: list[dict] = field(default_factory=list)
    hooks: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    timeout: int | None = None  # per-repo timeout in seconds

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
        if self.custom_build_steps:
            d["build_steps"] = self.custom_build_steps
        if self.hooks:
            d["hooks"] = self.hooks
        if self.depends_on:
            d["depends_on"] = self.depends_on
        if self.timeout:
            d["timeout"] = self.timeout
        return d

    @classmethod
    def from_dict(cls, data: dict) -> WorkspaceRepo:
        detected = data.get("detected", {})
        return cls(
            path=data["path"],
            url=data.get("url"),
            detected_ecosystem=detected.get("ecosystem"),
            detected_package_manager=detected.get("package_manager"),
            custom_build_steps=data.get("build_steps", []),
            hooks=data.get("hooks", {}),
            depends_on=data.get("depends_on", []),
            timeout=data.get("timeout"),
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


def _ecosystem_to_pm(ctx, primary: Ecosystem | None) -> str | None:
    """Get the package manager for the primary ecosystem."""
    if primary == Ecosystem.NODE:
        return ctx.node_package_manager
    if primary == Ecosystem.PYTHON:
        return ctx.python_tool
    if primary == Ecosystem.RUBY:
        return "bundler"
    return None


def _primary_ecosystem(ctx) -> Ecosystem | None:
    """Get the primary ecosystem (first non-Docker language ecosystem)."""
    for eco in ctx.ecosystems:
        if eco != Ecosystem.DOCKER:
            return eco
    if ctx.ecosystems:
        return ctx.ecosystems[0]
    return None


def clone_repo(url: str, dest: Path) -> bool:
    """Shallow-clone a git repo. Returns True on success or if already exists."""
    if dest.exists():
        return True
    try:
        result = subprocess.run(
            ["git", "clone", "--depth=1", "--single-branch", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def create_workspace(
    root: Path,
    repo_paths: list[Path] | None = None,
    clone_urls: list[tuple[str, str]] | None = None,
) -> Workspace:
    """Create a workspace by detecting each repo.

    Args:
        root: Workspace root directory.
        repo_paths: Local paths to repos.
        clone_urls: List of (url, dirname) to clone into root.
    """
    repo_paths = repo_paths or []
    clone_urls = clone_urls or []
    repos: list[WorkspaceRepo] = []

    # Clone any URLs first
    for url, dirname in clone_urls:
        dest = root / dirname
        clone_repo(url, dest)
        if dest.exists():
            repo_paths.append(dest)

    for repo_path in repo_paths:
        if not repo_path.is_dir():
            continue
        ctx = detect_project(repo_path)
        try:
            rel = str(repo_path.relative_to(root))
        except ValueError:
            rel = str(repo_path)

        primary = _primary_ecosystem(ctx)
        repos.append(
            WorkspaceRepo(
                path=f"./{rel}",
                detected_ecosystem=primary.value if primary else None,
                detected_package_manager=_ecosystem_to_pm(ctx, primary),
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
