"""Clean build artifacts, dependency caches, and virtual environments."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

CLEANABLE_DIR_NAMES: set[str] = {
    # Node
    "node_modules",
    ".next",
    ".nuxt",
    # Python
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    # Rust
    "target",
}

CLEANABLE_SUFFIXES: set[str] = {
    ".egg-info",
}

SKIP_DIRS: set[str] = {
    ".git",
}


@dataclass
class CleanResult:
    dirs_found: int = 0
    dirs_removed: int = 0
    bytes_freed: int = 0


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def find_cleanable_dirs(root: Path, max_depth: int = 4) -> list[Path]:
    """Find directories that can be cleaned."""
    cleanable: list[Path] = []

    def _scan(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            for entry in sorted(directory.iterdir()):
                if not entry.is_dir():
                    continue
                name = entry.name
                if name in SKIP_DIRS:
                    continue
                if name in CLEANABLE_DIR_NAMES:
                    cleanable.append(entry)
                    continue  # don't recurse into cleanable dirs
                if any(name.endswith(suffix) for suffix in CLEANABLE_SUFFIXES):
                    cleanable.append(entry)
                    continue
                # Recurse into other dirs
                _scan(entry, depth + 1)
        except PermissionError:
            pass

    _scan(root, 0)
    return cleanable


def clean_project(root: Path, dry_run: bool = True) -> CleanResult:
    """Clean build artifacts from a project."""
    dirs = find_cleanable_dirs(root)
    result = CleanResult(dirs_found=len(dirs))

    if dry_run:
        return result

    for d in dirs:
        size = _dir_size(d)
        try:
            shutil.rmtree(d)
            result.dirs_removed += 1
            result.bytes_freed += size
        except OSError:
            pass

    return result
