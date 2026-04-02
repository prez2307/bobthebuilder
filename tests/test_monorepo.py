"""Tests for monorepo workspace detection."""

import json
from pathlib import Path

import pytest

from bobthebuilder.monorepo import detect_monorepo, should_skip_subproject_install


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


class TestDetectMonorepo:
    def test_detects_npm_workspaces(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({
                "name": "monorepo",
                "workspaces": ["packages/*"],
            }),
            "package-lock.json": "{}",
            "packages/core/package.json": json.dumps({"name": "@mono/core"}),
            "packages/web/package.json": json.dumps({"name": "@mono/web"}),
        })
        info = detect_monorepo(root)
        assert info is not None
        assert info.tool == "npm"
        assert info.is_workspace_root is True
        assert "packages/core" in info.packages
        assert "packages/web" in info.packages

    def test_detects_yarn_workspaces(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({
                "name": "monorepo",
                "workspaces": ["packages/*"],
            }),
            "yarn.lock": "",
            "packages/ui/package.json": json.dumps({"name": "@mono/ui"}),
        })
        info = detect_monorepo(root)
        assert info is not None
        assert info.tool == "yarn"

    def test_detects_pnpm_workspace_yaml(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "monorepo"}),
            "pnpm-lock.yaml": "",
            "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n",
            "packages/api/package.json": json.dumps({"name": "@mono/api"}),
        })
        info = detect_monorepo(root)
        assert info is not None
        assert info.tool == "pnpm"

    def test_detects_turborepo(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({
                "name": "turborepo",
                "workspaces": ["apps/*", "packages/*"],
            }),
            "package-lock.json": "{}",
            "turbo.json": "{}",
            "apps/web/package.json": json.dumps({"name": "web"}),
            "packages/ui/package.json": json.dumps({"name": "ui"}),
        })
        info = detect_monorepo(root)
        assert info is not None
        assert info.tool == "turborepo"

    def test_workspaces_as_object(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({
                "name": "monorepo",
                "workspaces": {"packages": ["packages/*"]},
            }),
            "package-lock.json": "{}",
            "packages/lib/package.json": json.dumps({"name": "lib"}),
        })
        info = detect_monorepo(root)
        assert info is not None
        assert "packages/lib" in info.packages

    def test_no_workspaces(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "simple-app"}),
            "package-lock.json": "{}",
        })
        info = detect_monorepo(root)
        assert info is None

    def test_empty_dir(self, tmp_project):
        root = tmp_project({})
        info = detect_monorepo(root)
        assert info is None

    def test_direct_path_workspaces(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({
                "name": "monorepo",
                "workspaces": ["packages/core"],
            }),
            "package-lock.json": "{}",
            "packages/core/package.json": json.dumps({"name": "core"}),
        })
        info = detect_monorepo(root)
        assert info is not None
        assert "packages/core" in info.packages


class TestShouldSkipSubprojectInstall:
    def test_skips_for_workspace_root(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({
                "name": "monorepo",
                "workspaces": ["packages/*"],
            }),
            "package-lock.json": "{}",
            "packages/lib/package.json": json.dumps({"name": "lib"}),
        })
        assert should_skip_subproject_install(root) is True

    def test_does_not_skip_for_regular_project(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "simple-app"}),
            "package-lock.json": "{}",
        })
        assert should_skip_subproject_install(root) is False
