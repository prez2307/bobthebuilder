"""Tests for pre/post hooks."""

import pytest

from bobthebuilder.hooks import HookConfig, run_hook


class TestHookConfig:
    def test_from_dict_empty(self):
        config = HookConfig.from_dict(None)
        assert config.pre_build is None
        assert config.post_build is None

    def test_from_dict_with_hooks(self):
        config = HookConfig.from_dict({
            "pre_build": "cp config.example config.yml",
            "post_build": "python manage.py migrate",
        })
        assert config.pre_build == ["cp", "config.example", "config.yml"]
        assert config.post_build == ["python", "manage.py", "migrate"]

    def test_from_dict_with_list(self):
        config = HookConfig.from_dict({
            "pre_build": ["echo", "hello world"],
        })
        assert config.pre_build == ["echo", "hello world"]

    def test_get_hooks_build(self):
        config = HookConfig.from_dict({
            "pre_build": "echo before",
            "post_build": "echo after",
        })
        pre, post = config.get_hooks("build")
        assert pre == ["echo", "before"]
        assert post == ["echo", "after"]

    def test_get_hooks_run(self):
        config = HookConfig.from_dict({
            "pre_run": "docker compose up -d postgres",
        })
        pre, post = config.get_hooks("run")
        assert pre == ["docker", "compose", "up", "-d", "postgres"]
        assert post is None

    def test_get_hooks_test(self):
        config = HookConfig.from_dict({
            "pre_test": "docker compose up -d",
            "post_test": "docker compose down",
        })
        pre, post = config.get_hooks("test")
        assert pre is not None
        assert post is not None

    def test_to_dict(self):
        config = HookConfig.from_dict({
            "pre_build": "echo before",
            "post_build": "echo after",
        })
        d = config.to_dict()
        assert "pre_build" in d
        assert "post_build" in d

    def test_to_dict_empty(self):
        config = HookConfig()
        assert config.to_dict() == {}


class TestRunHook:
    def test_runs_allowed_command(self, tmp_path):
        result = run_hook("test-hook", ["echo", "hello"], cwd=str(tmp_path))
        assert result.success is True
        assert "hello" in result.stdout

    def test_blocks_unsafe_command(self, tmp_path):
        result = run_hook("test-hook", ["rm", "-rf", "/"], cwd=str(tmp_path))
        assert result.success is False
        assert "blocked" in result.error

    def test_dry_run(self, tmp_path):
        result = run_hook("test-hook", ["echo", "hello"], cwd=str(tmp_path), dry_run=True)
        assert result.success is True
        assert result.stdout == ""  # nothing actually ran

    def test_command_not_found(self, tmp_path):
        result = run_hook("test-hook", ["nonexistent_binary_xyz"], cwd=str(tmp_path))
        assert result.success is False
        assert "not found" in result.error.lower() or "blocked" in result.error.lower()

    def test_has_duration(self, tmp_path):
        result = run_hook("test-hook", ["echo", "hi"], cwd=str(tmp_path))
        assert result.duration_s >= 0
