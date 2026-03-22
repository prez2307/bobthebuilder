"""Git worktree management across workspace repos."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorktreeInfo:
    """A single worktree entry from git."""

    path: str
    branch: str
    commit: str = ""
    is_bare: bool = False

    def to_dict(self) -> dict:
        d: dict = {"path": self.path, "branch": self.branch}
        if self.commit:
            d["commit"] = self.commit
        return d


@dataclass
class WorktreeResult:
    """Result of a worktree operation on one repo."""

    repo: str
    success: bool
    message: str = ""
    worktree_path: str = ""

    def to_dict(self) -> dict:
        d: dict = {"repo": self.repo, "success": self.success, "message": self.message}
        if self.worktree_path:
            d["worktree_path"] = self.worktree_path
        return d


@dataclass
class WorktreeListResult:
    """Result of listing worktrees for one repo."""

    repo: str
    success: bool
    worktrees: list[WorktreeInfo] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        d: dict = {"repo": self.repo, "success": self.success}
        if self.worktrees:
            d["worktrees"] = [w.to_dict() for w in self.worktrees]
        if self.message:
            d["message"] = self.message
        return d


def _run_git(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a git command."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists() or (path / ".git").is_file()


def create_worktrees(
    repo_paths: list[Path],
    branch: str,
    base_dir: Path | None = None,
) -> list[WorktreeResult]:
    """Create a worktree for each repo on the given branch.

    Worktrees are placed at: <base_dir>/<branch>/<repo_name>/
    If base_dir is not given, worktrees go to ../<branch>/<repo_name>/ relative
    to the workspace root.
    """
    results: list[WorktreeResult] = []

    for repo_path in repo_paths:
        repo_name = repo_path.name

        if not _is_git_repo(repo_path):
            results.append(WorktreeResult(
                repo=repo_name, success=False,
                message="Not a git repository",
            ))
            continue

        # Determine worktree destination
        if base_dir:
            wt_path = base_dir / branch / repo_name
        else:
            wt_path = repo_path.parent / ".worktrees" / branch / repo_name

        if wt_path.exists():
            results.append(WorktreeResult(
                repo=repo_name, success=True,
                message="Worktree already exists",
                worktree_path=str(wt_path),
            ))
            continue

        # Ensure parent directory exists
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Try to create worktree. If the branch exists, check it out;
            # otherwise create a new branch.
            result = _run_git(
                ["worktree", "add", str(wt_path), branch],
                cwd=str(repo_path),
            )

            if result.returncode != 0:
                # Branch might not exist — create it
                if "not a valid" in result.stderr or "invalid reference" in result.stderr:
                    result = _run_git(
                        ["worktree", "add", "-b", branch, str(wt_path)],
                        cwd=str(repo_path),
                    )

            if result.returncode == 0:
                results.append(WorktreeResult(
                    repo=repo_name, success=True,
                    message=f"Created worktree on branch '{branch}'",
                    worktree_path=str(wt_path),
                ))
            else:
                results.append(WorktreeResult(
                    repo=repo_name, success=False,
                    message=result.stderr.strip() or result.stdout.strip(),
                ))
        except subprocess.TimeoutExpired:
            results.append(WorktreeResult(
                repo=repo_name, success=False,
                message="Timed out creating worktree",
            ))
        except FileNotFoundError:
            results.append(WorktreeResult(
                repo=repo_name, success=False,
                message="git not found",
            ))

    return results


def list_worktrees(repo_paths: list[Path]) -> list[WorktreeListResult]:
    """List all worktrees for each repo."""
    results: list[WorktreeListResult] = []

    for repo_path in repo_paths:
        repo_name = repo_path.name

        if not _is_git_repo(repo_path):
            results.append(WorktreeListResult(
                repo=repo_name, success=False,
                message="Not a git repository",
            ))
            continue

        try:
            result = _run_git(
                ["worktree", "list", "--porcelain"],
                cwd=str(repo_path),
            )

            if result.returncode != 0:
                results.append(WorktreeListResult(
                    repo=repo_name, success=False,
                    message=result.stderr.strip(),
                ))
                continue

            worktrees = _parse_worktree_list(result.stdout)
            results.append(WorktreeListResult(
                repo=repo_name, success=True,
                worktrees=worktrees,
            ))
        except subprocess.TimeoutExpired:
            results.append(WorktreeListResult(
                repo=repo_name, success=False,
                message="Timed out listing worktrees",
            ))
        except FileNotFoundError:
            results.append(WorktreeListResult(
                repo=repo_name, success=False,
                message="git not found",
            ))

    return results


def remove_worktrees(
    repo_paths: list[Path],
    branch: str,
    base_dir: Path | None = None,
    force: bool = False,
) -> list[WorktreeResult]:
    """Remove worktrees for the given branch across all repos."""
    results: list[WorktreeResult] = []

    for repo_path in repo_paths:
        repo_name = repo_path.name

        if not _is_git_repo(repo_path):
            results.append(WorktreeResult(
                repo=repo_name, success=False,
                message="Not a git repository",
            ))
            continue

        # Find the worktree path
        if base_dir:
            wt_path = base_dir / branch / repo_name
        else:
            wt_path = repo_path.parent / ".worktrees" / branch / repo_name

        if not wt_path.exists():
            # Also check the actual worktree list for any worktree on this branch
            wt_path_found = _find_worktree_by_branch(repo_path, branch)
            if wt_path_found:
                wt_path = Path(wt_path_found)
            else:
                results.append(WorktreeResult(
                    repo=repo_name, success=True,
                    message=f"No worktree found for branch '{branch}'",
                ))
                continue

        try:
            args = ["worktree", "remove", str(wt_path)]
            if force:
                args.append("--force")
            result = _run_git(args, cwd=str(repo_path))

            if result.returncode == 0:
                results.append(WorktreeResult(
                    repo=repo_name, success=True,
                    message=f"Removed worktree for branch '{branch}'",
                ))
            else:
                results.append(WorktreeResult(
                    repo=repo_name, success=False,
                    message=result.stderr.strip() or result.stdout.strip(),
                ))
        except subprocess.TimeoutExpired:
            results.append(WorktreeResult(
                repo=repo_name, success=False,
                message="Timed out removing worktree",
            ))
        except FileNotFoundError:
            results.append(WorktreeResult(
                repo=repo_name, success=False,
                message="git not found",
            ))

    return results


def _parse_worktree_list(output: str) -> list[WorktreeInfo]:
    """Parse `git worktree list --porcelain` output."""
    worktrees: list[WorktreeInfo] = []
    current: dict = {}

    for line in output.splitlines():
        if not line.strip():
            if current:
                worktrees.append(WorktreeInfo(
                    path=current.get("worktree", ""),
                    branch=current.get("branch", "").replace("refs/heads/", ""),
                    commit=current.get("HEAD", ""),
                    is_bare="bare" in current,
                ))
                current = {}
            continue

        if line.startswith("worktree "):
            current["worktree"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["branch"] = "(detached)"

    # Handle last entry (no trailing blank line)
    if current:
        worktrees.append(WorktreeInfo(
            path=current.get("worktree", ""),
            branch=current.get("branch", "").replace("refs/heads/", ""),
            commit=current.get("HEAD", ""),
            is_bare="bare" in current,
        ))

    return worktrees


def _find_worktree_by_branch(repo_path: Path, branch: str) -> str | None:
    """Find a worktree path by branch name."""
    try:
        result = _run_git(
            ["worktree", "list", "--porcelain"],
            cwd=str(repo_path),
        )
        if result.returncode != 0:
            return None
        for wt in _parse_worktree_list(result.stdout):
            if wt.branch == branch:
                return wt.path
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None
