"""Moving from ChartBook 0.5 to 0.6: what each person types and sees (``docs_src/design/pins-and-rebuilds.md``, "Upgrading").

A store needs nothing: its layout is the same, and both versions read and
write it. A lockfile is another matter. It is written again once, in a
version that began with 0.6.0, and an earlier ChartBook cannot read it: it
says only which version it reads. Told by the manifest's
``requires_chartbook`` that it is too old, it says what to install. So a
manifest that says which ChartBook it needs is raised when such a lockfile
is written, and ``chartbook check`` fails on one that was not.

And the pins themselves: one made from a snapshot of an earlier ChartBook
records no rows, so no rebuild meets it. The commands say so when such
pins are made, and say what gives pins a rebuild can meet: ``chartbook
snapshot`` again in the upstream, then ``chartbook update``.
"""

import json
import os
import stat
import sys
from pathlib import Path

import polars as pl
import pytest
import tomli
from click.testing import CliRunner

from chartbook import config, lock, manifest, rowhash, snapshot
from chartbook.__about__ import __version__
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline
from tests.test_lock_by_kind import _as_version_1
from tests.test_standins import MANIFEST, _write_manifest, _yields

#: A manifest as a person keeps it: comments, an order of its own, and a line that only looks like the key
REPORT = '''# The report
[project]
id = "acme/report"   # its ID
requires_chartbook = ">=0.5.0"  # the ChartBook it needs
description = """
requires_chartbook = ">=0.1.0"
"""

[dependencies]
"acme/rates" = { path = "../rates" }
'''


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


@pytest.fixture
def rates(work):
    """The upstream: a table of yields dated by ``ds``, a table of codes, a chart and a model."""
    directory = work / "rates"
    _write_manifest(directory, MANIFEST)
    (directory / "_data").mkdir()
    _yields(40).write_parquet(directory / "_data" / "treasury.parquet")
    pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]}).write_parquet(directory / "_data" / "codes.parquet")
    (directory / "_output").mkdir()
    (directory / "_output" / "curve.html").write_bytes(b"<html>the author's</html>")
    (directory / "_models").mkdir()
    (directory / "_models" / "ar1.joblib").write_bytes(b"weights")
    commit_pipeline(directory)
    return directory


@pytest.fixture
def report(work, rates, monkeypatch):
    """A report that depends on it, whose manifest asks for ChartBook 0.5.0 or later. Commands are run in its folder."""
    directory = work / "report"
    directory.mkdir()
    (directory / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
    monkeypatch.chdir(directory)
    return directory


def _asked_for(folder: Path) -> str:
    return tomli.loads((folder / "chartbook.toml").read_text(encoding="utf-8"))["project"].get("requires_chartbook")


def _run(*arguments: str):
    return CliRunner().invoke(main, list(arguments))


def _as_an_earlier_one_made_it(taken: snapshot.Snapshot, version: str = "0.5.1") -> None:
    """A snapshot in the store as a ChartBook before 0.6.0 made it: nothing of a dataframe's rows, and that version's name."""
    document = json.loads(taken.path.read_text(encoding="utf-8"))
    for record in document["records"]:
        for key in rowhash.FIELDS:
            record.pop(key, None)
    document["built_with"]["chartbook"] = version
    os.chmod(taken.path, stat.S_IWRITE | stat.S_IREAD)
    taken.path.write_text(json.dumps(document, indent=2), encoding="utf-8", newline="\n")


RAISED = (
    'chartbook.toml: requires_chartbook is now ">=0.6.0" (it was ">=0.5.0"). chartbook.lock is of a version that began '
    "with ChartBook 0.6.0, and an earlier one cannot read it: it is now told to upgrade, and how. Commit the two files together."
)


class TestTheManifestAsksForAChartBookThatReadsItsLockfile:
    """``requires_chartbook`` is where an earlier ChartBook learns that it is too old, and what to install."""

    def test_the_version_that_began_this_lockfile_is_one_this_chartbook_is(self):
        from packaging.version import Version

        # A manifest raised to it must not shut out the ChartBook that raised it
        assert Version(__version__) >= Version(lock.SINCE)
        manifest.require_chartbook({"project": {"requires_chartbook": f">={lock.SINCE}"}})

    def test_pin_raises_it_with_the_lockfile_it_writes(self, report, rates, store):
        snapshot.make(rates, store=store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-2:] == [RAISED, "Wrote chartbook.lock."]
        assert _asked_for(report) == ">=0.6.0"
        # Every other character of the file is as it was: comments, order, and the line that only looked like the key
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == REPORT.replace(
            'requires_chartbook = ">=0.5.0"  # the ChartBook it needs', 'requires_chartbook = ">=0.6.0"  # the ChartBook it needs'
        )

    def test_the_next_pin_says_nothing_of_it(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert _run("pin").exit_code == 0
        result = _run("pin")
        assert "requires_chartbook" not in result.output and result.output.rstrip().endswith("chartbook.lock is unchanged.")

    def test_an_earlier_chartbook_is_then_told_what_to_install(self, report, rates, store, monkeypatch):
        snapshot.make(rates, store=store)
        assert _run("pin").exit_code == 0
        monkeypatch.setattr("chartbook.__about__.__version__", "0.5.1")
        with pytest.raises(manifest.RequiresChartbookError) as told:
            manifest.require_chartbook(tomli.loads((report / "chartbook.toml").read_text(encoding="utf-8")))
        assert 'requires ChartBook >=0.6.0' in str(told.value) and '`pip install -U "chartbook>=0.6.0"`' in str(told.value)
        assert '`uv add "chartbook>=0.6.0"`' in str(told.value)

    def test_an_earlier_lockfile_written_again_raises_it(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")  # as it was under 0.5
        _as_version_1(report, store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert "chartbook.lock was in an earlier form" in result.output and RAISED in result.output
        assert _asked_for(report) == ">=0.6.0"

    def test_an_earlier_lockfile_that_is_only_checked_is_left_with_its_manifest(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
        _as_version_1(report, store)
        before = (report / "chartbook.toml").read_bytes(), (report / "chartbook.lock").read_bytes()
        result = _run("pin", "--check")
        assert result.exit_code == 0, result.output
        assert "requires_chartbook" not in result.output
        # An earlier ChartBook reads that lockfile, so nothing asks for more yet
        assert ((report / "chartbook.toml").read_bytes(), (report / "chartbook.lock").read_bytes()) == before

    def test_a_pin_that_changes_nothing_still_sees_to_it(self, report, rates, store):
        """A manifest put back, or merged from a branch that had not moved: the lockfile is as it was, and the line is raised."""
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-2:] == [RAISED, "chartbook.lock is unchanged."]
        assert _asked_for(report) == ">=0.6.0"

    def test_update_says_it_too(self, report, rates, store):
        snapshot.make(rates, store=store)
        result = _run("update")
        assert result.exit_code == 0, result.output
        assert RAISED in result.output and _asked_for(report) == ">=0.6.0"

    def test_run_says_it_before_it_builds_and_a_frozen_run_writes_nothing(self, report, rates, store):
        """A pin step with nothing else to say still says this: a manifest is never written in silence."""
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        text = REPORT + '\n[scripts]\nbuild = "echo built"\n'  # the manifest put back, with a build
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")

        frozen = _run("run", "--frozen")
        assert frozen.exit_code == 0, frozen.output
        assert "requires_chartbook" not in frozen.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text

        result = _run("run")
        assert result.exit_code == 0, result.output
        said = result.output.splitlines()
        assert said[:4] == ["acme/report: pinning what it depends on", "acme/rates: 3 already pinned", RAISED, "chartbook.lock is unchanged."]
        assert said.index("acme/report: build") > said.index(RAISED)
        assert _asked_for(report) == ">=0.6.0"
        # And the run after it has nothing to say of its pins
        assert "pinning what it depends on" not in _run("run").output

    def test_a_read_that_pins_says_it_on_stderr(self, report, rates, store, capsys):
        from chartbook import data

        snapshot.make(rates, store=store)
        assert data.load("acme/rates:treasury").collect().height == 80
        assert RAISED in capsys.readouterr().err
        assert _asked_for(report) == ">=0.6.0"

    @pytest.mark.parametrize(
        ("was", "now"),
        [
            (">=0.5.0", ">=0.6.0"),
            (">0.5.1", ">=0.6.0"),
            (">=0.5,<0.7", ">=0.6.0,<0.7"),
            (">=0.4.0, <2", ">=0.6.0,<2"),
            ("<1", ">=0.6.0,<1"),
            ("!=0.5.3", ">=0.6.0,!=0.5.3"),
            ("~=0.5", ">=0.6.0,~=0.5"),
            ("==0.*", ">=0.6.0,==0.*"),
        ],
    )
    def test_the_rest_of_what_it_says_is_kept(self, was, now):
        from packaging.specifiers import SpecifierSet

        assert manifest.admits_before(was, "0.6.0")
        assert manifest.raised_to(was, "0.6.0") == now
        # What it gives admits no earlier one, and admits 0.6.0 wherever what it was given did
        assert not manifest.admits_before(now, "0.6.0")
        assert SpecifierSet(now).contains("0.6.0") == SpecifierSet(was).contains("0.6.0")

    @pytest.mark.parametrize("enough", [">=0.6.0", ">=0.6", ">=0.6,<1", "==0.6.*", ">=1.0", "~=0.6.0", ">0.6.0"])
    def test_one_that_asks_for_enough_is_left(self, enough, report, rates, store):
        assert not manifest.admits_before(enough, "0.6.0")
        text = REPORT.replace(">=0.5.0", enough)
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        if not manifest_admits_this(enough):
            return  # this ChartBook is not one it asks for: nothing here runs
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert "requires_chartbook" not in result.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text

    def test_a_manifest_that_says_nothing_of_versions_is_left(self, report, rates, store):
        """It made no promise to keep true. An earlier ChartBook there says which version of a lockfile it reads."""
        text = REPORT.replace('requires_chartbook = ">=0.5.0"  # the ChartBook it needs\n', "")
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        found = lock.pin(report, store)
        assert found.written and found.floor is None
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text
        assert _run("check", "--skip-outputs").output.count("requires_chartbook") == 0

    @pytest.mark.parametrize(
        "line",
        [
            'requires_chartbook = ">=0.5.0"',
            "requires_chartbook = '>=0.5.0'",
            '  requires_chartbook=">=0.5.0"   # why',
            'requires_chartbook\t=\t">=0.5.0"',
        ],
    )
    @pytest.mark.parametrize("newline", ["\n", "\r\n"])
    def test_every_other_character_stays(self, line, newline, report, rates, store):
        text = f'# top{newline}[project]{newline}id = "acme/report"{newline}{line}{newline}{newline}[dependencies]{newline}"acme/rates" = {{ path = "../rates" }}{newline}'
        with open(report / "chartbook.toml", "w", encoding="utf-8", newline="") as f:
            f.write(text)
        snapshot.make(rates, store=store)
        found = lock.pin(report, store)
        assert found.floor is not None and found.floor.written and (found.floor.was, found.floor.now) == (">=0.5.0", ">=0.6.0")
        with open(report / "chartbook.toml", encoding="utf-8", newline="") as f:
            after = f.read()
        quoted = line[line.index("=") + 1:].strip().split()[0]
        assert after == text.replace(quoted, '">=0.6.0"')

    def test_the_key_written_with_the_table_in_its_name(self, report, rates, store):
        text = 'project.id = "acme/report"\nproject.requires_chartbook = ">=0.5.0"\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n'
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        assert lock.pin(report, store).floor.written
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text.replace(">=0.5.0", ">=0.6.0")

    @pytest.mark.parametrize(
        "text",
        [
            'project = { id = "acme/report", requires_chartbook = ">=0.5.0" }\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n',
            '[project]\nid = "acme/report"\nrequires_chartbook = """>=0.5.0"""\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n',
            '[project]\nid = "acme/report"\n"requires_chartbook" = ">=0.5.0"\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n',
        ],
    )
    def test_a_line_it_cannot_rewrite_is_the_users_to_write(self, text, report, rates, store):
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert (
            'chartbook.toml: write requires_chartbook = ">=0.6.0" under [project] (it says ">=0.5.0"). chartbook.lock is of a '
            "version that began with ChartBook 0.6.0, and an earlier one cannot read it: with that line it is told to "
            "upgrade, and how. It was not written for you: its line there is not one that can be rewritten in place."
        ) in result.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text and (report / "chartbook.lock").is_file()

    @pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="a file's mode stops no write here")
    def test_a_manifest_that_cannot_be_written_is_the_users_to_write(self, report, rates, store):
        snapshot.make(rates, store=store)
        os.chmod(report / "chartbook.toml", stat.S_IREAD)
        try:
            result = _run("pin")
        finally:
            os.chmod(report / "chartbook.toml", stat.S_IREAD | stat.S_IWRITE)
        assert result.exit_code == 0, result.output
        assert 'chartbook.toml: write requires_chartbook = ">=0.6.0" under [project]' in result.output
        assert "It was not written for you: the file could not be written (Permission denied)." in result.output
        assert _asked_for(report) == ">=0.5.0" and (report / "chartbook.lock").is_file()

    def test_a_line_that_looks_like_the_key_elsewhere_is_never_written_into(self):
        text = (
            '[project]\nid = "acme/report"\n\n[dataframes.a]\npath = "./a.parquet"\ndocs = """\n'
            'requires_chartbook = ">=0.5.0"\n"""\n\n[tool.other]\nrequires_chartbook = ">=0.5.0"\n'
        )
        # The manifest's own [project] has no such key: there is nothing to rewrite, and nothing is
        assert manifest.with_requires_chartbook(text, ">=0.6.0") is None
        with_it = text.replace('id = "acme/report"\n', 'id = "acme/report"\nrequires_chartbook = ">=0.5.0"\n')
        changed = manifest.with_requires_chartbook(with_it, ">=0.6.0")
        assert changed == with_it.replace('id = "acme/report"\nrequires_chartbook = ">=0.5.0"', 'id = "acme/report"\nrequires_chartbook = ">=0.6.0"')


def manifest_admits_this(specifier: str) -> bool:
    from packaging.specifiers import SpecifierSet

    return SpecifierSet(specifier).contains(__version__, prereleases=True)


class TestCheckHoldsTheManifestToItsLockfile:
    """``chartbook check`` fails on a lockfile an earlier ChartBook cannot read, under a manifest that admits one."""

    PROBLEM = (
        'chartbook.toml: [project] requires_chartbook: ">=0.5.0" admits a ChartBook that cannot read chartbook.lock, which is '
        'of a version that began with 0.6.0: such a one says only which version it reads. Write ">=0.6.0" (`chartbook pin` '
        "does), and it is told to upgrade, and how"
    )

    def test_it_is_a_problem(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")  # put back, or merged
        result = _run("check", "--skip-outputs")
        assert result.exit_code == 1, result.output
        assert self.PROBLEM in result.output

    def test_pin_ends_it(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
        assert _run("pin").exit_code == 0
        assert "requires_chartbook" not in _run("check", "--skip-outputs").output

    def test_an_earlier_lockfile_asks_for_no_more(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
        _as_version_1(report, store)
        assert "requires_chartbook" not in _run("check", "--skip-outputs").output

    def test_with_no_lockfile_there_is_nothing_to_ask_for(self, report):
        assert "requires_chartbook" not in _run("check", "--skip-outputs").output


class TestAFileOfALaterVersion:
    """This ChartBook, given a file a later one wrote, says so and how to get that one: the next upgrade is told as this one could not be."""

    ADVICE = (
        f". A later ChartBook than this one ({__version__}) wrote it. Install it: `pip install -U chartbook`, or "
        f"`uv sync --upgrade-package chartbook` in a uv project"
    )

    def test_a_lockfile(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        path = report / "chartbook.lock"
        path.write_text(path.read_text(encoding="utf-8").replace("chartbook/lock/v2", "chartbook/lock/v3"), encoding="utf-8", newline="\n")
        result = _run("pin", "--check")
        assert result.exit_code == 1
        assert (
            f"its schema is 'chartbook/lock/v3', and this version of ChartBook reads 'chartbook/lock/v2'{self.ADVICE}"
        ) in result.output

    def test_a_snapshot(self, rates, store):
        taken = snapshot.make(rates, store=store).snapshot
        os.chmod(taken.path, stat.S_IWRITE | stat.S_IREAD)
        taken.path.write_text(
            taken.path.read_text(encoding="utf-8").replace(snapshot.SCHEMA, "chartbook/snapshot/v3"), encoding="utf-8", newline="\n"
        )
        with pytest.raises(snapshot.SnapshotError) as told:
            snapshot.read(taken.path)
        assert f"its schema is 'chartbook/snapshot/v3', and this version of ChartBook reads {snapshot.SCHEMA!r}{self.ADVICE}" in str(told.value)

    @pytest.mark.parametrize("found", ["chartbook/lock/v1", "chartbook/lock/v2", "chartbook/snapshot/v3", "chartbook/lock/v03x", "v3", "", None, 3])
    def test_any_other_file_is_given_no_advice(self, found):
        assert manifest.later_form_said(found, "chartbook/lock/v2") == ""

    def test_a_version_far_later(self):
        assert manifest.later_form_said("chartbook/lock/v12", "chartbook/lock/v2") == self.ADVICE


class TestPinsFromBeforeRowsWereRecorded:
    """A snapshot made by ChartBook 0.5 says nothing of a table's rows, so a pin of it is met by the same file only."""

    def said(self, count: int) -> str:
        return lock.without_rows_said([f"acme/rates:{i}" for i in range(count)])

    def test_what_is_said(self):
        assert self.said(1) == (
            "1 dataframe is pinned by its file alone: its snapshot is from before ChartBook 0.6.0, which recorded no rows, "
            "and no rebuild meets such a pin. To pin its rows: `chartbook snapshot` again in its pipeline, with this version "
            "(the same commit and the same files make a new snapshot, once, that records them), then `chartbook update` here."
        )
        assert self.said(2) == (
            "2 dataframes are pinned by their files alone: their snapshots are from before ChartBook 0.6.0, which recorded no "
            "rows, and no rebuild meets such a pin. To pin their rows: `chartbook snapshot` again in each of their pipelines, "
            "with this version (the same commit and the same files make a new snapshot, once, that records them), then "
            "`chartbook update` here."
        )

    def test_a_pin_of_a_snapshot_an_earlier_chartbook_made_says_it(self, report, rates, store):
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-3:] == [self.said(2), RAISED, "Wrote chartbook.lock."]
        records = json.loads((report / "chartbook.lock").read_text(encoding="utf-8"))["records"][1:]
        assert not any(key in record for record in records for key in ("rows", "not_hashed"))

    def test_an_earlier_lockfile_written_again_says_it(self, report, rates, store):
        """The first ``chartbook pin`` after upgrading, in a pipeline pinned under 0.5: nothing moves, and both things are told once."""
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        assert not lock.pin(report, store).problems
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
        _as_version_1(report, store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/rates: 3 already pinned",
            "chartbook.lock was in an earlier form, which pinned every asset. It is written again without its 1 chart: it is "
            "not pinned, and is read from the snapshot the lockfile names, or from your own build of that commit where the "
            "store does not have that snapshot.",
            self.said(2),
            RAISED,
            "Wrote chartbook.lock.",
        ]
        # And once only: the next pin finds nothing to write, and says nothing of any of it
        assert _run("pin").output.splitlines() == ["acme/rates: 3 already pinned", "chartbook.lock is unchanged."]

    def test_nothing_is_said_of_a_snapshot_this_version_made(self, report, rates, store):
        snapshot.make(rates, store=store)
        result = _run("pin")
        assert "pinned by" not in result.output and result.exit_code == 0

    def test_the_owner_snapshots_again_and_the_reader_updates(self, report, rates, store):
        """The whole way on: the same commit and the same files make one new snapshot, which records the rows; ``update`` takes them."""
        first = snapshot.make(rates, store=store).snapshot
        _as_an_earlier_one_made_it(first)
        assert _run("pin").exit_code == 0

        again = _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates))
        assert again.exit_code == 0, again.output
        said = [line for line in again.output.splitlines() if line.startswith("  The same files")]
        assert len(said) == 1 and said[0].endswith(
            "UTC, which says nothing of its dataframes' rows: this one records them, so that a rebuild can meet a pin of it."
        )
        assert "Snapshot made." in again.output
        # Once: a third finds a snapshot that says its rows, and makes none
        assert "No new snapshot" in _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates)).output

        moved = _run("update")
        assert moved.exit_code == 0, moved.output
        # The pin has not moved, and the lockfile is written: the command says what changed in it
        assert moved.output.splitlines() == [
            "acme/rates: 3 already pinned. Its 1 chart is not pinned: each build draws it anew",
            moved.output.splitlines()[1],
            "2 dataframes have their rows pinned now, as well as their files: a build of someone's own that holds the same "
            "rows meets the pin.",
            "Wrote chartbook.lock.",
        ]
        assert moved.output.splitlines()[1].startswith("  From its snapshot at ")
        # Once: an update with nothing to move says nothing of it
        assert "rows pinned now" not in _run("update").output
        pinned = lock.read_lock(report).assets
        assert set(pinned["acme/rates:treasury"]["rows"]) and pinned["acme/rates:treasury"]["as_of"] == "2026-01-09"
        assert pinned["acme/rates:codes"]["rows"].keys() == {"all"}

    def test_a_pin_that_moves_to_another_file_is_not_said_to_have_gained_its_rows(self, report, rates, store):
        """It says what its rows did beside the pin it had, where that can be told: here the earlier pin has none to tell by."""
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        assert _run("pin").exit_code == 0
        _yields(41).write_parquet(rates / "_data" / "treasury.parquet")
        assert _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates)).exit_code == 0
        moved = _run("update")
        assert moved.exit_code == 0, moved.output
        # The table of codes is the same file, pinned with its rows now; the yields moved
        assert "1 dataframe has its rows pinned now, as well as its file: a build of someone's own that holds the same rows meets the pin." in moved.output.splitlines()
        assert "pinned by" not in moved.output

    def test_a_snapshot_of_other_files_says_nothing_of_it(self, rates, store):
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        _yields(41).write_parquet(rates / "_data" / "treasury.parquet")
        result = _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates))
        assert result.exit_code == 0 and "The same files" not in result.output

    def test_which_records_are_of_these(self):
        """One by one: only a dataframe, of a dependency pinned from a snapshot, that says nothing of its rows, from a snapshot of an earlier ChartBook."""

        def record(name: str, kind: str = "dataframe", pipeline: str = "acme/rates", **more) -> dict:
            return {"id": f"{pipeline}:{name}", "pipeline": pipeline, "ref": {"kind": kind}, "content_hash": "sha256:" + "a" * 64, **more}

        entries = [
            {"id": "acme/rates", "location": {"kind": "store"}},
            {"id": "acme/folder", "location": {"kind": "path"}},
            {"id": "acme/cloned", "location": {"kind": "git"}},
        ]
        records = [
            record("plain"),
            record("hashed", rows={"all": "sha256:" + "b" * 64}),
            record("too_wide", not_hashed="more than 256 columns"),
            record("model/ar1", kind="model"),
            record("unbuilt", content_hash=None),
            record("of_a_folder", pipeline="acme/folder"),
            record("of_a_clone", pipeline="acme/cloned"),
        ]
        after = lock.Lock(root="acme/report", dependencies=entries, assets={r["id"]: r for r in records})
        earlier = type("Taken", (), {"built_with": {"chartbook": "0.5.1"}})()
        this = type("Taken", (), {"built_with": {"chartbook": __version__}})()
        unsaid = type("Taken", (), {"built_with": {}})()

        # Pinned in this run from snapshots an earlier ChartBook made
        found = lock.pinned_before_rows(after, lock.Lock(root="acme/report"), {"acme/rates": earlier, "acme/folder": unsaid})
        assert found == ["acme/folder:of_a_folder", "acme/rates:plain"]
        # From one this version made, a record that says nothing of its rows is a file that is no table: not of these
        assert lock.pinned_before_rows(after, lock.Lock(root="acme/report"), {"acme/rates": this, "acme/folder": this}) == []
        # Not pinned in this run, and in a lockfile of this version before: nothing is known of its snapshot, and nothing is said
        assert lock.pinned_before_rows(after, after, {}) == []
        # As a lockfile of the earlier version had it, which recorded no rows
        before = lock.Lock(root="acme/report", dependencies=entries, assets={r["id"]: dict(r) for r in records}, read_as="chartbook/lock/v1")
        assert lock.pinned_before_rows(after, before, {}) == ["acme/folder:of_a_folder", "acme/rates:plain"]
        # And not where its file is another than the earlier lockfile's
        before.assets["acme/rates:plain"]["content_hash"] = "sha256:" + "c" * 64
        assert lock.pinned_before_rows(after, before, {}) == ["acme/folder:of_a_folder"]
