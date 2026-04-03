"""Project detection - scans a directory to identify ecosystems and gather context."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Ecosystem, MarkerFile, ProjectContext, SubProject

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

# Primary markers that indicate "this directory is a project"
PRIMARY_MARKERS: set[str] = {
    "package.json",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}

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

# Directories to skip during subdirectory scanning
SKIP_DIRS: set[str] = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".github",
    ".next",
    ".nuxt",
    "target",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "vendor",
}

MAX_SUBDIR_DEPTH = 3


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


def _detect_node_pm(directory: Path) -> str | None:
    """Detect Node.js package manager from lockfiles or package.json field."""
    for lockfile, pm in NODE_LOCKFILE_TO_PM.items():
        if (directory / lockfile).exists():
            return pm
    pkg_json = _read_safe(directory / "package.json")
    if pkg_json:
        try:
            data = json.loads(pkg_json)
            pm_field = data.get("packageManager", "")
            if pm_field:
                name = pm_field.split("@")[0].strip()
                if name in ("npm", "yarn", "pnpm", "bun"):
                    return name
        except (json.JSONDecodeError, AttributeError):
            pass
    if (directory / "package.json").exists():
        return "npm"
    return None


def _detect_node_scripts(directory: Path) -> list[str]:
    """Extract script names from package.json."""
    pkg_json = _read_safe(directory / "package.json")
    if not pkg_json:
        return []
    try:
        data = json.loads(pkg_json)
        return list(data.get("scripts", {}).keys())
    except (json.JSONDecodeError, AttributeError):
        return []


def _detect_python_tool(directory: Path) -> str | None:
    """Detect Python package manager from lockfiles."""
    for lockfile, tool in PYTHON_TOOL_PRIORITY:
        if (directory / lockfile).exists():
            return tool
    python_markers = ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"]
    for marker in python_markers:
        if (directory / marker).exists():
            return "pip"
    return None


def _parse_makefile_targets(content: str) -> list[str]:
    targets: list[str] = []
    for line in content.splitlines():
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_.-]*)\s*:", line)
        if match and not match.group(1).startswith("."):
            targets.append(match.group(1))
    return targets


def _find_env_templates(directory: Path) -> list[str]:
    patterns = [".env.example", ".env.sample", ".env.template", "env.example"]
    return [p for p in patterns if (directory / p).is_file()]


def _has_docker_compose(directory: Path) -> bool:
    return any(
        (directory / n).exists()
        for n in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
    )


def _has_primary_marker(directory: Path) -> bool:
    """Check if a directory has any primary project marker."""
    return any((directory / m).exists() for m in PRIMARY_MARKERS)


def _detect_ecosystems_in_dir(directory: Path) -> set[Ecosystem]:
    """Detect which ecosystems are present in a single directory (no recursion)."""
    ecosystems: set[Ecosystem] = set()
    for filename, ecosystem, _ in MARKERS:
        if (directory / filename).exists():
            ecosystems.add(ecosystem)
    return ecosystems


def _scan_subdirs(root: Path, max_depth: int = MAX_SUBDIR_DEPTH) -> list[SubProject]:
    """Scan subdirectories for additional project ecosystems."""
    subprojects: list[SubProject] = []
    seen_ecosystems_at_root = _detect_ecosystems_in_dir(root)

    def _scan(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            for entry in sorted(directory.iterdir()):
                if not entry.is_dir():
                    continue
                name = entry.name
                if name in SKIP_DIRS or name.startswith("."):
                    continue

                # Check if this subdir has its own project markers
                if _has_primary_marker(entry):
                    ecosystems = _detect_ecosystems_in_dir(entry)
                    # Filter to language ecosystems not already at root
                    lang_ecosystems = {
                        e for e in ecosystems if e not in (Ecosystem.MAKE, Ecosystem.DOCKER)
                    }

                    rel_path = str(entry.relative_to(root))

                    for eco in lang_ecosystems:
                        sub = SubProject(
                            path=rel_path,
                            ecosystem=eco,
                        )
                        if eco == Ecosystem.NODE:
                            sub.node_package_manager = _detect_node_pm(entry)
                            sub.node_scripts = _detect_node_scripts(entry)
                        elif eco == Ecosystem.PYTHON:
                            sub.python_tool = _detect_python_tool(entry)
                        elif eco == Ecosystem.RUBY:
                            sub.ruby_has_gemfile_lock = (entry / "Gemfile.lock").exists()
                        subprojects.append(sub)

                    # Check for docker compose in subdirs
                    if _has_docker_compose(entry):
                        sub = SubProject(
                            path=rel_path,
                            ecosystem=Ecosystem.DOCKER,
                            has_docker_compose=True,
                        )
                        subprojects.append(sub)

                    # Check for env templates in subdirs
                    env_files = _find_env_templates(entry)
                    if env_files and subprojects:
                        # Attach to the last subproject for this dir
                        for sp in reversed(subprojects):
                            if sp.path == rel_path:
                                sp.env_example_files = env_files
                                break

                    # Continue scanning inside this subproject for OTHER ecosystems
                    # (e.g., Tauri has Cargo.toml inside a Node package)
                    _scan(entry, depth + 1)
                    continue

                # Not a project dir, recurse
                _scan(entry, depth + 1)
        except PermissionError:
            pass

    _scan(root, 0)
    return subprojects


def detect_project(path: str | Path) -> ProjectContext:
    """Scan a directory and build a ProjectContext."""
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    # Scan root for markers
    marker_files: list[MarkerFile] = []
    ecosystems: set[Ecosystem] = set()

    for filename, ecosystem, description in MARKERS:
        if (root / filename).exists():
            marker_files.append(
                MarkerFile(path=filename, ecosystem=ecosystem, description=description)
            )
            ecosystems.add(ecosystem)

    # Root-level detection
    has_compose = _has_docker_compose(root)
    makefile_targets: list[str] = []
    for mf in ["Makefile", "makefile", "GNUmakefile"]:
        content = _read_safe(root / mf)
        if content:
            makefile_targets = _parse_makefile_targets(content)
            break

    readme_content = None
    for name in ["README.md", "README.rst", "README.txt", "README", "readme.md"]:
        readme_content = _read_safe(root / name)
        if readme_content is not None:
            break

    env_example_files = _find_env_templates(root)
    node_pm = _detect_node_pm(root)
    node_scripts = _detect_node_scripts(root)
    python_tool = _detect_python_tool(root)
    ruby_has_gemfile_lock = (root / "Gemfile.lock").exists()

    # Scan subdirectories
    subprojects = _scan_subdirs(root)

    # Merge subproject ecosystems into the main ecosystems list
    all_ecosystems = set(ecosystems)
    for sp in subprojects:
        all_ecosystems.add(sp.ecosystem)
        if sp.has_docker_compose:
            has_compose = True
        # If root doesn't have a python/node tool but subdir does, use subdir's
        if sp.ecosystem == Ecosystem.PYTHON and python_tool is None:
            python_tool = sp.python_tool
        if sp.ecosystem == Ecosystem.NODE and node_pm is None:
            node_pm = sp.node_package_manager
            node_scripts = sp.node_scripts

    # Merge subproject env files
    for sp in subprojects:
        for ef in sp.env_example_files:
            qualified = f"{sp.path}/{ef}"
            if qualified not in env_example_files:
                env_example_files.append(qualified)

    # Root ecosystems (before subdir merging) - used by strategies to avoid
    # running root-level install for ecosystems only found in subdirs
    root_only_ecosystems = sorted(
        [e for e in ecosystems if e not in (Ecosystem.MAKE, Ecosystem.DOCKER)],
        key=lambda e: e.value,
    )
    if Ecosystem.DOCKER in ecosystems and has_compose:
        root_only_ecosystems.append(Ecosystem.DOCKER)

    # Filter all ecosystems for reporting
    reported_ecosystems = sorted(
        [e for e in all_ecosystems if e != Ecosystem.MAKE],
        key=lambda e: e.value,
    )
    if Ecosystem.DOCKER in reported_ecosystems and not has_compose:
        reported_ecosystems = [e for e in reported_ecosystems if e != Ecosystem.DOCKER]

    return ProjectContext(
        root=str(root),
        ecosystems=reported_ecosystems,
        root_ecosystems=root_only_ecosystems,
        marker_files=marker_files,
        readme_content=readme_content,
        env_example_files=env_example_files,
        has_docker_compose=has_compose,
        makefile_targets=makefile_targets,
        node_package_manager=node_pm,
        node_scripts=node_scripts,
        python_tool=python_tool,
        ruby_has_gemfile_lock=ruby_has_gemfile_lock,
        subprojects=subprojects,
    )
