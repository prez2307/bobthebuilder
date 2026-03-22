"""Tests for git clone support in bob init."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bobthebuilder.workspace import create_workspace, clone_repo

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/tmp", "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com", "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com"}


def _git(args, cwd=None):
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false"] + args,
        cwd=cwd, capture_output=True, text=True, env={**GIT_ENV, "PATH": subprocess.os.environ.get("PATH", "")},
    )


class TestCloneRepo:
    def test_clones_to_target_dir(self, tmp_path):
        """Test clone_repo actually clones (integration-ish, uses git)."""
        dest = tmp_path / "test-repo"
        source = tmp_path / "source"
        source.mkdir()
        _git(["init", "--initial-branch=main", str(source)])
        (source / "f.txt").write_text("hi")
        _git(["add", "."], cwd=str(source))
        _git(["commit", "-m", "init"], cwd=str(source))
        bare = tmp_path / "bare.git"
        _git(["clone", "--bare", str(source), str(bare)])

        result = clone_repo(str(bare), dest)
        assert result is True
        assert dest.exists()
        assert (dest / ".git").exists()

    def test_skips_if_already_exists(self, tmp_path):
        """If target directory exists, skip clone."""
        dest = tmp_path / "existing"
        dest.mkdir()
        (dest / "file.txt").write_text("already here")

        result = clone_repo("https://example.com/fake.git", dest)
        assert result is True  # success, but skipped
        assert (dest / "file.txt").exists()

    def test_returns_false_on_failure(self, tmp_path):
        """Bad URL returns False."""
        dest = tmp_path / "bad-clone"
        result = clone_repo("https://invalid-url-that-doesnt-exist.example.com/repo.git", dest)
        assert result is False

    def test_clone_has_files(self, tmp_path):
        """Clone should have the repo's files."""
        source = tmp_path / "source"
        source.mkdir()
        _git(["init", "--initial-branch=main", str(source)])
        (source / "file.txt").write_text("content")
        _git(["add", "."], cwd=str(source))
        _git(["commit", "-m", "init"], cwd=str(source))

        bare = tmp_path / "bare.git"
        _git(["clone", "--bare", str(source), str(bare)])

        dest = tmp_path / "cloned"
        clone_repo(str(bare), dest)
        assert (dest / "file.txt").exists()
        assert (dest / "file.txt").read_text() == "content"


class TestInitWithUrls:
    def test_workspace_with_mixed_paths_and_urls(self, tmp_path):
        """bob init should handle both local paths and git URLs."""
        local_repo = tmp_path / "local-source"
        local_repo.mkdir()
        _git(["init", "--initial-branch=main", str(local_repo)])
        (local_repo / "package.json").write_text('{"name": "test"}')
        _git(["add", "."], cwd=str(local_repo))
        _git(["commit", "-m", "init"], cwd=str(local_repo))

        # Create a local path project
        local_path = tmp_path / "already-here"
        local_path.mkdir()
        (local_path / "pyproject.toml").write_text("[project]\nname='test'")

        ws = create_workspace(
            tmp_path,
            repo_paths=[local_path],
            clone_urls=[(str(local_repo), "cloned-repo")],
        )
        assert len(ws.repos) == 2
