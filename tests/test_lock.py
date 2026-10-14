"""Tests for pinning: ``chartbook.lock``, ``chartbook.lock`` the file,
``chartbook pin``, ``chartbook update`` and ``chartbook store gc``.

Pinning is the third part of step 3 of ``docs_src/design/overview.md``. A
pipeline freezes what its dependencies have: their files go in the store
and their hashes in a lockfile. References still do not resolve across
pipelines; that is the next part.
"""

import functools
import hashlib
import json
import os
import time
from pathlib import Path

import jsonschema
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, hashing, index, lock
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.lock import LOCK_FILE, SCHEMA, Lock, LockError, PinEvent
from chartbook.store import Root, Store, StoreError
from tests.fixtures import create_catalog_project

HELLO = "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

# These tests pin from a folder as it stands. That is what ``--from-folder``
# does, and what pinning did before there were snapshots. Pinning from a
# snapshot, which is the ordinary way, is tested in tests/test_snapshot.py.
pin_folder = functools.partial(lock.pin, from_folder=True)
update_folder = functools.partial(lock.update, from_folder=True)


def _write_manifest(directory: Path, config_table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(config_table))


def _replace(path: Path, content: bytes) -> None:
    """Put new bytes where a file is, as a new file.

    What every kind of link but a symlink survives, so that these tests say
    the same thing on a disk with copy-on-write clones and one without.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _depend(downstream: Path, **dependencies) -> None:
    """Set a pipeline's ``[dependencies]``. A ``/`` in a key is written ``__``."""
    table = {key.replace("__", "/"): entry for key, entry in dependencies.items()}
    _write_manifest(downstream, {"project": {"id": "downstream"}, "dependencies": table})


def _statuses(report, dependency=None) -> dict:
    """Each asset's status, by its ID with the dependency's name taken off."""
    return {
        event.asset.split(":", 1)[1]: event.status
        for event in report.events
        if event.asset and dependency in (None, event.dependency)
    }


def _age(store: Store, seconds: float = 2 * lock.RECENT_SECONDS) -> None:
    """Make every object in a store look as if it was stored a while ago."""
    then = time.time() - seconds
    for content_hash in store.hashes():
        os.utime(store.object_path(content_hash), (then, then))


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work):
    return Store(work / "store")


@pytest.fixture
def rates(work):
    """An upstream pipeline: a file, a partitioned dataset, a chart, an unbuilt model."""
    directory = work / "rates"
    _write_manifest(
        directory,
        {
            "project": {"id": "rates"},
            "dataframes": {
                "treasury": {"path": "./_data/treasury.parquet", "docs": "d"},
                "by_year": {"path": "./_data/by_year/**/*.parquet", "docs": "d"},
            },
            "charts": {
                "curve": {
                    "path": "./_output/curve.html",
                    "dataframe": "treasury",
                    "docs": "d",
                }
            },
            "models": {"ar1": {"path": "./_models/ar1"}},
        },
    )
    (directory / "_data" / "by_year" / "year=2024").mkdir(parents=True)
    (directory / "_data" / "treasury.parquet").write_bytes(b"hello")
    (directory / "_data" / "by_year" / "year=2024" / "part-0.parquet").write_bytes(b"a" * 10)
    (directory / "_output").mkdir()
    (directory / "_output" / "curve.html").write_bytes(b"<html>curve</html>")
    return directory


@pytest.fixture
def downstream(work, rates):
    """A pipeline that depends on ``rates``, under the name ``acme/rates``."""
    directory = work / "downstream"
    _depend(directory, acme__rates={"path": "../rates"})
    return directory


class TestFrozen:
    """`--frozen`: nothing written; either every pin can be had, or no."""

    def _ok(self, downstream, store):
        report = lock.verify(downstream, store)
        assert report.problems == [], [p.message for p in report.problems]
        return report

    def test_no_lockfile_is_a_problem_when_there_are_dependencies(self, downstream, store, work):
        report = lock.verify(downstream, store)
        assert report.dependencies == 1 and report.pins == 0
        (problem,) = report.problems
        assert "does not exist" in problem.message and "1 dependency" in problem.message
        assert not (downstream / lock.LOCK_FILE).exists() and not (work / "store").exists()
        # ...and no problem at all for a pipeline with nothing to pin
        alone = work / "alone"
        _write_manifest(alone, {"project": {"id": "alone"}})
        assert lock.verify(alone, store).problems == []

    def test_every_pin_in_the_store_is_no_problem_and_writes_nothing(self, downstream, rates, store):
        _train(rates)
        pin_folder(downstream, store)
        before = (downstream / lock.LOCK_FILE).read_bytes()
        report = self._ok(downstream, store)
        assert (report.dependencies, report.pins) == (1, 4)
        assert (downstream / lock.LOCK_FILE).read_bytes() == before

    def test_an_asset_not_built_when_pinned_is_a_problem(self, downstream, store):
        """The stricter choice the design kept for --frozen."""
        pin_folder(downstream, store)  # the model is declared and not built
        (problem,) = lock.verify(downstream, store).problems
        assert problem.asset == "acme/rates:model/ar1" and "not built when it was pinned" in problem.message

    def test_a_pin_the_store_has_lost_is_a_problem(self, downstream, rates, store):
        _train(rates)
        pin_folder(downstream, store)
        store.delete(HELLO)
        (problem,) = lock.verify(downstream, store).problems
        assert problem.asset == "acme/rates:treasury" and "does not have it" in problem.message
        assert "CHARTBOOK_STORE" in problem.message

    def test_the_manifest_and_the_lockfile_must_agree(self, downstream, rates, store, work):
        _train(rates)
        pin_folder(downstream, store)
        # A dependency added since
        _write_manifest(work / "other", {"project": {"id": "other"}})
        _depend(downstream, acme__rates={"path": "../rates"}, other={"path": "../other"})
        (problem,) = lock.verify(downstream, store).problems
        assert problem.dependency == "other" and "not in the lockfile" in problem.message
        # ...one taken away
        _depend(downstream)
        (problem,) = lock.verify(downstream, store).problems
        assert problem.dependency == "acme/rates" and "no longer in [dependencies]" in problem.message
        # ...one that moved
        _depend(downstream, acme__rates={"path": "../elsewhere"})
        problems = lock.verify(downstream, store).problems
        assert any("is pinned from ../rates and [dependencies] now says ../elsewhere" in p.message for p in problems)

    def test_the_command_exits_one_and_writes_nothing(self, downstream, rates, store, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main

        monkeypatch.setenv("CHARTBOOK_STORE", str(store.root))
        result = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(downstream)])
        assert result.exit_code == 1 and "does not exist" in result.output
        assert "Nothing written" in result.output and not (downstream / lock.LOCK_FILE).exists()
        _train(rates)
        pin_folder(downstream, store)
        result = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(downstream)])
        assert result.exit_code == 0, result.output
        assert "4 pin(s) of 1 dependency, all in the store. Nothing written." in result.output
        refused = CliRunner().invoke(main, ["pin", "--frozen", "--from-folder", "--project-dir", str(downstream)])
        assert refused.exit_code == 1 and "One or the other" in refused.output

    def test_a_full_disk_is_still_an_error_and_leaves_no_half_written_note(self, downstream, rates, store, monkeypatch):
        """Found by a reviewer: every OSError was read as "read-only"."""
        import errno
        import json

        _train(rates)
        pin_folder(downstream, store)
        store.remove_root(downstream / lock.LOCK_FILE)

        def full(*args, **kwargs):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(json, "dump", full)
        with pytest.raises(lock.LockError, match="was written, and the store's note.*No space left"):
            pin_folder(downstream, store)
        assert not list((store.root / "roots").glob("*.tmp"))
        assert (downstream / lock.LOCK_FILE).exists()

    def test_a_lockfile_entry_without_an_id_is_a_lock_error(self, downstream, rates, store):
        import json

        _train(rates)
        pin_folder(downstream, store)
        path = downstream / lock.LOCK_FILE
        document = json.loads(path.read_text())
        del document["records"][0]["dependencies"][0]["id"]
        path.write_text(json.dumps(document))
        with pytest.raises(lock.LockError, match="without an id"):
            lock.verify(downstream, store)

    def test_the_remedy_for_a_lost_pin_depends_on_the_kind(self, downstream, rates, store):
        """Found by a reviewer: `chartbook pin` never re-stores a path dependency's lost pin."""
        _train(rates)
        pin_folder(downstream, store)
        store.delete(HELLO)
        (problem,) = lock.verify(downstream, store).problems
        # Pinned from the folder: only the folder can put it back
        assert "`chartbook pin --from-folder`, where the store can be written, puts it back" in problem.message
        assert lock.pin(downstream, store, from_folder=True) and store.has(HELLO)

    @pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a store this user cannot write")
    def test_a_read_only_roots_folder_is_a_note_not_a_failure(self, downstream, rates, store):
        """Only the note for gc could not be left; the pins are made."""
        _train(rates)
        pin_folder(downstream, store)  # the objects get into the store
        (downstream / lock.LOCK_FILE).unlink()
        store.remove_root(downstream / lock.LOCK_FILE)
        roots = store.root / "roots"
        mode = roots.stat().st_mode
        os.chmod(roots, 0o555)
        try:
            report = pin_folder(downstream, store)
        finally:
            os.chmod(roots, mode)
        assert report.written and "Permission denied" in report.unrooted
        assert set(_statuses(report).values()) == {"pinned"}
        assert lock.verify(downstream, store).problems == []


def _train(rates: Path) -> None:
    """Build the upstream's model: a directory of two files."""
    (rates / "_models" / "ar1" / "weights").mkdir(parents=True, exist_ok=True)
    (rates / "_models" / "ar1" / "config.json").write_bytes(b"{}")
    (rates / "_models" / "ar1" / "weights" / "best.pt").write_bytes(b"w" * 100)


class TestPin:
    def test_every_built_asset_of_a_dependency_is_pinned(self, downstream, rates, store):
        report = pin_folder(downstream, store)
        assert report.lockfile == downstream / LOCK_FILE and report.written
        assert _statuses(report) == {
            "treasury": "pinned",
            "by_year": "pinned",
            "chart/curve": "pinned",
            "model/ar1": "not_built",
        }
        assert report.problems == []

        locked = lock.read_lock(downstream)
        assert locked.root == "downstream"
        assert locked.assets["acme/rates:treasury"]["content_hash"] == HELLO
        # ...and the bytes are in the store, under the file's own name
        assert (store.get(HELLO) / "treasury.parquet").read_bytes() == b"hello"
        partitioned = locked.assets["acme/rates:by_year"]["content_hash"]
        assert (store.get(partitioned) / "year=2024" / "part-0.parquet").is_file()
        assert set(store.hashes()) == locked.hashes()

    def test_the_lockfile(self, downstream, rates, store):
        """The whole file, for a dependency with one asset built and one not."""
        _write_manifest(
            rates,
            {
                "project": {"id": "rates"},
                "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
                "models": {"ar1": {"path": "./_models/ar1"}},
            },
        )
        pin_folder(downstream, store)
        listing = f"{HELLO.split(':')[1]}  acme/rates:treasury\n"
        overall = "sha256:" + hashlib.sha256(listing.encode()).hexdigest()
        assert json.loads((downstream / LOCK_FILE).read_text()) == {
            "schema": "chartbook/lock/v1",
            "root": "downstream",
            "records": [
                {
                    "kind": "Pipeline",
                    "version": "chartbook/v1",
                    "id": "downstream",
                    "dependencies": [
                        {
                            "id": "acme/rates",
                            "via": "path",
                            "location": {"kind": "path", "path": "../rates"},
                            "pinned_hash": overall,
                        }
                    ],
                },
                {
                    "kind": "Model",
                    "version": "chartbook/v1",
                    "id": "acme/rates:model/ar1",
                    "ref": {
                        "scope": "acme",
                        "pipeline": "rates",
                        "kind": "model",
                        "name": "ar1",
                    },
                    "pipeline": "acme/rates",
                    "location": {"kind": "file", "path": "./_models/ar1"},
                },
                {
                    "kind": "Dataframe",
                    "version": "chartbook/v1",
                    "id": "acme/rates:treasury",
                    "ref": {
                        "scope": "acme",
                        "pipeline": "rates",
                        "kind": "dataframe",
                        "name": "treasury",
                    },
                    "pipeline": "acme/rates",
                    "location": {"kind": "file", "path": "./_data/treasury.parquet"},
                    "content_hash": HELLO,
                    "size_bytes": 5,
                },
            ],
        }

    def test_it_has_nothing_of_this_machine_or_this_moment_in_it(
        self, downstream, rates, store, work
    ):
        pin_folder(downstream, store)
        text = (downstream / LOCK_FILE).read_text()
        assert str(work) not in text
        document = json.loads(text)
        assert set(document) == {"schema", "root", "records"}
        assert text.endswith("}\n")

    def test_pinning_twice_writes_the_same_bytes(self, downstream, rates, store):
        pin_folder(downstream, store)
        lockfile = downstream / LOCK_FILE
        first, written_at = lockfile.read_bytes(), lockfile.stat().st_mtime_ns
        report = pin_folder(downstream, store)
        assert report.written is False
        assert lockfile.read_bytes() == first
        assert lockfile.stat().st_mtime_ns == written_at
        assert _statuses(report)["treasury"] == "kept"

    def test_a_pin_is_never_moved_by_pinning_again(self, downstream, rates, store):
        """The decision: only `update` moves a pin."""
        pin_folder(downstream, store)
        before = (downstream / LOCK_FILE).read_bytes()
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")

        report = pin_folder(downstream, store)
        assert _statuses(report)["treasury"] == "stale"
        assert report.count("stale") == 1 and report.problems == []
        assert report.written is False
        assert (downstream / LOCK_FILE).read_bytes() == before
        assert (store.get(HELLO) / "treasury.parquet").read_bytes() == b"hello"

    def test_what_has_no_pin_yet_is_pinned(self, downstream, rates, store):
        pin_folder(downstream, store)
        _train(rates)  # an asset that was declared and not built
        report = pin_folder(downstream, store)
        assert _statuses(report) == {
            "treasury": "kept",
            "by_year": "kept",
            "chart/curve": "kept",
            "model/ar1": "pinned",
        }
        model = lock.read_lock(downstream).assets["acme/rates:model/ar1"]
        assert model["content_hash"] == hashing.hash_directory(rates / "_models" / "ar1").content_hash
        assert model["size_bytes"] == 102
        assert (store.get(model["content_hash"]) / "weights" / "best.pt").is_file()

    def test_an_asset_that_is_not_built_is_recorded_without_a_hash(
        self, downstream, rates, store
    ):
        report = pin_folder(downstream, store)
        (event,) = [e for e in report.events if e.status == "not_built"]
        assert event == PinEvent(
            "not_built", "acme/rates", "acme/rates:model/ar1", detail="./_models/ar1"
        )
        record = lock.read_lock(downstream).assets["acme/rates:model/ar1"]
        assert "content_hash" not in record and "size_bytes" not in record
        assert record["location"] == {"kind": "file", "path": "./_models/ar1"}

    def test_a_clean_clone_gets_its_pins_back(self, downstream, rates, store):
        """The lockfile is committed; the store is not. `pin` fills it again."""
        pin_folder(downstream, store)
        before = (downstream / LOCK_FILE).read_bytes()
        for content_hash in list(store.hashes()):
            store.delete(content_hash)

        report = pin_folder(downstream, store)
        assert _statuses(report)["treasury"] == "restored"
        assert report.problems == [] and report.written is False
        assert (downstream / LOCK_FILE).read_bytes() == before
        assert store.has(HELLO)

    def test_a_pin_that_cannot_be_got_back_is_a_problem(self, downstream, rates, store):
        pin_folder(downstream, store)
        before = (downstream / LOCK_FILE).read_bytes()
        store.delete(HELLO)
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")

        report = pin_folder(downstream, store)
        (problem,) = report.problems
        assert problem.status == "lost" and problem.asset == "acme/rates:treasury"
        assert problem.old == HELLO
        assert "the other pipeline no longer has those bytes" in problem.detail
        # The pin is not quietly moved to what is there now
        assert (downstream / LOCK_FILE).read_bytes() == before
        assert not store.has(hashing.hash_file(rates / "_data" / "treasury.parquet").content_hash)

    def test_a_dependency_that_is_no_longer_declared_is_let_go(self, downstream, rates, store, work):
        other = work / "macro"
        _write_manifest(other, {"dataframes": {"gdp": {"path": "./gdp.parquet", "docs": "d"}}})
        (other / "gdp.parquet").write_bytes(b"gdp")
        _depend(downstream, acme__rates={"path": "../rates"}, macro={"path": "../macro"})
        pin_folder(downstream, store)
        assert "macro:gdp" in lock.read_lock(downstream).assets

        _depend(downstream, acme__rates={"path": "../rates"})
        report = pin_folder(downstream, store)
        assert PinEvent("removed", "macro") in report.events
        locked = lock.read_lock(downstream)
        assert "macro:gdp" not in locked.assets
        assert [entry["id"] for entry in locked.dependencies] == ["acme/rates"]

    def test_a_dependency_that_is_not_there_cannot_be_pinned(self, downstream, store):
        _depend(downstream, acme__rates={"path": "../not_cloned_yet"})
        report = pin_folder(downstream, store)
        (problem,) = report.problems
        assert problem.status == "unreachable" and problem.dependency == "acme/rates"
        assert "no pipeline can be read at" in problem.detail
        assert lock.read_lock(downstream).dependencies == [
            {
                "id": "acme/rates",
                "via": "path",
                "location": {"kind": "path", "path": "../not_cloned_yet"},
            }
        ]

    def test_a_pinned_dependency_can_go_away(self, downstream, rates, store):
        """What pinning is for: the pins are in the store."""
        pin_folder(downstream, store)
        before = (downstream / LOCK_FILE).read_bytes()
        os.rename(rates, rates.with_name("rates_moved_away"))

        report = pin_folder(downstream, store)
        assert report.problems == []
        assert set(_statuses(report).values()) == {"kept"}
        assert (downstream / LOCK_FILE).read_bytes() == before

    def test_an_asset_the_dependency_stops_declaring_stays_pinned(
        self, downstream, rates, store
    ):
        pin_folder(downstream, store)
        _write_manifest(
            rates,
            {"dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}},
        )
        report = pin_folder(downstream, store)
        assert _statuses(report) == {
            "treasury": "kept",
            "by_year": "kept",
            "chart/curve": "kept",
        }
        locked = lock.read_lock(downstream)
        assert "acme/rates:by_year" in locked.assets
        # The model was never pinned, so there was nothing to keep
        assert "acme/rates:model/ar1" not in locked.assets

    def test_a_pipeline_with_no_dependencies_gets_no_lockfile(self, work, store):
        alone = work / "alone"
        _write_manifest(alone, {"project": {"id": "alone"}})
        report = pin_folder(alone, store)
        assert report.events == [] and report.written is False
        assert not (alone / LOCK_FILE).exists()
        assert not store.root.exists()

    def test_the_last_dependency_removed_empties_the_lockfile(self, downstream, rates, store):
        pin_folder(downstream, store)
        _write_manifest(downstream, {"project": {"id": "downstream"}})
        report = pin_folder(downstream, store)
        assert report.events == [PinEvent("removed", "acme/rates")]
        locked = lock.read_lock(downstream)
        assert locked.dependencies == [] and locked.assets == {}
        assert store.roots() == []

    def test_the_store_is_told_which_lockfile_names_what(self, downstream, rates, store):
        pin_folder(downstream, store)
        assert store.roots() == [
            Root(downstream / LOCK_FILE, tuple(sorted(lock.read_lock(downstream).hashes())))
        ]

    def test_a_pin_is_a_clone_or_a_copy_and_never_a_link(
        self, downstream, rates, store, monkeypatch
    ):
        """Decided: a pin must not change when the upstream rewrites its file."""
        assert lock.PIN_LINKS == ("reflink", "copy")

        def refuse(*args, **kwargs):
            raise OSError(95, "not supported here")

        monkeypatch.setattr(store_module, "_reflink", refuse)  # a disk with no clones
        pin_folder(downstream, store)
        upstream = rates / "_data" / "treasury.parquet"
        held = store.get(HELLO) / "treasury.parquet"
        assert not held.is_symlink() and not held.samefile(upstream)
        assert os.stat(held).st_nlink == 1

        # Rewritten in place, as pandas and polars rewrite a parquet file
        with open(upstream, "r+b") as f:
            f.write(b"new numbers")
            f.truncate()
        assert held.read_bytes() == b"hello"
        assert store.verify() == []

    def test_a_pin_replaces_an_object_that_was_stored_as_a_link(
        self, downstream, rates, store
    ):
        """Something else may have stored the same bytes more cheaply."""
        upstream = rates / "_data" / "treasury.parquet"
        store.put(upstream, links=("hardlink",))
        assert (store.get(HELLO) / "treasury.parquet").samefile(upstream)

        pin_folder(downstream, store)
        held = store.get(HELLO) / "treasury.parquet"
        assert not held.samefile(upstream)
        assert held.read_bytes() == b"hello" and store.verify() == []

    def test_only_what_pinning_needs_is_read_from_the_manifest(self, downstream, rates, store):
        """A dataframe with no write-up does not load, and can still be pinned from."""
        with open(downstream / "chartbook.toml", "a") as f:
            f.write('\n[dataframes.broken]\npath = "./x.parquet"\n')
        assert pin_folder(downstream, store).problems == []

    def test_a_catalog_has_nothing_to_pin(self, work, store):
        catalog = create_catalog_project(work / "cat")
        with pytest.raises(LockError, match="is a catalog"):
            pin_folder(catalog, store)

    def test_a_directory_with_no_manifest(self, work, store):
        (work / "empty").mkdir()
        with pytest.raises(LockError, match="No chartbook.toml in"):
            pin_folder(work / "empty", store)

    def test_a_malformed_dependencies_table_names_the_file(self, downstream, store):
        _depend(downstream, rates={"path": "../rates", "git": "https://x/y"})
        with pytest.raises(ValueError) as e:
            pin_folder(downstream, store)
        assert str(downstream / "chartbook.toml") in str(e.value)
        assert "both 'path' and 'git'" in str(e.value)


class TestUpdate:
    def test_it_moves_a_pin_to_what_the_dependency_has_now(self, downstream, rates, store):
        pin_folder(downstream, store)
        before = lock.read_lock(downstream)
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        now = hashing.hash_file(rates / "_data" / "treasury.parquet").content_hash

        report = update_folder(downstream, store=store)
        assert report.written is True
        (moved,) = [e for e in report.events if e.status == "moved"]
        assert moved.asset == "acme/rates:treasury"
        assert (moved.old, moved.new) == (HELLO, now)
        assert _statuses(report)["by_year"] == "kept"

        after = lock.read_lock(downstream)
        assert after.assets["acme/rates:treasury"]["content_hash"] == now
        assert after.assets["acme/rates:treasury"]["size_bytes"] == 11
        assert after.dependencies[0]["pinned_hash"] != before.dependencies[0]["pinned_hash"]
        # The old object is still in the store, until it is cleared out
        assert store.has(HELLO) and store.has(now)

    def test_nothing_changed_writes_nothing(self, downstream, rates, store):
        pin_folder(downstream, store)
        report = update_folder(downstream, store=store)
        assert report.written is False
        assert set(_statuses(report).values()) == {"kept", "not_built"}

    def test_only_the_dependencies_named(self, downstream, rates, store, work):
        macro = work / "macro"
        _write_manifest(macro, {"dataframes": {"gdp": {"path": "./gdp.parquet", "docs": "d"}}})
        (macro / "gdp.parquet").write_bytes(b"gdp")
        _depend(downstream, acme__rates={"path": "../rates"}, macro={"path": "../macro"})
        pin_folder(downstream, store)
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        _replace(macro / "gdp.parquet", b"new gdp")

        report = update_folder(downstream, ["rates"], store=store)  # the scope left off
        assert _statuses(report, "acme/rates")["treasury"] == "moved"
        assert _statuses(report, "macro")["gdp"] == "stale"

        report = update_folder(downstream, ["macro"], store=store)
        assert _statuses(report, "macro")["gdp"] == "moved"

    def test_a_name_that_is_not_a_dependency(self, downstream, rates, store):
        with pytest.raises(LockError) as e:
            update_folder(downstream, ["nope"], store=store)
        assert "Pipeline 'nope' not found" in str(e.value)
        assert "Declared in [dependencies]: acme/rates." in str(e.value)
        assert "In the catalog" not in str(e.value)

    def test_an_asset_that_is_no_longer_built_keeps_its_pin(self, downstream, rates, store):
        pin_folder(downstream, store)
        (rates / "_data" / "treasury.parquet").unlink()
        report = update_folder(downstream, store=store)
        assert _statuses(report)["treasury"] == "kept"
        assert lock.read_lock(downstream).assets["acme/rates:treasury"]["content_hash"] == HELLO

    def test_an_asset_no_longer_declared_is_dropped(self, downstream, rates, store):
        pin_folder(downstream, store)
        _write_manifest(
            rates,
            {"dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}},
        )
        report = update_folder(downstream, store=store)
        dropped = sorted(e.asset for e in report.events if e.status == "dropped")
        assert dropped == ["acme/rates:by_year", "acme/rates:chart/curve"]
        assert set(lock.read_lock(downstream).assets) == {"acme/rates:treasury"}

    def test_a_dependency_that_is_not_there_cannot_be_updated(self, downstream, rates, store):
        pin_folder(downstream, store)
        before = (downstream / LOCK_FILE).read_bytes()
        os.rename(rates, rates.with_name("rates_moved_away"))
        report = update_folder(downstream, store=store)
        assert [p.status for p in report.problems] == ["unreachable"]
        assert (downstream / LOCK_FILE).read_bytes() == before


class TestPinnedHash:
    def test_it_is_a_listing_of_the_pins(self):
        records = [
            {"id": "r:b", "content_hash": "sha256:" + "b" * 64},
            {"id": "r:a", "content_hash": "sha256:" + "a" * 64},
            {"id": "r:not_built"},
        ]
        listing = f"{'a' * 64}  r:a\n{'b' * 64}  r:b\n"
        assert lock.pinned_hash(records) == (
            "sha256:" + hashlib.sha256(listing.encode()).hexdigest()
        )
        assert lock.pinned_hash(reversed(records)) == lock.pinned_hash(records)

    def test_nothing_pinned_has_none(self):
        assert lock.pinned_hash([{"id": "r:not_built"}]) is None
        assert lock.pinned_hash([]) is None


class TestReadingAndWriting:
    def test_a_lockfile_reads_back_as_it_was_written(self, downstream, rates, store):
        pin_folder(downstream, store)
        locked = lock.read_lock(downstream / LOCK_FILE)
        assert isinstance(locked, Lock)
        assert lock.read_lock(downstream) == locked  # a directory will do
        assert locked.to_document() == json.loads((downstream / LOCK_FILE).read_text())
        assert set(locked.assets_of("acme/rates")) == set(locked.assets)
        assert locked.assets_of("nope") == {}

    def test_no_lockfile_is_none(self, work):
        assert lock.read_lock(work) is None
        assert lock.read_lock(work / LOCK_FILE) is None

    @pytest.mark.parametrize(
        "content",
        ["not json", "[]", '{"schema": "chartbook/lock/v9", "root": "x", "records": []}',
         '{"schema": "chartbook/lock/v1"}'],
    )
    def test_a_file_that_is_not_a_lockfile(self, work, content):
        (work / LOCK_FILE).write_text(content)
        with pytest.raises(LockError, match="Cannot read"):
            lock.read_lock(work)

    def test_a_lockfile_from_a_later_version_says_so(self, work):
        (work / LOCK_FILE).write_text(
            '{"schema": "chartbook/lock/v9", "root": "x", "records": []}'
        )
        with pytest.raises(LockError, match="reads 'chartbook/lock/v1'"):
            lock.read_lock(work)

    def test_write_lock_leaves_an_identical_file_alone(self, work):
        locked = Lock(root="p")
        assert lock.write_lock(locked, work / LOCK_FILE) is True
        assert lock.write_lock(locked, work / LOCK_FILE) is False
        assert json.loads((work / LOCK_FILE).read_text())["schema"] == SCHEMA
        assert not (work / (LOCK_FILE + ".tmp")).exists()


class TestSchemas:
    """The lockfile is in the index's format: no second one."""

    def test_the_file_fits_its_schema(self, downstream, rates, store):
        pin_folder(downstream, store)
        document = json.loads((downstream / LOCK_FILE).read_text())
        jsonschema.validate(document, json.loads(lock.schema_path().read_text()))

    def test_each_asset_record_fits_the_indexs_schema_for_its_kind(
        self, downstream, rates, store
    ):
        _train(rates)
        pin_folder(downstream, store)
        records = json.loads((downstream / LOCK_FILE).read_text())["records"]
        kinds = set()
        for record in records[1:]:
            schema = json.loads(index.schema_path(record["kind"]).read_text())
            jsonschema.validate(record, schema)
            kinds.add(record["kind"])
        assert kinds == {"Dataframe", "Chart", "Model"}

    def test_each_dependency_fits_the_indexs_schema_for_one(self, downstream, rates, store):
        _depend(
            downstream,
            acme__rates={"path": "../rates"},
            crsp={"git": "https://example.org/acme/crsp.git"},
        )
        pin_folder(downstream, store)
        pipeline = json.loads(index.schema_path("Pipeline").read_text())
        dependency = pipeline["properties"]["dependencies"]["items"]
        for entry in lock.read_lock(downstream).dependencies:
            jsonschema.validate(entry, dependency)

    def test_the_schema_is_shipped_beside_the_indexs(self):
        assert lock.schema_path().parent.parent == index.SCHEMAS_DIR
        schema = json.loads(lock.schema_path().read_text())
        assert schema["properties"]["schema"] == {"const": SCHEMA}
        jsonschema.Draft202012Validator.check_schema(schema)


class TestStoreRoots:
    def test_a_lockfile_is_noted_and_the_note_replaced(self, store, work):
        lockfile = work / "p" / LOCK_FILE
        other = "sha256:" + "0" * 64
        store.add_root(lockfile, [HELLO])
        store.add_root(lockfile, [other, HELLO, other])
        assert store.roots() == [Root(lockfile, (other, HELLO))]

    def test_roots_are_listed_by_path(self, store, work):
        store.add_root(work / "b" / LOCK_FILE, [HELLO])
        store.add_root(work / "a" / LOCK_FILE, [HELLO])
        assert [root.lockfile.parent.name for root in store.roots()] == ["a", "b"]

    def test_forgetting_one(self, store, work):
        store.add_root(work / LOCK_FILE, [HELLO])
        assert store.remove_root(work / LOCK_FILE) is True
        assert store.remove_root(work / LOCK_FILE) is False
        assert store.roots() == []

    def test_a_store_with_no_notes(self, store):
        assert store.roots() == []
        assert store.remove_root("anything") is False
        assert not store.root.exists()

    def test_only_a_content_hash_is_noted(self, store, work):
        with pytest.raises(ValueError, match="is not a content hash"):
            store.add_root(work / LOCK_FILE, ["../../etc"])
        assert not store.root.exists()

    def test_a_note_that_cannot_be_read_stops_everything(self, store, work):
        store.add_root(work / LOCK_FILE, [HELLO])
        (note,) = (store.root / "roots").glob("*.json")
        note.write_text("not json")
        with pytest.raises(StoreError, match="Cannot read"):
            store.roots()


class TestGc:
    @pytest.fixture
    def moved(self, downstream, rates, store):
        """A store with one object that an update left behind, an hour old."""
        pin_folder(downstream, store)
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        update_folder(downstream, store=store)
        _age(store)
        return store

    def test_what_no_lockfile_names_can_go(self, moved, downstream):
        plan = lock.plan_gc(moved)
        assert plan.lockfiles == [(downstream / LOCK_FILE, True)]
        assert plan.kept == 3
        assert plan.delete == [(HELLO, 5)] and plan.size_bytes == 5
        assert plan.recent == [] and plan.forget == []
        # Planning removes nothing
        assert moved.has(HELLO)

        assert lock.run_gc(plan, moved) == (0, 1)
        assert not moved.has(HELLO)
        assert set(moved.hashes()) == lock.read_lock(downstream).hashes()
        assert moved.verify() == []
        assert lock.plan_gc(moved).delete == []

    def test_what_was_stored_in_the_last_hour_is_left_alone(self, downstream, rates, store):
        """A pin stores a file before it writes the lockfile that names it."""
        pin_folder(downstream, store)
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        update_folder(downstream, store=store)
        plan = lock.plan_gc(store)
        assert plan.delete == [] and plan.recent == [HELLO]
        assert lock.plan_gc(store, recent_seconds=0).delete == [(HELLO, 5)]

    def test_storing_an_object_again_makes_it_recent(self, moved, rates):
        _replace(rates / "_data" / "old.parquet", b"hello")
        moved.put(rates / "_data" / "old.parquet")
        assert lock.plan_gc(moved).recent == [HELLO]

    def test_another_projects_pins_are_kept(self, moved, downstream, rates, work):
        """The store is shared. Clearing it out from one project spares the rest."""
        other = work / "other"
        _write_manifest(rates.with_name("old_rates"), {"dataframes": {"t": {"path": "./t.parquet", "docs": "d"}}})
        (rates.with_name("old_rates") / "t.parquet").write_bytes(b"hello")
        _depend(other, old={"path": "../old_rates"})
        pin_folder(other, moved)
        _age(moved)

        plan = lock.plan_gc(moved)
        assert [found for _, found in plan.lockfiles] == [True, True]
        assert plan.delete == [] and plan.kept == 4

    def test_a_lockfile_that_cannot_be_found_still_keeps_its_pins(self, moved, downstream):
        kept_before = lock.read_lock(downstream).hashes()
        os.rename(downstream, downstream.with_name("unplugged"))
        plan = lock.plan_gc(moved)
        assert plan.lockfiles == [(downstream / LOCK_FILE, False)]
        assert plan.kept == 3 and plan.delete == [(HELLO, 5)]
        lock.run_gc(plan, moved)
        assert set(moved.hashes()) == kept_before
        assert len(moved.roots()) == 1

    def test_unless_told_to_forget_it(self, moved, downstream):
        os.rename(downstream, downstream.with_name("deleted"))
        plan = lock.plan_gc(moved, forget_missing=True)
        assert plan.forget == [downstream / LOCK_FILE]
        assert plan.kept == 0 and len(plan.delete) == 4
        assert lock.run_gc(plan, moved) == (0, 4)
        assert list(moved.hashes()) == [] and moved.roots() == []

    def test_a_lockfile_is_read_as_it_is_now(self, moved, downstream):
        """Checked out at another commit, say, and not pinned again since."""
        locked = lock.read_lock(downstream)
        del locked.assets["acme/rates:by_year"]
        lock.write_lock(locked, downstream / LOCK_FILE)
        assert len(lock.plan_gc(moved).delete) == 2

    def test_a_lockfile_that_cannot_be_read_stops_it(self, moved, downstream):
        (downstream / LOCK_FILE).write_text("not json")
        with pytest.raises(LockError, match="Cannot read"):
            lock.plan_gc(moved)
        assert moved.has(HELLO)

    def test_a_store_nobody_has_pinned_into(self, store, work):
        (work / "f").write_bytes(b"hello")
        store.put(work / "f")
        _age(store)
        plan = lock.plan_gc(store)
        assert plan.lockfiles == [] and plan.delete == [(HELLO, 5)]
        assert lock.plan_gc(Store(work / "no_store")).delete == []


class TestCommands:
    @pytest.fixture
    def here(self, work, downstream, monkeypatch):
        """Run commands in the downstream pipeline, with a scratch store."""
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
        monkeypatch.chdir(downstream)
        return Store(work / "store")

    def _run(self, *args, **kwargs):
        if args and args[0] in ("pin", "update"):
            args = (*args, "--from-folder")
        return CliRunner().invoke(main, list(args), **kwargs)

    def test_pin(self, here, downstream):
        result = self._run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/rates: 3 pinned, 1 not built",
            "  not built: acme/rates:model/ar1 (./_models/ar1)",
            "  Taken from its folder as it is now, not from a snapshot.",
            "Wrote chartbook.lock.",
        ]
        assert (downstream / LOCK_FILE).is_file()
        assert len(list(here.hashes())) == 3

    def test_pin_again_says_nothing_moved(self, here, rates):
        self._run("pin")
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        result = self._run("pin")
        assert result.exit_code == 0, result.output
        assert "acme/rates: 2 already pinned, 1 changed upstream since it was pinned, 1 not built" in (
            result.output
        )
        assert "  changed upstream: acme/rates:treasury" in result.output
        assert "chartbook.lock is unchanged." in result.output
        assert "1 pinned asset(s) have changed upstream. `chartbook update` moves the pins." in (
            result.output
        )

    def test_update_shows_what_moved(self, here, rates):
        self._run("pin")
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        now = hashing.hash_file(rates / "_data" / "treasury.parquet").content_hash
        result = self._run("update", "rates")
        assert result.exit_code == 0, result.output
        assert "acme/rates: 1 moved, 2 already pinned, 1 not built" in result.output
        assert f"  acme/rates:treasury\n    {HELLO} -> {now}" in result.output
        assert "Wrote chartbook.lock." in result.output

    def test_update_of_something_that_is_not_a_dependency(self, here):
        result = self._run("update", "nope")
        assert result.exit_code == 1
        assert result.output.startswith("Error: Pipeline 'nope' not found.")

    def test_a_dependency_that_cannot_be_pinned_fails(self, here, downstream):
        _depend(downstream, acme__rates={"path": "../not_cloned_yet"})
        result = self._run("pin")
        assert result.exit_code == 1
        assert "acme/rates: cannot be pinned: no pipeline can be read at" in result.output
        assert "1 thing(s) could not be pinned." in result.output

    def test_no_dependencies(self, here, downstream):
        _write_manifest(downstream, {"project": {"id": "downstream"}})
        result = self._run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "No dependencies to pin."

    def test_pin_in_a_catalog_is_a_clean_error(self, here, work, monkeypatch):
        monkeypatch.chdir(create_catalog_project(work / "cat"))
        result = self._run("pin")
        assert result.exit_code == 1
        assert result.output.startswith("Error: ") and "is a catalog" in result.output

    def test_project_dir(self, here, downstream, work, monkeypatch):
        monkeypatch.chdir(work)
        result = self._run("pin", "--project-dir", str(downstream))
        assert result.exit_code == 0, result.output
        assert (downstream / LOCK_FILE).is_file()

    @pytest.fixture
    def garbage(self, here, rates):
        """A store with one object that an update left behind, an hour old."""
        self._run("pin")
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        self._run("update")
        _age(here)
        return here

    def test_gc_dry_run_removes_nothing(self, garbage, downstream):
        result = self._run("store", "gc", "--dry-run")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "Kept: 3 object(s), named by 1 lockfile(s)",
            f"  {downstream / LOCK_FILE}",
            "Would remove 1 object(s), 5 bytes, that nothing names:",
            f"  {HELLO}  5 bytes",
        ]
        assert garbage.has(HELLO)

    def test_gc_asks_first(self, garbage):
        result = self._run("store", "gc", input="n\n")
        assert result.exit_code == 0, result.output
        assert "Would remove 1 object(s), 5 bytes, that nothing names." in result.output
        assert "Remove them? [y/N]" in result.output
        assert "Nothing was removed." in result.output
        assert garbage.has(HELLO)

        result = self._run("store", "gc", input="y\n")
        assert "Removed 0 snapshot(s) and 1 object(s), 5 bytes." in result.output
        assert not garbage.has(HELLO)

    def test_gc_with_no_answer_removes_nothing(self, garbage):
        result = self._run("store", "gc", input="")
        assert garbage.has(HELLO)
        assert "Removed" not in result.output

    def test_gc_yes(self, garbage):
        result = self._run("store", "gc", "--yes")
        assert result.exit_code == 0, result.output
        assert "Remove them?" not in result.output
        assert "Removed 0 snapshot(s) and 1 object(s), 5 bytes." in result.output
        assert not garbage.has(HELLO)
        assert "Nothing to remove." in self._run("store", "gc").output

    def test_gc_says_what_it_spared_for_being_new(self, here, rates):
        self._run("pin")
        _replace(rates / "_data" / "treasury.parquet", b"new numbers")
        self._run("update")
        result = self._run("store", "gc", "--yes")
        assert "Kept: 1 object(s) nothing names, stored in the last hour" in result.output
        assert "Nothing to remove." in result.output
        assert here.has(HELLO)

    def test_gc_keeps_the_pins_of_a_lockfile_it_cannot_find(self, garbage, downstream):
        os.rename(downstream / LOCK_FILE, downstream / "moved.lock")
        result = self._run("store", "gc", "--yes")
        assert f"  {downstream / LOCK_FILE}  (not found; its pins are kept)" in result.output
        assert len(list(garbage.hashes())) == 3

        result = self._run("store", "gc", "--yes", "--forget-missing")
        assert f"  {downstream / LOCK_FILE}  (not found; forgotten)" in result.output
        assert "Removed 0 snapshot(s) and 3 object(s)" in result.output
        assert list(garbage.hashes()) == [] and garbage.roots() == []

    def test_gc_stops_at_a_lockfile_it_cannot_read(self, garbage, downstream):
        (downstream / LOCK_FILE).write_text("not json")
        result = self._run("store", "gc", "--yes")
        assert result.exit_code == 1
        assert result.output.startswith("Error: Cannot read")
        assert "Nothing was removed." in result.output
        assert garbage.has(HELLO)

    def test_sizes_are_written_for_people(self):
        from chartbook.cli import _format_bytes

        assert _format_bytes(5) == "5 bytes"
        assert _format_bytes(1536) == "1.5 KB"
        assert _format_bytes(5 * 1024**2) == "5.0 MB"
        assert _format_bytes(3 * 1024**4) == "3072.0 GB"

    def test_what_is_pinned_between_the_plan_and_the_yes_is_kept(self, here, downstream, work):
        """The plan is made again when the yes comes."""
        _write_manifest(work / "stray", {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (work / "stray" / "x.parquet").write_bytes(b"stray bytes")
        stray = here.put(work / "stray" / "x.parquet")
        plan = lock.plan_gc(here, recent_seconds=0)
        assert [h for h, _ in plan.delete] == [stray.content_hash]
        # ...and before the yes, a project pins it
        _write_manifest(downstream, {"dependencies": {"stray": {"path": "../stray"}}})
        pin_folder(downstream, here)
        removed_snapshots, removed = lock.run_gc(plan, here)
        assert (removed_snapshots, removed) == (0, 0) and here.has(stray.content_hash)
