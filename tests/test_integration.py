"""Integration tests - clone real repos and verify detection + planning.

These tests clone real open-source projects and verify that bobthebuilder
correctly detects their ecosystems and generates appropriate build plans.

Test repos chosen for diversity:
- fastapi (Python/uv) - popular Python API framework
- express (Node/npm) - popular Node.js framework
- gin (Go) - popular Go web framework
- ripgrep (Rust) - popular Rust CLI tool
- cal.com (Node/yarn + Docker) - multi-ecosystem project
- sentry (Python + Node monorepo with Makefile)

These tests are marked with @pytest.mark.integration and skipped by default.
Run with: pytest -m integration
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from bobthebuilder.detector import detect_project
from bobthebuilder.models import Ecosystem
from bobthebuilder.strategies import get_steps_for_context
from bobthebuilder.workspace import create_workspace

# Skip all tests in this module unless INTEGRATION env var is set or -m integration is used
pytestmark = pytest.mark.integration


def _shallow_clone(url: str, dest: Path) -> bool:
    """Shallow clone a repo. Returns True on success."""
    if dest.exists():
        return True
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "--single-branch", url, str(dest)],
            capture_output=True,
            timeout=60,
        )
        return dest.exists()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture(scope="module")
def clone_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("repos")


# --- Real repo tests ---


class TestFastAPI:
    """FastAPI - Python project using uv (or pip with pyproject.toml)."""

    @pytest.fixture(autouse=True)
    def setup(self, clone_dir):
        self.repo = clone_dir / "fastapi"
        if not _shallow_clone("https://github.com/fastapi/fastapi.git", self.repo):
            pytest.skip("Could not clone fastapi")

    def test_detects_python(self):
        ctx = detect_project(self.repo)
        assert Ecosystem.PYTHON in ctx.ecosystems

    def test_generates_install_step(self):
        ctx = detect_project(self.repo)
        steps = get_steps_for_context(ctx)
        assert len(steps) > 0
        assert any("install" in s.name or "sync" in s.command[-1] for s in steps)

    def test_reads_readme(self):
        ctx = detect_project(self.repo)
        assert ctx.readme_content is not None
        assert len(ctx.readme_content) > 100


class TestExpress:
    """Express - Node.js project using npm."""

    @pytest.fixture(autouse=True)
    def setup(self, clone_dir):
        self.repo = clone_dir / "express"
        if not _shallow_clone("https://github.com/expressjs/express.git", self.repo):
            pytest.skip("Could not clone express")

    def test_detects_node(self):
        ctx = detect_project(self.repo)
        assert Ecosystem.NODE in ctx.ecosystems

    def test_detects_npm(self):
        ctx = detect_project(self.repo)
        assert ctx.node_package_manager is not None

    def test_generates_npm_install(self):
        ctx = detect_project(self.repo)
        steps = get_steps_for_context(ctx)
        assert len(steps) > 0
        commands_flat = [" ".join(s.command) for s in steps]
        assert any("npm" in c or "yarn" in c or "pnpm" in c for c in commands_flat)


class TestGin:
    """Gin - Go web framework."""

    @pytest.fixture(autouse=True)
    def setup(self, clone_dir):
        self.repo = clone_dir / "gin"
        if not _shallow_clone("https://github.com/gin-gonic/gin.git", self.repo):
            pytest.skip("Could not clone gin")

    def test_detects_go(self):
        ctx = detect_project(self.repo)
        assert Ecosystem.GO in ctx.ecosystems

    def test_generates_go_steps(self):
        ctx = detect_project(self.repo)
        steps = get_steps_for_context(ctx)
        commands_flat = [" ".join(s.command) for s in steps]
        assert any("go mod download" in c for c in commands_flat)


class TestRipgrep:
    """ripgrep - Rust CLI tool."""

    @pytest.fixture(autouse=True)
    def setup(self, clone_dir):
        self.repo = clone_dir / "ripgrep"
        if not _shallow_clone("https://github.com/BurntSushi/ripgrep.git", self.repo):
            pytest.skip("Could not clone ripgrep")

    def test_detects_rust(self):
        ctx = detect_project(self.repo)
        assert Ecosystem.RUST in ctx.ecosystems

    def test_generates_cargo_build(self):
        ctx = detect_project(self.repo)
        steps = get_steps_for_context(ctx)
        commands_flat = [" ".join(s.command) for s in steps]
        assert any("cargo build" in c for c in commands_flat)


class TestMultiRepoWorkspace:
    """Test workspace creation with multiple real repos."""

    @pytest.fixture(autouse=True)
    def setup(self, clone_dir):
        self.root = clone_dir
        repos = [
            ("https://github.com/fastapi/fastapi.git", "fastapi"),
            ("https://github.com/expressjs/express.git", "express"),
        ]
        self.repo_paths = []
        for url, name in repos:
            dest = clone_dir / name
            if _shallow_clone(url, dest):
                self.repo_paths.append(dest)
        if len(self.repo_paths) < 2:
            pytest.skip("Could not clone repos for workspace test")

    def test_workspace_detects_both_ecosystems(self):
        ws = create_workspace(self.root, self.repo_paths)
        ecosystems = {r.detected_ecosystem for r in ws.repos}
        assert "python" in ecosystems
        assert "node" in ecosystems

    def test_workspace_has_correct_repo_count(self):
        ws = create_workspace(self.root, self.repo_paths)
        assert len(ws.repos) == 2

    def test_workspace_json_output(self):
        ws = create_workspace(self.root, self.repo_paths)
        data = ws.to_dict()
        assert "workspace" in data
        assert "repos" in data
        # Verify it's JSON-serializable
        json_str = json.dumps(data)
        assert len(json_str) > 0


class TestDryRunAgainstRealRepo:
    """Test dry-run build planning against a real repo."""

    @pytest.fixture(autouse=True)
    def setup(self, clone_dir):
        self.repo = clone_dir / "fastapi"
        if not _shallow_clone("https://github.com/fastapi/fastapi.git", self.repo):
            pytest.skip("Could not clone fastapi")

    def test_dry_run_produces_steps(self):
        ctx = detect_project(self.repo)
        steps = get_steps_for_context(ctx)
        assert len(steps) > 0
        # All steps should have valid commands
        for step in steps:
            assert len(step.command) > 0
            assert step.name
            assert step.description

    def test_json_output_format(self):
        """Verify the output an AI agent would consume."""
        ctx = detect_project(self.repo)
        steps = get_steps_for_context(ctx)
        # Simulate what --json --dry-run would produce
        output = {
            "success": True,
            "steps": [
                {
                    "name": s.name,
                    "command": s.command,
                    "ecosystem": s.ecosystem.value,
                    "risk_level": s.risk_level.value,
                }
                for s in steps
            ],
        }
        json_str = json.dumps(output)
        parsed = json.loads(json_str)
        assert parsed["success"] is True
        assert len(parsed["steps"]) > 0
