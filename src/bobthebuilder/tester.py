"""Test runner - detect and run test suites per ecosystem."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .detector import detect_project
from .models import Ecosystem


# Scripts in package.json that indicate a test suite (priority order)
NODE_TEST_SCRIPTS = ["test", "test:unit", "test:all", "spec"]

# Makefile targets that indicate a test command
MAKE_TEST_TARGETS = ["test", "tests", "check", "spec"]


@dataclass
class TestConfig:
    """Detected test configuration for a project."""

    path: str
    command: list[str]
    description: str
    ecosystem: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "command": self.command,
            "description": self.description,
            "ecosystem": self.ecosystem,
        }


def detect_test_command(project_path: Path) -> TestConfig | None:
    """Detect how to run tests in the given project directory."""
    ctx = detect_project(project_path)

    for ecosystem in ctx.root_ecosystems:
        config = None
        if ecosystem == Ecosystem.NODE:
            config = _detect_node_test(project_path, ctx)
        elif ecosystem == Ecosystem.PYTHON:
            config = _detect_python_test(project_path, ctx)
        elif ecosystem == Ecosystem.GO:
            config = _detect_go_test(project_path)
        elif ecosystem == Ecosystem.RUST:
            config = _detect_rust_test(project_path)
        elif ecosystem == Ecosystem.RUBY:
            config = _detect_ruby_test(project_path)
        if config:
            return config

    # Fallback: Makefile test targets
    if ctx.makefile_targets:
        for target in MAKE_TEST_TARGETS:
            if target in ctx.makefile_targets:
                return TestConfig(
                    path=str(project_path),
                    command=["make", target],
                    description=f"make {target}",
                    ecosystem="make",
                )

    return None


def _detect_node_test(project_path: Path, ctx) -> TestConfig | None:
    """Detect Node.js test command from package.json scripts."""
    pm = ctx.node_package_manager or "npm"

    for script in NODE_TEST_SCRIPTS:
        if script in ctx.node_scripts:
            return TestConfig(
                path=str(project_path),
                command=[pm, "run" if script != "test" else "test"] if script == "test" else [pm, "run", script],
                description=f"{pm} {'test' if script == 'test' else f'run {script}'}",
                ecosystem="node",
            )

    return None


def _detect_python_test(project_path: Path, ctx) -> TestConfig | None:
    """Detect Python test command."""
    tool = ctx.python_tool

    # Check for pytest (most common)
    has_pytest_config = any([
        (project_path / "pytest.ini").exists(),
        (project_path / "conftest.py").exists(),
        (project_path / "tests").is_dir(),
        (project_path / "test").is_dir(),
    ])

    # Check pyproject.toml for pytest config
    if not has_pytest_config:
        pyproject = project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                if "[tool.pytest" in content or "pytest" in content.lower():
                    has_pytest_config = True
            except OSError:
                pass

    # Check setup.cfg for pytest config
    if not has_pytest_config:
        setup_cfg = project_path / "setup.cfg"
        if setup_cfg.exists():
            try:
                content = setup_cfg.read_text()
                if "[tool:pytest]" in content:
                    has_pytest_config = True
            except OSError:
                pass

    if has_pytest_config:
        if tool == "uv":
            cmd = ["uv", "run", "pytest"]
        elif tool == "poetry":
            cmd = ["poetry", "run", "pytest"]
        else:
            cmd = ["python", "-m", "pytest"]
        return TestConfig(
            path=str(project_path),
            command=cmd,
            description=" ".join(cmd),
            ecosystem="python",
        )

    # Check for unittest (manage.py test for Django)
    if (project_path / "manage.py").exists():
        if tool == "uv":
            cmd = ["uv", "run", "python", "manage.py", "test"]
        elif tool == "poetry":
            cmd = ["poetry", "run", "python", "manage.py", "test"]
        else:
            cmd = ["python", "manage.py", "test"]
        return TestConfig(
            path=str(project_path),
            command=cmd,
            description=" ".join(cmd),
            ecosystem="python",
        )

    return None


def _detect_go_test(project_path: Path) -> TestConfig | None:
    """Detect Go test command."""
    if (project_path / "go.mod").exists():
        return TestConfig(
            path=str(project_path),
            command=["go", "test", "./..."],
            description="go test ./...",
            ecosystem="go",
        )
    return None


def _detect_rust_test(project_path: Path) -> TestConfig | None:
    """Detect Rust test command."""
    if (project_path / "Cargo.toml").exists():
        return TestConfig(
            path=str(project_path),
            command=["cargo", "test"],
            description="cargo test",
            ecosystem="rust",
        )
    return None


def _detect_ruby_test(project_path: Path) -> TestConfig | None:
    """Detect Ruby test command."""
    # RSpec
    if (project_path / ".rspec").exists() or (project_path / "spec").is_dir():
        return TestConfig(
            path=str(project_path),
            command=["bundle", "exec", "rspec"],
            description="bundle exec rspec",
            ecosystem="ruby",
        )

    # Minitest / Rails
    if (project_path / "test").is_dir():
        if (project_path / "bin" / "rails").exists():
            return TestConfig(
                path=str(project_path),
                command=["bundle", "exec", "rails", "test"],
                description="bundle exec rails test",
                ecosystem="ruby",
            )
        return TestConfig(
            path=str(project_path),
            command=["bundle", "exec", "rake", "test"],
            description="bundle exec rake test",
            ecosystem="ruby",
        )

    return None
