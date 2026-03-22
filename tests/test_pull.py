"""Tests for bob pull command."""

import subprocess
from pathlib import Path

import pytest
import yaml

from bobthebuilder.workspace import load_workspace

# Git env that disables signing for tests
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/tmp", "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com", "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com"}


def _git(args, cwd=None):
    """Run git command without signing."""
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"] + args,
        cwd=cwd, capture_output=True, text=True, env={**GIT_ENV, "PATH": subprocess.os.environ.get("PATH", "")},
    )


class TestPullCommand:
    def _make_repo_with_remote(self, tmp_path, name):
        """Create a local git repo with a bare remote for pulling."""
        source = tmp_path / f"{name}-source"
        source.mkdir()
        _git(["init", "--initial-branch=main", str(source)])
        (source / "file.txt").write_text("initial")
        _git(["add", "."], cwd=str(source))
        _git(["commit", "-m", "init"], cwd=str(source))

        bare = tmp_path / f"{name}-bare.git"
        _git(["clone", "--bare", str(source), str(bare)])

        repo = tmp_path / name
        _git(["clone", str(bare), str(repo)])

        return repo, bare

    def test_pull_updates_repo(self, tmp_path):
        """bob pull should update repos to latest."""
        from bobthebuilder.puller import pull_repos

        repo, bare = self._make_repo_with_remote(tmp_path, "myrepo")

        # Push a new commit from another clone
        other = tmp_path / "other"
        _git(["clone", str(bare), str(other)])
        (other / "new-file.txt").write_text("new content")
        _git(["add", "."], cwd=str(other))
        _git(["commit", "-m", "new commit"], cwd=str(other))
        _git(["push"], cwd=str(other))

        # Now pull
        results = pull_repos([repo])
        assert results[0].success is True
        assert (repo / "new-file.txt").exists()

    def test_pull_reports_already_up_to_date(self, tmp_path):
        from bobthebuilder.puller import pull_repos

        repo, bare = self._make_repo_with_remote(tmp_path, "myrepo2")
        results = pull_repos([repo])
        assert results[0].success is True

    def test_pull_non_git_dir(self, tmp_path):
        """Pulling a non-git directory should report failure gracefully."""
        from bobthebuilder.puller import pull_repos

        non_git = tmp_path / "not-a-repo"
        non_git.mkdir()

        results = pull_repos([non_git])
        assert results[0].success is False
