"""Validate - fast feedback loop for changes. Lint + typecheck + affected tests in parallel."""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    """Result of a single validation check."""

    name: str
    app: str
    success: bool
    duration_s: float = 0.0
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "app": self.app,
            "success": self.success,
            "duration_s": round(self.duration_s, 2),
        }
        if self.command:
            d["command"] = self.command
        if not self.success and self.stderr:
            d["stderr"] = self.stderr[:500]
        return d


@dataclass
class ValidateResult:
    """Result of full validation."""

    checks: list[CheckResult] = field(default_factory=list)
    total_duration_s: float = 0.0
    affected_apps: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(c.success for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "total_duration_s": round(self.total_duration_s, 2),
            "affected_apps": self.affected_apps,
            "changed_files_count": len(self.changed_files),
            "checks": [c.to_dict() for c in self.checks],
        }


def run_validation(
    repo_path: Path,
    affected_apps: list[str],
    test_env: dict[str, str] | None = None,
    parallel: bool = True,
) -> ValidateResult:
    """Run lint, typecheck, and tests for affected apps in parallel."""
    import os

    env = {**os.environ, **(test_env or {})}
    tasks: list[tuple[str, str, list[str], str]] = []

    # Generate all checks for affected apps
    for app in affected_apps:
        app_checks = _checks_for_app(repo_path, app)
        tasks.extend(app_checks)

    if not tasks:
        return ValidateResult()

    total_start = time.monotonic()
    results: list[CheckResult] = []

    if parallel and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=min(len(tasks), 6)) as executor:
            futures = {}
            for name, app, cmd, cwd in tasks:
                future = executor.submit(_run_check, name, app, cmd, cwd, env)
                futures[future] = (name, app)

            for future in as_completed(futures):
                results.append(future.result())
    else:
        for name, app, cmd, cwd in tasks:
            results.append(_run_check(name, app, cmd, cwd, env))

    total_duration = time.monotonic() - total_start

    # Sort by app then name for consistent output
    results.sort(key=lambda r: (r.app, r.name))

    return ValidateResult(
        checks=results,
        total_duration_s=total_duration,
        affected_apps=affected_apps,
    )


def _checks_for_app(repo_path: Path, app: str) -> list[tuple[str, str, list[str], str]]:
    """Generate (name, app, command, cwd) tuples for validation checks."""
    checks: list[tuple[str, str, list[str], str]] = []

    if app == "backend":
        backend_dir = str(repo_path / "apps" / "backend")
        checks.append(("lint", "backend", ["uv", "run", "ruff", "check", "."], backend_dir))
        checks.append(("test", "backend", [
            "uv", "run", "pytest", "tests/", "--ignore=tests/contract", "-q", "--no-header",
        ], backend_dir))

    elif app == "frontend":
        root = str(repo_path)
        checks.append(("lint", "frontend", ["pnpm", "--filter", "@isol8/frontend", "lint"], root))
        checks.append(("typecheck", "frontend", ["pnpm", "--filter", "@isol8/frontend", "run", "build"], root))
        checks.append(("test", "frontend", ["pnpm", "--filter", "@isol8/frontend", "test"], root))

    elif app == "infra":
        root = str(repo_path)
        checks.append(("test", "infra", ["pnpm", "--filter", "@isol8/infra", "test"], root))

    return checks


def _run_check(
    name: str,
    app: str,
    command: list[str],
    cwd: str,
    env: dict,
) -> CheckResult:
    """Run a single validation check."""
    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        duration = time.monotonic() - start
        return CheckResult(
            name=name,
            app=app,
            success=result.returncode == 0,
            duration_s=duration,
            command=command,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name=name, app=app, success=False,
            duration_s=time.monotonic() - start,
            command=command, stderr="Timed out after 300s",
        )
    except FileNotFoundError:
        return CheckResult(
            name=name, app=app, success=False,
            duration_s=0, command=command,
            stderr=f"Command not found: {command[0]}",
        )
