"""Tests for bob run command - run detection per ecosystem."""

import json
from pathlib import Path

import pytest

from bobthebuilder.runner import detect_run_command


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


class TestNodeRunDetection:
    def test_detects_dev_script(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"dev": "next dev", "build": "next build"}}),
            "package-lock.json": "{}",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["npm", "run", "dev"]
        assert config.ecosystem == "node"

    def test_detects_start_script(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"start": "node server.js", "test": "jest"}}),
            "package-lock.json": "{}",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["npm", "run", "start"]

    def test_prefers_dev_over_start(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"start": "node .", "dev": "nodemon ."}}),
            "package-lock.json": "{}",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["npm", "run", "dev"]

    def test_uses_yarn_when_detected(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"dev": "vite"}}),
            "yarn.lock": "",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["yarn", "run", "dev"]

    def test_uses_pnpm_when_detected(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "scripts": {"start": "node ."}}),
            "pnpm-lock.yaml": "",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["pnpm", "run", "start"]

    def test_falls_back_to_main_field(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "app", "main": "index.js"}),
            "index.js": "console.log('hi')",
            "package-lock.json": "{}",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["node", "index.js"]

    def test_no_run_script_no_main(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "lib", "scripts": {"test": "jest", "build": "tsc"}}),
            "package-lock.json": "{}",
        })
        config = detect_run_command(root)
        # build is not a run script, should not be detected as runnable
        assert config is None


class TestPythonRunDetection:
    def test_detects_manage_py(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "manage.py": "#!/usr/bin/env python",
            "uv.lock": "",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["uv", "run", "manage.py", "runserver"]
        assert config.ecosystem == "python"

    def test_detects_app_py(self, tmp_project):
        root = tmp_project({
            "requirements.txt": "flask",
            "app.py": "from flask import Flask",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["python", "app.py"]

    def test_detects_main_py(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "main.py": "print('hello')",
        })
        config = detect_run_command(root)
        assert config is not None
        assert "main.py" in config.command

    def test_poetry_run_prefix(self, tmp_project):
        root = tmp_project({
            "pyproject.toml": "[project]\nname='myapp'",
            "poetry.lock": "",
            "app.py": "from flask import Flask",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["poetry", "run", "python", "app.py"]


class TestGoRunDetection:
    def test_detects_cmd_dir(self, tmp_project):
        root = tmp_project({
            "go.mod": "module example.com/test\n\ngo 1.21",
            "cmd/server/main.go": "package main",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["go", "run", "./cmd/server"]
        assert config.ecosystem == "go"

    def test_detects_main_go(self, tmp_project):
        root = tmp_project({
            "go.mod": "module example.com/test\n\ngo 1.21",
            "main.go": "package main",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["go", "run", "."]


class TestRustRunDetection:
    def test_detects_cargo_run(self, tmp_project):
        root = tmp_project({
            "Cargo.toml": '[package]\nname = "myapp"',
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["cargo", "run"]
        assert config.ecosystem == "rust"


class TestRubyRunDetection:
    def test_detects_rails(self, tmp_project):
        root = tmp_project({
            "Gemfile": 'gem "rails"',
            "bin/rails": "#!/usr/bin/env ruby",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["bundle", "exec", "rails", "server"]
        assert config.ecosystem == "ruby"

    def test_detects_rack(self, tmp_project):
        root = tmp_project({
            "Gemfile": 'gem "sinatra"',
            "config.ru": "run MyApp",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["bundle", "exec", "rackup"]

    def test_detects_app_rb(self, tmp_project):
        root = tmp_project({
            "Gemfile": 'gem "sinatra"',
            "app.rb": "require 'sinatra'",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["ruby", "app.rb"]


class TestDockerRunDetection:
    def test_detects_docker_compose(self, tmp_project):
        root = tmp_project({
            "docker-compose.yml": "version: '3'\nservices:\n  app:\n    image: node",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["docker", "compose", "up"]
        assert config.ecosystem == "docker"


class TestMakefileRunFallback:
    def test_detects_make_run(self, tmp_project):
        root = tmp_project({
            "Makefile": "run:\n\techo running\n",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["make", "run"]
        assert config.ecosystem == "make"

    def test_detects_make_start(self, tmp_project):
        root = tmp_project({
            "Makefile": "start:\n\techo starting\n",
        })
        config = detect_run_command(root)
        assert config is not None
        assert config.command == ["make", "start"]


class TestNoRunDetection:
    def test_empty_dir(self, tmp_project):
        root = tmp_project({})
        config = detect_run_command(root)
        assert config is None

    def test_only_test_scripts(self, tmp_project):
        root = tmp_project({
            "package.json": json.dumps({"name": "lib", "scripts": {"test": "jest", "lint": "eslint ."}}),
            "package-lock.json": "{}",
        })
        config = detect_run_command(root)
        assert config is None
