"""Tests for project detection."""

import json
from pathlib import Path

import pytest

from bobthebuilder.detector import detect_project
from bobthebuilder.models import Ecosystem


@pytest.fixture
def tmp_project(tmp_path):
    """Helper to create a fake project directory with marker files."""

    def _create(files: dict[str, str | None] = None):
        files = files or {}
        for name, content in files.items():
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content or "")
        return tmp_path

    return _create


# --- Node.js detection ---


class TestNodeDetection:
    def test_detects_npm_from_package_lock(self, tmp_project):
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "test", "scripts": {"build": "tsc"}}),
                "package-lock.json": "{}",
            }
        )
        ctx = detect_project(root)
        assert Ecosystem.NODE in ctx.ecosystems
        assert ctx.node_package_manager == "npm"
        assert "build" in ctx.node_scripts

    def test_detects_yarn_from_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"}), "yarn.lock": ""})
        ctx = detect_project(root)
        assert Ecosystem.NODE in ctx.ecosystems
        assert ctx.node_package_manager == "yarn"

    def test_detects_pnpm_from_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"}), "pnpm-lock.yaml": ""})
        ctx = detect_project(root)
        assert Ecosystem.NODE in ctx.ecosystems
        assert ctx.node_package_manager == "pnpm"

    def test_detects_bun_from_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"}), "bun.lockb": ""})
        ctx = detect_project(root)
        assert Ecosystem.NODE in ctx.ecosystems
        assert ctx.node_package_manager == "bun"

    def test_detects_package_manager_field(self, tmp_project):
        root = tmp_project(
            {"package.json": json.dumps({"name": "test", "packageManager": "pnpm@8.0.0"})}
        )
        ctx = detect_project(root)
        assert ctx.node_package_manager == "pnpm"

    def test_defaults_to_npm_no_lockfile(self, tmp_project):
        root = tmp_project({"package.json": json.dumps({"name": "test"})})
        ctx = detect_project(root)
        assert ctx.node_package_manager == "npm"


# --- Python detection ---


class TestPythonDetection:
    def test_detects_uv_from_lockfile(self, tmp_project):
        root = tmp_project({"pyproject.toml": "[project]\nname='test'", "uv.lock": ""})
        ctx = detect_project(root)
        assert Ecosystem.PYTHON in ctx.ecosystems
        assert ctx.python_tool == "uv"

    def test_detects_poetry_from_lockfile(self, tmp_project):
        root = tmp_project({"pyproject.toml": "[project]\nname='test'", "poetry.lock": ""})
        ctx = detect_project(root)
        assert Ecosystem.PYTHON in ctx.ecosystems
        assert ctx.python_tool == "poetry"

    def test_detects_pipenv_from_lockfile(self, tmp_project):
        root = tmp_project({"Pipfile": "", "Pipfile.lock": ""})
        ctx = detect_project(root)
        assert Ecosystem.PYTHON in ctx.ecosystems
        assert ctx.python_tool == "pipenv"

    def test_detects_requirements_txt(self, tmp_project):
        root = tmp_project({"requirements.txt": "flask\nrequests"})
        ctx = detect_project(root)
        assert Ecosystem.PYTHON in ctx.ecosystems
        assert ctx.python_tool == "pip"

    def test_detects_pyproject_no_lock(self, tmp_project):
        root = tmp_project({"pyproject.toml": "[project]\nname='test'"})
        ctx = detect_project(root)
        assert Ecosystem.PYTHON in ctx.ecosystems
        assert ctx.python_tool == "pip"

    def test_uv_takes_priority_over_requirements(self, tmp_project):
        root = tmp_project(
            {
                "pyproject.toml": "[project]\nname='test'",
                "uv.lock": "",
                "requirements.txt": "flask",
            }
        )
        ctx = detect_project(root)
        assert ctx.python_tool == "uv"


# --- Go detection ---


class TestGoDetection:
    def test_detects_go_mod(self, tmp_project):
        root = tmp_project({"go.mod": "module example.com/test\n\ngo 1.21"})
        ctx = detect_project(root)
        assert Ecosystem.GO in ctx.ecosystems


# --- Rust detection ---


class TestRustDetection:
    def test_detects_cargo_toml(self, tmp_project):
        root = tmp_project({"Cargo.toml": '[package]\nname = "test"'})
        ctx = detect_project(root)
        assert Ecosystem.RUST in ctx.ecosystems


# --- Docker detection ---


class TestDockerDetection:
    def test_detects_docker_compose_yml(self, tmp_project):
        root = tmp_project({"docker-compose.yml": "version: '3'"})
        ctx = detect_project(root)
        assert ctx.has_docker_compose

    def test_detects_compose_yaml(self, tmp_project):
        root = tmp_project({"compose.yaml": "services:"})
        ctx = detect_project(root)
        assert ctx.has_docker_compose


# --- Env file detection ---


class TestEnvDetection:
    def test_detects_env_example(self, tmp_project):
        root = tmp_project({".env.example": "DB_HOST=localhost"})
        ctx = detect_project(root)
        assert ".env.example" in ctx.env_example_files

    def test_detects_env_sample(self, tmp_project):
        root = tmp_project({".env.sample": "SECRET_KEY=changeme"})
        ctx = detect_project(root)
        assert ".env.sample" in ctx.env_example_files


# --- Makefile detection ---


class TestMakefileDetection:
    def test_detects_makefile_targets(self, tmp_project):
        root = tmp_project(
            {
                "Makefile": (
                    "install:\n\tnpm install\n\n"
                    "build:\n\tnpm run build\n\n"
                    "test:\n\tnpm test\n"
                )
            }
        )
        ctx = detect_project(root)
        assert "install" in ctx.makefile_targets
        assert "build" in ctx.makefile_targets
        assert "test" in ctx.makefile_targets


# --- Multi-ecosystem detection ---


class TestMultiEcosystem:
    def test_detects_node_and_python(self, tmp_project):
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "frontend"}),
                "package-lock.json": "{}",
                "requirements.txt": "django",
            }
        )
        ctx = detect_project(root)
        assert Ecosystem.NODE in ctx.ecosystems
        assert Ecosystem.PYTHON in ctx.ecosystems

    def test_empty_directory(self, tmp_project):
        root = tmp_project({})
        ctx = detect_project(root)
        assert ctx.ecosystems == []
        assert ctx.marker_files == []

    def test_reads_readme(self, tmp_project):
        root = tmp_project({"README.md": "# My Project\nRun `npm install` to get started."})
        ctx = detect_project(root)
        assert ctx.readme_content is not None
        assert "npm install" in ctx.readme_content
