"""Tests for ecosystem strategies."""

import json
from pathlib import Path

import pytest

from bobthebuilder.detector import detect_project
from bobthebuilder.models import BuildStep, Ecosystem, RiskLevel
from bobthebuilder.strategies import get_steps_for_context


@pytest.fixture
def tmp_project(tmp_path):
    def _create(files: dict[str, str | None] = None):
        files = files or {}
        for name, content in files.items():
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content or "")
        return tmp_path

    return _create


# --- Node strategies ---


class TestNodeStrategy:
    def test_npm_ci_with_lockfile(self, tmp_project):
        root = tmp_project(
            {"package.json": json.dumps({"name": "test"}), "package-lock.json": "{}"}
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["npm", "ci"] in commands

    def test_yarn_install_with_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"}), "yarn.lock": ""})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["yarn", "install", "--frozen-lockfile"] in commands

    def test_pnpm_install_with_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"}), "pnpm-lock.yaml": ""})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["pnpm", "install", "--frozen-lockfile"] in commands

    def test_bun_install_with_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"}), "bun.lockb": ""})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["bun", "install"] in commands

    def test_npm_install_no_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"})})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["npm", "install"] in commands

    def test_build_script_detected(self, tmp_project):
        root = tmp_project(
            {
                "package.json": json.dumps(
                    {"name": "test", "scripts": {"build": "tsc", "test": "jest"}}
                ),
                "package-lock.json": "{}",
            }
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["npm", "run", "build"] in commands
        # test script should NOT be auto-run
        assert ["npm", "run", "test"] not in commands


# --- Python strategies ---


class TestPythonStrategy:
    def test_uv_sync(self, tmp_project):
        root = tmp_project({"pyproject.toml": "[project]\nname='test'", "uv.lock": ""})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["uv", "sync"] in commands

    def test_poetry_install(self, tmp_project):
        root = tmp_project({"pyproject.toml": "[project]\nname='test'", "poetry.lock": ""})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["poetry", "install"] in commands

    def test_pipenv_install(self, tmp_project):
        root = tmp_project({"Pipfile": "", "Pipfile.lock": ""})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["pipenv", "install"] in commands

    def test_pip_requirements(self, tmp_project):
        root = tmp_project({"requirements.txt": "flask\nrequests"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["pip", "install", "-r", "requirements.txt"] in commands

    def test_pip_editable_pyproject(self, tmp_project):
        root = tmp_project({"pyproject.toml": "[project]\nname='test'"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["pip", "install", "-e", "."] in commands


# --- Go strategies ---


class TestGoStrategy:
    def test_go_mod_download(self, tmp_project):
        root = tmp_project({"go.mod": "module example.com/test\n\ngo 1.21"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["go", "mod", "download"] in commands

    def test_go_build(self, tmp_project):
        root = tmp_project({"go.mod": "module example.com/test\n\ngo 1.21"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["go", "build", "./..."] in commands


# --- Rust strategies ---


class TestRustStrategy:
    def test_cargo_build(self, tmp_project):
        root = tmp_project({"Cargo.toml": '[package]\nname = "test"'})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["cargo", "build"] in commands


# --- Ruby strategies ---


class TestRubyStrategy:
    def test_bundle_install(self, tmp_project):
        root = tmp_project({"Gemfile": 'gem "rails"', "Gemfile.lock": ""})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["bundle", "install"] in commands

    def test_bundle_install_no_lock(self, tmp_project):
        root = tmp_project({"Gemfile": 'gem "sinatra"'})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["bundle", "install"] in commands


# --- Docker strategies ---


class TestDockerStrategy:
    def test_docker_compose_with_flag(self, tmp_project):
        root = tmp_project({"docker-compose.yml": "version: '3'\nservices:\n  db:\n    image: postgres"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx, docker_flag=True)
        commands = [s.command for s in steps]
        assert ["docker", "compose", "up", "-d"] in commands

    def test_docker_compose_without_flag(self, tmp_project):
        root = tmp_project({"docker-compose.yml": "version: '3'"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx, docker_flag=False)
        commands = [s.command for s in steps]
        assert ["docker", "compose", "up", "-d"] not in commands


# --- Env strategies ---


class TestEnvStrategy:
    def test_copies_env_example(self, tmp_project):
        root = tmp_project({".env.example": "DB_HOST=localhost"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        assert any(s.name == "copy-env" for s in steps)
        env_step = next(s for s in steps if s.name == "copy-env")
        assert ".env.example" in env_step.command
        assert ".env" in env_step.command

    def test_no_copy_if_env_exists(self, tmp_project):
        root = tmp_project({".env.example": "DB_HOST=localhost", ".env": "DB_HOST=prod"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        assert not any(s.name == "copy-env" for s in steps)


# --- Ordering ---


class TestStepOrdering:
    def test_env_before_install(self, tmp_project):
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "test"}),
                "package-lock.json": "{}",
                ".env.example": "KEY=val",
            }
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        names = [s.name for s in steps]
        env_idx = names.index("copy-env")
        install_idx = names.index("install-deps")
        assert env_idx < install_idx

    def test_install_before_build(self, tmp_project):
        root = tmp_project(
            {
                "package.json": json.dumps(
                    {"name": "test", "scripts": {"build": "tsc"}}
                ),
                "package-lock.json": "{}",
            }
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        names = [s.name for s in steps]
        install_idx = names.index("install-deps")
        build_idx = names.index("build")
        assert install_idx < build_idx


# --- Risk levels ---


class TestRiskLevels:
    def test_install_is_low_risk(self, tmp_project):
        root = tmp_project(
            {"package.json": json.dumps({"name": "test"}), "package-lock.json": "{}"}
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        install = next(s for s in steps if s.name == "install-deps")
        assert install.risk_level == RiskLevel.LOW

    def test_docker_is_medium_risk(self, tmp_project):
        root = tmp_project({"docker-compose.yml": "version: '3'\nservices:\n  app:\n    image: node"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx, docker_flag=True)
        docker_step = next(s for s in steps if s.ecosystem == Ecosystem.DOCKER)
        assert docker_step.risk_level == RiskLevel.MEDIUM
