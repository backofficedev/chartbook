"""Tests for content hashing: ``chartbook.hashing``.

The rules tested here are part of the index specification
(``docs_src/design/index-schema.md``, "Hashes"). They must not change
without a new algorithm prefix, so these tests pin exact digests.
"""

import hashlib
import json
import os
import shutil
import subprocess

import pytest

from chartbook import hashing
from chartbook.hashing import (
    ContentHash,
    HashCache,
    glob_root,
    hash_directory,
    hash_file,
    hash_files,
    hash_path,
)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
HELLO_SHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


@pytest.fixture
def tree(tmp_path):
    """A small directory: two files at the top, one below."""
    root = tmp_path / "rates"
    (root / "year=2024").mkdir(parents=True)
    (root / "b.parquet").write_bytes(b"bbb")
    (root / "a.parquet").write_bytes(b"hello")
    (root / "year=2024" / "part.parquet").write_bytes(b"")
    return root


class TestHashFile:
    def test_is_sha256_of_the_bytes(self, tmp_path):
        file = tmp_path / "x.bin"
        file.write_bytes(b"hello")
        assert hash_file(file) == ContentHash(f"sha256:{HELLO_SHA256}", 5)

    def test_empty_file(self, tmp_path):
        file = tmp_path / "empty"
        file.write_bytes(b"")
        assert hash_file(file).content_hash == f"sha256:{EMPTY_SHA256}"

    def test_reads_large_files_in_chunks(self, tmp_path):
        payload = os.urandom(3 * 1024 * 1024 + 17)
        file = tmp_path / "big.bin"
        file.write_bytes(payload)
        assert hash_file(file).content_hash == (
            "sha256:" + hashlib.sha256(payload).hexdigest()
        )

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(OSError):
            hash_file(tmp_path / "nope")


class TestHashFiles:
    def test_is_sha256_of_a_sorted_listing(self, tree):
        """One line per file: hex, two spaces, relative path, newline."""
        listing = (
            f"{HELLO_SHA256}  a.parquet\n"
            f"{hashlib.sha256(b'bbb').hexdigest()}  b.parquet\n"
            f"{EMPTY_SHA256}  year=2024/part.parquet\n"
        )
        expected = "sha256:" + hashlib.sha256(listing.encode()).hexdigest()
        result = hash_directory(tree)
        assert result.content_hash == expected
        assert result.size_bytes == 8
        assert [f.path for f in result.files] == [
            "a.parquet",
            "b.parquet",
            "year=2024/part.parquet",
        ]
        assert result.files[0].content_hash == f"sha256:{HELLO_SHA256}"
        assert result.files[0].size_bytes == 5

    def test_order_given_does_not_matter(self, tree):
        files = sorted(p for p in tree.rglob("*") if p.is_file())
        assert hash_files(files, tree) == hash_files(reversed(files), tree)

    def test_a_renamed_file_changes_the_hash(self, tree):
        before = hash_directory(tree).content_hash
        (tree / "a.parquet").rename(tree / "c.parquet")
        assert hash_directory(tree).content_hash != before

    def test_one_file_listed_is_not_the_file_itself(self, tmp_path):
        """A glob that matches one file is still a listing."""
        file = tmp_path / "only.parquet"
        file.write_bytes(b"hello")
        assert hash_files([file], tmp_path).content_hash != hash_file(file).content_hash

    def test_file_outside_the_root_is_refused(self, tree, tmp_path):
        outside = tmp_path / "elsewhere.parquet"
        outside.write_bytes(b"x")
        with pytest.raises(ValueError, match="is not under"):
            hash_files([outside], tree)

    @pytest.mark.skipif(
        shutil.which("shasum") is None, reason="needs the shasum command"
    )
    def test_can_be_reproduced_by_hand(self, tree):
        """The listing is `sha256sum` output, so a shell gives the same answer."""
        script = (
            "find . -type f | sed 's|^\\./||' | LC_ALL=C sort "
            "| xargs shasum -a 256 | shasum -a 256"
        )
        output = subprocess.run(
            ["sh", "-c", script], cwd=tree, capture_output=True, text=True, check=True
        ).stdout
        assert hash_directory(tree).content_hash == "sha256:" + output.split()[0]


class TestGlobRoot:
    @pytest.mark.parametrize(
        "pattern,root",
        [
            ("_data/rates/**/*.parquet", "_data/rates"),
            ("_data/part-*.parquet", "_data"),
            ("/abs/_data/year=*/part.parquet", "/abs/_data"),
            ("*.parquet", "."),
            ("_data/rates/part-[0-9].parquet", "_data/rates"),
        ],
    )
    def test_is_the_leading_directories_without_a_wildcard(self, pattern, root):
        assert glob_root(pattern).as_posix() == root


class TestHashPath:
    def test_file(self, tree):
        assert hash_path(tree / "a.parquet") == hash_file(tree / "a.parquet")

    def test_directory(self, tree):
        assert hash_path(tree) == hash_directory(tree)

    def test_glob_lists_relative_to_its_fixed_prefix(self, tree):
        result = hash_path(tree / "**" / "*.parquet")
        assert [f.path for f in result.files] == [
            "a.parquet",
            "b.parquet",
            "year=2024/part.parquet",
        ]
        # Every file matched, so it is the directory's hash
        assert result.content_hash == hash_directory(tree).content_hash

    def test_glob_that_matches_some_files(self, tree):
        result = hash_path(tree / "*.parquet")
        assert [f.path for f in result.files] == ["a.parquet", "b.parquet"]

    def test_nothing_there_yet(self, tmp_path):
        assert hash_path(tmp_path / "not_built.parquet") is None
        assert hash_path(tmp_path / "none" / "**" / "*.parquet") is None


class TestHashCache:
    @pytest.fixture
    def counted(self, monkeypatch):
        """Count how many files are actually read."""
        reads = []
        real = hashing._file_hex
        monkeypatch.setattr(
            hashing, "_file_hex", lambda path: (reads.append(path), real(path))[1]
        )
        return reads

    def test_unchanged_file_is_not_read_again(self, tree, tmp_path, counted):
        cache_file = tmp_path / "cache.json"
        cache = HashCache(cache_file)
        first = hash_directory(tree, cache)
        cache.save()
        assert len(counted) == 3

        again = HashCache(cache_file)
        assert hash_directory(tree, again) == first
        assert len(counted) == 3

    def test_changed_file_is_read_again(self, tree, tmp_path, counted):
        cache_file = tmp_path / "cache.json"
        cache = HashCache(cache_file)
        before = hash_directory(tree, cache)
        cache.save()

        (tree / "a.parquet").write_bytes(b"different size")
        again = HashCache(cache_file)
        after = hash_directory(tree, again)
        assert after.content_hash != before.content_hash
        assert len(counted) == 4

    def test_same_size_newer_time_is_read_again(self, tree, tmp_path, counted):
        cache_file = tmp_path / "cache.json"
        cache = HashCache(cache_file)
        hash_file(tree / "a.parquet", cache)
        cache.save()

        (tree / "a.parquet").write_bytes(b"HELLO")
        stat = (tree / "a.parquet").stat()
        os.utime(tree / "a.parquet", ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        result = hash_file(tree / "a.parquet", HashCache(cache_file))
        assert result.content_hash == "sha256:" + hashlib.sha256(b"HELLO").hexdigest()
        assert len(counted) == 2

    def test_save_keeps_only_files_asked_about(self, tree, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache = HashCache(cache_file)
        hash_directory(tree, cache)
        cache.save()
        assert len(json.loads(cache_file.read_text())["files"]) == 3

        smaller = HashCache(cache_file)
        hash_file(tree / "a.parquet", smaller)
        smaller.save()
        stored = json.loads(cache_file.read_text())
        assert list(stored["files"]) == [os.path.abspath(tree / "a.parquet")]
        assert stored["version"] == hashing.CACHE_VERSION

    def test_save_leaves_an_unchanged_cache_alone(self, tree, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache = HashCache(cache_file)
        hash_directory(tree, cache)
        cache.save()
        os.utime(cache_file, ns=(1_000_000_000, 1_000_000_000))

        again = HashCache(cache_file)
        hash_directory(tree, again)
        again.save()
        assert cache_file.stat().st_mtime_ns == 1_000_000_000

        (tree / "new.parquet").write_bytes(b"new")
        grown = HashCache(cache_file)
        hash_directory(tree, grown)
        grown.save()
        assert cache_file.stat().st_mtime_ns != 1_000_000_000

    def test_without_a_file_it_only_remembers(self, tree, counted):
        cache = HashCache()
        hash_file(tree / "a.parquet", cache)
        hash_file(tree / "a.parquet", cache)
        cache.save()
        assert len(counted) == 1

    @pytest.mark.parametrize(
        "content", ["not json", "[]", '{"version": 999, "files": {}}', '{"version": 1}']
    )
    def test_unreadable_cache_is_ignored(self, tree, tmp_path, content):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(content)
        result = hash_file(tree / "a.parquet", HashCache(cache_file))
        assert result.content_hash == f"sha256:{HELLO_SHA256}"

    def test_damaged_entry_is_ignored(self, tree, tmp_path):
        cache_file = tmp_path / "cache.json"
        key = os.path.abspath(tree / "a.parquet")
        cache_file.write_text(json.dumps({"version": 1, "files": {key: "oops"}}))
        result = hash_file(tree / "a.parquet", HashCache(cache_file))
        assert result.content_hash == f"sha256:{HELLO_SHA256}"
