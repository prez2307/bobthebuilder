"""Affected test detection - figure out what to test based on what changed."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AffectedResult:
    """What's affected by recent changes."""

    changed_files: list[str] = field(default_factory=list)
    affected_ecosystems: list[str] = field(default_factory=list)
    affected_apps: list[str] = field(default_factory=list)
    suggested_tests: list[dict] = field(default_factory=list)
    skip_reason: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "changed_files": self.changed_files,
            "affected_ecosystems": self.affected_ecosystems,
            "affected_apps": self.affected_apps,
            "suggested_tests": self.suggested_tests,
        }
        if self.skip_reason:
            d["skip_reason"] = self.skip_reason
        return d


# Map file patterns to the app/ecosystem they belong to
APP_PATTERNS: list[tuple[str, str, str]] = [
    # (path_prefix, app_name, ecosystem)
    ("apps/backend/", "backend", "python"),
    ("apps/frontend/", "frontend", "node"),
    ("apps/infra/", "infra", "node"),
    ("packages/", "packages", "node"),
]

# Files that affect everything
GLOBAL_FILES: set[str] = {
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "turbo.json",
    "docker-compose.yml",
    "docker-compose.yaml",
    "bob.yaml",
    ".github",
}


def detect_affected(
    repo_path: Path,
    base: str = "HEAD~1",
    head: str = "HEAD",
) -> AffectedResult:
    """Detect what's affected by changes between base and head.

    Works with:
    - Uncommitted changes (base=HEAD, head=working tree)
    - Last commit (base=HEAD~1, head=HEAD)
    - PR diff (base=main, head=feature-branch)
    """
    result = AffectedResult()

    # Get changed files
    changed = _get_changed_files(repo_path, base, head)
    if not changed:
        # Check for uncommitted changes
        changed = _get_uncommitted_changes(repo_path)

    if not changed:
        result.skip_reason = "No changes detected"
        return result

    result.changed_files = changed

    # Classify changes
    affected_apps: set[str] = set()
    affected_ecos: set[str] = set()
    is_global = False

    for f in changed:
        # Check global files
        for gf in GLOBAL_FILES:
            if f == gf or f.startswith(gf):
                is_global = True
                break

        # Check app patterns
        for prefix, app_name, eco in APP_PATTERNS:
            if f.startswith(prefix):
                affected_apps.add(app_name)
                affected_ecos.add(eco)
                break

    if is_global:
        # Global change — test everything
        affected_apps = {"backend", "frontend", "infra"}
        affected_ecos = {"python", "node"}

    result.affected_apps = sorted(affected_apps)
    result.affected_ecosystems = sorted(affected_ecos)

    # Generate test suggestions
    result.suggested_tests = _suggest_tests(repo_path, result.affected_apps, result.affected_ecosystems)

    return result


def detect_affected_from_diff(repo_path: Path) -> AffectedResult:
    """Detect affected from uncommitted + staged changes (most common for dev)."""
    result = AffectedResult()

    changed = _get_uncommitted_changes(repo_path)
    staged = _get_staged_changes(repo_path)
    all_changed = list(set(changed + staged))

    if not all_changed:
        result.skip_reason = "No changes detected"
        return result

    result.changed_files = all_changed

    affected_apps: set[str] = set()
    affected_ecos: set[str] = set()

    for f in all_changed:
        for gf in GLOBAL_FILES:
            if f == gf or f.startswith(gf):
                affected_apps = {"backend", "frontend", "infra"}
                affected_ecos = {"python", "node"}
                break

        for prefix, app_name, eco in APP_PATTERNS:
            if f.startswith(prefix):
                affected_apps.add(app_name)
                affected_ecos.add(eco)
                break

    result.affected_apps = sorted(affected_apps)
    result.affected_ecosystems = sorted(affected_ecos)
    result.suggested_tests = _suggest_tests(repo_path, result.affected_apps, result.affected_ecosystems)

    return result


def _suggest_tests(repo_path: Path, apps: set[str] | list[str], ecos: set[str] | list[str]) -> list[dict]:
    """Suggest specific test commands based on affected apps."""
    suggestions: list[dict] = []

    if "backend" in apps:
        suggestions.append({
            "app": "backend",
            "command": ["uv", "run", "pytest", "tests/", "--ignore=tests/contract", "-q"],
            "cwd": str(repo_path / "apps" / "backend"),
            "ecosystem": "python",
            "description": "Backend unit tests",
        })

    if "frontend" in apps:
        suggestions.append({
            "app": "frontend",
            "command": ["pnpm", "--filter", "@isol8/frontend", "test"],
            "cwd": str(repo_path),
            "ecosystem": "node",
            "description": "Frontend unit tests (vitest)",
        })

    if "infra" in apps:
        suggestions.append({
            "app": "infra",
            "command": ["pnpm", "--filter", "@isol8/infra", "test"],
            "cwd": str(repo_path),
            "ecosystem": "node",
            "description": "Infrastructure tests (jest)",
        })

    return suggestions


def _get_changed_files(repo_path: Path, base: str, head: str) -> list[str]:
    """Get files changed between two git refs."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base, head],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def _get_uncommitted_changes(repo_path: Path) -> list[str]:
    """Get uncommitted changed files (working tree)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def _get_staged_changes(repo_path: Path) -> list[str]:
    """Get staged changed files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []
