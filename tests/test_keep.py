"""Tests for ``keep = true``: a costly output's every version stays in the store,
``chartbook restore`` puts it back on disk, and a build that would make it again
stops first. The design is ``docs_src/design/keep.md``.

``costly`` is a pipeline with a dataframe that cost something to make,
``embeddings``, marked ``keep = true``, and a cheap one, ``summary``.
"""

import re
import subprocess
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import index, lock, run, snapshot
from chartbook.check import check_paths
from chartbook.cli import main
from chartbook.manifest import load_manifest
from chartbook.run import RunError
from chartbook.store import default_store

OLDEST = "2025-11-01T00:00:00.000000Z"
OLDER = "2025-12-01T00:00:00.000000Z"
OLD = "2026-01-01T00:00:00.000000Z"
LESS_OLD = "2026-02-01T00:00:00.000000Z"  # all four long before any keep window
KEPT = "which is kept (`keep = true` in its chartbook.toml)"


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
    if not (repository / ".git").exists():
        (repository / ".gitignore").write_text("chartbook.lock\n_data/\n_models/\n*.log\n")
        _git(repository, "init", "--quiet", "-b", "main")
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "--allow-empty", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _manifest(directory: Path, table: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table))
    return directory


def _write(directory: Path, name: str, content: bytes) -> Path:
    (directory / "_data").mkdir(exist_ok=True)
    file = directory / "_data" / f"{name}.parquet"
    file.write_bytes(content)
    return file


COSTLY = {
    "project": {"id": "acme/docs"},
    "dataframes": {
        "embeddings": {"path": "./_data/embeddings.parquet", "docs": "d", "keep": True},
        "summary": {"path": "./_data/summary.parquet", "docs": "d"},
    },
    "scripts": {"build": "echo built >> build.log"},
}


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def costly(work):
    """A pipeline whose ``embeddings`` cost something to make, and is marked; built and committed."""
    directory = _manifest(work / "docs", COSTLY)
    (directory / "README.md").write_text("# docs\n")
    _write(directory, "embeddings", b"emb-1")
    _write(directory, "summary", b"sum-1")
    _commit(work)
    return directory


def _elsewhere(tmp_path: Path) -> None:
    """Make every snapshot's folder of origin one that is not on this machine."""
    for folder in {taken.path.parent for taken in snapshot.all_snapshots(default_store())}:
        (folder / "origins").write_text(str(tmp_path / "another-machine") + "\n")


def _plan(**kwargs):
    kwargs.setdefault("keep_days", 7)
    return snapshot.plan_removals(default_store(), set(), set(), **kwargs)


class TestTheMark:
    @pytest.mark.parametrize("value, word", [("yes", "a string"), (False, "a boolean"), (1, "an integer")])
    def test_a_value_that_is_not_true_is_refused(self, work, value, word):
        table = {**COSTLY, "dataframes": {"embeddings": {"path": "./_data/e.parquet", "docs": "d", "keep": value}}}
        directory = _manifest(work / "p", table)
        with pytest.raises(ValueError, match=re.escape(
            f"[dataframes.embeddings]: keep = {value!r} is {word}, and keep is true, or left out. "
            f"Write keep = true to keep every version of the dataframe in the store, or take the key out."
        )):
            load_manifest(directory)

    def test_keeps_of_lists_the_marked_assets_by_reference(self):
        raw = {
            "dataframes": {"e": {"path": "x", "keep": True}, "s": {"path": "y"}},
            "models": {"m": {"path": "z", "keep": True}},
            "charts": {"c": {"path": "w", "keep": False}},
        }
        assert snapshot.keeps_of(raw) == {"e", "model/m"}
        assert snapshot.keeps_of({}) == set()

    def test_the_snapshot_record_carries_it(self, costly):
        taken = snapshot.make(costly).snapshot
        assert taken.assets["embeddings"]["keep"] is True
        assert "keep" not in taken.assets["summary"]
        assert snapshot.read(taken.path).assets["embeddings"]["keep"] is True  # and the written record validates

    def test_an_asset_declared_and_not_built_keeps_the_mark(self, costly):
        (costly / "_data" / "embeddings.parquet").unlink()
        taken = snapshot.make(costly).snapshot
        assert taken.assets["embeddings"]["keep"] is True and "content_hash" not in taken.assets["embeddings"]

    def test_the_index_record_carries_it(self, costly):
        records = {r["id"]: r for r in index.build_index(load_manifest(costly))["records"]}
        assert records["acme/docs:embeddings"]["keep"] is True
        assert "keep" not in records["acme/docs:summary"]

    def test_a_lockfile_does_not(self, costly, work):
        """The mark is the owner's intent about the owner's store; a lockfile records what was got."""
        snapshot.make(costly)
        user = _manifest(work / "user", {"project": {"id": "acme/user"}, "dependencies": {"acme/docs": {"path": "../docs"}}})
        _commit(work)
        lock.pin(user)
        pinned = lock.read_lock(user / "chartbook.lock")
        assert pinned.assets["acme/docs:embeddings"]["content_hash"]
        assert "keep" not in pinned.assets["acme/docs:embeddings"]


class TestWhatTheStoreKeeps:
    @pytest.fixture
    def versions(self, costly):
        """Four old snapshots, oldest first: embeddings at three versions, the last of them held twice."""
        first = snapshot.make(costly, made_at=OLDEST).snapshot
        _write(costly, "embeddings", b"emb-2")
        second = snapshot.make(costly, made_at=OLDER).snapshot
        _write(costly, "embeddings", b"emb-3")
        third = snapshot.make(costly, made_at=OLD).snapshot
        _write(costly, "summary", b"sum-2")
        fourth = snapshot.make(costly, made_at=LESS_OLD).snapshot
        return first, second, third, fourth

    def test_every_version_is_kept_each_in_the_newest_snapshot_holding_it(self, versions):
        first, second, third, fourth = versions
        plan = _plan()
        assert (first, f"it holds a version of embeddings, {KEPT}") in plan.keep
        assert (second, f"it holds a version of embeddings, {KEPT}") in plan.keep
        assert (fourth, "it is the newest of its pipeline") in plan.keep
        # The third's version is the fourth's too, and the fourth is newer
        assert [t for t, _ in plan.remove] == [third]
        bill = {(kept.name, kept.content_hash): kept.snapshot for kept in plan.kept_versions}
        assert bill == {
            ("embeddings", first.assets["embeddings"]["content_hash"]): first,
            ("embeddings", second.assets["embeddings"]["content_hash"]): second,
            ("embeddings", fourth.assets["embeddings"]["content_hash"]): fourth,
        }
        assert all(kept.pipeline == "acme/docs" and kept.size_bytes == 5 for kept in plan.kept_versions)

    def test_aggressive_keeps_them_too(self, versions):
        """A mark is a cost, not a name."""
        first, second, third, fourth = versions
        plan = _plan(aggressive=True, keep_days=0)
        assert {t.made_at for t, _ in plan.keep} == {first.made_at, second.made_at, fourth.made_at}
        assert [t for t, _ in plan.remove] == [third]

    def test_the_mark_travels_with_snapshots(self, versions, tmp_path):
        """Another machine, sharing the store, has no folder to read the manifest from."""
        first, second, third, fourth = versions
        _elsewhere(tmp_path)
        plan = _plan()
        assert {t.made_at for t, _ in plan.keep} == {first.made_at, second.made_at, fourth.made_at}

    def test_taking_the_mark_out_releases_the_old_versions(self, versions, costly, work, tmp_path):
        first, second, third, fourth = versions
        without = {**COSTLY, "dataframes": {**COSTLY["dataframes"], "embeddings": {"path": "./_data/embeddings.parquet", "docs": "d"}}}
        _manifest(costly, without)
        _commit(work)
        fifth = snapshot.make(costly).snapshot
        assert "keep" not in fifth.assets["embeddings"]
        plan = _plan()
        assert {t.made_at for t, _ in plan.remove} == {first.made_at, second.made_at, third.made_at, fourth.made_at}
        assert plan.kept_versions == []
        # And from another machine, which reads the newest snapshot's records
        _elsewhere(tmp_path)
        assert {t.made_at for t, _ in _plan().remove} == {first.made_at, second.made_at, third.made_at, fourth.made_at}

    def test_gc_says_what_the_marks_keep(self, versions, monkeypatch):
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Kept for `keep = true`: 3 version(s) of acme/docs:embeddings, 15 bytes, in 3 snapshot(s)" in result.output
        assert f"it holds a version of embeddings, {KEPT}" in result.output
        assert "Would remove 1 snapshot(s):" in result.output


class TestRestore:
    def test_a_kept_asset_that_is_missing_comes_back(self, costly):
        taken = snapshot.make(costly).snapshot
        (costly / "_data" / "embeddings.parquet").unlink()
        report = snapshot.restore(costly)
        assert report.put_back == [("embeddings", "./_data/embeddings.parquet", taken, 5)]
        assert report.left == []
        assert (costly / "_data" / "embeddings.parquet").read_bytes() == b"emb-1"
        assert (costly / "_data" / "summary.parquet").read_bytes() == b"sum-1"

    def test_from_the_newest_snapshot_holding_it(self, costly):
        snapshot.make(costly, made_at=OLDER)
        _write(costly, "embeddings", b"emb-2")
        newer = snapshot.make(costly).snapshot
        (costly / "_data" / "embeddings.parquet").unlink()
        report = snapshot.restore(costly)
        assert [(name, taken) for name, _, taken, _ in report.put_back] == [("embeddings", newer)]
        assert (costly / "_data" / "embeddings.parquet").read_bytes() == b"emb-2"

    def test_nothing_on_disk_is_written_over(self, costly):
        snapshot.make(costly)
        (costly / "_data" / "embeddings.parquet").write_bytes(b"mine")
        assert snapshot.restore(costly) == snapshot.Restored()  # a kept asset that is there needs nothing
        report = snapshot.restore(costly, ["embeddings"])
        assert report.left == [("embeddings", "on disk at ./_data/embeddings.parquet; nothing is written over")]
        assert (costly / "_data" / "embeddings.parquet").read_bytes() == b"mine"

    def test_a_named_asset_need_not_be_marked(self, costly):
        snapshot.make(costly)
        (costly / "_data" / "summary.parquet").unlink()
        assert snapshot.restore(costly) == snapshot.Restored()  # not marked: not asked for
        report = snapshot.restore(costly, ["summary"])
        assert [name for name, *_ in report.put_back] == ["summary"]
        assert (costly / "_data" / "summary.parquet").read_bytes() == b"sum-1"

    def test_a_directory_asset(self, costly, work):
        table = {**COSTLY, "models": {"m": {"path": "./_models/m", "docs": "d", "keep": True}}}
        _manifest(costly, table)
        (costly / "_models" / "m").mkdir(parents=True)
        (costly / "_models" / "m" / "weights.bin").write_bytes(b"w")
        (costly / "_models" / "m" / "config.json").write_bytes(b"{}")
        _commit(work)
        taken = snapshot.make(costly).snapshot
        import shutil

        shutil.rmtree(costly / "_models" / "m")
        report = snapshot.restore(costly)
        assert [(name, path, t) for name, path, t, _ in report.put_back] == [("model/m", "./_models/m", taken)]
        assert (costly / "_models" / "m" / "weights.bin").read_bytes() == b"w"
        assert (costly / "_models" / "m" / "config.json").read_bytes() == b"{}"

    def test_what_cannot_be_put_back_is_said(self, costly, work):
        (costly / "_data" / "embeddings.parquet").unlink()
        assert snapshot.restore(costly).left == [("embeddings", "no snapshot of this pipeline holds it")]
        snapshot.make(costly)  # declared and not built: still no snapshot holds it
        assert snapshot.restore(costly).left == [("embeddings", "no snapshot of this pipeline holds it")]
        assert snapshot.restore(costly, ["chart/none"]).left == [("chart/none", "not declared with a path in chartbook.toml")]
        with pytest.raises(ValueError, match="names another pipeline's asset"):
            snapshot.restore(costly, ["other:embeddings"])

    def test_a_table_in_a_source_has_no_file_to_put_back(self, costly, work):
        table = {
            **COSTLY,
            "sources": {"db": {"backend": "duckdb", "url": "./_data/x.duckdb"}},
            "dataframes": {**COSTLY["dataframes"], "t": {"source": "db", "table": "t", "docs": "d", "keep": True}},
        }
        _manifest(costly, table)
        _commit(work)
        assert snapshot.restore(costly, ["t"]).left == [("t", "a table or a query in a source: it has no file to put back")]
        assert snapshot.restore(costly).left == [("t", "a table or a query in a source: it has no file to put back")]

    def test_the_command(self, costly, monkeypatch):
        taken = snapshot.make(costly).snapshot
        monkeypatch.chdir(costly)
        result = CliRunner().invoke(main, ["restore"])
        assert result.exit_code == 0, result.output
        assert result.output == "Nothing to restore: nothing marked `keep = true` is missing from disk.\n"
        (costly / "_data" / "embeddings.parquet").unlink()
        result = CliRunner().invoke(main, ["restore"])
        assert result.exit_code == 0, result.output
        assert result.output == (
            f"embeddings: put back at ./_data/embeddings.parquet from the snapshot at {taken.commit[:7]}, "
            f"made {taken.made_at[:10]} {taken.made_at[11:16]} UTC (5 bytes)\n"
        )
        result = CliRunner().invoke(main, ["restore", "summary", "chart/none"])
        assert result.exit_code == 1
        assert "summary: not put back: on disk at ./_data/summary.parquet; nothing is written over" in result.output
        assert "chart/none: not put back: not declared with a path in chartbook.toml" in result.output


class TestTheStopBeforeABuild:
    def _run(self, directory, **kwargs):
        return run.run(directory, echo=lambda line: None, **kwargs)

    def test_run_stops_when_a_kept_asset_is_missing_and_the_store_has_it(self, costly):
        taken = snapshot.make(costly).snapshot
        (costly / "_data" / "embeddings.parquet").unlink()
        with pytest.raises(RunError) as error:
            self._run(costly)
        said = str(error.value)
        assert said.startswith(
            f"acme/docs: embeddings is kept, and is not on disk (./_data/embeddings.parquet). The store has its version "
            f"from {taken.commit[:7]}, made {taken.made_at[:10]} {taken.made_at[11:16]} UTC.\n"
        )
        assert "\n  chartbook restore           puts it back\n" in said
        assert "\n  chartbook run --remake      runs the build without it, which makes it again\n" in said
        assert said.endswith("\nNothing was built.")
        assert not (costly / "build.log").exists()

    def test_remake_runs_the_build(self, costly):
        snapshot.make(costly)
        (costly / "_data" / "embeddings.parquet").unlink()
        report = self._run(costly, remake=True)
        assert report.failed is None and (costly / "build.log").read_text().split() == ["built"]

    def test_a_first_build_is_not_stopped(self, costly):
        """No version in the store: there is nothing to put back, and the asset has to be made."""
        (costly / "_data" / "embeddings.parquet").unlink()
        assert self._run(costly).failed is None
        assert (costly / "build.log").exists()

    def test_a_kept_asset_on_disk_and_a_cheap_one_missing_stop_nothing(self, costly):
        snapshot.make(costly)
        assert self._run(costly).failed is None
        (costly / "_data" / "summary.parquet").unlink()
        assert self._run(costly).failed is None

    def test_a_catalog_is_checked_whole_before_anything_runs(self, costly, work):
        snapshot.make(costly)
        cheap = _manifest(work / "cheap", {"project": {"id": "acme/cheap"}, "scripts": {"build": "echo built >> build.log"}})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"cheap": {"path": "cheap"}, "docs": {"path": "docs"}}})
        )
        _commit(work)
        (costly / "_data" / "embeddings.parquet").unlink()
        with pytest.raises(RunError, match="acme/docs: embeddings is kept"):
            self._run(work)
        assert not (cheap / "build.log").exists() and not (costly / "build.log").exists()

    def test_the_commands_say_it(self, costly, monkeypatch):
        snapshot.make(costly)
        (costly / "_data" / "embeddings.parquet").unlink()
        monkeypatch.chdir(costly)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1
        assert "Error: acme/docs: embeddings is kept, and is not on disk" in result.output
        assert "chartbook run --remake      runs the build without it" in result.output
        assert not (costly / "build.log").exists()
        result = CliRunner().invoke(main, ["build", "./site", "-f"])
        assert result.exit_code == 1
        assert "chartbook build --remake    runs the build without it" in result.output
        assert not (costly / "site").exists()
        result = CliRunner().invoke(main, ["run", "--remake"])
        assert result.exit_code == 0, result.output
        assert (costly / "build.log").read_text().split() == ["built"]

    def test_kept_missing_alone(self, costly):
        assert run.kept_missing(costly) == []
        taken = snapshot.make(costly).snapshot
        (costly / "_data" / "embeddings.parquet").unlink()
        assert run.kept_missing(costly) == [("embeddings", "./_data/embeddings.parquet", taken)]


class TestCheck:
    def test_check_says_restore_for_a_kept_asset_that_is_missing(self, costly):
        (costly / "_data" / "embeddings.parquet").unlink()
        (problem,) = check_paths(load_manifest(costly), costly)
        assert (problem.table, problem.field) == ("dataframes.embeddings", "path")
        assert problem.message.startswith("file not found: ")
        assert problem.message.endswith("; it is marked keep = true, and `chartbook restore` puts it back from the store")

    def test_a_cheap_asset_gets_no_such_hint(self, costly):
        (costly / "_data" / "summary.parquet").unlink()
        (problem,) = check_paths(load_manifest(costly), costly)
        assert "restore" not in problem.message
