"""Tests for bob clean command."""

from pathlib import Path

import pytest

from bobthebuilder.cleaner import find_cleanable_dirs, clean_project


@pytest.fixture
def tmp_project(tmp_path):
    def _create(files_and_dirs: dict[str, str | None] = None):
        files_and_dirs = files_and_dirs or {}
        for name, content in files_and_dirs.items():
            p = tmp_path / name
            if content is None:
                # Create directory
                p.mkdir(parents=True, exist_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
        return tmp_path

    return _create


class TestFindCleanableDirs:
    def test_finds_node_modules(self, tmp_project):
        root = tmp_project({"node_modules/.keep": ""})
        dirs = find_cleanable_dirs(root)
        assert any("node_modules" in str(d) for d in dirs)

    def test_finds_venv(self, tmp_project):
        root = tmp_project({".venv/bin/python": ""})
        dirs = find_cleanable_dirs(root)
        assert any(".venv" in str(d) for d in dirs)

    def test_finds_python_venv(self, tmp_project):
        root = tmp_project({"venv/bin/python": ""})
        dirs = find_cleanable_dirs(root)
        assert any(d.name == "venv" for d in dirs)

    def test_finds_rust_target(self, tmp_project):
        root = tmp_project({"target/debug/.keep": ""})
        dirs = find_cleanable_dirs(root)
        assert any("target" in str(d) for d in dirs)

    def test_finds_python_cache(self, tmp_project):
        root = tmp_project({"__pycache__/module.cpython-311.pyc": ""})
        dirs = find_cleanable_dirs(root)
        assert any("__pycache__" in str(d) for d in dirs)

    def test_finds_pytest_cache(self, tmp_project):
        root = tmp_project({".pytest_cache/.keep": ""})
        dirs = find_cleanable_dirs(root)
        assert any(".pytest_cache" in str(d) for d in dirs)

    def test_finds_dist(self, tmp_project):
        root = tmp_project({"dist/package.tar.gz": ""})
        dirs = find_cleanable_dirs(root)
        assert any("dist" in str(d) for d in dirs)

    def test_finds_build_dir(self, tmp_project):
        root = tmp_project({"build/lib/.keep": ""})
        dirs = find_cleanable_dirs(root)
        assert any("build" in str(d) for d in dirs)

    def test_finds_egg_info(self, tmp_project):
        root = tmp_project({"mypackage.egg-info/PKG-INFO": ""})
        dirs = find_cleanable_dirs(root)
        assert any(".egg-info" in str(d) for d in dirs)

    def test_finds_in_subdirs(self, tmp_project):
        root = tmp_project({"frontend/node_modules/.keep": "", "backend/.venv/bin/python": ""})
        dirs = find_cleanable_dirs(root)
        assert len(dirs) >= 2

    def test_empty_project(self, tmp_project):
        root = tmp_project({})
        dirs = find_cleanable_dirs(root)
        assert dirs == []

    def test_does_not_include_git(self, tmp_project):
        root = tmp_project({".git/objects/.keep": ""})
        dirs = find_cleanable_dirs(root)
        assert not any(".git" == d.name for d in dirs)


class TestCleanProject:
    def test_removes_node_modules(self, tmp_project):
        root = tmp_project({"node_modules/express/index.js": "module.exports = {}"})
        assert (root / "node_modules").exists()
        result = clean_project(root, dry_run=False)
        assert not (root / "node_modules").exists()
        assert result.dirs_removed > 0

    def test_dry_run_does_not_remove(self, tmp_project):
        root = tmp_project({"node_modules/.keep": ""})
        result = clean_project(root, dry_run=True)
        assert (root / "node_modules").exists()
        assert result.dirs_found > 0
        assert result.dirs_removed == 0

    def test_reports_space_freed(self, tmp_project):
        root = tmp_project({"node_modules/big-file.txt": "x" * 10000})
        result = clean_project(root, dry_run=False)
        assert result.bytes_freed > 0

    def test_cleans_multiple_dirs(self, tmp_project):
        root = tmp_project(
            {
                "node_modules/.keep": "",
                ".venv/bin/python": "",
                "__pycache__/mod.pyc": "",
            }
        )
        result = clean_project(root, dry_run=False)
        assert result.dirs_removed == 3
        assert not (root / "node_modules").exists()
        assert not (root / ".venv").exists()
        assert not (root / "__pycache__").exists()
