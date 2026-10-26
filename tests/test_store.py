"""Tests for the store: ``chartbook.store``, where it lives, and
``chartbook store verify``.

The store is the second part of step 3 of ``docs_src/design/overview.md``.
It keeps an asset's files under the hash of their content, behind four
operations: has, get, put, delete. Nothing uses it yet, so it is tested
alone.
"""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, hashing
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.store import (
    FROZEN_LINKS,
    LINKS,
    FolderStore,
    MARKER_FILE,
    SCHEMA,
    ObjectNotFoundError,
    Store,
    StoredObject,
    StoreError,
    StoreProblem,
    default_store,
)

HELLO = "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def _reflink_works(directory: Path) -> bool:
    """Whether the disk the tests run on can clone a file copy-on-write."""
    source, clone = directory / "probe", directory / "probe.clone"
    source.write_bytes(b"x")
    try:
        store_module._reflink(str(source), str(clone))
    except (OSError, AttributeError):
        return False
    finally:
        for path in (source, clone):
            if path.exists():
                path.unlink()
    return True


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _rewrite(path: Path, content: bytes) -> None:
    """Write new bytes into the file that is there, as ``to_parquet`` does."""
    with open(path, "r+b") as f:
        f.seek(0)
        f.write(content)
        f.truncate()


def _replace(path: Path, content: bytes) -> None:
    """Write new bytes to a new file and put it where the old one was."""
    temporary = path.with_name(path.name + ".new")
    temporary.write_bytes(content)
    os.replace(temporary, path)


@pytest.fixture
def work(tmp_path):
    """A resolved scratch directory, so paths compare without surprises."""
    return tmp_path.resolve()


@pytest.fixture
def store(work):
    return FolderStore(work / "store")


@pytest.fixture
def rates(work):
    """One data file, ``hello`` inside."""
    path = work / "pipeline" / "_data" / "rates.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"hello")
    return path


@pytest.fixture
def partitioned(work):
    """A dataset of three files in two folders, plus what Finder leaves."""
    root = work / "pipeline" / "_data" / "by_year"
    (root / "year=2023").mkdir(parents=True)
    (root / "year=2024").mkdir()
    (root / "year=2023" / "part-0.parquet").write_bytes(b"a" * 10)
    (root / "year=2024" / "part-0.parquet").write_bytes(b"b" * 20)
    (root / "year=2024" / "part-1.parquet").write_bytes(b"c" * 30)
    (root / ".DS_Store").write_bytes(b"finder")
    return root


def _a_kind(request, work):
    if request.param == "reflink" and not _reflink_works(work):
        pytest.skip("this filesystem cannot clone files")
    return request.param


@pytest.fixture(params=LINKS)
def kind(request, work):
    """Each kind of link in turn, skipping a clone where the disk has none."""
    return _a_kind(request, work)


@pytest.fixture(params=sorted(FROZEN_LINKS))
def frozen_kind(request, work):
    """Each kind of link that makes the store's own bytes."""
    return _a_kind(request, work)


class TestLayout:
    def test_an_object_is_a_directory_named_by_its_hash(self, store, work):
        assert store.object_path(HELLO) == (
            work / "store" / "objects" / "sha256" / "2c" / HELLO[len("sha256:2c") :]
        )

    @pytest.mark.parametrize(
        "not_a_hash",
        [
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            "md5:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            "sha256:2CF24DBA5FB0A30E26E83B2AC5B9E29E1B161E5C1FA7425E73043362938B9824",
            "sha256:2cf24dba",
            "sha256:../../../../etc/passwd",
            "sha256:" + "g" * 64,
            "",
        ],
    )
    def test_nothing_but_a_content_hash_becomes_a_path(self, store, not_a_hash):
        for operation in (store.object_path, store.has, store.get, store.delete):
            with pytest.raises(ValueError, match="is not a content hash"):
                operation(not_a_hash)

    def test_the_root_is_absolute(self, work, monkeypatch):
        monkeypatch.chdir(work)
        assert FolderStore("relative/store").root == work / "relative" / "store"
        monkeypatch.setenv("HOME", str(work))
        assert FolderStore("~/store").root == work / "store"

    def test_looking_makes_nothing(self, store):
        """Only putting something in a store brings it into being."""
        assert not store.has(HELLO)
        assert list(store.hashes()) == []
        assert store.verify() == []
        assert store.delete(HELLO) is False
        assert not store.root.exists()

    def test_the_first_put_says_which_layout_this_is(self, store, rates):
        store.put(rates)
        marker = json.loads((store.root / MARKER_FILE).read_text())
        assert marker == {"schema": SCHEMA}

    def test_a_store_laid_out_differently_is_refused(self, store, rates):
        store.put(rates)
        (store.root / MARKER_FILE).write_text('{"schema": "chartbook/store/v9"}')
        newer = FolderStore(store.root)
        for operation in (
            lambda: newer.put(rates),
            lambda: newer.get(HELLO),
            lambda: list(newer.hashes()),
            lambda: newer.verify(),
        ):
            with pytest.raises(StoreError, match="has the layout 'chartbook/store/v9'"):
                operation()

    def test_a_marker_that_cannot_be_read_is_refused(self, store, rates):
        store.put(rates)
        (store.root / MARKER_FILE).write_text("not json")
        with pytest.raises(StoreError, match="Cannot read"):
            FolderStore(store.root).put(rates)


class TestPut:
    def test_a_file_is_stored_under_its_hash_and_its_own_name(self, store, rates):
        stored = store.put(rates)
        assert isinstance(stored, StoredObject)
        assert stored.content_hash == HELLO == hashing.hash_file(rates).content_hash
        assert stored.size_bytes == 5
        assert stored.path == store.object_path(HELLO)
        assert stored.files == ("rates.parquet",)
        assert stored.created is True
        assert (stored.path / "rates.parquet").read_bytes() == b"hello"

    def test_the_declared_file_stays_where_it_is(self, store, rates):
        mode = _mode(rates)
        store.put(rates)
        assert rates.read_bytes() == b"hello"
        assert not rates.is_symlink()
        assert _mode(rates) == mode

    def test_a_directory_keeps_its_folders(self, store, partitioned):
        stored = store.put(partitioned)
        assert stored.content_hash == hashing.hash_directory(partitioned).content_hash
        assert stored.size_bytes == 60
        assert stored.files == (
            "year=2023/part-0.parquet",
            "year=2024/part-0.parquet",
            "year=2024/part-1.parquet",
        )
        assert (stored.path / "year=2024" / "part-1.parquet").read_bytes() == b"c" * 30

    def test_what_the_operating_system_left_is_not_stored(self, store, partitioned):
        stored = store.put(partitioned)
        assert not (stored.path / ".DS_Store").exists()

    def test_a_glob_is_laid_out_from_its_fixed_prefix(self, store, partitioned):
        pattern = partitioned / "year=2024" / "*.parquet"
        stored = store.put(pattern)
        assert stored.content_hash == hashing.hash_path(pattern).content_hash
        assert stored.files == ("part-0.parquet", "part-1.parquet")

        everything = store.put(partitioned / "**" / "*.parquet")
        assert everything.content_hash == hashing.hash_directory(partitioned).content_hash
        assert "year=2023/part-0.parquet" in everything.files

    def test_a_glob_of_one_file_is_not_the_file(self, store, rates):
        as_file = store.put(rates)
        as_glob = store.put(rates.parent / "*.parquet")
        assert as_glob.content_hash != as_file.content_hash
        assert as_glob.content_hash == hashing.hash_path(rates.parent / "*.parquet").content_hash
        assert store.verify() == []

    def test_the_same_content_twice_is_one_object(self, store, rates):
        first = store.put(rates)
        second = store.put(rates)
        assert second.content_hash == first.content_hash
        assert second.created is False and second.links == ()
        assert second.frozen is False  # how it was first made is not known
        assert list(store.hashes()) == [HELLO]

    def test_the_same_bytes_under_another_name_adds_the_name(self, store, rates):
        twin = rates.with_name("treasury.parquet")
        twin.write_bytes(b"hello")
        store.put(rates)
        stored = store.put(twin)
        assert stored.created is False
        assert stored.files == ("rates.parquet", "treasury.parquet")
        assert (stored.path / "treasury.parquet").read_bytes() == b"hello"
        assert list(store.hashes()) == [HELLO]
        assert store.verify() == []

    def test_nothing_there_is_an_error(self, store, work):
        with pytest.raises(FileNotFoundError, match="Nothing at"):
            store.put(work / "not_built.parquet")
        with pytest.raises(FileNotFoundError, match="Nothing at"):
            store.put(work / "none" / "*.parquet")
        (work / "empty").mkdir()
        with pytest.raises(FileNotFoundError, match="Nothing at"):
            store.put(work / "empty")

    @pytest.mark.parametrize("links", [("zip",), ("copy", "clone"), (), "copy"])
    def test_an_unknown_kind_of_link_is_refused(self, store, rates, links):
        with pytest.raises(ValueError, match="The kinds are: reflink, hardlink"):
            store.put(rates, links=links)
        assert not store.root.exists()

    def test_nothing_is_left_behind_in_staging(self, store, rates, partitioned):
        store.put(rates)
        store.put(partitioned)
        store.put(rates)
        assert list((store.root / "tmp").iterdir()) == []

    def test_a_file_that_is_a_link_is_stored_as_the_file_it_points_at(self, store, rates, work):
        alias = work / "alias.parquet"
        alias.symlink_to(rates)
        stored = store.put(alias, links=("symlink",))
        assert os.readlink(stored.path / "alias.parquet") == str(rates)


class TestLinks:
    """The four ways to hold a file, and what each one promises."""

    def test_the_order_is_the_designs(self):
        assert LINKS == ("reflink", "hardlink", "symlink", "copy")
        assert FROZEN_LINKS == {"reflink", "copy"}

    def test_every_kind_stores_the_same_object(self, store, rates, kind):
        stored = store.put(rates, links=(kind,))
        assert stored.links == (kind,)
        assert stored.content_hash == HELLO
        assert (stored.path / "rates.parquet").read_bytes() == b"hello"
        assert store.verify() == []

    def test_every_kind_stores_a_directory(self, store, partitioned, kind):
        stored = store.put(partitioned, links=(kind,))
        assert stored.links == (kind,)
        assert stored.content_hash == hashing.hash_directory(partitioned).content_hash
        assert store.verify() == []

    def test_a_clone_or_a_copy_is_the_stores_own(self, store, rates, frozen_kind):
        mode = _mode(rates)
        stored = store.put(rates, links=(frozen_kind,))
        held = stored.path / "rates.parquet"
        assert stored.frozen is True
        assert not held.is_symlink() and not held.samefile(rates)
        assert _mode(held) == 0o444  # not to be written through the store
        assert _mode(rates) == mode  # and the original is as it was

        _rewrite(rates, b"changed upstream")
        assert held.read_bytes() == b"hello"
        assert store.verify() == []

    def test_a_hard_link_is_the_original_file(self, store, rates):
        mode = _mode(rates)
        stored = store.put(rates, links=("hardlink",))
        held = stored.path / "rates.parquet"
        assert stored.frozen is False
        assert held.samefile(rates) and not held.is_symlink()
        # One file has one set of permissions, so nothing is made read-only
        assert _mode(rates) == mode

    def test_a_symlink_points_at_the_original_file(self, store, rates):
        stored = store.put(rates, links=("symlink",))
        held = stored.path / "rates.parquet"
        assert stored.frozen is False
        assert held.is_symlink() and os.readlink(held) == str(rates)

    def test_each_kind_is_tried_in_turn(self, store, rates, monkeypatch):
        def refuse(*args, **kwargs):
            raise OSError(95, "not supported here")

        monkeypatch.setattr(store_module, "_reflink", refuse)
        assert store.put(rates, links=LINKS).links == ("hardlink",)
        store.delete(HELLO)

        monkeypatch.setattr(os, "link", refuse)
        assert store.put(rates, links=LINKS).links == ("symlink",)
        store.delete(HELLO)

        monkeypatch.setattr(os, "symlink", refuse)
        stored = store.put(rates, links=LINKS)
        assert stored.links == ("copy",) and stored.frozen
        assert (stored.path / "rates.parquet").read_bytes() == b"hello"

    def test_a_kind_that_fails_part_way_leaves_nothing(self, store, rates, monkeypatch):
        def half_a_clone(source, destination):
            Path(destination).write_bytes(b"he")
            raise OSError(5, "the disk gave up")

        monkeypatch.setattr(store_module, "_reflink", half_a_clone)
        stored = store.put(rates, links=("reflink", "copy"))
        assert stored.links == ("copy",)
        assert (stored.path / "rates.parquet").read_bytes() == b"hello"

    def test_when_no_kind_works_it_says_what_was_tried(self, store, rates, monkeypatch):
        def refuse(*args, **kwargs):
            raise OSError(95, "not supported here")

        monkeypatch.setattr(store_module, "_reflink", refuse)
        monkeypatch.setattr(os, "link", refuse)
        with pytest.raises(StoreError) as e:
            store.put(rates, links=("reflink", "hardlink"))
        assert f"Could not store {rates}" in str(e.value)
        assert "reflink: " in str(e.value) and "hardlink: " in str(e.value)
        assert list(store.hashes()) == []
        assert list((store.root / "tmp").iterdir()) == []

    def test_a_directory_may_use_more_than_one_kind(self, store, partitioned, monkeypatch):
        real_link = os.link

        def only_2023(source, destination, *args, **kwargs):
            if "year=2024" in str(source):
                raise OSError(18, "another disk")
            return real_link(source, destination, *args, **kwargs)

        monkeypatch.setattr(os, "link", only_2023)
        stored = store.put(partitioned, links=("hardlink", "copy"))
        assert stored.links == ("hardlink", "copy")
        assert stored.frozen is False
        assert store.verify() == []


class TestAskingForAFrozenObject:
    """A caller that must not see an object change asks for a clone or a copy."""

    FROZEN = ("reflink", "copy")

    def test_one_that_is_there_as_a_link_is_replaced(self, store, rates):
        linked = store.put(rates, links=("hardlink",))
        assert (linked.path / "rates.parquet").samefile(rates)

        frozen = store.put(rates, links=self.FROZEN)
        assert frozen.content_hash == linked.content_hash == HELLO
        assert frozen.created is True and frozen.frozen is True
        held = frozen.path / "rates.parquet"
        assert not held.samefile(rates) and not held.is_symlink()
        assert list(store.hashes()) == [HELLO]
        assert list((store.root / "tmp").iterdir()) == []

        _rewrite(rates, b"changed upstream")
        assert held.read_bytes() == b"hello" and store.verify() == []

    def test_a_symlinked_directory_is_replaced_too(self, store, partitioned):
        store.put(partitioned, links=("symlink",))
        frozen = store.put(partitioned, links=self.FROZEN)
        assert frozen.created is True
        assert not any(
            (frozen.path / name).is_symlink() for name in frozen.files
        )
        assert store.verify() == []

    def test_one_that_is_already_the_stores_own_is_left_alone(self, store, rates):
        first = store.put(rates, links=self.FROZEN)
        held = first.path / "rates.parquet"
        inode = os.stat(held).st_ino
        again = store.put(rates, links=self.FROZEN)
        assert again.created is False
        assert os.stat(held).st_ino == inode

    def test_a_cheaper_put_does_not_thaw_a_frozen_object(self, store, rates):
        store.put(rates, links=self.FROZEN)
        again = store.put(rates, links=("hardlink",))
        assert again.created is False
        assert not (again.path / "rates.parquet").samefile(rates)

    def test_a_hard_link_whose_original_is_gone_is_the_stores_own(self, store, rates):
        """With no other name left, nothing outside the store can change it."""
        stored = store.put(rates, links=("hardlink",))
        rates.unlink()
        assert store_module._is_frozen(stored.path) is True


class TestGetHasDelete:
    def test_has_and_get(self, store, rates):
        assert store.has(HELLO) is False
        store.put(rates)
        assert store.has(HELLO) is True
        assert store.get(HELLO) == store.object_path(HELLO)
        assert (store.get(HELLO) / "rates.parquet").read_bytes() == b"hello"

    def test_getting_what_is_not_there(self, store, rates):
        with pytest.raises(ObjectNotFoundError, match="has no object sha256:2cf2") as e:
            store.get(HELLO)
        assert isinstance(e.value, (LookupError, StoreError))

    def test_delete_removes_the_object_and_nothing_else(self, store, rates, kind):
        store.put(rates, links=(kind,))
        assert store.delete(HELLO) is True
        assert not store.has(HELLO)
        assert list(store.hashes()) == []
        # Whatever kind of link it was, the declared file is untouched
        assert rates.read_bytes() == b"hello" and not rates.is_symlink()
        assert store.delete(HELLO) is False

    def test_delete_copes_with_a_folder_it_cannot_write_to(self, store, rates):
        stored = store.put(rates, links=("copy",))
        os.chmod(stored.path, 0o555)
        try:
            assert store.delete(HELLO) is True
        finally:
            if stored.path.exists():
                os.chmod(stored.path, 0o755)
        assert not store.has(HELLO)

    @pytest.mark.parametrize("kind_of_link", ["hardlink", "symlink"])
    def test_a_retried_removal_never_touches_the_file_a_link_leads_to(
        self, store, rates, kind_of_link
    ):
        """Its permissions are the upstream's business, not the store's."""
        os.chmod(rates, 0o444)
        stored = store.put(rates, links=(kind_of_link,))
        store_module._make_removable(str(stored.path / "rates.parquet"))
        assert _mode(rates) == 0o444

    def test_a_retried_removal_frees_the_stores_own_copy(self, store, rates):
        stored = store.put(rates, links=("copy",))
        held = stored.path / "rates.parquet"
        store_module._make_removable(str(held))
        assert _mode(held) == 0o600

    def test_delete_tidies_the_folder_it_emptied(self, store, rates, partitioned):
        store.put(rates)
        other = store.put(partitioned)
        store.delete(HELLO)
        assert not store.object_path(HELLO).parent.exists()
        assert other.path.is_dir()

    def test_hashes_are_in_order_and_skip_what_is_not_an_object(self, store, rates, partitioned):
        first = store.put(rates).content_hash
        second = store.put(partitioned).content_hash
        (store.root / "objects" / "sha256" / "README").write_text("not an object")
        (store.root / "objects" / "sha256" / "zz").mkdir()
        (store.root / "objects" / "sha256" / "zz" / "nope").mkdir()
        assert list(store.hashes()) == sorted([first, second])


class TestVerify:
    def test_an_untouched_store_has_no_problems(self, store, rates, partitioned):
        store.put(rates)
        store.put(partitioned)
        assert store.verify() == []

    def test_a_hard_link_changes_when_the_original_is_rewritten(self, store, rates):
        """What the maintainer chose to live with, and what verify is for."""
        stored = store.put(rates, links=("hardlink",))
        _rewrite(rates, b"new numbers")
        assert (stored.path / "rates.parquet").read_bytes() == b"new numbers"

        (problem,) = store.verify()
        assert isinstance(problem, StoreProblem)
        assert problem.content_hash == HELLO and problem.path == stored.path
        now = hashing.hash_file(rates).content_hash
        assert problem.message == (
            f"its content is no longer what its name says (now {now}). "
            f"rates.parquet is a hard link to a file outside the store, "
            f"which has been rewritten"
        )
        assert problem.format() == f"{HELLO}: {problem.message}"

    def test_a_hard_link_survives_the_original_being_replaced(self, store, rates):
        """A writer that makes a new file and moves it into place leaves the pin alone."""
        stored = store.put(rates, links=("hardlink",))
        _replace(rates, b"new numbers")
        assert rates.read_bytes() == b"new numbers"
        assert (stored.path / "rates.parquet").read_bytes() == b"hello"
        assert store.verify() == []

    def test_a_symlink_changes_whenever_the_original_does(self, store, rates):
        store.put(rates, links=("symlink",))
        _replace(rates, b"new numbers")
        (problem,) = store.verify()
        assert f"rates.parquet is a link to {rates}, which has been rewritten" in (
            problem.message
        )

    def test_a_symlink_whose_file_has_gone(self, store, rates):
        store.put(rates, links=("symlink",))
        rates.unlink()
        (problem,) = store.verify()
        assert problem.message == (
            f"rates.parquet is a link to {rates}, which is no longer there"
        )

    @pytest.mark.parametrize(
        "kind_of_link, how_it_changed, object_changes",
        [
            ("reflink", "rewritten", False),
            ("reflink", "replaced", False),
            ("hardlink", "rewritten", True),
            ("hardlink", "replaced", False),
            ("symlink", "rewritten", True),
            ("symlink", "replaced", True),
            ("copy", "rewritten", False),
            ("copy", "replaced", False),
        ],
    )
    def test_what_each_kind_of_link_promises(
        self, store, rates, work, kind_of_link, how_it_changed, object_changes
    ):
        """The whole table: which objects change when the original does."""
        if kind_of_link == "reflink" and not _reflink_works(work):
            pytest.skip("this filesystem cannot clone files")
        stored = store.put(rates, links=(kind_of_link,))
        assert stored.frozen is (kind_of_link in FROZEN_LINKS)

        (_rewrite if how_it_changed == "rewritten" else _replace)(rates, b"new numbers")

        held = (stored.path / "rates.parquet").read_bytes()
        assert held == (b"new numbers" if object_changes else b"hello")
        assert bool(store.verify()) is object_changes

    def test_an_object_edited_by_hand(self, store, rates):
        stored = store.put(rates, links=("copy",))
        held = stored.path / "rates.parquet"
        os.chmod(held, 0o644)
        held.write_bytes(b"tampered")
        (problem,) = store.verify()
        assert "no longer what its name says" in problem.message
        assert "outside the store" not in problem.message

    @pytest.mark.parametrize("change", ["edit", "add", "remove"])
    def test_a_directory_whose_files_changed(self, store, partitioned, change):
        stored = store.put(partitioned, links=("copy",))
        target = stored.path / "year=2024" / "part-1.parquet"
        if change == "edit":
            os.chmod(target, 0o644)
            target.write_bytes(b"x" * 30)
        elif change == "add":
            (stored.path / "year=2024" / "part-2.parquet").write_bytes(b"extra")
        else:
            target.unlink()
        (problem,) = store.verify()
        assert problem.content_hash == stored.content_hash
        assert "no longer what its name says" in problem.message

    def test_what_the_operating_system_leaves_in_an_object_is_no_problem(
        self, store, rates, partitioned
    ):
        for stored in (store.put(rates), store.put(partitioned)):
            (stored.path / ".DS_Store").write_bytes(b"finder looked in the store")
        assert store.verify() == []

    def test_an_emptied_object(self, store, rates):
        stored = store.put(rates, links=("copy",))
        (stored.path / "rates.parquet").unlink()
        (problem,) = store.verify()
        assert problem.message == "the object is empty"

    def test_only_the_objects_asked_about(self, store, rates, partitioned):
        store.put(rates, links=("hardlink",))
        other = store.put(partitioned).content_hash
        _rewrite(rates, b"new numbers")
        assert store.verify([other]) == []
        assert [p.content_hash for p in store.verify([HELLO, other])] == [HELLO]

    def test_asking_about_one_that_is_not_there(self, store, rates):
        store.put(rates)
        missing = "sha256:" + "0" * 64
        (problem,) = store.verify([missing])
        assert problem.message == "not in the store"

    def test_every_byte_is_read_again(self, store, rates, monkeypatch):
        """A remembered hash would hide exactly the change being looked for."""
        store.put(rates)
        read = []
        real = hashing._file_hex
        monkeypatch.setattr(hashing, "_file_hex", lambda p: read.append(p) or real(p))
        store.verify()
        store.verify()
        assert len(read) == 2


class TestTogether:
    def test_storing_the_same_file_from_many_threads_makes_one_object(self, store, rates):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.put(rates), range(24)))
        assert {r.content_hash for r in results} == {HELLO}
        assert sum(r.created for r in results) == 1
        assert list(store.hashes()) == [HELLO]
        assert list((store.root / "tmp").iterdir()) == []
        assert store.verify() == []

    def test_an_object_that_appears_meanwhile_wins(self, store, rates, work):
        """Two processes store the same content; the second finds it there."""
        final = store.object_path(HELLO)
        staging = work / "staging"
        staging.mkdir()
        (staging / "rates.parquet").write_bytes(b"hello")
        final.mkdir(parents=True)
        (final / "rates.parquet").write_bytes(b"hello")
        assert FolderStore._move_into_place(staging, final, single=True) is False
        assert sorted(p.name for p in final.iterdir()) == ["rates.parquet"]


@pytest.fixture
def fake_config_dir(work, monkeypatch):
    """Redirect ``~/.chartbook`` to a scratch directory, with no store set."""
    fake_dir = work / ".chartbook"
    monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
    monkeypatch.setattr(
        config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
    )
    monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
    return fake_dir


class TestWhereTheStoreIs:
    def test_beside_the_settings_by_default(self, fake_config_dir):
        assert config.get_store_path() == fake_config_dir / "store"
        assert default_store().root == fake_config_dir / "store"

    def test_the_settings_file_can_move_it(self, fake_config_dir, work):
        fake_config_dir.mkdir()
        settings = {"catalog": {"path": "/c/chartbook.toml"}, "store": {"path": str(work / "big")}}
        (fake_config_dir / "settings.toml").write_text(tomli_w.dumps(settings))
        assert config.get_store_path() == work / "big"

    def test_the_environment_wins(self, fake_config_dir, work, monkeypatch):
        fake_config_dir.mkdir()
        (fake_config_dir / "settings.toml").write_text(
            tomli_w.dumps({"store": {"path": str(work / "big")}})
        )
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "shared"))
        assert config.get_store_path() == work / "shared"
        assert default_store().root == work / "shared"

    def test_an_empty_variable_is_not_a_setting(self, fake_config_dir, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, "  ")
        assert config.get_store_path() == fake_config_dir / "store"

    def test_a_home_directory_is_expanded(self, fake_config_dir, work, monkeypatch):
        monkeypatch.setenv("HOME", str(work))
        monkeypatch.setenv(config.STORE_ENV_VAR, "~/elsewhere")
        assert config.get_store_path() == work / "elsewhere"

    @pytest.mark.parametrize("table", [{}, {"url": ""}, {"url": 3}, {"path": ""}, {"dir": "/x"}])
    def test_a_store_table_without_a_url_is_an_error(self, fake_config_dir, table):
        fake_config_dir.mkdir()
        (fake_config_dir / "settings.toml").write_text(tomli_w.dumps({"store": table}))
        with pytest.raises(ValueError, match=r"\[store\] needs a 'url'"):
            config.get_store_path()


class TestVerifyCommand:
    @pytest.fixture
    def here(self, work, monkeypatch):
        """Point ChartBook's store at a scratch directory, and return it."""
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
        return FolderStore(work / "store")

    def _verify(self):
        return CliRunner().invoke(main, ["store", "verify"])

    def test_a_store_that_is_not_there_yet(self, here):
        result = self._verify()
        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"{here.root}: OK (0 object(s))"
        assert not here.root.exists()

    def test_an_intact_store(self, here, rates, partitioned):
        here.put(rates)
        here.put(partitioned)
        result = self._verify()
        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"{here.root}: OK (2 object(s))"

    def test_a_changed_object_fails(self, here, rates, partitioned):
        here.put(rates, links=("hardlink",))
        here.put(partitioned)
        _rewrite(rates, b"new numbers")
        result = self._verify()
        assert result.exit_code == 1
        first = result.output.splitlines()[0]
        assert first.startswith(f"{HELLO}: its content is no longer what its name says")
        assert f"1 of 2 object(s) in {here.root} are not what their names say." in (
            result.output
        )

    def test_a_store_it_cannot_read_is_a_clean_error(self, here, rates):
        here.put(rates)
        (here.root / MARKER_FILE).write_text('{"schema": "chartbook/store/v9"}')
        result = self._verify()
        assert result.exit_code == 1
        assert result.output.startswith("Error: The store at")

    def test_it_is_listed_in_help(self):
        result = CliRunner().invoke(main, ["store", "--help"])
        assert result.exit_code == 0
        assert "verify" in result.output


class TestAFrozenPutOverALinkedObject:
    def test_keeps_every_name_the_object_had(self, store, work):
        """Found by a reviewer: the same bytes under two names, from two
        pipelines; a frozen put of the second once dropped the first."""
        (work / "a.parquet").write_bytes(b"same bytes")
        (work / "b.parquet").write_bytes(b"same bytes")
        first = store.put(work / "a.parquet", links=("hardlink",))
        assert sorted(p.name for p in store.object_path(first.content_hash).iterdir()) == ["a.parquet"]
        second = store.put(work / "b.parquet", links=("reflink", "copy"))
        assert second.content_hash == first.content_hash
        held = store.object_path(first.content_hash)
        assert sorted(p.name for p in held.iterdir()) == ["a.parquet", "b.parquet"]
        assert (held / "a.parquet").read_bytes() == b"same bytes"
        # ...and now the whole object is the store's own
        (work / "a.parquet").write_bytes(b"rewritten")
        assert (held / "a.parquet").read_bytes() == b"same bytes"



def test_a_folder_store_says_what_an_object_of_one_file_lacks(tmp_path):
    store = store_module.FolderStore(tmp_path / "store")
    (tmp_path / "rates.parquet").write_bytes(b"rates")
    stored = store.put(tmp_path / "rates.parquet")
    assert not store.lacks(stored.content_hash, ["rates.parquet"])
    assert store.lacks(stored.content_hash, ["twin.parquet"])
    # A put adds a name to an object of one file only: not a file to a directory's
    assert not store.lacks(stored.content_hash, ["twin.parquet"], single=False)
    assert not store.lacks(stored.content_hash, ["a.parquet", "b.parquet"])
    assert not store.lacks(stored.content_hash, ["../twin.parquet"])  # not a name in the object
