"""Tests for subdirectory scanning."""

import json
from pathlib import Path

import pytest

from bobthebuilder.detector import detect_project
from bobthebuilder.models import Ecosystem
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


class TestSubdirectoryDetection:
    def test_detects_python_in_subdir(self, tmp_project):
        """Like Immich's machine-learning/ subdirectory."""
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "root"}),
                "pnpm-lock.yaml": "",
                "machine-learning/pyproject.toml": "[project]\nname='ml'",
                "machine-learning/uv.lock": "",
            }
        )
        ctx = detect_project(root)
        assert Ecosystem.NODE in ctx.ecosystems
        assert Ecosystem.PYTHON in ctx.ecosystems
        assert ctx.python_tool == "uv"

    def test_detects_docker_in_subdir(self, tmp_project):
        """Like Immich's docker/ subdirectory."""
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "root"}),
                "docker/docker-compose.yml": "services:\n  db:\n    image: postgres",
            }
        )
        ctx = detect_project(root)
        assert ctx.has_docker_compose

    def test_subdir_steps_include_working_dir(self, tmp_project):
        """Steps for subdirectory projects should specify working_dir."""
        root = tmp_project(
            {
                "machine-learning/pyproject.toml": "[project]\nname='ml'",
                "machine-learning/uv.lock": "",
            }
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        assert len(steps) > 0
        # The Python step should have working_dir set
        python_step = next(s for s in steps if s.ecosystem == Ecosystem.PYTHON)
        assert python_step.working_dir is not None
        assert "machine-learning" in python_step.working_dir

    def test_ignores_node_modules(self, tmp_project):
        """Should not scan inside node_modules."""
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "root"}),
                "node_modules/some-pkg/package.json": json.dumps({"name": "dep"}),
            }
        )
        ctx = detect_project(root)
        # Should only detect root package.json, not the one in node_modules
        assert ctx.node_package_manager == "npm"
        # Should not have duplicate ecosystems
        assert ctx.ecosystems.count(Ecosystem.NODE) == 1

    def test_ignores_venv(self, tmp_project):
        """Should not scan inside .venv or venv."""
        root = tmp_project(
            {
                "pyproject.toml": "[project]\nname='root'",
                ".venv/lib/python3.11/site-packages/something/setup.py": "",
                "venv/lib/setup.py": "",
            }
        )
        ctx = detect_project(root)
        assert ctx.ecosystems.count(Ecosystem.PYTHON) == 1

    def test_ignores_hidden_dirs(self, tmp_project):
        """Should not scan inside .git, .github, etc."""
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "root"}),
                ".git/hooks/package.json": json.dumps({"name": "gitpkg"}),
            }
        )
        ctx = detect_project(root)
        assert ctx.ecosystems.count(Ecosystem.NODE) == 1

    def test_max_depth_limit(self, tmp_project):
        """Should not recurse too deep."""
        root = tmp_project(
            {
                "a/b/c/d/e/pyproject.toml": "[project]\nname='deep'",
            }
        )
        ctx = detect_project(root)
        # Depth 5 should be ignored (max depth = 3)
        assert Ecosystem.PYTHON not in ctx.ecosystems

    def test_multiple_subdirs_detected(self, tmp_project):
        """Detect different ecosystems in different subdirs."""
        root = tmp_project(
            {
                "frontend/package.json": json.dumps({"name": "fe"}),
                "frontend/package-lock.json": "{}",
                "backend/pyproject.toml": "[project]\nname='be'",
                "backend/uv.lock": "",
                "services/go.mod": "module example.com/svc\n\ngo 1.21",
            }
        )
        ctx = detect_project(root)
        assert Ecosystem.NODE in ctx.ecosystems
        assert Ecosystem.PYTHON in ctx.ecosystems
        assert Ecosystem.GO in ctx.ecosystems

    def test_subdir_env_template_detected(self, tmp_project):
        """Detect .env.example in subdirectories."""
        root = tmp_project(
            {
                "backend/pyproject.toml": "[project]\nname='be'",
                "backend/.env.example": "DB_HOST=localhost",
            }
        )
        ctx = detect_project(root)
        assert len(ctx.env_example_files) > 0

    def test_root_takes_priority_over_subdir(self, tmp_project):
        """If root has a Python project and subdir too, root config wins for tool detection."""
        root = tmp_project(
            {
                "pyproject.toml": "[project]\nname='root'",
                "uv.lock": "",
                "subpkg/pyproject.toml": "[project]\nname='sub'",
                "subpkg/requirements.txt": "flask",
            }
        )
        ctx = detect_project(root)
        # Root uv.lock should be the detected tool
        assert ctx.python_tool == "uv"
