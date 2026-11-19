"""Moving from ChartBook 0.5 to 0.6: what each person types and sees (``docs_src/design/pins-and-rebuilds.md``, "Upgrading").

A store needs nothing: its layout is the same, and both versions read and
write it. A lockfile is another matter. It is written again once, in a
version that began with 0.6.0, and an earlier ChartBook cannot read it: it
says only which version it reads. Told by the manifest's
``requires_chartbook`` that it is too old, it says what to install. So
``chartbook pin``, ``update`` and ``add`` raise that line when they leave
such a lockfile; a build and a read never write a manifest, and say which
command does; and ``chartbook run --check`` fails on one that was not raised.

And the pins themselves: one made from a snapshot of an earlier ChartBook
records no rows, so no rebuild meets it. The commands say so when such
pins are made, and say what gives pins a rebuild can meet: ``chartbook
snapshot`` again in the upstream, then ``chartbook pin --update``.
"""

import errno
import json
import os
import stat
import sys
from pathlib import Path

import polars as pl
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import config, lock, manifest, rowhash, snapshot
from chartbook.__about__ import __version__
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline
from tests.test_lock_by_kind import _as_version_1, _git
from tests.test_run import _commit, _with_data
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

#: What ``pin``, ``update`` and ``add`` say when they have raised it
RAISED = (
    'chartbook.toml: requires_chartbook is now ">=0.6.0" (it was ">=0.5.0"). chartbook.lock is of a version that began '
    "with ChartBook 0.6.0, and an earlier one cannot read it: with this line it is told to upgrade, and how. Commit the "
    "manifest with the lockfile."
)
#: What a build and a read say, which write no manifest
TOLD = (
    'chartbook.toml: requires_chartbook = ">=0.5.0" admits a ChartBook that cannot read chartbook.lock, which is of a '
    "version that began with 0.6.0: such a one says only which version it reads. `chartbook pin` raises the line to "
    '">=0.6.0", and it is then told to upgrade, and how.'
)
#: And what any of them says of a line that cannot be rewritten where it stands
NOT_IN_PLACE = (
    'chartbook.toml: write requires_chartbook = ">=0.6.0" under [project] (it says ">=0.5.0"). chartbook.lock is of a '
    "version that began with ChartBook 0.6.0, and an earlier one cannot read it: with that line it is told to "
    "upgrade, and how. It was not written for you: its line there is not one that can be rewritten in place."
)


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _upstream(directory: Path, table: dict, files: dict) -> Path:
    _write_manifest(directory, table)
    for relative, content in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, pl.DataFrame):
            content.write_parquet(path)
        else:
            path.write_bytes(content)
    commit_pipeline(directory)
    return directory


@pytest.fixture
def rates(work):
    """The upstream: a table of yields dated by ``ds``, a table of codes, a chart and a model."""
    return _upstream(
        work / "rates", MANIFEST,
        {
            "_data/treasury.parquet": _yields(40),
            "_data/codes.parquet": pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]}),
            "_output/curve.html": b"<html>the author's</html>",
            "_models/ar1.joblib": b"weights",
        },
    )


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


def _admits_this(specifier: str) -> bool:
    from packaging.specifiers import SpecifierSet

    return SpecifierSet(specifier).contains(__version__, prereleases=True)


class TestPinUpdateAndAddRaiseTheLine:
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
        # Nothing is left beside it
        assert sorted(path.name for path in report.iterdir()) == ["chartbook.lock", "chartbook.toml"]

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
        assert "requires ChartBook >=0.6.0" in str(told.value) and '`pip install -U "chartbook>=0.6.0"`' in str(told.value)
        assert '`uv add "chartbook>=0.6.0"`' in str(told.value)

    def test_an_earlier_lockfile_written_again_raises_it(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        _as_version_1(report, store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert "chartbook.lock was in an earlier form" in result.output and RAISED in result.output
        assert _asked_for(report) == ">=0.6.0"

    def test_an_earlier_lockfile_that_is_only_checked_is_left_with_its_manifest(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        _as_version_1(report, store)
        before = (report / "chartbook.toml").read_bytes(), (report / "chartbook.lock").read_bytes()
        result = _run("pin", "--check")
        assert result.exit_code == 0, result.output
        assert "requires_chartbook" not in result.output
        # An earlier ChartBook reads that lockfile, so nothing asks for more yet
        assert ((report / "chartbook.toml").read_bytes(), (report / "chartbook.lock").read_bytes()) == before

    def test_a_check_of_a_lockfile_of_this_version_writes_nothing_either(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        before = (report / "chartbook.toml").read_bytes()
        result = _run("pin", "--check")
        assert result.exit_code == 0 and "requires_chartbook" not in result.output
        assert (report / "chartbook.toml").read_bytes() == before

    def test_a_pin_that_changes_nothing_still_sees_to_it(self, report, rates, store):
        """A manifest put back, or merged from a branch that had not moved: the lockfile is as it was, and the line is raised."""
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-2:] == [RAISED, "chartbook.lock is unchanged."]
        assert _asked_for(report) == ">=0.6.0"

    def test_update_says_it_too(self, report, rates, store):
        snapshot.make(rates, store=store)
        result = _run("pin", "--update")
        assert result.exit_code == 0, result.output
        assert RAISED in result.output and _asked_for(report) == ">=0.6.0"

    def test_add_says_it_too(self, report, rates, store):
        snapshot.make(rates, store=store)
        (report / "chartbook.toml").write_text('[project]\nid = "acme/report"\nrequires_chartbook = ">=0.5.0"\n', encoding="utf-8", newline="\n")
        result = _run("add", "acme/rates")
        assert result.exit_code == 0, result.output
        assert RAISED in result.output and _asked_for(report) == ">=0.6.0"
        assert '"acme/rates" = {}' in (report / "chartbook.toml").read_text(encoding="utf-8")

    @pytest.mark.parametrize("ignored", [True, False])
    def test_a_lockfile_git_ignores_reaches_no_one_and_its_manifest_is_left(self, ignored, report, rates, store):
        """Each person's ChartBook then writes a lockfile of its own, and nobody on an earlier one is handed this one."""
        (report / ".gitignore").write_text("/chartbook.lock\n" if ignored else "/other\n", encoding="utf-8", newline="\n")
        _git(report, "init", "--quiet", "-b", "main")
        _git(report, "add", "-A")
        _git(report, "commit", "--quiet", "-m", "The report")
        snapshot.make(rates, store=store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        checked = _run("run", "--check").output
        if ignored:
            assert "requires_chartbook" not in result.output and _asked_for(report) == ">=0.5.0"
            assert "requires_chartbook" not in checked and _git(report, "status", "--porcelain") == ""
        else:
            # One git would track, though it is not committed yet, is on its way to someone
            assert RAISED in result.output.splitlines() and _asked_for(report) == ">=0.6.0"
            assert "requires_chartbook" not in checked

    def test_the_python_function_leaves_the_manifest_unless_asked(self, report, rates, store):
        snapshot.make(rates, store=store)
        found = lock.pin(report, store)
        assert found.written and found.floor is not None and not found.floor.written and not found.floor.asked
        assert (found.floor.was, found.floor.now) == (">=0.5.0", ">=0.6.0") and _asked_for(report) == ">=0.5.0"
        found = lock.update(report, store=store, raise_floor=True)
        assert found.floor.written and found.floor.asked and _asked_for(report) == ">=0.6.0"

    def test_a_pipeline_with_no_lockfile_is_left(self, report):
        """Nothing to pin, so no lockfile, so nothing an earlier ChartBook cannot read."""
        text = '[project]\nid = "acme/report"\nrequires_chartbook = ">=0.5.0"\n'
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        result = _run("pin")
        assert result.exit_code == 0 and "requires_chartbook" not in result.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text and not (report / "chartbook.lock").exists()

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
            # One that shuts out the whole line before it, and admits the lines before that
            ("!=0.5.*", ">=0.6.0,!=0.5.*"),
            ("<2,!=0.5.*", ">=0.6.0,<2,!=0.5.*"),
            # The line before every other one
            ("<0.1", ">=0.6.0,<0.1"),
            # One that lets in neither end of the line before it, and what lies between
            (">=0.5.1,!=0.5.99999", ">=0.6.0,!=0.5.99999"),
        ],
    )
    def test_the_rest_of_what_it_says_is_kept(self, was, now):
        from packaging.specifiers import SpecifierSet

        assert manifest.admits_before(was, "0.6.0")
        assert manifest.raised_to(was, "0.6.0") == now
        # What it gives admits no earlier one, and admits 0.6.0 wherever what it was given did
        assert not manifest.admits_before(now, "0.6.0")
        assert SpecifierSet(now).contains("0.6.0") == SpecifierSet(was).contains("0.6.0")

    def test_a_floor_with_a_patch_number_asks_of_its_own_line(self):
        assert manifest.admits_before("==0.6.0", "0.6.1") and manifest.admits_before("~=0.6.0", "0.6.2")
        assert not manifest.admits_before(">=0.6.1", "0.6.1") and not manifest.admits_before("==0.6.1", "0.6.1")

    @pytest.mark.parametrize(
        "enough",
        [
            ">=0.6.0", ">=0.6", ">=0.6,<1", "==0.6.*", ">=1.0", "~=0.6.0", ">0.6.0", "!=0.5.*,!=0.4.*,!=0.3.*,!=0.2.*,!=0.1.*,!=0.0.*",
            # A release candidate of 0.6.0 itself is not an earlier ChartBook, however the line lets it in
            ">=0.6.0rc1",
        ],
    )
    def test_one_that_asks_for_enough_is_left(self, enough, report, rates, store):
        assert not manifest.admits_before(enough, "0.6.0")
        text = REPORT.replace(">=0.5.0", enough)
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        if not _admits_this(enough):
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
        result = _run("pin")
        assert result.exit_code == 0 and "requires_chartbook" not in result.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text
        assert _run("run", "--check").output.count("requires_chartbook") == 0

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
        found = lock.pin(report, store, raise_floor=True)
        assert found.floor is not None and found.floor.written and (found.floor.was, found.floor.now) == (">=0.5.0", ">=0.6.0")
        with open(report / "chartbook.toml", encoding="utf-8", newline="") as f:
            after = f.read()
        # The quotes it had, its spacing, its comment, its line endings
        assert after == text.replace(">=0.5.0", ">=0.6.0")

    def test_the_key_written_with_the_table_in_its_name(self, report, rates, store):
        text = 'project.id = "acme/report"\nproject.requires_chartbook = ">=0.5.0"\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n'
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        assert lock.pin(report, store, raise_floor=True).floor.written
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text.replace(">=0.5.0", ">=0.6.0")

    def test_a_line_that_looks_like_the_key_comes_first(self, report, rates, store):
        """Another table's key of the same name, above the manifest's own: it is not the one written."""
        text = (
            '[tool.other]\nrequires_chartbook = ">=0.5.0"\n\n[project]\nid = "acme/report"\nrequires_chartbook = ">=0.5.0"\n\n'
            '[dependencies]\n"acme/rates" = { path = "../rates" }\n'
        )
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        assert _run("pin").exit_code == 0
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text.replace(
            '[project]\nid = "acme/report"\nrequires_chartbook = ">=0.5.0"', '[project]\nid = "acme/report"\nrequires_chartbook = ">=0.6.0"'
        )

    def test_a_line_that_looks_like_the_key_elsewhere_is_never_written_into(self):
        text = (
            '[project]\nid = "acme/report"\n\n[dataframes.a]\npath = "./a.parquet"\ndocs = """\n'
            'requires_chartbook = ">=0.5.0"\n"""\n\n[tool.other]\nrequires_chartbook = ">=0.5.0"\n'
        )
        # The manifest's own [project] has no such key: there is nothing to rewrite, and nothing is
        assert manifest.with_requires_chartbook(text, ">=0.6.0") is None

    @pytest.mark.parametrize(
        "text",
        [
            'project = { id = "acme/report", requires_chartbook = ">=0.5.0" }\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n',
            '[project]\nid = "acme/report"\nrequires_chartbook = """>=0.5.0"""\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n',
            '[project]\nid = "acme/report"\n"requires_chartbook" = ">=0.5.0"\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n',
            # Written with an escape: what the line holds is not what it says
            '[project]\nid = "acme/report"\nrequires_chartbook = "\\u003e=0.5.0"\n\n[dependencies]\n"acme/rates" = { path = "../rates" }\n',
        ],
    )
    def test_a_line_it_cannot_rewrite_is_the_users_to_write(self, text, report, rates, store):
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert NOT_IN_PLACE in result.output.splitlines()
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text and (report / "chartbook.lock").is_file()
        # And the check does not name a command that cannot do it
        checked = _run("run", "--check")
        assert checked.exit_code == 1 and 'Write ">=0.6.0", and it is told to upgrade, and how' in checked.output
        assert "`chartbook pin` does" not in checked.output

    @pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="a file's mode stops no write here")
    def test_a_manifest_its_owner_made_read_only_is_the_users_to_write(self, report, rates, store):
        snapshot.make(rates, store=store)
        os.chmod(report / "chartbook.toml", stat.S_IREAD)
        try:
            result = _run("pin")
            mode = stat.S_IMODE((report / "chartbook.toml").stat().st_mode)
        finally:
            os.chmod(report / "chartbook.toml", stat.S_IREAD | stat.S_IWRITE)
        assert result.exit_code == 0, result.output
        assert 'chartbook.toml: write requires_chartbook = ">=0.6.0" under [project]' in result.output
        assert "It was not written for you: the file could not be written (Permission denied)." in result.output
        assert _asked_for(report) == ">=0.5.0" and mode == stat.S_IREAD and (report / "chartbook.lock").is_file()

    @pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="a file's mode stops no write here")
    def test_nothing_names_pin_for_a_manifest_it_cannot_write(self, report, rates, store):
        """A build and the check say what to write, and not that a command writes it which would then say it could not."""
        snapshot.make(rates, store=store)
        (report / "chartbook.toml").write_text(REPORT + '\n[scripts]\nbuild = "echo built"\n', encoding="utf-8", newline="\n")
        os.chmod(report / "chartbook.toml", stat.S_IREAD)
        try:
            ran, checked = _run("run"), _run("run", "--check")
        finally:
            os.chmod(report / "chartbook.toml", stat.S_IREAD | stat.S_IWRITE)
        assert ran.exit_code == 0, ran.output
        assert 'chartbook.toml: write requires_chartbook = ">=0.6.0" under [project]' in ran.output
        assert "It was not written for you: the file could not be written (Permission denied)." in ran.output
        assert "`chartbook pin`" not in ran.output
        assert 'Write ">=0.6.0", and it is told to upgrade, and how' in checked.output and "`chartbook pin` does" not in checked.output

    @pytest.mark.skipif(sys.platform == "win32", reason="a file's mode is another thing there")
    def test_the_files_mode_is_kept(self, report, rates, store):
        snapshot.make(rates, store=store)
        os.chmod(report / "chartbook.toml", 0o640)
        assert _run("pin").exit_code == 0
        assert _asked_for(report) == ">=0.6.0" and stat.S_IMODE((report / "chartbook.toml").stat().st_mode) == 0o640

    def test_a_write_that_fails_half_way_leaves_the_manifest_whole(self, report, rates, store, monkeypatch):
        """The new text goes to a file beside it, moved over it only when whole: a disk that fills leaves the manifest as it was."""
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems  # the lockfile, by a pin that leaves the manifest

        def full(source, target):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(lock, "replace_when_let", full)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert 'chartbook.toml: write requires_chartbook = ">=0.6.0" under [project]' in result.output
        assert "It was not written for you: the file could not be written (No space left on device)." in result.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == REPORT
        # And the file it was written to beside it is gone
        assert sorted(path.name for path in report.iterdir()) == ["chartbook.lock", "chartbook.toml"]

    @pytest.mark.skipif(sys.platform == "win32", reason="making a link needs a right there that a test may not have")
    def test_a_manifest_that_is_a_link_stays_one(self, report, rates, store, work):
        (work / "kept").mkdir()
        (work / "kept" / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
        (report / "chartbook.toml").unlink()
        (report / "chartbook.toml").symlink_to(work / "kept" / "chartbook.toml")
        snapshot.make(rates, store=store)
        assert _run("pin").exit_code == 0
        assert (report / "chartbook.toml").is_symlink() and _asked_for(work / "kept") == ">=0.6.0"

    def test_a_pin_stopped_by_the_stores_note_leaves_the_manifest(self, report, rates, store, monkeypatch):
        """What stops a pin after its lockfile is written stops it before the manifest is: nothing is written that is not said."""
        snapshot.make(rates, store=store)

        def full(self, *arguments, **options):
            raise OSError(errno.ENOSPC, "No space left on device")

        with monkeypatch.context() as patch:
            patch.setattr(FolderStore, "add_root", full)
            result = _run("pin")
        assert result.exit_code == 1 and "the store's note of it" in result.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == REPORT
        # The next pin, with room for the note, raises it and says so
        assert RAISED in _run("pin").output.splitlines()


class TestABuildAndAReadNeverWriteAManifest:
    """``chartbook run`` and a read say which command raises the line: a run that snapshots must leave the folder as its commit has it."""

    def test_run_says_which_command_does_each_time_and_writes_nothing(self, report, rates, store):
        snapshot.make(rates, store=store)
        text = REPORT + '\n[scripts]\nbuild = "echo built"\n'
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        first = _run("run")
        assert first.exit_code == 0, first.output
        said = first.output.splitlines()
        # The run that pins says it with its pins
        assert said[0] == "acme/report: pinning what it depends on" and TOLD in said and "Wrote chartbook.lock." in said
        assert said.index("acme/report: build") > said.index(TOLD)
        # And each run after it, in one line, until someone runs the command
        again = _run("run")
        assert again.exit_code == 0, again.output
        assert again.output.splitlines()[0] == f"acme/report: {TOLD}"
        assert "pinning what it depends on" not in again.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text
        assert _run("pin").exit_code == 0 and _asked_for(report) == ">=0.6.0"
        assert "requires_chartbook" not in _run("run").output

    def test_a_frozen_run_says_nothing_and_writes_nothing(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        text = REPORT + '\n[scripts]\nbuild = "echo built"\n'
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        frozen = _run("run", "--frozen")
        assert frozen.exit_code == 0, frozen.output
        assert "requires_chartbook" not in frozen.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text

    def test_a_run_that_snapshots_is_not_stopped_by_it(self, report, rates, store):
        """The first ``chartbook run --snapshot`` after upgrading, a lockfile of the earlier version committed: the lockfile is written again, the manifest is not, and the snapshot is made."""
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        _as_version_1(report, store)
        text = REPORT + '\n[scripts]\nbuild = "echo built"\n\n[dataframes.out]\npath = "./out.csv"\ndocs = "d"\n'
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        (report / "out.csv").write_text("a,b\n1,2\n", encoding="utf-8", newline="\n")
        (report / ".gitignore").write_text("/out.csv\n", encoding="utf-8", newline="\n")
        _git(report, "init", "--quiet", "-b", "main")
        _git(report, "add", "-A")
        _git(report, "commit", "--quiet", "-m", "The report, pinned under 0.5")
        result = _run("run", "--snapshot", "--no-gc-reminder")
        assert result.exit_code == 0, result.output
        said = result.output.splitlines()
        assert TOLD in said and any(line.startswith("chartbook.lock was in an earlier form") for line in said)
        assert "Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`." in said
        # The manifest is as its commit has it; the lockfile is the one file a run may write
        assert _git(report, "status", "--porcelain") == "M chartbook.lock"
        # And the run after it is not refused for a manifest that changed
        assert _run("run", "--snapshot", "--no-gc-reminder").exit_code == 0

    @pytest.mark.parametrize("ignored", [True, False])
    def test_an_upstream_built_first_keeps_its_manifest(self, ignored, work, monkeypatch):
        """``chartbook run --upstream``: the upstream is another folder of this machine, built and snapshotted first, and its manifest is its owner's to change."""
        _with_data(work / "c", {"build": "echo built"})
        b = _with_data(work / "b", {"build": "echo built"}, {"c": {"path": "../c"}})
        a = _with_data(work / "a", {"build": "echo built"}, {"b": {"path": "../b"}})
        raw = tomli.loads((b / "chartbook.toml").read_text(encoding="utf-8"))
        raw["project"]["requires_chartbook"] = ">=0.5.0"
        (b / "chartbook.toml").write_text(tomli_w.dumps(raw), encoding="utf-8", newline="\n")
        _commit(work)  # with lockfiles ignored, as its .gitignore has them
        if not ignored:
            (work / ".gitignore").write_text("_data/\n_output/\n*.log\n", encoding="utf-8", newline="\n")
            _commit(work)
        snapshot.make(work / "c")
        monkeypatch.chdir(a)
        result = _run("run", "--upstream")
        assert result.exit_code == 0, result.output
        assert _asked_for(b) == ">=0.5.0"
        # With the command to run, and where: the upstream's folder is not the one the run was started in
        told = (
            f'{b / "chartbook.toml"}: requires_chartbook = ">=0.5.0" admits a ChartBook that cannot read chartbook.lock, which is '
            f"of a version that began with 0.6.0: such a one says only which version it reads. `chartbook pin --project-dir {b}` "
            f'raises the line to ">=0.6.0", and it is then told to upgrade, and how.'
        )
        if ignored:
            assert "requires_chartbook" not in result.output and _git(work, "status", "--porcelain") == ""
        else:
            # Told, of the folder it is in; and the two lockfiles are all that the run left
            assert told in result.output
            assert sorted(_git(work, "status", "--porcelain").split()) == ["??", "??", "a/chartbook.lock", "b/chartbook.lock"]

    def test_a_dependency_built_in_chartbooks_own_copy_is_neither_written_nor_told_of(self, work, monkeypatch):
        """A ``git`` dependency with pins of its own is built in ChartBook's copy of it: that lockfile goes nowhere, and that manifest is nobody's to commit."""
        (work / "b").mkdir()
        base = _with_data(work / "b" / "base", {"build": "echo built"})
        (base / "chartbook.toml").write_text(
            (base / "chartbook.toml").read_text(encoding="utf-8").replace('id = "base"', 'id = "acme/base"'), encoding="utf-8", newline="\n"
        )
        _commit(work / "b")
        snapshot.make(base)
        ref = _with_data(work / "ref", {"build": "echo built"}, {"acme/base": {}})
        raw = tomli.loads((ref / "chartbook.toml").read_text(encoding="utf-8"))
        raw["project"]["requires_chartbook"] = ">=0.5.0"
        (ref / "chartbook.toml").write_text(tomli_w.dumps(raw), encoding="utf-8", newline="\n")
        _commit(work / "ref")
        (work / "top").mkdir()
        top = _with_data(work / "top" / "pipeline", {"build": "echo built"}, {"ref": {"git": "../../ref"}})
        _commit(work / "top")
        monkeypatch.chdir(top)
        result = _run("run")
        assert result.exit_code == 0, result.output
        assert "requires_chartbook" not in result.output
        copies = sorted(Path(os.environ["CHARTBOOK_GIT_CACHE"]).rglob("chartbook.toml"))
        assert copies and all(tomli.loads(path.read_text(encoding="utf-8"))["project"].get("requires_chartbook") in (None, ">=0.5.0") for path in copies)
        assert any(path.with_name("chartbook.lock").is_file() for path in copies)  # the pin step ran there

    def test_a_read_that_pins_says_which_command_does_on_stderr(self, report, rates, store, capsys):
        from chartbook import data

        snapshot.make(rates, store=store)
        assert data.load("acme/rates:treasury").collect().height == 80
        assert TOLD in capsys.readouterr().err.splitlines()
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == REPORT
        # Once: the read after it pins nothing, and says nothing
        assert data.load("acme/rates:treasury").collect().height == 80
        assert "requires_chartbook" not in capsys.readouterr().err


class TestCheckHoldsTheManifestToItsLockfile:
    """``chartbook run --check`` fails on a lockfile an earlier ChartBook cannot read, under a manifest that admits one."""

    PROBLEM = (
        'chartbook.toml: [project] requires_chartbook: ">=0.5.0" admits a ChartBook that cannot read chartbook.lock, which is '
        'of a version that began with 0.6.0: such a one says only which version it reads. Write ">=0.6.0" (`chartbook pin` '
        "does), and it is told to upgrade, and how"
    )

    def test_it_is_a_problem(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        result = _run("run", "--check")
        assert result.exit_code == 1, result.output
        assert self.PROBLEM in result.output.splitlines()

    def test_pin_ends_it(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        assert _run("pin").exit_code == 0
        assert "requires_chartbook" not in _run("run", "--check").output

    def test_an_earlier_lockfile_asks_for_no_more(self, report, rates, store):
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        _as_version_1(report, store)
        assert "requires_chartbook" not in _run("run", "--check").output

    def test_with_no_lockfile_there_is_nothing_to_ask_for(self, report):
        assert "requires_chartbook" not in _run("run", "--check").output


class TestAFileOfALaterVersion:
    """This ChartBook, given a file a later one wrote, says so and how to get that one: the next upgrade is told as this one could not be."""

    ADVICE = (
        f". A later ChartBook than this one ({__version__}) wrote it. Install it: `pip install -U chartbook`, or "
        f"`uv sync --upgrade-package chartbook` in a uv project"
    )

    def later(self, taken: snapshot.Snapshot) -> None:
        os.chmod(taken.path, stat.S_IWRITE | stat.S_IREAD)
        taken.path.write_text(
            taken.path.read_text(encoding="utf-8").replace(snapshot.SCHEMA, "chartbook/snapshot/v3"), encoding="utf-8", newline="\n"
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
        self.later(taken)
        with pytest.raises(snapshot.SnapshotError) as told:
            snapshot.read(taken.path)
        assert f"its schema is 'chartbook/snapshot/v3', and this version of ChartBook reads {snapshot.SCHEMA!r}{self.ADVICE}" in str(told.value)

    def test_a_listing_of_the_store_says_what_it_did_not_list(self, rates, store):
        """One it cannot read is not passed over in silence: ``No snapshots.`` of a store that has one would be false."""
        first = snapshot.make(rates, store=store).snapshot
        _yields(41).write_parquet(rates / "_data" / "treasury.parquet")
        second = snapshot.make(rates, store=store).snapshot
        # Beside one it can read, which is listed
        self.later(first)
        both = _run("store", "ls")
        assert both.exit_code == 0, both.output
        assert "acme/rates (1 snapshot(s))" in both.output.splitlines()
        assert len([line for line in both.output.splitlines() if line.startswith("  not listed: Cannot read the snapshot ")]) == 1
        assert self.ADVICE in both.output
        # And where it can read none
        self.later(second)
        none = _run("store", "ls")
        assert none.exit_code == 0, none.output
        assert len([line for line in none.output.splitlines() if line.startswith("  not listed: Cannot read the snapshot ")]) == 2
        assert none.output.splitlines()[-1] == "No snapshots that this ChartBook can read."

    @pytest.mark.parametrize("found", ["chartbook/lock/v1", "chartbook/lock/v2", "chartbook/snapshot/v3", "chartbook/lock/v03x", "v3", "", None, 3])
    def test_any_other_file_is_given_no_advice(self, found):
        assert manifest.later_form_said(found, "chartbook/lock/v2") == ""

    def test_a_version_far_later(self):
        assert manifest.later_form_said("chartbook/lock/v12", "chartbook/lock/v2") == self.ADVICE


def _earlier(count: int) -> str:
    return lock.without_rows_said([f"acme/rates:{i}" for i in range(count)])


class TestPinsFromBeforeRowsWereRecorded:
    """A snapshot made by ChartBook 0.5 says nothing of a table's rows, so a pin of it is met by the same file only."""

    def test_what_is_said(self):
        assert _earlier(1) == (
            "1 dataframe is pinned by its file alone: its snapshot is from before ChartBook 0.6.0, which recorded no rows, "
            "and no rebuild meets such a pin. To pin its rows: `chartbook snapshot` again in its pipeline, with this version, "
            "then `chartbook pin --update` here. Nothing has to be built again: where a table's rows can be recorded, the same "
            "commit and the same files make a new snapshot, once."
        )
        assert _earlier(2) == (
            "2 dataframes are pinned by their files alone: their snapshots are from before ChartBook 0.6.0, which recorded no "
            "rows, and no rebuild meets such a pin. To pin their rows: `chartbook snapshot` again in each of their pipelines, "
            "with this version, then `chartbook pin --update` here. Nothing has to be built again: where a table's rows can be "
            "recorded, the same commit and the same files make a new snapshot, once."
        )
        assert lock.rows_now_said(["a"]) == (
            "1 dataframe has its rows pinned now, as well as its file: a build of someone's own that holds the same rows meets the pin."
        )
        assert lock.rows_now_said(["a", "b"]) == (
            "2 dataframes have their rows pinned now, as well as their files: a build of someone's own that holds the same "
            "rows meets the pin."
        )

    def test_a_pin_of_a_snapshot_an_earlier_chartbook_made_says_it(self, report, rates, store):
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-3:] == [_earlier(2), RAISED, "Wrote chartbook.lock."]
        records = json.loads((report / "chartbook.lock").read_text(encoding="utf-8"))["records"][1:]
        assert not any(key in record for record in records for key in ("rows", "not_hashed"))

    def test_an_earlier_lockfile_written_again_says_it(self, report, rates, store):
        """The first ``chartbook pin`` after upgrading, in a pipeline pinned under 0.5: nothing moves, and both things are told once."""
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        assert not lock.pin(report, store).problems
        _as_version_1(report, store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/rates: 3 already pinned",
            "chartbook.lock was in an earlier form, which pinned every asset. It is written again without its 1 chart: it is "
            "not pinned, and is read from the snapshot the lockfile names, or from your own build of that commit where the "
            "store does not have that snapshot.",
            _earlier(2),
            RAISED,
            "Wrote chartbook.lock.",
        ]
        # And once only: the next pin finds nothing to write, and says nothing of any of it; nor does an update with nothing to move to
        assert _run("pin").output.splitlines() == ["acme/rates: 3 already pinned", "chartbook.lock is unchanged."]
        unmoved = _run("pin", "--update").output
        assert "pinned by" not in unmoved and "rows pinned now" not in unmoved and unmoved.rstrip().endswith("chartbook.lock is unchanged.")

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
            "UTC, which says nothing of the rows of 2 dataframes: this one records them, so that a rebuild can meet a pin of them."
        )
        assert "Snapshot made." in again.output
        # Once: a third finds a snapshot that says its rows, and makes none
        assert "No new snapshot" in _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates)).output

        moved = _run("pin", "--update")
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
        assert "rows pinned now" not in _run("pin", "--update").output
        pinned = lock.read_lock(report).assets
        assert set(pinned["acme/rates:treasury"]["rows"]) and pinned["acme/rates:treasury"]["as_of"] == "2026-01-09"
        assert pinned["acme/rates:codes"]["rows"].keys() == {"all"}

    def test_a_pin_that_moves_to_another_file_is_not_said_to_have_gained_its_rows(self, report, rates, store):
        """It says what its rows did beside the pin it had, where that can be told: here the earlier pin has none to tell by."""
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        assert _run("pin").exit_code == 0
        _yields(41).write_parquet(rates / "_data" / "treasury.parquet")
        assert _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates)).exit_code == 0
        moved = _run("pin", "--update")
        assert moved.exit_code == 0, moved.output
        # The table of codes is the same file, pinned with its rows now; the yields moved
        assert lock.rows_now_said(["acme/rates:codes"]) in moved.output.splitlines()
        assert "pinned by" not in moved.output

    def test_a_dependency_that_did_not_move_is_not_told_of_again(self, report, rates, store, work):
        """Two dependencies pinned under 0.5, and one of them snapshotted again: the other was told of when it was pinned, and is not at every update after."""
        other = _upstream(
            work / "other",
            {"project": {"id": "acme/other"}, "dataframes": {"t": {"path": "./_data/t.parquet", "docs": "d"}}},
            {"_data/t.parquet": pl.DataFrame({"a": [1, 2, 3]})},
        )
        (report / "chartbook.toml").write_text(
            REPORT + '"acme/other" = { path = "../other" }\n', encoding="utf-8", newline="\n"
        )
        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        _as_an_earlier_one_made_it(snapshot.make(other, store=store).snapshot)
        first = _run("pin")
        assert first.exit_code == 0 and _earlier(3) in first.output.splitlines()
        # The rates' owner snapshots again; the reader updates, twice
        assert _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates)).exit_code == 0
        moved = _run("pin", "--update")
        assert moved.exit_code == 0, moved.output
        assert "pinned by" not in moved.output and lock.rows_now_said(["a", "b"]) in moved.output.splitlines()
        _yields(41).write_parquet(rates / "_data" / "treasury.parquet")
        assert _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates)).exit_code == 0
        again = _run("pin", "--update")
        assert again.exit_code == 0 and "Wrote chartbook.lock." in again.output and "pinned by" not in again.output
        assert "rows" not in lock.read_lock(report).assets["acme/other:t"]

    def test_a_table_whose_rows_cannot_be_hashed_says_why_at_each_step(self, report, work, store):
        """A column of lists: the snapshot made again says why it has no rows, and nothing of recording them; the update says why the lockfile changed."""
        nested = _upstream(
            work / "nested",
            {"project": {"id": "acme/rates"}, "dataframes": {"nested": {"path": "./_data/nested.parquet", "docs": "d"}}},
            {"_data/nested.parquet": pl.DataFrame({"a": [1, 2], "l": [[1], [2, 3]]})},
        )
        (report / "chartbook.toml").write_text(REPORT.replace("../rates", "../nested"), encoding="utf-8", newline="\n")
        _as_an_earlier_one_made_it(snapshot.make(nested, store=store).snapshot)
        assert _earlier(1) in _run("pin").output.splitlines()

        again = _run("snapshot", "--no-gc-reminder", "--project-dir", str(nested))
        assert again.exit_code == 0, again.output
        assert "  rows not hashed: acme/rates:nested (column 'l' is List" in again.output
        assert "The same files" not in again.output and "Snapshot made." in again.output

        moved = _run("pin", "--update")
        assert moved.exit_code == 0, moved.output
        (said,) = [line for line in moved.output.splitlines() if line.startswith("acme/rates:nested: its rows are not hashed")]
        assert said.startswith("acme/rates:nested: its rows are not hashed (column 'l' is List") and said.endswith(
            "): it stays pinned by its file alone."
        )
        assert "rows pinned now" not in moved.output and "pinned by its file alone: its snapshot" not in moved.output
        assert "Wrote chartbook.lock." in moved.output
        # Once
        assert "not hashed" not in _run("pin", "--update").output

    def test_a_file_that_is_no_table_is_promised_no_snapshot(self, report, work, store):
        """Whoever pins cannot tell it from a table an earlier ChartBook did not hash, so the advice promises a new snapshot only where rows can be recorded."""
        blob = _upstream(
            work / "blob",
            {"project": {"id": "acme/rates"}, "dataframes": {"blob": {"path": "./_data/blob.parquet", "docs": "d"}}},
            {"_data/blob.parquet": b"not a table"},
        )
        (report / "chartbook.toml").write_text(REPORT.replace("../rates", "../blob"), encoding="utf-8", newline="\n")
        _as_an_earlier_one_made_it(snapshot.make(blob, store=store).snapshot)
        said = _run("pin").output
        assert "where a table's rows can be recorded, the same commit and the same files make a new snapshot, once." in said
        assert "No new snapshot" in _run("snapshot", "--no-gc-reminder", "--project-dir", str(blob)).output

    def test_a_snapshot_made_again_for_another_reason_says_nothing_of_rows(self, rates, store):
        """A tag put on the commit makes a new snapshot of the same files: the one before said its rows, and nothing is said of them."""
        snapshot.make(rates, store=store)
        _git(rates, "tag", "v1")
        result = _run("snapshot", "--no-gc-reminder", "--project-dir", str(rates))
        assert result.exit_code == 0 and "Snapshot made." in result.output
        assert "The same files" not in result.output

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
        none = lock.Lock(root="acme/report")

        def taken(version, **assets):
            return type("Taken", (), {"built_with": {"chartbook": version} if version else {}, "assets": assets})()

        # Pinned in this run from snapshots an earlier ChartBook made, or one that does not say what made it
        found = lock.pinned_before_rows(after, none, {"acme/rates": taken("0.5.1"), "acme/folder": taken(None)})
        assert found == ["acme/folder:of_a_folder", "acme/rates:plain"]
        # From one this version made, a record that says nothing of its rows is a file that is no table: not of these
        assert lock.pinned_before_rows(after, none, {"acme/rates": taken(__version__), "acme/folder": taken(__version__)}) == []
        # Nor from one that names an earlier version and records some table's rows: this ChartBook, built before it had its number
        with_rows = {"hashed": {"rows": {"all": "sha256:" + "b" * 64}}}
        with_why = {"too_wide": {"not_hashed": "more than 256 columns"}}
        assert lock.pinned_before_rows(after, none, {"acme/rates": taken("0.5.2", **with_rows), "acme/folder": taken("0.5.2", **with_why)}) == []
        # Not pinned in this run, and in a lockfile of this version before, as it is: told of when it was made, and not again
        assert lock.pinned_before_rows(after, after, {}) == []
        assert lock.pinned_before_rows(after, after, {"acme/rates": taken("0.5.1"), "acme/folder": taken("0.5.1")}) == []
        # As a lockfile of the earlier version had it, which recorded no rows
        before = lock.Lock(root="acme/report", dependencies=entries, assets={r["id"]: dict(r) for r in records}, read_as="chartbook/lock/v1")
        assert lock.pinned_before_rows(after, before, {}) == ["acme/folder:of_a_folder", "acme/rates:plain"]
        # And not where its file is another than the earlier lockfile's
        before.assets["acme/rates:plain"]["content_hash"] = "sha256:" + "c" * 64
        assert lock.pinned_before_rows(after, before, {}) == ["acme/folder:of_a_folder"]

    def test_which_pins_gained_their_rows(self):
        """A pin of the same file, whose record said nothing of rows and now says them, or says why it has none."""

        def record(content: str, **more) -> dict:
            return {"content_hash": "sha256:" + content * 64, **more}

        rows = {"rows": {"all": "sha256:" + "b" * 64}}
        why = {"not_hashed": "column 'l' is List(Int64)"}
        before = lock.Lock(root="r", assets={
            "gained": record("a"), "says_why": record("a"), "had_them": record("a", **rows), "had_a_reason": record("a", **why),
            "moved": record("a"), "still_none": record("a"), "said_why_already": record("a", **why), "lost_them": record("a", **rows),
            "moved_to_one_with_none": record("a"),
        })
        after = lock.Lock(root="r", assets={
            "gained": record("a", **rows), "says_why": record("a", **why), "had_them": record("a", **rows),
            "had_a_reason": record("a", **rows), "moved": record("c", **rows), "still_none": record("a"), "new": record("d", **rows),
            "said_why_already": record("a", **why), "lost_them": record("a", **why), "moved_to_one_with_none": record("c", **why),
        })
        assert lock.rows_pinned_now(after, before) == ["gained"]
        assert lock.rows_not_hashed_now(after, before) == [("says_why", "column 'l' is List(Int64)")]


class TestWhatTheSecondReviewFound:
    """Each of these was a gap a second review of the rework found, or a change to the code that no test noticed."""

    def test_a_read_that_writes_the_lockfile_again_says_what_a_pin_would_of_its_rows(self, report, rates, store, work, capsys):
        """A dependency added since, read before any command: the read pins it and writes the earlier lockfile again, and the pin after it finds nothing to say."""
        from chartbook import data

        _as_an_earlier_one_made_it(snapshot.make(rates, store=store).snapshot)
        assert not lock.pin(report, store).problems
        _as_version_1(report, store)
        other = _upstream(
            work / "other",
            {"project": {"id": "acme/other"}, "dataframes": {"t": {"path": "./_data/t.parquet", "docs": "d"}}},
            {"_data/t.parquet": pl.DataFrame({"a": [1, 2, 3]})},
        )
        snapshot.make(other, store=store)
        (report / "chartbook.toml").write_text(REPORT + '"acme/other" = { path = "../other" }\n', encoding="utf-8", newline="\n")
        capsys.readouterr()
        assert data.load("acme/other:t").collect().height == 3
        said = capsys.readouterr().err.splitlines()
        assert any(line.startswith("chartbook.lock was in an earlier form") for line in said)
        assert _earlier(2) in said and TOLD in said and said.index(_earlier(2)) < said.index(TOLD)
        assert lock.read_lock(report).read_as == lock.SCHEMA

    def test_a_lockfile_git_tracks_is_not_one_it_ignores_whatever_the_rules_say(self, report, rates, store):
        """Added by force past a rule that would leave it out: it is in the repository, and reaches whoever clones it."""
        snapshot.make(rates, store=store)
        assert not lock.pin(report, store).problems
        (report / ".gitignore").write_text("/chartbook.lock\n", encoding="utf-8", newline="\n")
        _git(report, "init", "--quiet", "-b", "main")
        _git(report, "add", "-A")
        _git(report, "add", "--force", "chartbook.lock")
        _git(report, "commit", "--quiet", "-m", "The report, its lockfile too")
        assert not snapshot.ignored_by_git(report / "chartbook.lock")
        assert RAISED in _run("pin").output.splitlines() and _asked_for(report) == ">=0.6.0"

    def test_a_project_a_repository_above_it_leaves_out_whole_is_held_to_its_lockfile(self, report, rates, store, work):
        """A home folder kept in git with everything ignored: that says nothing of how this project is shared."""
        (work / ".gitignore").write_text("*\n", encoding="utf-8", newline="\n")
        _git(work, "init", "--quiet", "-b", "main")
        snapshot.make(rates, store=store)
        assert snapshot.ignored_by_git(report / "chartbook.lock") and snapshot.ignored_by_git(report / "chartbook.toml")
        assert RAISED in _run("pin").output.splitlines() and _asked_for(report) == ">=0.6.0"

    @pytest.mark.parametrize("error", [FileNotFoundError("git"), __import__("subprocess").TimeoutExpired("git", 5)])
    def test_with_no_git_to_ask_it_cannot_be_told(self, error, report, monkeypatch):
        """Neither ignored nor not: a caller that leaves a manifest alone for git's answer needs the answer."""
        assert snapshot.ignored_by_git(report / "chartbook.lock") is None  # no repository here

        def no_git(*arguments, **options):
            raise error

        monkeypatch.setattr(snapshot.subprocess, "run", no_git)
        assert snapshot.ignored_by_git(report / "chartbook.lock") is None

    @pytest.mark.parametrize(("of_the_lockfile", "of_the_manifest", "left"), [
        (True, False, True),    # shared through git, its lockfile left out
        (True, None, False),    # git answered once and not again
        (True, True, False),    # the whole project left out of a repository above it
        (None, False, False),
        (False, False, False),
    ])
    def test_the_manifest_is_left_only_on_both_of_gits_answers(self, of_the_lockfile, of_the_manifest, left, report, rates, store, monkeypatch):
        answers = {"chartbook.lock": of_the_lockfile, "chartbook.toml": of_the_manifest}
        monkeypatch.setattr(snapshot, "ignored_by_git", lambda path: answers[Path(path).name])
        snapshot.make(rates, store=store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert (RAISED not in result.output.splitlines()) == left and _asked_for(report) == (">=0.5.0" if left else ">=0.6.0")
        # And the check asks the same question, and gets the same answer
        (report / "chartbook.toml").write_text(REPORT, encoding="utf-8", newline="\n")
        assert ("requires_chartbook" not in _run("run", "--check").output) == left

    @pytest.mark.skipif(sys.platform == "win32", reason="a second name for a file is made another way there")
    def test_a_manifest_with_a_second_name_is_the_users_to_write(self, report, rates, store, work):
        """A new file moved over one name would leave the other with the old text, and a write in place can be cut short: neither is done."""
        os.link(report / "chartbook.toml", work / "the-same-file.toml")
        snapshot.make(rates, store=store)
        result = _run("pin")
        assert result.exit_code == 0, result.output
        assert (
            "It was not written for you: the file has a second name (a hard link), which a new file moved over this one "
            "would leave with the old text."
        ) in result.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == REPORT == (work / "the-same-file.toml").read_text(encoding="utf-8")
        assert (work / "the-same-file.toml").stat().st_ino == (report / "chartbook.toml").stat().st_ino
        assert "`chartbook pin` does" not in _run("run", "--check").output

    @pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="a folder's mode stops no write here")
    def test_a_folder_that_cannot_be_written_is_asked_of_too(self, report, rates, store):
        """The new text is written beside the manifest, so its folder has to take a file: asked before any command is named as what writes it."""
        snapshot.make(rates, store=store)
        (report / "chartbook.toml").write_text(REPORT + '\n[scripts]\nbuild = "echo built"\n', encoding="utf-8", newline="\n")
        assert not lock.pin(report, store).problems  # the lockfile, while the folder takes one
        os.chmod(report, stat.S_IREAD | stat.S_IEXEC)
        try:
            pinned, ran, checked = _run("pin"), _run("run"), _run("run", "--check")
        finally:
            os.chmod(report, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        for told in (pinned, ran):
            assert told.exit_code == 0, told.output
            assert 'chartbook.toml: write requires_chartbook = ">=0.6.0" under [project]' in told.output
            assert "It was not written for you: the file could not be written (Permission denied)." in told.output
        assert "`chartbook pin`" not in ran.output and "`chartbook pin` does" not in checked.output
        assert _asked_for(report) == ">=0.5.0"

    def test_a_read_from_a_folder_inside_the_project_says_where_to_pin(self, report, rates, store, monkeypatch, capsys):
        """`chartbook pin` in a notebook's folder finds no manifest: the line gives the command whole."""
        from chartbook import data

        snapshot.make(rates, store=store)
        (report / "notebooks").mkdir()
        monkeypatch.chdir(report / "notebooks")
        assert data.load("acme/rates:treasury").collect().height == 80
        said = capsys.readouterr().err
        assert f"`chartbook pin --project-dir {report}` raises the line to \">=0.6.0\"" in said

    def test_a_folder_with_a_space_in_its_name_is_quoted(self, work):
        floor = lock.Floor(work / "my report (draft)" / "chartbook.toml", ">=0.5.0", ">=0.6.0")
        assert lock.where_to_pin(floor) == f' --project-dir "{work / "my report (draft)"}"'
        assert lock.where_to_pin(lock.Floor(Path.cwd() / "chartbook.toml", ">=0.5.0", ">=0.6.0")) == ""

    def test_a_build_and_a_read_say_what_to_write_where_no_command_can(self, report, rates, store, capsys):
        """A line written inline: `chartbook pin` could not rewrite it either, so it is not named."""
        from chartbook import data

        text = (
            'project = { id = "acme/report", requires_chartbook = ">=0.5.0" }\n\n[scripts]\nbuild = "echo built"\n\n'
            '[dependencies]\n"acme/rates" = { path = "../rates" }\n'
        )
        (report / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        snapshot.make(rates, store=store)
        capsys.readouterr()
        assert data.load("acme/rates:treasury").collect().height == 80
        said = capsys.readouterr().err
        assert NOT_IN_PLACE in said.splitlines() and "`chartbook pin`" not in said
        ran = _run("run")
        assert ran.exit_code == 0 and f"acme/report: {NOT_IN_PLACE}" in ran.output.splitlines() and "`chartbook pin`" not in ran.output
        assert (report / "chartbook.toml").read_text(encoding="utf-8") == text

    def test_the_snapshots_line_for_one_dataframe(self, work, store):
        one = _upstream(
            work / "one",
            {"project": {"id": "acme/one"}, "dataframes": {"t": {"path": "./_data/t.parquet", "docs": "d"}}},
            {"_data/t.parquet": pl.DataFrame({"a": [1, 2, 3]})},
        )
        _as_an_earlier_one_made_it(snapshot.make(one, store=store).snapshot)
        again = _run("snapshot", "--no-gc-reminder", "--project-dir", str(one))
        (said,) = [line for line in again.output.splitlines() if line.startswith("  The same files")]
        assert said.endswith("UTC, which says nothing of the rows of 1 dataframe: this one records them, so that a rebuild can meet a pin of it.")

    def test_a_listing_of_one_pipeline_says_nothing_of_anothers_records(self, rates, store, work):
        other = _upstream(
            work / "other",
            {"project": {"id": "acme/other"}, "dataframes": {"t": {"path": "./_data/t.parquet", "docs": "d"}}},
            {"_data/t.parquet": pl.DataFrame({"a": [1, 2, 3]})},
        )
        snapshot.make(other, store=store)
        TestAFileOfALaterVersion().later(snapshot.make(rates, store=store).snapshot)
        of_other = _run("store", "ls", "acme/other").output
        assert "acme/other (1 snapshot(s))" in of_other and "not listed" not in of_other
        of_rates = _run("store", "ls", "acme/rates").output
        assert "  not listed: Cannot read the snapshot " in of_rates
        assert of_rates.splitlines()[-1] == "No snapshot of acme/rates that this ChartBook can read."
