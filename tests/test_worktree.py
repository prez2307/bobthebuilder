"""Tests for bob worktree command."""

import subprocess
from pathlib import Path

import pytest

from bobthebuilder.worktree import (
    WorktreeInfo,
    _parse_worktree_list,
    create_worktrees,
    list_worktrees,
    remove_worktrees,
)

# Git env that disables signing for tests
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "HOME": "/tmp",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
}


def _git(args, cwd=None):
    """Run git command without signing."""
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**GIT_ENV, "PATH": subprocess.os.environ.get("PATH", "")},
    )


def _make_repo(tmp_path, name="repo"):
    """Create a simple git repo with one commit."""
    repo = tmp_path / name
    repo.mkdir()
    _git(["init", "--initial-branch=main", str(repo)])
    (repo / "file.txt").write_text("hello")
    _git(["add", "."], cwd=str(repo))
    _git(["commit", "-m", "initial"], cwd=str(repo))
    return repo


class TestParseWorktreeList:
    def test_parses_porcelain_output(self):
        output = (
            "worktree /home/user/repo\n"
            "HEAD abc123def456\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /home/user/repo-feature\n"
            "HEAD def789abc012\n"
            "branch refs/heads/feature\n"
            "\n"
        )
        worktrees = _parse_worktree_list(output)
        assert len(worktrees) == 2
        assert worktrees[0].path == "/home/user/repo"
        assert worktrees[0].branch == "main"
        assert worktrees[0].commit == "abc123def456"
        assert worktrees[1].branch == "feature"

    def test_handles_detached_head(self):
        output = (
            "worktree /home/user/repo\n"
            "HEAD abc123\n"
            "detached\n"
            "\n"
        )
        worktrees = _parse_worktree_list(output)
        assert len(worktrees) == 1
        assert worktrees[0].branch == "(detached)"

    def test_handles_bare_repo(self):
        output = "worktree /home/user/repo.git\nbare\n\n"
        worktrees = _parse_worktree_list(output)
        assert len(worktrees) == 1
        assert worktrees[0].is_bare is True

    def test_handles_no_trailing_newline(self):
        output = "worktree /home/user/repo\nHEAD abc123\nbranch refs/heads/main"
        worktrees = _parse_worktree_list(output)
        assert len(worktrees) == 1
        assert worktrees[0].branch == "main"


class TestCreateWorktrees:
    def test_creates_worktree_new_branch(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        results = create_worktrees([repo], "feature-x")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].repo == "myrepo"
        assert results[0].worktree_path
        assert Path(results[0].worktree_path).exists()

    def test_creates_worktree_existing_branch(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        _git(["branch", "existing-branch"], cwd=str(repo))

        results = create_worktrees([repo], "existing-branch")
        assert results[0].success is True

    def test_creates_worktrees_multiple_repos(self, tmp_path):
        repo1 = _make_repo(tmp_path, "frontend")
        repo2 = _make_repo(tmp_path, "backend")

        results = create_worktrees([repo1, repo2], "feature-y")
        assert all(r.success for r in results)
        assert len(results) == 2
        assert results[0].repo == "frontend"
        assert results[1].repo == "backend"

    def test_skips_existing_worktree(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        create_worktrees([repo], "feat")
        # Second call should skip gracefully
        results = create_worktrees([repo], "feat")
        assert results[0].success is True
        assert "already exists" in results[0].message

    def test_non_git_dir(self, tmp_path):
        not_git = tmp_path / "notgit"
        not_git.mkdir()
        results = create_worktrees([not_git], "branch")
        assert results[0].success is False
        assert "Not a git repository" in results[0].message

    def test_custom_base_dir(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        base = tmp_path / "my-worktrees"
        results = create_worktrees([repo], "feat", base_dir=base)
        assert results[0].success is True
        assert str(base) in results[0].worktree_path


class TestListWorktrees:
    def test_lists_main_worktree(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        results = list_worktrees([repo])
        assert results[0].success is True
        assert len(results[0].worktrees) >= 1
        branches = [wt.branch for wt in results[0].worktrees]
        assert "main" in branches

    def test_lists_created_worktree(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        create_worktrees([repo], "feature-z")
        results = list_worktrees([repo])
        assert results[0].success is True
        branches = [wt.branch for wt in results[0].worktrees]
        assert "main" in branches
        assert "feature-z" in branches

    def test_non_git_dir(self, tmp_path):
        not_git = tmp_path / "notgit"
        not_git.mkdir()
        results = list_worktrees([not_git])
        assert results[0].success is False


class TestRemoveWorktrees:
    def test_removes_worktree(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        create_results = create_worktrees([repo], "to-remove")
        assert create_results[0].success is True
        wt_path = create_results[0].worktree_path

        remove_results = remove_worktrees([repo], "to-remove")
        assert remove_results[0].success is True
        assert not Path(wt_path).exists()

    def test_remove_nonexistent_branch(self, tmp_path):
        repo = _make_repo(tmp_path, "myrepo")
        results = remove_worktrees([repo], "nonexistent")
        assert results[0].success is True
        assert "No worktree found" in results[0].message

    def test_remove_multiple_repos(self, tmp_path):
        repo1 = _make_repo(tmp_path, "frontend")
        repo2 = _make_repo(tmp_path, "backend")
        create_worktrees([repo1, repo2], "shared-branch")
        results = remove_worktrees([repo1, repo2], "shared-branch")
        assert all(r.success for r in results)
