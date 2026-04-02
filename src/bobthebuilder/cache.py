"""Incremental build cache - skip builds when lockfiles haven't changed."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


# Lockfiles to track per ecosystem
LOCKFILES: dict[str, list[str]] = {
    "node": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "package.json"],
    "python": ["uv.lock", "poetry.lock", "Pipfile.lock", "requirements.txt", "pyproject.toml"],
    "go": ["go.sum", "go.mod"],
    "rust": ["Cargo.lock", "Cargo.toml"],
    "ruby": ["Gemfile.lock", "Gemfile"],
}

BOB_STATE_DIR = ".bob"
CACHE_FILE = "build-cache.json"


@dataclass
class CacheEntry:
    """Cached state for a single repo."""

    repo_path: str
    lockfile_hashes: dict[str, str] = field(default_factory=dict)
    last_build_time: float = 0.0
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "repo_path": self.repo_path,
            "lockfile_hashes": self.lockfile_hashes,
            "last_build_time": self.last_build_time,
            "success": self.success,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CacheEntry:
        return cls(
            repo_path=data["repo_path"],
            lockfile_hashes=data.get("lockfile_hashes", {}),
            last_build_time=data.get("last_build_time", 0.0),
            success=data.get("success", False),
        )


@dataclass
class BuildCache:
    """Build cache for the entire workspace."""

    entries: dict[str, CacheEntry] = field(default_factory=dict)

    def save(self, ws_root: Path) -> None:
        """Save cache to .bob/build-cache.json."""
        state_dir = ws_root / BOB_STATE_DIR
        state_dir.mkdir(exist_ok=True)
        cache_path = state_dir / CACHE_FILE
        data = {k: v.to_dict() for k, v in self.entries.items()}
        cache_path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, ws_root: Path) -> BuildCache:
        """Load cache from .bob/build-cache.json."""
        cache_path = ws_root / BOB_STATE_DIR / CACHE_FILE
        if not cache_path.exists():
            return cls()
        try:
            data = json.loads(cache_path.read_text())
            entries = {k: CacheEntry.from_dict(v) for k, v in data.items()}
            return cls(entries=entries)
        except (json.JSONDecodeError, KeyError, OSError):
            return cls()

    def is_up_to_date(self, repo_path: Path, ecosystem: str | None) -> bool:
        """Check if a repo's lockfiles match the cached hashes."""
        key = str(repo_path)
        if key not in self.entries:
            return False

        entry = self.entries[key]
        if not entry.success:
            return False

        current = _hash_lockfiles(repo_path, ecosystem)
        return current == entry.lockfile_hashes

    def record_build(self, repo_path: Path, ecosystem: str | None, success: bool) -> None:
        """Record a build result in the cache."""
        key = str(repo_path)
        self.entries[key] = CacheEntry(
            repo_path=key,
            lockfile_hashes=_hash_lockfiles(repo_path, ecosystem),
            last_build_time=time.time(),
            success=success,
        )


def _hash_lockfiles(repo_path: Path, ecosystem: str | None) -> dict[str, str]:
    """Hash all relevant lockfiles for a repo."""
    hashes: dict[str, str] = {}

    lockfile_names: list[str] = []
    if ecosystem:
        lockfile_names = LOCKFILES.get(ecosystem, [])
    else:
        # Check all lockfiles
        for files in LOCKFILES.values():
            lockfile_names.extend(files)

    for name in lockfile_names:
        path = repo_path / name
        if path.exists():
            try:
                content = path.read_bytes()
                hashes[name] = hashlib.sha256(content).hexdigest()[:16]
            except OSError:
                pass

    return hashes
