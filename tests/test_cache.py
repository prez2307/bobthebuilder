"""Tests for incremental build cache."""

from pathlib import Path

import pytest

from bobthebuilder.cache import BuildCache, CacheEntry, _hash_lockfiles


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


class TestHashLockfiles:
    def test_hashes_existing_files(self, tmp_project):
        root = tmp_project({"package-lock.json": '{"lockfileVersion": 2}'})
        hashes = _hash_lockfiles(root, "node")
        assert "package-lock.json" in hashes
        assert len(hashes["package-lock.json"]) == 16

    def test_ignores_missing_files(self, tmp_project):
        root = tmp_project({"package.json": "{}"})
        hashes = _hash_lockfiles(root, "node")
        assert "package.json" in hashes
        assert "package-lock.json" not in hashes

    def test_different_content_different_hash(self, tmp_project):
        root = tmp_project({"requirements.txt": "flask==2.0"})
        hash1 = _hash_lockfiles(root, "python")

        (root / "requirements.txt").write_text("flask==3.0")
        hash2 = _hash_lockfiles(root, "python")

        assert hash1["requirements.txt"] != hash2["requirements.txt"]

    def test_same_content_same_hash(self, tmp_project):
        root = tmp_project({"go.sum": "abc123"})
        hash1 = _hash_lockfiles(root, "go")
        hash2 = _hash_lockfiles(root, "go")
        assert hash1 == hash2


class TestCacheEntry:
    def test_round_trip(self):
        entry = CacheEntry(
            repo_path="/tmp/myrepo",
            lockfile_hashes={"package-lock.json": "abc123"},
            last_build_time=1000.0,
            success=True,
        )
        d = entry.to_dict()
        restored = CacheEntry.from_dict(d)
        assert restored.repo_path == entry.repo_path
        assert restored.lockfile_hashes == entry.lockfile_hashes
        assert restored.success is True


class TestBuildCache:
    def test_save_and_load(self, tmp_path):
        cache = BuildCache()
        cache.entries["/tmp/repo"] = CacheEntry(
            repo_path="/tmp/repo",
            lockfile_hashes={"go.sum": "abc"},
            last_build_time=1000.0,
            success=True,
        )
        cache.save(tmp_path)

        loaded = BuildCache.load(tmp_path)
        assert "/tmp/repo" in loaded.entries
        assert loaded.entries["/tmp/repo"].lockfile_hashes == {"go.sum": "abc"}

    def test_load_missing_cache(self, tmp_path):
        cache = BuildCache.load(tmp_path)
        assert cache.entries == {}

    def test_load_corrupt_cache(self, tmp_path):
        state_dir = tmp_path / ".bob"
        state_dir.mkdir()
        (state_dir / "build-cache.json").write_text("not json!")
        cache = BuildCache.load(tmp_path)
        assert cache.entries == {}

    def test_is_up_to_date_true(self, tmp_project):
        root = tmp_project({"package-lock.json": '{"version": 1}'})
        cache = BuildCache()
        cache.record_build(root, "node", True)
        assert cache.is_up_to_date(root, "node") is True

    def test_is_up_to_date_false_after_change(self, tmp_project):
        root = tmp_project({"package-lock.json": '{"version": 1}'})
        cache = BuildCache()
        cache.record_build(root, "node", True)

        # Change the lockfile
        (root / "package-lock.json").write_text('{"version": 2}')
        assert cache.is_up_to_date(root, "node") is False

    def test_is_up_to_date_false_no_entry(self, tmp_project):
        root = tmp_project({"package-lock.json": '{"version": 1}'})
        cache = BuildCache()
        assert cache.is_up_to_date(root, "node") is False

    def test_is_up_to_date_false_after_failed_build(self, tmp_project):
        root = tmp_project({"package-lock.json": '{"version": 1}'})
        cache = BuildCache()
        cache.record_build(root, "node", False)  # Failed build
        assert cache.is_up_to_date(root, "node") is False

    def test_record_build_updates_entry(self, tmp_project):
        root = tmp_project({"requirements.txt": "flask"})
        cache = BuildCache()
        cache.record_build(root, "python", True)

        entry = cache.entries[str(root)]
        assert entry.success is True
        assert "requirements.txt" in entry.lockfile_hashes
        assert entry.last_build_time > 0
