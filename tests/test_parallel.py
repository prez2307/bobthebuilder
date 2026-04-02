"""Tests for parallel build execution."""

import time
from pathlib import Path

import pytest

from bobthebuilder.executor import ExecutionResult
from bobthebuilder.parallel import RepoResult, build_repos_parallel


class TestRepoResult:
    def test_success_when_all_pass(self):
        rr = RepoResult(
            repo_name="test",
            repo_path="/tmp/test",
            results=[
                ExecutionResult(step_name="a", success=True),
                ExecutionResult(step_name="b", success=True),
            ],
        )
        assert rr.success is True

    def test_failure_when_any_fails(self):
        rr = RepoResult(
            repo_name="test",
            repo_path="/tmp/test",
            results=[
                ExecutionResult(step_name="a", success=True),
                ExecutionResult(step_name="b", success=False),
            ],
        )
        assert rr.success is False

    def test_to_dict(self):
        rr = RepoResult(
            repo_name="test",
            repo_path="/tmp/test",
            results=[ExecutionResult(step_name="a", success=True)],
            duration_s=1.5,
        )
        d = rr.to_dict()
        assert d["repo"] == "test"
        assert d["success"] is True
        assert d["duration_s"] == 1.5


class TestBuildReposParallel:
    def test_single_repo(self):
        def build_fn():
            return [ExecutionResult(step_name="install", success=True)]

        results = build_repos_parallel([("repo1", Path("/tmp/repo1"), build_fn)])
        assert len(results) == 1
        assert results[0].success is True

    def test_multiple_repos(self):
        def build_fn_a():
            return [ExecutionResult(step_name="install", success=True)]

        def build_fn_b():
            return [ExecutionResult(step_name="install", success=True)]

        results = build_repos_parallel([
            ("repo1", Path("/tmp/repo1"), build_fn_a),
            ("repo2", Path("/tmp/repo2"), build_fn_b),
        ])
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_preserves_order(self):
        def make_fn(name):
            def fn():
                return [ExecutionResult(step_name=name, success=True)]
            return fn

        tasks = [
            ("alpha", Path("/tmp/alpha"), make_fn("alpha")),
            ("beta", Path("/tmp/beta"), make_fn("beta")),
            ("gamma", Path("/tmp/gamma"), make_fn("gamma")),
        ]
        results = build_repos_parallel(tasks)
        assert [r.repo_name for r in results] == ["alpha", "beta", "gamma"]

    def test_handles_failure(self):
        def fail_fn():
            return [ExecutionResult(step_name="build", success=False, error="compile error")]

        def ok_fn():
            return [ExecutionResult(step_name="build", success=True)]

        results = build_repos_parallel([
            ("good", Path("/tmp/good"), ok_fn),
            ("bad", Path("/tmp/bad"), fail_fn),
        ])
        assert len(results) == 2
        good = next(r for r in results if r.repo_name == "good")
        bad = next(r for r in results if r.repo_name == "bad")
        assert good.success is True
        assert bad.success is False

    def test_handles_exception(self):
        def explode():
            raise RuntimeError("boom")

        results = build_repos_parallel([
            ("broken", Path("/tmp/broken"), explode),
        ])
        assert len(results) == 1
        assert results[0].success is False

    def test_actually_parallel(self):
        """Verify that parallel execution is actually faster than sequential."""
        def slow_fn():
            time.sleep(0.1)
            return [ExecutionResult(step_name="slow", success=True)]

        tasks = [
            (f"repo{i}", Path(f"/tmp/repo{i}"), slow_fn)
            for i in range(4)
        ]

        start = time.monotonic()
        results = build_repos_parallel(tasks, max_workers=4)
        duration = time.monotonic() - start

        assert len(results) == 4
        # If truly parallel, 4 x 0.1s tasks should take ~0.1-0.2s, not 0.4s
        assert duration < 0.35

    def test_empty_tasks(self):
        results = build_repos_parallel([])
        assert results == []
