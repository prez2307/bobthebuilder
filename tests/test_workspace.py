"""Tests for workspace management (bob.yaml)."""

import json
from pathlib import Path

import pytest
import yaml

from bobthebuilder.workspace import Workspace, WorkspaceRepo, create_workspace, load_workspace


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a tmp dir with some repo-like subdirectories."""

    def _create(repos: dict[str, dict[str, str | None]] = None):
        repos = repos or {}
        for repo_name, files in repos.items():
            repo_dir = tmp_path / repo_name
            repo_dir.mkdir()
            for fname, content in files.items():
                p = repo_dir / fname
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content or "")
        return tmp_path

    return _create


class TestCreateWorkspace:
    def test_creates_bob_yaml(self, tmp_workspace):
        root = tmp_workspace(
            {
                "frontend": {"package.json": json.dumps({"name": "frontend"}), "package-lock.json": "{}"},
                "backend": {"pyproject.toml": "[project]\nname='backend'", "uv.lock": ""},
            }
        )
        ws = create_workspace(root, [root / "frontend", root / "backend"])
        assert ws.name == root.name
        assert len(ws.repos) == 2

        # Check detection results
        fe = next(r for r in ws.repos if "frontend" in r.path)
        assert fe.detected_ecosystem == "node"
        assert fe.detected_package_manager == "npm"

        be = next(r for r in ws.repos if "backend" in r.path)
        assert be.detected_ecosystem == "python"
        assert be.detected_package_manager == "uv"

    def test_saves_and_loads_bob_yaml(self, tmp_workspace):
        root = tmp_workspace(
            {
                "api": {"go.mod": "module example.com/api\n\ngo 1.21"},
            }
        )
        ws = create_workspace(root, [root / "api"])
        ws.save(root / "bob.yaml")

        loaded = load_workspace(root / "bob.yaml")
        assert loaded.name == ws.name
        assert len(loaded.repos) == 1
        assert loaded.repos[0].detected_ecosystem == "go"

    def test_bob_yaml_format(self, tmp_workspace):
        root = tmp_workspace(
            {
                "app": {"Cargo.toml": '[package]\nname = "app"'},
            }
        )
        ws = create_workspace(root, [root / "app"])
        ws.save(root / "bob.yaml")

        raw = yaml.safe_load((root / "bob.yaml").read_text())
        assert "workspace" in raw
        assert "repos" in raw
        assert raw["repos"][0]["detected"]["ecosystem"] == "rust"


class TestWorkspaceModel:
    def test_workspace_repo_from_detection(self, tmp_workspace):
        root = tmp_workspace(
            {"svc": {"package.json": json.dumps({"name": "svc"}), "yarn.lock": ""}}
        )
        ws = create_workspace(root, [root / "svc"])
        repo = ws.repos[0]
        assert repo.detected_ecosystem == "node"
        assert repo.detected_package_manager == "yarn"

    def test_empty_workspace(self, tmp_workspace):
        root = tmp_workspace({})
        ws = create_workspace(root, [])
        assert ws.repos == []
        assert ws.name == root.name
