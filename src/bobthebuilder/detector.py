"""Project detection - scans a directory to identify ecosystems and gather context."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Ecosystem, MarkerFile, ProjectContext

# (filename, ecosystem, description)
MARKERS: list[tuple[str, Ecosystem, str]] = [
    ("package.json", Ecosystem.NODE, "Node.js package manifest"),
    ("package-lock.json", Ecosystem.NODE, "npm lockfile"),
    ("yarn.lock", Ecosystem.NODE, "Yarn lockfile"),
    ("pnpm-lock.yaml", Ecosystem.NODE, "pnpm lockfile"),
    ("bun.lockb", Ecosystem.NODE, "Bun lockfile"),
    (".nvmrc", Ecosystem.NODE, "Node version file"),
    (".node-version", Ecosystem.NODE, "Node version file"),
    ("pyproject.toml", Ecosystem.PYTHON, "Python project manifest"),
    ("setup.py", Ecosystem.PYTHON, "Python setup script"),
    ("setup.cfg", Ecosystem.PYTHON, "Python setup config"),
    ("requirements.txt", Ecosystem.PYTHON, "pip requirements"),
    ("requirements-dev.txt", Ecosystem.PYTHON, "pip dev requirements"),
    ("Pipfile", Ecosystem.PYTHON, "Pipenv manifest"),
    ("Pipfile.lock", Ecosystem.PYTHON, "Pipenv lockfile"),
    ("poetry.lock", Ecosystem.PYTHON, "Poetry lockfile"),
    ("uv.lock", Ecosystem.PYTHON, "uv lockfile"),
    (".python-version", Ecosystem.PYTHON, "Python version file"),
    ("go.mod", Ecosystem.GO, "Go module manifest"),
    ("go.sum", Ecosystem.GO, "Go checksum file"),
    ("Cargo.toml", Ecosystem.RUST, "Cargo manifest"),
    ("Cargo.lock", Ecosystem.RUST, "Cargo lockfile"),
    ("Dockerfile", Ecosystem.DOCKER, "Dockerfile"),
    ("docker-compose.yml", Ecosystem.DOCKER, "Docker Compose config"),
    ("docker-compose.yaml", Ecosystem.DOCKER, "Docker Compose config"),
    ("compose.yml", Ecosystem.DOCKER, "Docker Compose config"),
    ("compose.yaml", Ecosystem.DOCKER, "Docker Compose config"),
    ("Gemfile", Ecosystem.RUBY, "Ruby Gemfile"),
    ("Gemfile.lock", Ecosystem.RUBY, "Ruby Gemfile lockfile"),
    (".ruby-version", Ecosystem.RUBY, "Ruby version file"),
    ("Rakefile", Ecosystem.RUBY, "Rake build file"),
    ("Makefile", Ecosystem.MAKE, "Makefile"),
    ("makefile", Ecosystem.MAKE, "Makefile"),
]

NODE_LOCKFILE_TO_PM: dict[str, str] = {
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "bun.lockb": "bun",
}

PYTHON_TOOL_PRIORITY: list[tuple[str, str]] = [
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("Pipfile.lock", "pipenv"),
]


def _read_safe(path: Path, max_bytes: int = 50_000) -> str | None:
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size == 0:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(min(size, max_bytes))
    except (OSError, PermissionError):
        return None


def _detect_node_pm(root: Path) -> str | None:
    """Detect Node.js package manager from lockfiles or package.json field."""
    for lockfile, pm in NODE_LOCKFILE_TO_PM.items():
        if (root / lockfile).exists():
            return pm
    # Check packageManager field in package.json
    pkg_json = _read_safe(root / "package.json")
    if pkg_json:
        try:
            data = json.loads(pkg_json)
            pm_field = data.get("packageManager", "")
            if pm_field:
                # Format: "pnpm@8.0.0" or "yarn@4.0.0"
                name = pm_field.split("@")[0].strip()
                if name in ("npm", "yarn", "pnpm", "bun"):
                    return name
        except (json.JSONDecodeError, AttributeError):
            pass
    # Default to npm if package.json exists
    if (root / "package.json").exists():
        return "npm"
    return None


def _detect_node_scripts(root: Path) -> list[str]:
    """Extract script names from package.json."""
    pkg_json = _read_safe(root / "package.json")
    if not pkg_json:
        return []
    try:
        data = json.loads(pkg_json)
        return list(data.get("scripts", {}).keys())
    except (json.JSONDecodeError, AttributeError):
        return []


def _detect_python_tool(root: Path) -> str | None:
    """Detect Python package manager from lockfiles."""
    for lockfile, tool in PYTHON_TOOL_PRIORITY:
        if (root / lockfile).exists():
            return tool
    # Fallback: if any python marker exists, default to pip
    python_markers = ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"]
    for marker in python_markers:
        if (root / marker).exists():
            return "pip"
    return None


def _parse_makefile_targets(content: str) -> list[str]:
    targets: list[str] = []
    for line in content.splitlines():
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_.-]*)\s*:", line)
        if match and not match.group(1).startswith("."):
            targets.append(match.group(1))
    return targets


def _find_env_templates(root: Path) -> list[str]:
    patterns = [".env.example", ".env.sample", ".env.template", "env.example"]
    return [p for p in patterns if (root / p).is_file()]


def detect_project(path: str | Path) -> ProjectContext:
    """Scan a directory and build a ProjectContext."""
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    marker_files: list[MarkerFile] = []
    ecosystems: set[Ecosystem] = set()

    for filename, ecosystem, description in MARKERS:
        if (root / filename).exists():
            marker_files.append(
                MarkerFile(path=filename, ecosystem=ecosystem, description=description)
            )
            ecosystems.add(ecosystem)

    # Docker compose detection
    has_docker_compose = any(
        (root / n).exists()
        for n in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
    )

    # Makefile targets
    makefile_targets: list[str] = []
    for mf in ["Makefile", "makefile", "GNUmakefile"]:
        content = _read_safe(root / mf)
        if content:
            makefile_targets = _parse_makefile_targets(content)
            break

    # README
    readme_content = None
    for name in ["README.md", "README.rst", "README.txt", "README", "readme.md"]:
        readme_content = _read_safe(root / name)
        if readme_content is not None:
            break

    # Remove MAKE from reported ecosystems (cross-cutting build tool)
    # Keep DOCKER only if docker-compose exists (not just Dockerfile)
    reported_ecosystems = sorted(
        [e for e in ecosystems if e != Ecosystem.MAKE],
        key=lambda e: e.value,
    )
    # Only include Docker if there's a compose file
    if Ecosystem.DOCKER in reported_ecosystems and not has_docker_compose:
        reported_ecosystems = [e for e in reported_ecosystems if e != Ecosystem.DOCKER]

    # Ruby detection
    ruby_has_gemfile_lock = (root / "Gemfile.lock").exists()

    return ProjectContext(
        root=str(root),
        ecosystems=reported_ecosystems,
        marker_files=marker_files,
        readme_content=readme_content,
        env_example_files=_find_env_templates(root),
        has_docker_compose=has_docker_compose,
        makefile_targets=makefile_targets,
        node_package_manager=_detect_node_pm(root),
        node_scripts=_detect_node_scripts(root),
        python_tool=_detect_python_tool(root),
        ruby_has_gemfile_lock=ruby_has_gemfile_lock,
    )
