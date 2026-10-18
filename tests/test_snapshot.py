"""Tests for snapshots: ``chartbook.snapshot``, ``chartbook snapshot``, and
pinning from one.

This is the second part of step 4 of ``docs_src/design/overview.md``, and
the model under "The snapshot model" there. A pipeline's owner declares a
build ready, at a commit, and that is what other pipelines pin. Nothing
reads a folder it depends on.

Two names run through these tests, as through the design: ``maker`` makes
data, and ``user`` uses it. They are in one repository unless a test says
otherwise.
"""

import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import data, index, lock, snapshot
from chartbook.cli import main
from chartbook.manifest import load_manifest
from chartbook.snapshot import SnapshotError
from chartbook.store import default_store
from tests.fixtures import name_no_snapshot


def _git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(repository: Path, message: str = "Work") -> str:
    """Commit everything in a repository, making it one first if need be."""
    if not (repository / ".git").exists():
        (repository / ".gitignore").write_text("chartbook.lock\n_data/\n_output/\n")
        _git(repository, "init", "--quiet", "-b", "main")
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "--allow-empty", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _manifest(directory: Path, table: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table))
    return directory


def _build(maker: Path, rates: bytes = b"rates-1", curve: bytes = b"curve-1") -> None:
    """Write the maker's built data, which git ignores, as a build would."""
    (maker / "_data").mkdir(exist_ok=True)
    (maker / "_data" / "rates.parquet").write_bytes(rates)
    (maker / "_output").mkdir(exist_ok=True)
    (maker / "_output" / "curve.html").write_bytes(curve)


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def maker(work):
    """A pipeline that declares a dataframe and a chart, built and committed."""
    directory = _manifest(
        work / "maker",
        {
            "project": {"id": "acme/maker"},
            "dataframes": {"rates": {"path": "./_data/rates.parquet", "docs": "d"}},
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "rates", "docs": "d"}},
        },
    )
    _build(directory)
    _commit(work)
    return directory


@pytest.fixture
def user(work, maker):
    """A pipeline that depends on ``maker``, in the same repository."""
    directory = _manifest(
        work / "user",
        {"project": {"id": "acme/user"}, "dependencies": {"acme/maker": {"path": "../maker"}}},
    )
    _commit(work)
    return directory


def _statuses(report) -> dict:
    return {e.asset.split(":")[1]: e.status for e in report.events if e.asset}


class TestMaking:
    def test_a_snapshot_is_what_a_commit_built(self, maker, work):
        commit = _git(work, "rev-parse", "HEAD")
        report = snapshot.make(maker)
        taken = report.snapshot
        assert report.made and report.not_built == []
        assert (taken.pipeline, taken.commit, taken.subdirectory) == ("acme/maker", commit, "maker")
        assert sorted(taken.assets) == ["chart/curve", "rates"]
        assert taken.path.parent == default_store().root / "snapshots" / commit / "maker"

        # The bytes are in the store, under the hash the record gives
        store = default_store()
        rates = taken.assets["rates"]
        assert rates["id"] == "acme/maker:rates"
        assert (store.get(rates["content_hash"]) / "rates.parquet").read_bytes() == b"rates-1"
        assert taken.asset_hashes() == {record["content_hash"] for record in taken.assets.values()}
        # The store keeps the version's index and documents too
        assert taken.hashes() == taken.asset_hashes() | {taken.index["content_hash"], taken.documents["content_hash"]}

    def test_the_record_is_json_in_the_index_format(self, maker):
        taken = snapshot.make(maker).snapshot
        document = json.loads(taken.path.read_text())
        assert list(document) == ["schema", "root", "code", "made_at", "built_with", "first_commit", "index", "documents", "records"]
        assert document["schema"] == "chartbook/snapshot/v1"
        assert document["code"] == {"commit": taken.commit, "subdirectory": "maker"}
        assert [record["id"] for record in document["records"]] == [
            "acme/maker:chart/curve",
            "acme/maker:rates",
        ]
        jsonschema.validate(document, json.loads(snapshot.schema_path().read_text()))
        for record in document["records"]:
            jsonschema.validate(record, json.loads(index.schema_path(record["kind"]).read_text()))
        assert snapshot.read(taken.path) == taken

    def test_it_gives_up_nothing_but_the_pipelines_own_files(self, maker, work):
        """A declared path that reaches outside the folder is refused."""
        secret = work / "secret.txt"
        secret.write_text("mine\n")
        _manifest(
            maker,
            {
                "project": {"id": "acme/maker"},
                "dataframes": {
                    "rates": {"path": "./_data/rates.parquet", "docs": "d"},
                    "other": {"path": "../secret.txt", "docs": "d"},
                },
            },
        )
        _commit(work)
        with pytest.raises(SnapshotError) as e:
            snapshot.make(maker)
        assert "'acme/maker:other' at '../secret.txt'" in str(e.value)
        assert "outside the pipeline's folder" in str(e.value)
        assert not (default_store().root / "snapshots").exists()

    def test_it_is_frozen(self, maker):
        """Its owner rewrites the file in place. The snapshot keeps what it had."""
        taken = snapshot.make(maker).snapshot
        with open(maker / "_data" / "rates.parquet", "r+b") as f:
            f.write(b"RATES-9")
        held = default_store().get(taken.assets["rates"]["content_hash"])
        assert (held / "rates.parquet").read_bytes() == b"rates-1"

    def test_a_pipeline_at_the_top_of_its_repository(self, work):
        directory = _manifest(work, {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (directory / "x.parquet").write_bytes(b"x")
        commit = _commit(directory)
        taken = snapshot.make(directory).snapshot
        assert taken.subdirectory == ""
        assert taken.path.parent == default_store().root / "snapshots" / commit / "_top"
        assert "subdirectory" not in json.loads(taken.path.read_text())["code"]

    def test_two_pipelines_never_share_a_folder_in_the_store(self, work):
        """``a--b/c`` and ``a/b--c`` would both be ``a--b--c``; so would ``_top`` and the top."""
        store = default_store()
        commit = "0" * 40
        names = ["", "_top", "a--b/c", "a/b--c", "a/b/c"]
        folders = [store.snapshot_folder(commit, snapshot.record_name(name)) for name in names]
        assert len(set(folders)) == len(names)
        assert folders[0].name == "_top" and folders[4].name == "a--b--c"
        assert folders[1].name.startswith("_top~") and folders[2].name.startswith("a--b--c~")

    def test_a_pipeline_deep_in_its_repository(self, work):
        directory = _manifest(
            work / "pipelines" / "macro" / "rates",
            {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}},
        )
        (directory / "x.parquet").write_bytes(b"x")
        commit = _commit(work)
        taken = snapshot.make(directory).snapshot
        assert taken.subdirectory == "pipelines/macro/rates"
        assert taken.path.parent.name == "pipelines--macro--rates"
        assert snapshot.find(default_store(), commit, "pipelines/macro/rates") == [taken]

    def test_a_folder_and_a_glob(self, work):
        directory = _manifest(
            work / "maker",
            {
                "dataframes": {"parts": {"path": "./parts/*.parquet", "docs": "d"}},
                "models": {"m": {"path": "./model"}},
            },
        )
        (directory / "parts").mkdir()
        (directory / "parts" / "a.parquet").write_bytes(b"a")
        (directory / "parts" / "b.parquet").write_bytes(b"b")
        (directory / "model").mkdir()
        (directory / "model" / "weights.bin").write_bytes(b"w")
        _commit(work)
        taken = snapshot.make(directory).snapshot
        assert [f["path"] for f in taken.assets["model/m"]["files"]] == ["weights.bin"]
        assert "files" not in taken.assets["parts"]  # a glob says which files by itself
        held = default_store().get(taken.assets["parts"]["content_hash"])
        assert sorted(p.name for p in held.iterdir()) == ["a.parquet", "b.parquet"]


class TestEverythingMustBeCommitted:
    """The label says "this is what that commit built". It has to be true."""

    def test_a_changed_file(self, maker):
        (maker / "chartbook.toml").write_text((maker / "chartbook.toml").read_text() + "\n# x\n")
        with pytest.raises(SnapshotError) as e:
            snapshot.make(maker)
        said = str(e.value)
        assert "acme/maker has changes that are not committed:" in said
        assert " M maker/chartbook.toml" in said
        assert "everything in the pipeline's folder must be committed first." in said
        assert not (default_store().root / "snapshots").exists()

    def test_a_new_file_git_does_not_ignore(self, maker):
        (maker / "pull.py").write_text("print('new')\n")
        with pytest.raises(SnapshotError, match=r"\?\? maker/pull.py"):
            snapshot.make(maker)

    def test_a_staged_change(self, maker, work):
        (maker / "pull.py").write_text("print('new')\n")
        _git(work, "add", "-A")
        with pytest.raises(SnapshotError, match="A  maker/pull.py"):
            snapshot.make(maker)

    def test_a_deleted_file(self, maker, work):
        (maker / "pull.py").write_text("print('new')\n")
        _commit(work)
        (maker / "pull.py").unlink()
        with pytest.raises(SnapshotError, match=" D maker/pull.py"):
            snapshot.make(maker)

    def test_many_are_cut_short(self, maker):
        for number in range(14):
            (maker / f"new_{number:02}.py").write_text("")
        with pytest.raises(SnapshotError) as e:
            snapshot.make(maker)
        assert "?? maker/new_09.py" in str(e.value) and "new_10.py" not in str(e.value)
        assert "and 4 more" in str(e.value)

    def test_what_git_ignores_does_not_count(self, maker):
        """Built data is rewritten by every build, and is not code."""
        _build(maker, rates=b"rates-2")
        (maker / "_data" / "scratch.tmp").write_bytes(b"x")
        assert snapshot.make(maker).made

    def test_other_work_in_the_same_repository_does_not_count(self, maker, work):
        """Somebody else is half-way through a change, in another pipeline."""
        _manifest(work / "other", {"project": {"id": "acme/other"}})
        (work / "notes.txt").write_text("not committed")
        assert snapshot.uncommitted(maker) == []
        assert snapshot.make(maker).made

    def test_committing_is_what_lets_it_through(self, maker, work):
        (maker / "pull.py").write_text("print('new')\n")
        with pytest.raises(SnapshotError):
            snapshot.make(maker)
        commit = _commit(work)
        assert snapshot.make(maker).snapshot.commit == commit


class TestWhatCannotHaveOne:
    def test_a_folder_that_is_not_in_git(self, work):
        directory = _manifest(work / "loose", {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (directory / "x.parquet").write_bytes(b"x")
        with pytest.raises(SnapshotError) as e:
            snapshot.make(directory)
        assert "loose cannot have a snapshot" in str(e.value)
        assert "is not in a git repository" in str(e.value)

    def test_a_repository_with_no_commit(self, work):
        directory = _manifest(work, {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        _git(directory, "init", "--quiet", "-b", "main")
        with pytest.raises(SnapshotError, match="has no commit yet"):
            snapshot.make(directory)

    def test_a_pipeline_that_has_built_nothing(self, maker):
        (maker / "_data" / "rates.parquet").unlink()
        (maker / "_output" / "curve.html").unlink()
        with pytest.raises(SnapshotError, match="has built nothing it declares") as e:
            snapshot.make(maker)
        assert "Build it first: `chartbook run`." in str(e.value)

    def test_a_pipeline_that_declares_nothing(self, work):
        directory = _manifest(work / "empty", {"project": {"id": "empty"}})
        _commit(work)
        with pytest.raises(SnapshotError, match="declares nothing with a path"):
            snapshot.make(directory)

    def test_a_catalog(self, maker, work):
        _manifest(work, {"project": {"type": "catalog"}, "pipelines": {"maker": {"path": "maker"}}})
        with pytest.raises(SnapshotError, match="is a catalog"):
            snapshot.make(work)

    def test_no_manifest(self, work):
        with pytest.raises(SnapshotError, match="No chartbook.toml in"):
            snapshot.make(work)


class TestSeveral:
    def test_what_is_not_built_is_in_it_without_a_hash(self, maker):
        (maker / "_output" / "curve.html").unlink()
        report = snapshot.make(maker)
        assert report.made
        assert report.not_built == [("acme/maker:chart/curve", "./_output/curve.html")]
        assert report.snapshot.content()["chart/curve"] is None
        assert "content_hash" not in report.snapshot.assets["chart/curve"]

    def test_nothing_changed_makes_no_new_one(self, maker):
        first = snapshot.make(maker)
        again = snapshot.make(maker)
        assert not again.made and again.snapshot == first.snapshot
        assert len(list(first.snapshot.path.parent.glob("*.json"))) == 1

    def test_new_data_at_the_same_commit_is_a_new_one(self, maker, work):
        """A pipeline that pulls from outside: other bytes, and no file changed."""
        first = snapshot.make(maker).snapshot
        _build(maker, rates=b"rates-2")
        second = snapshot.make(maker).snapshot
        assert second.commit == first.commit and second.made_at > first.made_at
        assert second.content()["rates"] != first.content()["rates"]
        assert second.content()["chart/curve"] == first.content()["chart/curve"]
        assert snapshot.find(default_store(), first.commit, "maker") == [second, first]

    def test_made_again_after_the_store_lost_everything_it_is_whole_again(self, maker):
        """Its index and documents too, not only its assets: a catalog shows the version from them.

        An index says when it was made, so it is not made again byte for
        byte: a new snapshot of the same bytes holds the new one.
        """
        taken = snapshot.make(maker).snapshot
        store = default_store()
        assert taken.index and taken.documents
        for content_hash in list(store.hashes()):
            store.delete(content_hash)
        again = snapshot.make(maker)
        assert again.made and again.snapshot.content() == taken.content()
        assert store.has(again.snapshot.index["content_hash"]) and store.has(again.snapshot.documents["content_hash"])
        assert all(store.has(content_hash) for content_hash in again.snapshot.hashes())
        assert snapshot.make(maker).made is False  # whole now: nothing new to make

    def test_two_made_at_one_instant_are_both_kept_in_order(self, maker):
        first = snapshot.make(maker, made_at="2026-10-13T18:22:05.000000Z").snapshot
        _build(maker, rates=b"rates-2")
        second = snapshot.make(maker, made_at="2026-10-13T18:22:05.000000Z").snapshot
        assert second.path != first.path
        assert snapshot.find(default_store(), first.commit, "maker") == [second, first]

    def test_a_record_that_cannot_be_read_is_an_error(self, maker):
        taken = snapshot.make(maker).snapshot
        taken.path.write_text('{"schema": "chartbook/snapshot/v9"}')
        with pytest.raises(SnapshotError, match="Cannot read the snapshot"):
            snapshot.find(default_store(), taken.commit, "maker")


class TestBuiltWith:
    """A note of the conditions, to explain a difference. Not a copy of anything."""

    def test_it_says_what_made_it(self, maker):
        import platform

        import chartbook

        taken = snapshot.make(maker).snapshot
        assert taken.built_with == {
            "run": False,
            "lineage": "pins",
            "chartbook": chartbook.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
        assert not taken.built_by_run
        assert snapshot.read(taken.path).built_with == taken.built_with

    def test_nothing_of_the_environment_is_in_it(self, maker, monkeypatch):
        """A pipeline's .env holds secrets, and a store is something to share."""
        monkeypatch.setenv("FRED_API_KEY", "s3cret-value")
        (maker / "_data" / ".env").write_text("FRED_API_KEY=s3cret-value\n")
        taken = snapshot.make(maker).snapshot
        assert "s3cret-value" not in taken.path.read_text()

    def test_it_says_what_the_pipeline_was_itself_pinned_to(self, user, maker, work):
        """So a snapshot of ``user`` says which snapshot of ``maker`` it was built from."""
        of_maker = snapshot.make(maker).snapshot
        lock.pin(user)
        (user / "_output").mkdir()
        (user / "_output" / "result.parquet").write_bytes(b"result")
        _manifest(
            user,
            {
                "project": {"id": "acme/user"},
                "dependencies": {"acme/maker": {"path": "../maker"}},
                "dataframes": {"result": {"path": "./_output/result.parquet", "docs": "d"}},
            },
        )
        _commit(work)
        taken = snapshot.make(user).snapshot
        (was,) = taken.inputs
        assert was["id"] == "acme/maker"
        assert was["location"]["commit"] == of_maker.commit
        assert was["snapshot"] == of_maker.made_at
        assert was["pinned_hash"].startswith("sha256:")
        assert snapshot.read(taken.path).inputs == taken.inputs
        jsonschema.validate(
            json.loads(taken.path.read_text()), json.loads(snapshot.schema_path().read_text())
        )

    def test_a_pipeline_with_no_lockfile_has_no_inputs(self, maker):
        taken = snapshot.make(maker).snapshot
        assert taken.inputs == [] and "inputs" not in json.loads(taken.path.read_text())

    def test_a_lockfile_that_cannot_be_read_stops_it(self, maker):
        (maker / "chartbook.lock").write_text("not json")
        with pytest.raises(SnapshotError, match="Cannot read"):
            snapshot.make(maker)

    def test_one_that_follows_a_build_replaces_one_that_took_its_owners_word(self, maker):
        """The same bytes, and now ChartBook saw them built."""
        first = snapshot.make(maker)
        second = snapshot.make(maker, built_by_run=True)
        assert second.made and second.snapshot.built_by_run
        assert second.snapshot.content() == first.snapshot.content()
        assert snapshot.newest_for(maker)[0] == second.snapshot
        # ...and after that, nothing changed is nothing made, either way
        assert not snapshot.make(maker, built_by_run=True).made
        assert not snapshot.make(maker).made


class TestFinding:
    def test_at_the_commit_the_folder_is_on(self, maker):
        taken = snapshot.make(maker).snapshot
        found, code = snapshot.newest_for(maker)
        assert found == taken
        assert (code.commit, code.subdirectory) == (taken.commit, "maker")

    def test_none(self, maker):
        found, code = snapshot.newest_for(maker)
        assert found is None and code.subdirectory == "maker"

    def test_at_the_nearest_commit_before(self, maker, work):
        """Its owner is three commits past the last build they declared ready."""
        taken = snapshot.make(maker).snapshot
        for number in range(3):
            (maker / "pull.py").write_text(f"print({number})\n")
            _commit(work)
        found, code = snapshot.newest_for(maker)
        assert found == taken and code.commit != taken.commit

    def test_the_newer_of_two_commits(self, maker, work):
        snapshot.make(maker)
        (maker / "pull.py").write_text("print('new')\n")
        _commit(work)
        _build(maker, rates=b"rates-2")
        second = snapshot.make(maker).snapshot
        (maker / "pull.py").write_text("print('newer')\n")
        _commit(work)
        assert snapshot.newest_for(maker)[0] == second

    def test_one_made_on_another_branch_is_not_found(self, maker, work):
        first = snapshot.make(maker).snapshot
        _git(work, "checkout", "--quiet", "-b", "experiment")
        (maker / "pull.py").write_text("print('experiment')\n")
        _commit(work)
        _build(maker, rates=b"experimental")
        on_branch = snapshot.make(maker).snapshot
        assert snapshot.newest_for(maker)[0] == on_branch
        _git(work, "checkout", "--quiet", "main")
        assert snapshot.newest_for(maker)[0] == first

    def test_another_pipelines_at_the_same_commit_is_not_this_ones(self, maker, work):
        other = _manifest(work / "other", {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (other / "x.parquet").write_bytes(b"x")
        _commit(work)
        snapshot.make(other)
        assert snapshot.newest_for(maker)[0] is None

    def test_from_another_clone_of_the_repository(self, maker, work, tmp_path_factory):
        """A commit is the same commit wherever it is checked out."""
        taken = snapshot.make(maker).snapshot
        elsewhere = tmp_path_factory.mktemp("clone").resolve() / "copy"
        _git(work, "clone", "--quiet", str(work), str(elsewhere))
        assert snapshot.newest_for(elsewhere / "maker")[0] == taken

    def test_a_folder_that_is_not_in_git(self, work):
        (work / "loose").mkdir()
        with pytest.raises(SnapshotError, match="is not in a git repository"):
            snapshot.newest_for(work / "loose")

    def test_a_folder_that_is_not_there(self, work):
        with pytest.raises(SnapshotError, match="there is no folder at"):
            snapshot.newest_for(work / "gone")


class TestPinning:
    """``pin`` and ``update`` take from a snapshot, and never from the folder."""

    def test_pin_takes_the_snapshot(self, user, maker, work):
        taken = snapshot.make(maker).snapshot
        report = lock.pin(user)
        assert _statuses(report) == {"rates": "pinned", "chart/curve": "pinned"}
        assert report.problems == [] and report.written
        assert report.snapshots == {"acme/maker": taken}

        locked = lock.read_lock(user)
        (listed,) = locked.dependencies
        assert listed["location"] == {"kind": "path", "path": "../maker", "commit": taken.commit}
        assert listed["snapshot"] == taken.made_at
        assert locked.hashes() == taken.asset_hashes()
        jsonschema.validate(
            json.loads((user / lock.LOCK_FILE).read_text()),
            json.loads(lock.schema_path().read_text()),
        )

    def test_the_folder_is_not_read(self, user, maker):
        """Half-built, emptied or rewritten since: what is pinned is the snapshot."""
        taken = snapshot.make(maker).snapshot
        (maker / "_data" / "rates.parquet").write_bytes(b"half way through a rebuild")
        (maker / "_output" / "curve.html").unlink()
        report = lock.pin(user)
        assert _statuses(report) == {"rates": "pinned", "chart/curve": "pinned"}
        assert lock.read_lock(user).hashes() == taken.asset_hashes()

    def test_code_reads_the_snapshot(self, user, maker, monkeypatch):
        snapshot.make(maker)
        lock.pin(user)
        (maker / "_data" / "rates.parquet").write_bytes(b"rewritten since")
        monkeypatch.chdir(user)
        path = data.path("maker:rates")
        assert path.read_bytes() == b"rates-1"
        assert default_store().root in path.parents

    def test_it_goes_by_the_name_it_is_declared_under(self, maker, work):
        """The maker calls itself acme/maker. This pipeline calls it upstream."""
        other = _manifest(work / "other", {"dependencies": {"upstream": {"path": "../maker"}}})
        _commit(work)
        snapshot.make(maker)
        lock.pin(other)
        locked = lock.read_lock(other)
        assert sorted(locked.assets) == ["upstream:chart/curve", "upstream:rates"]
        assert locked.assets["upstream:rates"]["pipeline"] == "upstream"
        assert locked.assets["upstream:rates"]["ref"] == {
            "pipeline": "upstream",
            "kind": "dataframe",
            "name": "rates",
        }

    def test_with_no_snapshot_nothing_can_be_pinned(self, user, maker, work):
        commit = _git(work, "rev-parse", "HEAD")
        report = lock.pin(user)
        (problem,) = report.problems
        assert problem.status == "no_snapshot" and problem.dependency == "acme/maker"
        assert problem.detail == (
            f"it has no snapshot at or before {commit[:7]}, the commit its folder is "
            f"on. In ../maker: commit, then run `chartbook snapshot`"
        )
        assert lock.read_lock(user).hashes() == set()

    def test_a_folder_that_is_not_in_git_has_none(self, work):
        loose = _manifest(work / "loose", {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (loose / "x.parquet").write_bytes(b"x")
        user = _manifest(work / "user", {"dependencies": {"loose": {"path": "../loose"}}})
        (problem,) = lock.pin(user).problems
        assert problem.status == "no_snapshot"
        assert "is not in a git repository" in problem.detail

    def test_pin_again_changes_nothing(self, user, maker):
        snapshot.make(maker)
        lock.pin(user)
        before = (user / lock.LOCK_FILE).read_bytes()
        report = lock.pin(user)
        assert _statuses(report) == {"rates": "kept", "chart/curve": "kept"}
        assert not report.written and (user / lock.LOCK_FILE).read_bytes() == before

    def test_pin_says_what_a_newer_snapshot_would_change_and_stays(self, user, maker):
        snapshot.make(maker)
        lock.pin(user)
        before = (user / lock.LOCK_FILE).read_bytes()
        _build(maker, rates=b"rates-2")
        snapshot.make(maker)
        report = lock.pin(user)
        assert _statuses(report) == {"rates": "stale", "chart/curve": "kept"}
        assert (user / lock.LOCK_FILE).read_bytes() == before

    def test_a_rebuild_with_no_snapshot_is_not_seen_by_pin_or_update(self, user, maker):
        snapshot.make(maker)
        lock.pin(user)
        _build(maker, rates=b"rates-2", curve=b"curve-2")
        assert _statuses(lock.pin(user)) == {"rates": "kept", "chart/curve": "kept"}
        moved = lock.update(user)
        assert _statuses(moved) == {"rates": "kept", "chart/curve": "kept"}
        assert not moved.written

    def test_update_moves_to_the_newest(self, user, maker, work):
        first = snapshot.make(maker).snapshot
        lock.pin(user)
        (maker / "pull.py").write_text("print('new code')\n")
        _commit(work)
        _build(maker, rates=b"rates-2")
        second = snapshot.make(maker).snapshot

        report = lock.update(user)
        assert _statuses(report) == {"rates": "moved", "chart/curve": "kept"}
        (moved,) = [e for e in report.events if e.status == "moved"]
        assert (moved.old, moved.new) == (first.content()["rates"], second.content()["rates"])
        (listed,) = lock.read_lock(user).dependencies
        assert listed["location"]["commit"] == second.commit != first.commit
        assert listed["snapshot"] == second.made_at

    def test_update_brings_what_the_newer_one_added_and_drops_what_it_lost(
        self, user, maker, work
    ):
        snapshot.make(maker)
        lock.pin(user)
        _manifest(
            maker,
            {
                "project": {"id": "acme/maker"},
                "dataframes": {
                    "rates": {"path": "./_data/rates.parquet", "docs": "d"},
                    "spreads": {"path": "./_data/spreads.parquet", "docs": "d"},
                },
            },
        )
        (maker / "_data" / "spreads.parquet").write_bytes(b"spreads")
        _commit(work)
        snapshot.make(maker)
        report = lock.update(user)
        assert _statuses(report) == {"rates": "kept", "spreads": "pinned", "chart/curve": "dropped"}
        assert sorted(lock.read_lock(user).assets) == ["acme/maker:rates", "acme/maker:spreads"]

    def test_what_the_newer_one_did_not_build_is_let_go(self, user, maker):
        """A pin from an older snapshot does not belong beside a newer one's commit."""
        snapshot.make(maker)
        lock.pin(user)
        (maker / "_output" / "curve.html").unlink()
        (maker / "_data" / "rates.parquet").write_bytes(b"rates-2")
        snapshot.make(maker)
        report = lock.update(user)
        assert _statuses(report) == {"rates": "moved", "chart/curve": "let_go"}
        assert "content_hash" not in lock.read_lock(user).assets["acme/maker:chart/curve"]

    def test_one_snapshot_whole(self, user, maker):
        """`pin` does not take one asset from a newer snapshot and leave the rest."""
        (maker / "_output" / "curve.html").unlink()
        snapshot.make(maker)
        lock.pin(user)
        _build(maker)  # the chart is built now, and declared ready
        snapshot.make(maker)
        report = lock.pin(user)
        assert _statuses(report) == {"rates": "kept", "chart/curve": "not_built"}
        assert _statuses(lock.update(user)) == {"rates": "kept", "chart/curve": "pinned"}

    def test_a_folder_that_has_gone_is_no_trouble_for_pin(self, user, maker, work):
        snapshot.make(maker)
        lock.pin(user)
        os.rename(maker, work / "moved_away")
        report = lock.pin(user)
        assert report.problems == []
        assert _statuses(report) == {"rates": "kept", "chart/curve": "kept"}

        # For an update it is: there is nowhere to look for something newer
        moved = lock.update(user)
        assert [e.status for e in moved.problems] == ["no_snapshot"]
        assert lock.read_lock(user).hashes()  # and the pins are kept

    def test_what_the_store_has_lost_is_reported(self, user, maker):
        taken = snapshot.make(maker).snapshot
        lock.pin(user)
        default_store().delete(taken.content()["rates"])
        report = lock.pin(user)
        assert _statuses(report) == {"rates": "lost", "chart/curve": "kept"}
        assert len(report.problems) == 1

    def test_update_to_a_snapshot_the_store_has_lost_part_of_moves_nothing(self, user, maker):
        """Found by a reviewer: the lockfile once named the new snapshot
        beside the old asset's bytes. A snapshot is taken whole or not at all."""
        first = snapshot.make(maker).snapshot
        lock.pin(user)
        before = (user / lock.LOCK_FILE).read_bytes()
        _build(maker, rates=b"rates-2")
        second = snapshot.make(maker).snapshot
        default_store().delete(second.content()["rates"])

        report = lock.update(user)
        assert _statuses(report) == {"rates": "lost", "chart/curve": "kept"}
        assert len(report.problems) == 1
        assert "nothing was moved" in report.problems[0].detail
        assert not report.written and (user / lock.LOCK_FILE).read_bytes() == before
        (listed,) = lock.read_lock(user).dependencies
        assert listed["location"]["commit"] == first.commit and listed["snapshot"] == first.made_at

    def test_moving_the_dependency_to_another_folder_is_followed_by_update_not_pin(
        self, user, maker, work
    ):
        snapshot.make(maker)
        lock.pin(user)
        other = _manifest(work / "elsewhere", {"project": {"id": "acme/maker"}, "dataframes": {"rates": {"path": "./_data/rates.parquet", "docs": "d"}}})
        _build(other, rates=b"elsewhere")
        _commit(work)
        snapshot.make(other)
        _manifest(user, {"project": {"id": "acme/user"}, "dependencies": {"acme/maker": {"path": "../elsewhere"}}})

        report = lock.pin(user)
        assert [e.status for e in report.events if e.asset is None] == ["relocated"]
        # It says what the new folder's snapshot would change, and stays put
        assert _statuses(report) == {"rates": "stale", "chart/curve": "kept"}
        (listed,) = lock.read_lock(user).dependencies
        assert listed["location"]["path"] == "../maker"  # still where the pins came from

        moved = lock.update(user)
        assert _statuses(moved) == {"rates": "moved", "chart/curve": "dropped"}
        (listed,) = lock.read_lock(user).dependencies
        assert listed["location"]["path"] == "../elsewhere"

    def test_the_index_names_the_snapshot(self, user, maker):
        taken = snapshot.make(maker).snapshot
        lock.pin(user)
        built = index.build_index(load_manifest(user))
        (dependency,) = built["records"][0]["dependencies"]
        assert dependency["location"]["commit"] == taken.commit
        assert dependency["snapshot"] == taken.made_at
        jsonschema.validate(
            built["records"][0], json.loads(index.schema_path("Pipeline").read_text())
        )


class TestAPinThatNamesNoSnapshot:
    """A lockfile from before every pin came from a snapshot, or changed by hand: a pin with no commit."""

    def test_pin_leaves_it_and_update_moves_to_a_snapshot(self, user, maker):
        snapshot.make(maker)
        lock.pin(user)
        name_no_snapshot(user, "acme/maker")
        _build(maker, rates=b"rates-2")
        taken = snapshot.make(maker).snapshot

        report = lock.pin(user)
        assert _statuses(report) == {"rates": "stale", "chart/curve": "kept"}
        assert "commit" not in lock.read_lock(user).dependencies[0]["location"]

        assert _statuses(lock.update(user)) == {"rates": "moved", "chart/curve": "kept"}
        (listed,) = lock.read_lock(user).dependencies
        assert listed["location"]["commit"] == taken.commit and listed["snapshot"] == taken.made_at


OLD = "2026-01-01T00:00:00.000000Z"  # long before any keep window
OLDER = "2025-12-01T00:00:00.000000Z"


def _plan(store, pinned=(), missing=(), keep_days=30):
    return snapshot.plan_removals(store, set(pinned), set(missing), keep_days=keep_days)


class TestKeeping:
    def test_a_new_snapshot_keeps_its_objects_from_being_cleared(self, maker):
        """Nothing pins it yet. It was declared ready, and that is enough."""
        taken = snapshot.make(maker).snapshot
        store = default_store()
        plan = lock.plan_gc(store, recent_seconds=0)
        assert plan.delete == [] and plan.kept == 4 and plan.snapshots == 4  # two assets, the index, the documents
        assert plan.snapshots_delete == []
        assert [why for _, why in plan.snapshots_kept] == ["it is the newest of its pipeline"]
        assert snapshot.all_hashes(store) == taken.hashes()

    def test_uncommitted_reads_a_path_git_would_quote(self, work):
        """A space or an accent in a folder name; the lockfile still does not count."""
        directory = _manifest(work / "my données", {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (directory / "x.parquet").write_bytes(b"x")
        (work / ".gitignore").write_text("_data/\n_output/\n")
        _git(work, "init", "--quiet", "-b", "main")
        _git(work, "add", "-A")
        _git(work, "commit", "--quiet", "-m", "Work")
        (directory / "chartbook.lock").write_text("{}")
        (directory / "new file.txt").write_text("new")
        assert snapshot.uncommitted(directory) == ["?? my données/chartbook.lock", "?? my données/new file.txt"]
        assert snapshot.uncommitted(directory, ignoring=("chartbook.lock",)) == ["?? my données/new file.txt"]
        # A rename shows both names
        _git(work, "add", "-A")
        _git(work, "commit", "--quiet", "-m", "More")
        _git(work, "mv", "my données/new file.txt", "my données/renamed.txt")
        assert snapshot.uncommitted(directory) == ["R  my données/new file.txt -> my données/renamed.txt"]

    def test_the_folder_a_snapshot_came_from_is_noted(self, maker, work):
        taken = snapshot.make(maker).snapshot
        assert snapshot.origins(default_store(), taken) == [work]
        snapshot.make(maker)  # again, with nothing changed: noted once
        assert (taken.path.parent / "origins").read_text().splitlines() == [str(work)]


class TestClearingOldSnapshots:
    """Which snapshots `chartbook store gc` keeps, and which it lets go."""

    @pytest.fixture
    def three(self, maker):
        """Three snapshots of ``maker``, oldest first; the first two long ago."""
        first = snapshot.make(maker, made_at=OLDER).snapshot
        _build(maker, rates=b"rates-2")
        second = snapshot.make(maker, made_at=OLD).snapshot
        _build(maker, rates=b"rates-3")
        third = snapshot.make(maker).snapshot
        return first, second, third

    def test_a_snapshot_from_a_checkout_that_is_gone_is_judged_like_any_other(self, three, tmp_path):
        """Found by a reviewer: a first design kept every such snapshot, and a
        CI runner's checkout is gone the moment the job ends."""
        first, second, third = three
        (third.path.parent / "origins").write_text(str(tmp_path / "ci-runner-checkout") + "\n")
        plan = _plan(default_store())
        assert [t for t, _ in plan.remove] == [first, second]
        assert [t for t, _ in plan.keep] == [third]

    def test_a_record_dated_ahead_does_not_take_the_newest_snapshots_labels(self, work, tmp_path):
        """gc reads the labels of the newest snapshot that is not dated after now."""
        import dataclasses

        directory = _manifest(work / "forecast", {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json"}}})
        (directory / "_output").mkdir()
        (directory / "_output" / "m.json").write_bytes(b"v1")
        _commit(work)
        first = snapshot.make(directory, made_at=OLDER).snapshot
        version = first.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        _manifest(directory, {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json", "aliases": {"champion": version}}}})
        _commit(work)
        (directory / "_output" / "m.json").write_bytes(b"v2")
        newest = snapshot.make(directory).snapshot
        snapshot._write(dataclasses.replace(newest, made_at="2099-01-01T00:00:00.000000Z", labels={}), default_store())
        for folder in {t.path.parent for t in snapshot.all_snapshots(default_store())}:
            (folder / "origins").write_text(str(tmp_path / "elsewhere") + "\n")
        assert (first, "a label points at a version in it") in _plan(default_store(), keep_days=7).keep

    def test_a_clock_behind_does_not_remove_a_new_snapshot(self, maker, tmp_path):
        """A store shared with a machine whose clock is ahead: what it just made stays."""
        from datetime import datetime, timedelta, timezone

        taken = snapshot.make(maker).snapshot
        (taken.path.parent / "origins").write_text(str(tmp_path / "elsewhere") + "\n")
        behind = datetime.now(timezone.utc) - timedelta(minutes=15)
        plan = snapshot.plan_removals(default_store(), set(), set(), keep_days=7, now=behind)
        assert plan.remove == [] and plan.keep == [(taken, "it is dated after now, by less than 7 days")]

    def test_labels_travel_with_snapshots(self, work, tmp_path):
        """A label given on one machine is known to gc on another, through
        the snapshots made after it."""
        directory = _manifest(
            work / "forecast",
            {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json"}}},
        )
        (directory / "_output").mkdir()
        (directory / "_output" / "m.json").write_bytes(b"v1")
        _commit(work)
        first = snapshot.make(directory, made_at=OLDER).snapshot
        assert first.labels == {}
        version = first.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        (directory / "_output" / "m.json").write_bytes(b"v2")
        snapshot.make(directory, made_at=OLD)
        # The owner labels the first version, commits, and makes another snapshot
        _manifest(
            directory,
            {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json", "aliases": {"champion": version}}}},
        )
        _commit(work)
        (directory / "_output" / "m.json").write_bytes(b"v3")
        third = snapshot.make(directory).snapshot
        assert third.labels == {"model/m": {"champion": version}}
        assert snapshot.read(third.path).labels == {"model/m": {"champion": version}}
        # Another machine: the folder is not here. The label still keeps the first.
        for folder in {t.path.parent for t in snapshot.all_snapshots(default_store())}:
            (folder / "origins").write_text(str(tmp_path / "elsewhere") + "\n")
        plan = _plan(default_store())
        assert (first, "a label points at a version in it") in plan.keep
        assert [t.made_at for t, _ in plan.remove] == [OLD]
        # The owner takes the label away and makes another snapshot: the
        # version is released. Only the newest snapshot's labels count.
        _manifest(
            directory,
            {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json"}}},
        )
        _commit(work)
        (directory / "_output" / "m.json").write_bytes(b"v4")
        fourth = snapshot.make(directory).snapshot
        assert fourth.labels == {}
        (fourth.path.parent / "origins").write_text(str(tmp_path / "elsewhere") + "\n")
        plan = _plan(default_store())
        assert {t.made_at for t, _ in plan.remove} == {OLDER, OLD}

    def test_the_remedy_for_a_pin_lost_from_a_snapshot_names_update_and_the_snapshot(self, maker, user):
        snapshot.make(maker)
        store = default_store()
        report = lock.pin(user, store)
        content_hash = next(iter(report.events)).new or [e.new for e in report.events if e.new][0]
        store.delete(content_hash)
        (problem,) = lock.verify(user, store).problems
        assert "`chartbook update acme/maker` moves to a snapshot the store has, or `chartbook snapshot`" in problem.message

    @pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a store this user cannot write")
    def test_pinning_from_a_snapshot_needs_no_write_to_the_store(self, maker, user):
        """A store a team shares, read-only for everyone but its owner."""
        snapshot.make(maker)
        store = default_store()
        modes = {}
        for path in [store.root, *store.root.rglob("*")]:
            if path.is_dir():
                modes[path] = path.stat().st_mode
                os.chmod(path, 0o555)
        try:
            report = lock.pin(user, store)
        finally:
            for path, mode in modes.items():
                os.chmod(path, mode)
        assert report.written and (user / lock.LOCK_FILE).exists()
        assert set(_statuses(report).values()) == {"pinned"} and "denied" in report.unrooted
        assert lock.verify(user, store).problems == []

    def test_the_newest_is_kept_and_old_unpinned_ones_may_go(self, three):
        first, second, third = three
        plan = _plan(default_store())
        assert [t for t, _ in plan.keep] == [third]
        assert [(t, why) for t, why in plan.remove] == [
            (first, "nothing pins it, it is not the newest, and it is older than 30 days"),
            (second, "nothing pins it, it is not the newest, and it is older than 30 days"),
        ]

    def test_a_recent_one_is_kept(self, maker):
        snapshot.make(maker, made_at=OLD)
        _build(maker, rates=b"rates-2")
        recent = snapshot.make(maker).snapshot  # now
        _build(maker, rates=b"rates-3")
        snapshot.make(maker)
        plan = _plan(default_store())
        assert (recent, "it was made in the last 30 days") in plan.keep
        assert len(plan.remove) == 1
        # ...unless the window is shorter
        assert len(_plan(default_store(), keep_days=0).remove) == 2

    def test_one_a_lockfile_pins_is_kept(self, three, user):
        first, second, third = three
        plan = _plan(default_store(), pinned={(first.commit, first.made_at)})
        assert (first, "a lockfile pins it") in plan.keep
        assert [t for t, _ in plan.remove] == [second]

    def test_one_a_missing_lockfile_named_is_kept(self, three):
        first, second, third = three
        plan = _plan(default_store(), missing={first.content()["rates"]})
        assert (first, "a lockfile that cannot be found named what it holds") in plan.keep
        assert [t for t, _ in plan.remove] == [second]

    def test_one_a_label_points_into_is_kept(self, work):
        """The manifest in the folder the snapshots came from says which."""
        directory = _manifest(
            work / "forecast",
            {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json"}}},
        )
        (directory / "_output").mkdir()
        (directory / "_output" / "m.json").write_bytes(b"v1")
        _commit(work)
        first = snapshot.make(directory, made_at=OLDER).snapshot
        (directory / "_output" / "m.json").write_bytes(b"v2")
        second = snapshot.make(directory, made_at=OLD).snapshot
        (directory / "_output" / "m.json").write_bytes(b"v3")
        snapshot.make(directory)

        # The label is added afterwards and not committed: the manifest is
        # read as it is, since a label is what someone is relying on now
        champion = first.content()["model/m"].split(":")[1][:12]
        _manifest(
            directory,
            {
                "project": {"id": "acme/forecast"},
                "models": {"m": {"path": "./_output/m.json", "aliases": {"champion": champion}}},
            },
        )
        plan = _plan(default_store())
        assert (first, "a label points at a version in it") in plan.keep
        assert [t for t, _ in plan.remove] == [second]

    def test_a_folder_that_is_gone_says_nothing_about_labels(self, three, work):
        first, second, third = three
        os.rename(work / "maker", work / "moved")
        plan = _plan(default_store())
        assert [t for t, _ in plan.remove] == [first, second]

    def test_pipelines_are_kept_apart(self, three, work):
        other = _manifest(work / "other", {"dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}})
        (other / "x.parquet").write_bytes(b"x")
        _commit(work)
        only = snapshot.make(other, made_at=OLDER).snapshot
        plan = _plan(default_store())
        assert (only, "it is the newest of its pipeline") in plan.keep

    def test_a_pin_that_lands_while_someone_is_deciding_is_honoured(self, user, maker, work):
        """Found by a reviewer: the plan was made before the yes, and run after.

        A `pin` in between took the old snapshot (the folder was checked out
        at that commit), and the removal then took the pin's only bytes.
        """
        first = snapshot.make(maker, made_at=OLDER).snapshot
        (maker / "pull.py").write_text("print(1)\n")
        second_commit = _commit(work)
        _build(maker, rates=b"rates-2")
        second = snapshot.make(maker, made_at=OLD).snapshot
        (maker / "pull.py").write_text("print(2)\n")
        _commit(work)
        _build(maker, rates=b"rates-3")
        snapshot.make(maker)
        store = default_store()
        plan = lock.plan_gc(store, recent_seconds=0)
        assert [t for t, _ in plan.snapshots_delete] == [first, second]

        # ...the user says yes slowly, and meanwhile a pin lands on `second`
        _git(work, "checkout", "--quiet", second_commit)
        report = lock.pin(user)
        _git(work, "checkout", "--quiet", "main")
        assert report.snapshots["acme/maker"] == second
        removed_snapshots, removed = lock.run_gc(plan, store)
        assert removed_snapshots == 1 and second.path.exists() and not first.path.exists()
        for content_hash in second.hashes():
            assert store.has(content_hash)

    def test_the_newest_a_branch_or_tag_can_pin_from_is_kept(self, maker, work):
        """A release branch's last snapshot is what its users pin; it stays."""
        release = snapshot.make(maker, made_at=OLDER).snapshot
        _git(work, "tag", "v1")
        (maker / "pull.py").write_text("print('main moves on')\n")
        _commit(work)
        _build(maker, rates=b"rates-2")
        snapshot.make(maker)
        plan = _plan(default_store())
        assert (release, "it is the newest a branch or tag can pin from") in plan.keep
        assert plan.remove == []
        # ...and not once the tag is gone
        _git(work, "tag", "-d", "v1")
        plan = _plan(default_store())
        assert [t for t, _ in plan.remove] == [release]

    def test_a_label_too_short_to_name_a_version_keeps_nothing(self, work):
        directory = _manifest(
            work / "forecast",
            {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json", "aliases": {"champion": "7f3a"}}}},
        )
        (directory / "_output").mkdir()
        (directory / "_output" / "m.json").write_bytes(b"v1")
        _commit(work)
        first = snapshot.make(directory, made_at=OLDER).snapshot
        (directory / "_output" / "m.json").write_bytes(b"v2")
        snapshot.make(directory)
        assert [t for t, _ in _plan(default_store()).remove] == [first]

    def test_a_line_in_origins_that_is_not_a_folder_says_nothing(self, three):
        first, second, third = three
        note = third.path.parent / "origins"
        note.write_text("relative/thing\n" + note.read_text())
        assert all(path.is_absolute() for path in snapshot.origins(default_store(), third))
        plan = _plan(default_store())  # no crash, and the same answer
        assert [t for t, _ in plan.remove] == [first, second]

    def test_removing_the_last_record_leaves_anothers_half_written_one_alone(self, maker, work):
        first = snapshot.make(maker, made_at=OLDER).snapshot
        (maker / "pull.py").write_text("print(1)\n")
        _commit(work)
        _build(maker, rates=b"rates-2")
        snapshot.make(maker)
        folder = first.path.parent
        half = folder / "deadbeef.tmp"  # another process, writing a record here now
        half.write_text("{")
        store = default_store()
        lock.run_gc(lock.plan_gc(store, recent_seconds=0), store)
        assert not first.path.exists()
        assert half.exists() and folder.exists() and not (folder / "origins").exists()

    def test_gc_removes_the_record_and_then_what_only_it_named(self, three):
        first, second, third = three
        store = default_store()
        plan = lock.plan_gc(store, recent_seconds=0)
        assert [t for t, _ in plan.snapshots_delete] == [first, second]
        gone = (first.hashes() | second.hashes()) - third.hashes()
        assert {first.content()["rates"], second.content()["rates"]} <= gone
        assert {h for h, _ in plan.delete} == gone  # the chart, and documents alike, are shared with the third
        lock.run_gc(plan, store)
        assert not first.path.exists() and not second.path.exists() and third.path.exists()
        assert all(not store.has(h) for h in gone)
        assert store.has(third.content()["rates"]) and store.has(third.content()["chart/curve"])
        assert snapshot.all_snapshots(store) == [third]

    def test_removing_the_last_record_at_a_commit_removes_its_folders(self, three, work):
        first, second, third = three
        (maker_dir,) = [work / "maker"]
        # Move on a commit so the old ones are alone at theirs
        store = default_store()
        plan = lock.plan_gc(store, recent_seconds=0)
        lock.run_gc(plan, store)
        assert not first.path.parent.exists() or any(first.path.parent.glob("*.json"))
        assert third.path.parent.exists() and (third.path.parent / "origins").exists()

    def test_the_command(self, three, monkeypatch):
        first, second, third = three
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert result.exit_code == 0, result.output
        said = result.output
        # No lockfile names them: the kept snapshot does
        assert said.startswith(f"Kept: {len(third.hashes())} object(s), named by 0 lockfile(s) or a kept snapshot\n")
        assert f"Kept: 1 snapshot(s), naming {len(third.hashes())} object(s): 1 because it is the newest of its pipeline" in said
        assert "Would remove 2 snapshot(s):" in said
        assert f"  acme/maker at {first.commit[:7]}, made 2025-12-01 00:00 UTC: nothing pins it" in said
        # Their objects were stored a moment ago, so this run spares them;
        # the next run, an hour on, removes them
        only_theirs = (first.hashes() | second.hashes()) - third.hashes()
        assert f"Kept: {len(only_theirs)} object(s) nothing names, stored in the last hour" in said
        assert first.path.exists()  # a dry run

        kept = CliRunner().invoke(main, ["store", "gc", "--dry-run", "--keep-days", "100000"])
        assert "Would remove" not in kept.output and "Nothing to remove." in kept.output

        assert "Would remove 0 object(s)" not in said  # no empty object list

        done = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert done.exit_code == 0, done.output
        assert "Removed 2 snapshot(s) and 0 object(s)" in done.output
        assert not first.path.exists() and third.path.exists()
        assert snapshot.all_snapshots(default_store()) == [third]

    def test_what_no_snapshot_and_no_lockfile_names_is_cleared(self, maker, work):
        snapshot.make(maker)
        store = default_store()
        (work / "stray.bin").write_bytes(b"stray")
        stray = store.put(work / "stray.bin")
        plan = lock.plan_gc(store, recent_seconds=0)
        assert [content_hash for content_hash, _ in plan.delete] == [stray.content_hash]

    def test_a_record_that_cannot_be_read_stops_the_clearing(self, maker):
        taken = snapshot.make(maker).snapshot
        taken.path.write_text("not json")
        with pytest.raises(lock.LockError, match="Cannot read the snapshot"):
            lock.plan_gc(default_store())


class TestCommands:
    def _run(self, *arguments):
        return CliRunner().invoke(main, [str(argument) for argument in arguments])

    def test_snapshot(self, maker, work, monkeypatch):
        commit = _git(work, "rev-parse", "HEAD")
        monkeypatch.chdir(maker)
        result = self._run("snapshot")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            f"acme/maker at {commit[:7]}: 2 asset(s) in the store",
            "Snapshot made. A pipeline that depends on this one gets it with "
            "`chartbook update`.",
        ]

    def test_snapshot_again(self, maker, monkeypatch):
        monkeypatch.chdir(maker)
        self._run("snapshot")
        result = self._run("snapshot")
        assert result.exit_code == 0
        last = result.output.splitlines()[-1]
        assert last.startswith("Nothing has changed since the snapshot of 20")
        assert last.endswith(" UTC. No new one was made.")

    def test_snapshot_says_what_is_not_built(self, maker, work):
        (maker / "_output" / "curve.html").unlink()
        result = self._run("snapshot", "--project-dir", maker)
        assert result.exit_code == 0, result.output
        said = result.output.splitlines()
        assert said[0].endswith(": 1 asset(s) in the store, 1 not built")
        assert said[1] == "  not built: acme/maker:chart/curve (./_output/curve.html)"

    def test_snapshot_with_uncommitted_changes_is_refused(self, maker, monkeypatch):
        (maker / "pull.py").write_text("print('new')\n")
        monkeypatch.chdir(maker)
        result = self._run("snapshot")
        assert result.exit_code == 1
        assert result.output.startswith("Error: acme/maker has changes that are not committed:")
        assert "  ?? maker/pull.py" in result.output.splitlines()

    def test_pin_says_which_snapshot(self, user, maker, work, monkeypatch):
        commit = _git(work, "rev-parse", "HEAD")
        snapshot.make(maker, made_at="2026-10-13T18:22:05.000000Z")
        monkeypatch.chdir(user)
        result = self._run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/maker: 2 pinned",
            f"  From its snapshot at {commit[:7]}, made 2026-10-13 18:22 UTC.",
            "Wrote chartbook.lock.",
        ]

    def test_pin_with_no_snapshot(self, user, work, monkeypatch):
        commit = _git(work, "rev-parse", "HEAD")
        monkeypatch.chdir(user)
        result = self._run("pin")
        assert result.exit_code == 1
        assert result.output.splitlines()[0] == (
            f"acme/maker: cannot be pinned: it has no snapshot at or before {commit[:7]}, "
            f"the commit its folder is on. In ../maker: commit, then run `chartbook snapshot`"
        )
        assert "1 thing(s) could not be pinned." in result.output

    def test_pin_then_update(self, user, maker, monkeypatch):
        snapshot.make(maker)
        monkeypatch.chdir(user)
        self._run("pin")
        _build(maker, rates=b"rates-2")
        snapshot.make(maker)

        stays = self._run("pin")
        assert "acme/maker: 1 already pinned, 1 changed upstream since it was pinned" in (
            stays.output
        )
        assert "chartbook.lock is unchanged." in stays.output
        assert "`chartbook update` moves the pins." in stays.output

        moves = self._run("update")
        assert moves.exit_code == 0, moves.output
        assert "acme/maker: 1 moved, 1 already pinned" in moves.output
        assert "Wrote chartbook.lock." in moves.output

    def test_update_says_what_was_let_go(self, user, maker, monkeypatch):
        snapshot.make(maker)
        monkeypatch.chdir(user)
        self._run("pin")
        (maker / "_output" / "curve.html").unlink()
        (maker / "_data" / "rates.parquet").write_bytes(b"rates-2")
        snapshot.make(maker)
        result = self._run("update")
        assert "  let go: acme/maker:chart/curve (./_output/curve.html)" in result.output
        assert "  What was let go is not built in the snapshot this moved to." in result.output

    def test_gc_keeps_a_snapshot(self, maker):
        snapshot.make(maker)
        result = self._run("store", "gc", "--dry-run")
        assert result.exit_code == 0, result.output
        assert "Nothing to remove." in result.output

    def test_it_is_in_help(self):
        assert "snapshot " in self._run("--help").output


def test_an_unneeded_snapshot_is_kept_a_week():
    """Decided 2026-10-16: 7 days, not 30, so a store stays small."""
    assert snapshot.KEEP_DAYS == 7


class TestNamesAndAggressiveGc:
    """A git tag is a version's name: recorded with the snapshot and shown; `store gc --aggressive`
    lets names keep nothing (decided 2026-10-16)."""

    def test_a_snapshot_records_the_tags_on_its_commit(self, maker, work):
        _git(work, "tag", "v1.0")
        _git(work, "tag", "paper-2026")
        taken = snapshot.make(maker).snapshot
        assert taken.tags == ["paper-2026", "v1.0"]
        assert snapshot.read(taken.path).tags == ["paper-2026", "v1.0"]

    def test_a_tag_not_in_a_tags_shape_is_left_out(self, maker, work):
        import json
        import os
        import stat

        taken = snapshot.make(maker).snapshot
        os.chmod(taken.path, stat.S_IRUSR | stat.S_IWUSR)
        document = json.loads(taken.path.read_text())
        document["tags"] = ["ok-1", "<script>", "a b", "..", 5, "x" * 200]
        taken.path.write_text(json.dumps(document))
        assert snapshot.read(taken.path).tags == ["ok-1"]

    def test_aggressive_lets_a_tag_keep_nothing(self, maker, work):
        release = snapshot.make(maker, made_at=OLDER).snapshot
        _git(work, "tag", "v1")
        (maker / "pull.py").write_text("print('main moves on')\n")
        _commit(work)
        _build(maker, rates=b"rates-2")
        newest = snapshot.make(maker).snapshot
        kept = snapshot.plan_removals(default_store(), set(), set(), keep_days=7)
        assert (release, "it is the newest a branch or tag can pin from") in kept.keep
        aggressive = snapshot.plan_removals(default_store(), set(), set(), keep_days=7, aggressive=True)
        assert [t for t, _ in aggressive.remove] == [release]
        assert (newest, "it is the newest of its pipeline") in aggressive.keep
        # A lockfile's pin still keeps it, whatever names say
        pinned = snapshot.plan_removals(default_store(), {(release.commit, release.made_at)}, set(), keep_days=7, aggressive=True)
        assert (release, "a lockfile pins it") in pinned.keep

    def test_aggressive_lets_a_label_keep_nothing(self, work):
        directory = _manifest(work / "forecast", {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json"}}})
        (directory / "_output").mkdir()
        (directory / "_output" / "m.json").write_bytes(b"v1")
        _commit(work)
        first = snapshot.make(directory, made_at=OLDER).snapshot
        version = first.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        _manifest(directory, {"project": {"id": "acme/forecast"}, "models": {"m": {"path": "./_output/m.json", "aliases": {"champion": version}}}})
        _commit(work)
        (directory / "_output" / "m.json").write_bytes(b"v2")
        snapshot.make(directory)
        assert (first, "a label points at a version in it") in _plan(default_store()).keep
        aggressive = snapshot.plan_removals(default_store(), set(), set(), keep_days=7, aggressive=True)
        assert [t for t, _ in aggressive.remove] == [first]

    def test_the_command_takes_aggressive_and_plans_it_again_on_yes(self, maker, work, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main

        release = snapshot.make(maker, made_at=OLDER).snapshot
        _git(work, "tag", "v1")
        (maker / "pull.py").write_text("print('main moves on')\n")
        _commit(work)
        _build(maker, rates=b"rates-2")
        snapshot.make(maker)
        monkeypatch.chdir(maker)
        listed = CliRunner().invoke(main, ["store", "gc", "--dry-run", "--aggressive"])
        assert listed.exit_code == 0 and release.commit[:7] in listed.output, listed.output
        plan = lock.plan_gc(default_store(), recent_seconds=0, aggressive=True)
        assert plan.aggressive and [t for t, _ in plan.snapshots_delete] == [release]
        removed, _ = lock.run_gc(plan, default_store())
        assert removed == 1 and not release.path.exists()


class TestARecordThatWouldReachOutsideItsObject:
    """A record may come from anyone who can write to a store: what a reader lays onto the object must be plain."""

    @staticmethod
    def _document(record):
        return {
            "schema": snapshot.SCHEMA,
            "root": "acme/evil",
            "code": {"commit": "c" * 40},
            "made_at": "2026-10-18T10:00:00.000000Z",
            "records": [record],
        }

    @staticmethod
    def _record(location, **more):
        return {
            "kind": "Dataframe",
            "version": "chartbook/v1",
            "id": "acme/evil:x",
            "ref": {"scope": "acme", "pipeline": "evil", "kind": "dataframe", "name": "x"},
            "pipeline": "acme/evil",
            "location": location,
            "content_hash": "sha256:" + "a" * 64,
            **more,
        }

    def _written(self, tmp_path, record):
        path = tmp_path / "20261018T100000.000000Z.json"
        path.write_text(json.dumps(self._document(record)))
        return path

    def test_a_glob_that_climbs_after_its_wildcard_is_refused(self, tmp_path):
        record = self._record({"kind": "file", "path": "_data/*/../../../../outside/*.parquet"})
        with pytest.raises(SnapshotError, match=r"acme/evil:x.*not plain after its wildcard"):
            snapshot.read(self._written(tmp_path, record))

    def test_a_listed_file_that_is_not_plain_is_refused(self, tmp_path):
        record = self._record(
            {"kind": "file", "path": "_data/parts"}, files=[{"path": "../../outside/x.parquet", "size_bytes": 8}]
        )
        with pytest.raises(SnapshotError, match="not a plain path in its object"):
            snapshot.read(self._written(tmp_path, record))

    def test_a_plain_glob_a_climbing_prefix_and_plain_files_are_read(self, tmp_path):
        # A glob's fixed prefix may climb (the manifest's path is the real location); only its tail is laid onto the object
        for record in (
            self._record({"kind": "file", "path": "_data/*/part-*.parquet"}),
            self._record({"kind": "file", "path": "../shared/*.parquet"}),
            self._record({"kind": "file", "path": "_data/parts"}, files=[{"path": "year=2024/a.parquet", "size_bytes": 8}]),
            self._record({"kind": "table", "source": "db", "identifier": "t"}),
        ):
            assert "acme/evil:x" in snapshot.read(self._written(tmp_path, record)).assets.values().__iter__().__next__()["id"]

    def test_improper_path_says_why(self):
        assert snapshot.improper_path(self._record({"kind": "file", "path": "_data/*/../x/*.parquet"})) == (
            "has the path '_data/*/../x/*.parquet', which is not plain after its wildcard"
        )
        assert snapshot.improper_path(self._record({"kind": "file", "path": "_data/x.parquet"})) is None
