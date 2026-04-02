"""Parallel build execution across repos."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .executor import ExecutionResult


@dataclass
class RepoResult:
    """Result of building a single repo (potentially parallel)."""

    repo_name: str
    repo_path: str
    results: list[ExecutionResult] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo_name,
            "path": self.repo_path,
            "success": self.success,
            "duration_s": round(self.duration_s, 2),
            "steps": [r.to_dict() for r in self.results],
        }


def build_repos_parallel(
    repo_tasks: list[tuple[str, Path, Callable]],
    max_workers: int | None = None,
) -> list[RepoResult]:
    """Build multiple repos in parallel.

    Args:
        repo_tasks: List of (repo_name, repo_path, build_fn).
                    build_fn takes no args and returns list[ExecutionResult].
        max_workers: Max parallel workers. None = min(len(tasks), 4).
    """
    if not repo_tasks:
        return []

    if len(repo_tasks) == 1:
        name, path, fn = repo_tasks[0]
        return [_timed_build(name, str(path), fn)]

    workers = max_workers or min(len(repo_tasks), 4)
    repo_results: list[RepoResult] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for name, path, fn in repo_tasks:
            future = executor.submit(_timed_build, name, str(path), fn)
            futures[future] = name

        for future in as_completed(futures):
            repo_results.append(future.result())

    # Sort by original order
    name_order = {name: i for i, (name, _, _) in enumerate(repo_tasks)}
    repo_results.sort(key=lambda r: name_order.get(r.repo_name, 999))

    return repo_results


def _timed_build(name: str, path: str, fn: Callable) -> RepoResult:
    """Run a build function and time it."""
    start = time.monotonic()
    try:
        results = fn()
    except Exception as e:
        results = [ExecutionResult(
            step_name="build",
            success=False,
            error=str(e),
        )]
    duration = time.monotonic() - start
    return RepoResult(
        repo_name=name,
        repo_path=path,
        results=results,
        duration_s=duration,
    )
