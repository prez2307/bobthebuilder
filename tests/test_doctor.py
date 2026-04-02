"""Tests for bob doctor command."""

import json
from pathlib import Path

import pytest

from bobthebuilder.doctor import ToolCheck, DoctorResult, check_repo, _tools_needed_for_repo


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


class TestToolCheck:
    def test_to_dict(self):
        check = ToolCheck(name="node", installed=True, version="v18.0.0", required=True)
        d = check.to_dict()
        assert d["name"] == "node"
        assert d["installed"] is True
        assert d["version"] == "v18.0.0"
        assert d["required"] is True

    def test_to_dict_with_wanted_version(self):
        check = ToolCheck(name="node", installed=True, version="v20.0.0", required=True, wanted_version="18.17.0")
        d = check.to_dict()
        assert d["wanted_version"] == "18.17.0"


class TestDoctorResult:
    def test_healthy_when_all_required_installed(self):
        result = DoctorResult(
            repo="myrepo",
            ecosystem="node",
            checks=[
                ToolCheck(name="node", installed=True, required=True),
                ToolCheck(name="npm", installed=True, required=True),
                ToolCheck(name="yarn", installed=False, required=False),
            ],
        )
        assert result.healthy is True

    def test_unhealthy_when_required_missing(self):
        result = DoctorResult(
            repo="myrepo",
            ecosystem="node",
            checks=[
                ToolCheck(name="node", installed=False, required=True),
            ],
        )
        assert result.healthy is False

    def test_to_dict(self):
        result = DoctorResult(
            repo="myrepo",
            ecosystem="node",
            checks=[ToolCheck(name="node", installed=True, required=True)],
            warnings=["node_modules not found"],
        )
        d = result.to_dict()
        assert d["repo"] == "myrepo"
        assert d["healthy"] is True
        assert len(d["checks"]) == 1
        assert d["warnings"] == ["node_modules not found"]


class TestCheckRepo:
    def test_checks_node_project(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app"}),
            "package-lock.json": "{}",
        })
        result = check_repo(root)
        assert result.ecosystem == "node"
        # node should be checked
        tool_names = [c.name for c in result.checks]
        assert "node" in tool_names

    def test_checks_python_project(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "uv.lock": "",
        })
        result = check_repo(root)
        assert result.ecosystem == "python"
        tool_names = [c.name for c in result.checks]
        assert "python" in tool_names

    def test_checks_go_project(self, tmp_project):
        root = tmp_project({
            "go.mod": "module example.com/test\n\ngo 1.21",
        })
        result = check_repo(root)
        assert result.ecosystem == "go"
        tool_names = [c.name for c in result.checks]
        assert "go" in tool_names

    def test_checks_rust_project(self, tmp_project):
        root = tmp_project({
            "Cargo.toml": '[package]\nname = "myapp"',
        })
        result = check_repo(root)
        assert result.ecosystem == "rust"

    def test_empty_dir_returns_unknown(self, tmp_project):
        root = tmp_project({})
        result = check_repo(root)
        assert result.ecosystem == "unknown"
        assert "No ecosystem detected" in result.warnings

    def test_reads_nvmrc_version(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app"}),
            "package-lock.json": "{}",
            ".nvmrc": "18.17.0",
        })
        result = check_repo(root)
        node_checks = [c for c in result.checks if c.name == "node"]
        assert len(node_checks) == 1
        assert node_checks[0].wanted_version == "18.17.0"

    def test_warns_missing_node_modules(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app"}),
            "package-lock.json": "{}",
        })
        result = check_repo(root)
        assert any("node_modules" in w for w in result.warnings)


class TestToolsNeeded:
    def test_node_npm(self, tmp_project):
        from bobthebuilder.detector import detect_project
        root = tmp_project({
            "package.json": json.dumps({"name": "app"}),
            "package-lock.json": "{}",
        })
        ctx = detect_project(root)
        needed = _tools_needed_for_repo(ctx)
        assert "node" in needed
        assert "npm" in needed

    def test_python_uv(self, tmp_project):
        from bobthebuilder.detector import detect_project
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "uv.lock": "",
        })
        ctx = detect_project(root)
        needed = _tools_needed_for_repo(ctx)
        assert "python" in needed
        assert "uv" in needed
