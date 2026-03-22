"""Git pull support for workspace repos."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PullResult:
    path: str
    success: bool
    message: str = ""


def pull_repos(repo_paths: list[Path]) -> list[PullResult]:
    """Pull latest for each repo."""
    results: list[PullResult] = []

    for repo_path in repo_paths:
        if not (repo_path / ".git").exists():
            results.append(
                PullResult(
                    path=str(repo_path),
                    success=False,
                    message="Not a git repository",
                )
            )
            continue

        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=60,
            )
            results.append(
                PullResult(
                    path=str(repo_path),
                    success=result.returncode == 0,
                    message=result.stdout.strip() or result.stderr.strip(),
                )
            )
        except subprocess.TimeoutExpired:
            results.append(
                PullResult(
                    path=str(repo_path),
                    success=False,
                    message="Pull timed out after 60 seconds",
                )
            )
        except FileNotFoundError:
            results.append(
                PullResult(
                    path=str(repo_path),
                    success=False,
                    message="git not found",
                )
            )

    return results
