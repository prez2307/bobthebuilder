"""Tests for Makefile target auto-execution."""

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


class TestMakefileStrategy:
    def test_runs_install_target(self, tmp_project):
        root = tmp_project({"Makefile": "install:\n\techo installing\n"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["make", "install"] in commands

    def test_runs_setup_target(self, tmp_project):
        root = tmp_project({"Makefile": "setup:\n\techo setting up\n"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["make", "setup"] in commands

    def test_runs_deps_target(self, tmp_project):
        root = tmp_project({"Makefile": "deps:\n\techo deps\n"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["make", "deps"] in commands

    def test_runs_bootstrap_target(self, tmp_project):
        root = tmp_project({"Makefile": "bootstrap:\n\techo bootstrap\n"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        commands = [s.command for s in steps]
        assert ["make", "bootstrap"] in commands

    def test_only_first_matching_target(self, tmp_project):
        """Should only run one setup-like target, not all of them."""
        root = tmp_project(
            {"Makefile": "install:\n\techo a\n\nsetup:\n\techo b\n\ndeps:\n\techo c\n"}
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        make_steps = [s for s in steps if s.command[0] == "make"]
        assert len(make_steps) == 1
        assert make_steps[0].command == ["make", "install"]  # first match wins

    def test_no_make_step_if_no_setup_target(self, tmp_project):
        """Makefile with only test/lint targets should not generate a step."""
        root = tmp_project({"Makefile": "test:\n\tpytest\n\nlint:\n\truff check .\n"})
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        make_steps = [s for s in steps if s.command[0] == "make"]
        assert len(make_steps) == 0

    def test_makefile_skipped_when_ecosystem_handles_install(self, tmp_project):
        """If npm/pip already handles install, don't also run make install."""
        root = tmp_project(
            {
                "package.json": json.dumps({"name": "test"}),
                "package-lock.json": "{}",
                "Makefile": "install:\n\tnpm install\n",
            }
        )
        ctx = detect_project(root)
        steps = get_steps_for_context(ctx)
        # Should have npm ci but NOT make install (redundant)
        commands = [s.command for s in steps]
        assert ["npm", "ci"] in commands
        assert ["make", "install"] not in commands


class TestCustomBuildSteps:
    """Test custom build_steps override in bob.yaml."""

    def test_custom_steps_override_detection(self, tmp_path):
        """When bob.yaml has custom build_steps, use those instead."""
        import yaml
        from bobthebuilder.workspace import load_workspace

        bob_yaml = tmp_path / "bob.yaml"
        bob_yaml.write_text(
            yaml.dump(
                {
                    "workspace": "test",
                    "repos": [
                        {
                            "path": "./app",
                            "detected": {"ecosystem": "node", "package_manager": "npm"},
                            "build_steps": [
                                {"command": "npm ci", "name": "install"},
                                {"command": "npm run migrate", "name": "migrate"},
                                {"command": "npm run build", "name": "build"},
                            ],
                        }
                    ],
                }
            )
        )
        ws = load_workspace(bob_yaml)
        repo = ws.repos[0]
        assert len(repo.custom_build_steps) == 3
        assert repo.custom_build_steps[1]["command"] == "npm run migrate"
