"""Application runner - detect and run applications per ecosystem."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .detector import detect_project
from .models import Ecosystem


# Scripts in package.json that indicate a runnable app (priority order)
NODE_RUN_SCRIPTS = ["dev", "start", "serve", "server", "develop"]

# Common Python run patterns (checked in order)
PYTHON_RUN_PATTERNS: list[tuple[str, list[str]]] = [
    ("manage.py", ["python", "manage.py", "runserver"]),
    ("app.py", ["python", "app.py"]),
    ("main.py", ["python", "main.py"]),
    ("server.py", ["python", "server.py"]),
    ("run.py", ["python", "run.py"]),
]

# Makefile targets that indicate a run command
MAKE_RUN_TARGETS = ["run", "start", "serve", "server", "dev", "up"]


@dataclass
class RunConfig:
    """Detected run configuration for a project."""

    path: str
    command: list[str]
    description: str
    ecosystem: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "command": self.command,
            "description": self.description,
            "ecosystem": self.ecosystem,
        }


def detect_run_command(project_path: Path) -> RunConfig | None:
    """Detect how to run the application in the given project directory."""
    ctx = detect_project(project_path)

    # Try ecosystem-specific detection in priority order
    for ecosystem in ctx.root_ecosystems:
        config = None
        if ecosystem == Ecosystem.NODE:
            config = _detect_node_run(project_path, ctx)
        elif ecosystem == Ecosystem.PYTHON:
            config = _detect_python_run(project_path, ctx)
        elif ecosystem == Ecosystem.GO:
            config = _detect_go_run(project_path)
        elif ecosystem == Ecosystem.RUST:
            config = _detect_rust_run(project_path)
        elif ecosystem == Ecosystem.RUBY:
            config = _detect_ruby_run(project_path)
        elif ecosystem == Ecosystem.DOCKER:
            config = _detect_docker_run(project_path)
        if config:
            return config

    # Fallback: Makefile run targets
    if ctx.makefile_targets:
        for target in MAKE_RUN_TARGETS:
            if target in ctx.makefile_targets:
                return RunConfig(
                    path=str(project_path),
                    command=["make", target],
                    description=f"make {target}",
                    ecosystem="make",
                )

    # Fallback: docker compose if present
    if ctx.has_docker_compose:
        return RunConfig(
            path=str(project_path),
            command=["docker", "compose", "up"],
            description="docker compose up",
            ecosystem="docker",
        )

    return None


def _detect_node_run(project_path: Path, ctx) -> RunConfig | None:
    """Detect Node.js run command from package.json scripts."""
    pm = ctx.node_package_manager or "npm"

    for script in NODE_RUN_SCRIPTS:
        if script in ctx.node_scripts:
            return RunConfig(
                path=str(project_path),
                command=[pm, "run", script],
                description=f"{pm} run {script}",
                ecosystem="node",
            )

    # If there's a "main" field in package.json, try node <main>
    pkg_json_path = project_path / "package.json"
    if pkg_json_path.exists():
        try:
            data = json.loads(pkg_json_path.read_text())
            main = data.get("main")
            if main and (project_path / main).exists():
                return RunConfig(
                    path=str(project_path),
                    command=["node", main],
                    description=f"node {main}",
                    ecosystem="node",
                )
        except (json.JSONDecodeError, OSError):
            pass

    return None


def _detect_python_run(project_path: Path, ctx) -> RunConfig | None:
    """Detect Python run command."""
    tool = ctx.python_tool

    # Check common entry points
    for filename, command in PYTHON_RUN_PATTERNS:
        if (project_path / filename).exists():
            # Use the appropriate Python runner
            if tool == "uv":
                cmd = ["uv", "run"] + command[1:]  # replace "python" with "uv run"
            elif tool == "poetry":
                cmd = ["poetry", "run"] + command
            else:
                cmd = command
            return RunConfig(
                path=str(project_path),
                command=cmd,
                description=" ".join(cmd),
                ecosystem="python",
            )

    # Check pyproject.toml for [project.scripts] entry points
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text()
            # Simple check for scripts section - if it exists, there's a CLI entry point
            if "[project.scripts]" in content:
                # After install, the script should be on PATH; detect the package name
                if tool == "uv":
                    return RunConfig(
                        path=str(project_path),
                        command=["uv", "run", "python", "-m", _guess_package_name(project_path)],
                        description=f"uv run python -m {_guess_package_name(project_path)}",
                        ecosystem="python",
                    )
        except OSError:
            pass

    return None


def _detect_go_run(project_path: Path) -> RunConfig | None:
    """Detect Go run command."""
    # Check for cmd/ directory pattern
    cmd_dir = project_path / "cmd"
    if cmd_dir.is_dir():
        subdirs = [d for d in sorted(cmd_dir.iterdir()) if d.is_dir()]
        if subdirs:
            rel = subdirs[0].relative_to(project_path)
            return RunConfig(
                path=str(project_path),
                command=["go", "run", f"./{rel}"],
                description=f"go run ./{rel}",
                ecosystem="go",
            )

    # Check for main.go at root
    if (project_path / "main.go").exists():
        return RunConfig(
            path=str(project_path),
            command=["go", "run", "."],
            description="go run .",
            ecosystem="go",
        )

    return None


def _detect_rust_run(project_path: Path) -> RunConfig | None:
    """Detect Rust run command."""
    if (project_path / "Cargo.toml").exists():
        return RunConfig(
            path=str(project_path),
            command=["cargo", "run"],
            description="cargo run",
            ecosystem="rust",
        )
    return None


def _detect_ruby_run(project_path: Path) -> RunConfig | None:
    """Detect Ruby run command."""
    # Rails
    if (project_path / "bin" / "rails").exists():
        return RunConfig(
            path=str(project_path),
            command=["bundle", "exec", "rails", "server"],
            description="bundle exec rails server",
            ecosystem="ruby",
        )

    # Rack-based (Sinatra, etc.)
    if (project_path / "config.ru").exists():
        return RunConfig(
            path=str(project_path),
            command=["bundle", "exec", "rackup"],
            description="bundle exec rackup",
            ecosystem="ruby",
        )

    # app.rb fallback
    if (project_path / "app.rb").exists():
        return RunConfig(
            path=str(project_path),
            command=["ruby", "app.rb"],
            description="ruby app.rb",
            ecosystem="ruby",
        )

    return None


def _detect_docker_run(project_path: Path) -> RunConfig | None:
    """Detect Docker Compose run command."""
    for name in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        if (project_path / name).exists():
            return RunConfig(
                path=str(project_path),
                command=["docker", "compose", "up"],
                description="docker compose up",
                ecosystem="docker",
            )
    return None


def _guess_package_name(project_path: Path) -> str:
    """Guess the Python package name from directory structure."""
    src_dir = project_path / "src"
    if src_dir.is_dir():
        for d in sorted(src_dir.iterdir()):
            if d.is_dir() and (d / "__init__.py").exists():
                return d.name
    # Try root-level packages
    for d in sorted(project_path.iterdir()):
        if d.is_dir() and (d / "__init__.py").exists() and d.name not in ("tests", "test"):
            return d.name
    return project_path.name


def run_app(config: RunConfig) -> int:
    """Run the application, streaming output to the terminal. Returns exit code."""
    # Set up signal forwarding so Ctrl+C propagates to the child
    proc = subprocess.Popen(
        config.command,
        cwd=config.path,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    def _forward_signal(signum, frame):
        proc.send_signal(signum)

    old_int = signal.signal(signal.SIGINT, _forward_signal)
    old_term = signal.signal(signal.SIGTERM, _forward_signal)

    try:
        return proc.wait()
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
