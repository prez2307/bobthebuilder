"""Tests for bob test command - test detection per ecosystem."""

import json
from pathlib import Path

import pytest

from bobthebuilder.tester import detect_test_command


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


class TestNodeTestDetection:
    def test_detects_npm_test(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"test": "jest", "build": "tsc"}}),
            "package-lock.json": "{}",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["npm", "test"]
        assert config.ecosystem == "node"

    def test_detects_yarn_test(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"test": "vitest"}}),
            "yarn.lock": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["yarn", "test"]

    def test_detects_test_unit_script(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"test:unit": "vitest"}}),
            "package-lock.json": "{}",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["npm", "run", "test:unit"]

    def test_no_test_script(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "lib", "scripts": {"build": "tsc"}}),
            "package-lock.json": "{}",
        })
        config = detect_test_command(root)
        assert config is None


class TestPythonTestDetection:
    def test_detects_pytest_from_conftest(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "conftest.py": "",
            "uv.lock": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["uv", "run", "pytest"]
        assert config.ecosystem == "python"

    def test_detects_pytest_from_tests_dir(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "tests/__init__.py": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert "pytest" in config.command

    def test_detects_pytest_from_pyproject_config(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'\n\n[tool.pytest.ini_options]\ntestpaths=['tests']",
        })
        config = detect_test_command(root)
        assert config is not None
        assert "pytest" in config.command

    def test_poetry_run_prefix(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "poetry.lock": "",
            "tests/__init__.py": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["poetry", "run", "pytest"]

    def test_detects_django_test(self, tmp_project):
        root = tmp_project({
            "requirements.txt": "django",
            "manage.py": "#!/usr/bin/env python",
        })
        config = detect_test_command(root)
        assert config is not None
        assert "manage.py" in config.command
        assert "test" in config.command

    def test_plain_pip_pytest(self, tmp_project):
        root = tmp_project({
            "requirements.txt": "pytest",
            "tests/__init__.py": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["python", "-m", "pytest"]


class TestGoTestDetection:
    def test_detects_go_test(self, tmp_project):
        root = tmp_project({
            "go.mod": "module example.com/test\n\ngo 1.21",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["go", "test", "./..."]
        assert config.ecosystem == "go"


class TestRustTestDetection:
    def test_detects_cargo_test(self, tmp_project):
        root = tmp_project({
            "Cargo.toml": '[package]\nname = "myapp"',
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["cargo", "test"]
        assert config.ecosystem == "rust"


class TestRubyTestDetection:
    def test_detects_rspec(self, tmp_project):
        root = tmp_project({
            "Gemfile": 'gem "rspec"',
            ".rspec": "--format documentation",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["bundle", "exec", "rspec"]
        assert config.ecosystem == "ruby"

    def test_detects_rspec_from_spec_dir(self, tmp_project):
        root = tmp_project({
            "Gemfile": 'gem "rspec"',
            "spec/test_spec.rb": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["bundle", "exec", "rspec"]

    def test_detects_rails_test(self, tmp_project):
        root = tmp_project({
            "Gemfile": 'gem "rails"',
            "bin/rails": "#!/usr/bin/env ruby",
            "test/test_helper.rb": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["bundle", "exec", "rails", "test"]

    def test_detects_minitest_rake(self, tmp_project):
        root = tmp_project({
            "Gemfile": 'gem "minitest"',
            "test/test_thing.rb": "",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["bundle", "exec", "rake", "test"]


class TestMakefileTestFallback:
    def test_detects_make_test(self, tmp_project):
        root = tmp_project({
            "Makefile": "test:\n\techo testing\n",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["make", "test"]
        assert config.ecosystem == "make"

    def test_detects_make_check(self, tmp_project):
        root = tmp_project({
            "Makefile": "check:\n\techo checking\n",
        })
        config = detect_test_command(root)
        assert config is not None
        assert config.command == ["make", "check"]


class TestNoTestDetection:
    def test_empty_dir(self, tmp_project):
        root = tmp_project({})
        config = detect_test_command(root)
        assert config is None
