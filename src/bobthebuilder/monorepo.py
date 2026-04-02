"""Monorepo workspace detection - npm/yarn/pnpm workspaces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MonorepoInfo:
    """Detected monorepo workspace configuration."""

    tool: str  # "npm", "yarn", "pnpm", "turborepo"
    root: str
    packages: list[str] = field(default_factory=list)
    is_workspace_root: bool = False

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "root": self.root,
            "packages": self.packages,
            "is_workspace_root": self.is_workspace_root,
        }


def detect_monorepo(project_path: Path) -> MonorepoInfo | None:
    """Detect if a project is a monorepo with workspace configuration."""
    # Check for Node.js workspaces
    info = _detect_node_workspaces(project_path)
    if info:
        return info

    # Check for pnpm workspaces
    info = _detect_pnpm_workspaces(project_path)
    if info:
        return info

    return None


def _detect_node_workspaces(project_path: Path) -> MonorepoInfo | None:
    """Detect npm/yarn workspaces from package.json."""
    pkg_json_path = project_path / "package.json"
    if not pkg_json_path.exists():
        return None

    try:
        data = json.loads(pkg_json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    workspaces = data.get("workspaces")
    if not workspaces:
        return None

    # workspaces can be a list or an object with "packages" key
    if isinstance(workspaces, dict):
        packages = workspaces.get("packages", [])
    elif isinstance(workspaces, list):
        packages = workspaces
    else:
        return None

    if not packages:
        return None

    # Determine tool from lockfiles
    if (project_path / "yarn.lock").exists():
        tool = "yarn"
    elif (project_path / "pnpm-lock.yaml").exists():
        tool = "pnpm"
    elif (project_path / "bun.lockb").exists():
        tool = "bun"
    else:
        tool = "npm"

    # Check for Turborepo
    if (project_path / "turbo.json").exists():
        tool = "turborepo"

    # Resolve glob patterns to actual packages
    resolved = _resolve_workspace_globs(project_path, packages)

    return MonorepoInfo(
        tool=tool,
        root=str(project_path),
        packages=resolved,
        is_workspace_root=True,
    )


def _detect_pnpm_workspaces(project_path: Path) -> MonorepoInfo | None:
    """Detect pnpm workspaces from pnpm-workspace.yaml."""
    ws_yaml_path = project_path / "pnpm-workspace.yaml"
    if not ws_yaml_path.exists():
        return None

    try:
        data = yaml.safe_load(ws_yaml_path.read_text())
    except (yaml.YAMLError, OSError):
        return None

    if not data or not isinstance(data, dict):
        return None

    packages = data.get("packages", [])
    if not packages:
        return None

    resolved = _resolve_workspace_globs(project_path, packages)

    return MonorepoInfo(
        tool="pnpm",
        root=str(project_path),
        packages=resolved,
        is_workspace_root=True,
    )


def _resolve_workspace_globs(root: Path, patterns: list[str]) -> list[str]:
    """Resolve workspace glob patterns to actual package directories."""
    resolved: list[str] = []

    for pattern in patterns:
        # Remove negation patterns
        if pattern.startswith("!"):
            continue

        # Handle simple globs like "packages/*" or "apps/*"
        if pattern.endswith("/*") or pattern.endswith("/**"):
            base = pattern.rstrip("/*")
            base_dir = root / base
            if base_dir.is_dir():
                for entry in sorted(base_dir.iterdir()):
                    if entry.is_dir() and (entry / "package.json").exists():
                        resolved.append(str(entry.relative_to(root)))
        else:
            # Direct path
            candidate = root / pattern
            if candidate.is_dir() and (candidate / "package.json").exists():
                resolved.append(pattern)

    return resolved


def should_skip_subproject_install(project_path: Path) -> bool:
    """Check if this is a workspace root where a single root install suffices.

    When a monorepo uses workspaces, `npm install` / `yarn install` / `pnpm install`
    at the root handles all subpackages. Individual subpackage installs are redundant.
    """
    return detect_monorepo(project_path) is not None
