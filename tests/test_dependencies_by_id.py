"""A dependency named by its pipeline ID alone, pinned from its snapshots in the store, with no folder
of it and no clone (docs_src/design/reading-other-pipelines.md, decision 1a)."""

import json
import shutil
import sys
import warnings
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli_w

from chartbook import data, lineage, lock, snapshot
from chartbook.index import SCHEMAS_DIR, build_index
from chartbook.manifest import load_manifest
from tests.test_model_versions import _git


def _commit(repository: Path, message: str = "Work") -> None:
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "-m", message)


def _rates(folder: Path, value: float) -> None:
    (folder / "_data").mkdir(parents=True, exist_ok=True)
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."}}})
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [value]}).write_parquet(folder / "_data" / "treasury.parquet")


def _forecast(folder: Path, dependencies: dict, scripts=None) -> Path:
    (folder / "_data").mkdir(parents=True, exist_ok=True)
    manifest = {
        "project": {"id": "acme/forecast"},
        "dependencies": dependencies,
        "dataframes": {"outlook": {"path": "./_data/outlook.parquet", "docs": "Its output."}},
    }
    if scripts:
        manifest["scripts"] = scripts
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    pl.DataFrame({"d": ["2024-02-01"], "f": [1.0]}).write_parquet(folder / "_data" / "outlook.parquet")
    return folder


@pytest.fixture
def elsewhere(tmp_path):
    """`acme/rates` snapshotted twice, at two commits, on "machine 1"; then its folder gone."""
    work = tmp_path.resolve()
    machine_one = work / "machine-one"
    rates = machine_one / "rates"
    _rates(rates, 4.1)
    _git(machine_one, "init", "--quiet", "-b", "main")
    (machine_one / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(machine_one)
    first = snapshot.make(rates).snapshot
    _rates(rates, 4.2)
    (rates / "notes.txt").write_text("a second commit\n")
    _commit(machine_one, "Second")
    second = snapshot.make(rates).snapshot
    shutil.rmtree(machine_one)
    return work, first, second


def _pinned(forecast: Path) -> dict:
    (entry,) = lock.read_lock(forecast / lock.LOCK_FILE).dependencies
    return entry


class TestPinnedFromTheStore:
    def test_the_newest_snapshot_with_no_folder_and_no_clone(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        entry = _pinned(forecast)
        assert entry["via"] == "store" and entry["location"] == {
            "kind": "store", "pipeline": "acme/rates", "commit": second.commit, "first_commit": second.first_commit,
        }
        assert entry["snapshot"] == second.made_at
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.2]
        assert lock.verify(forecast).problems == []

    def test_commit_narrows_it(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {"commit": first.commit[:7]}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == first.commit
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]

    def test_a_short_local_name(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"rates": {"id": "acme/rates"}})
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        assert data.load("rates:treasury").collect()["r"].to_list() == [4.2]

    def test_pin_keeps_and_update_moves(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {"commit": first.commit[:7]}})
        lock.pin(forecast)
        _forecast(forecast, {"acme/rates": {}})  # the manifest now takes the newest
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == first.commit  # pin never moves a pin
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit

    def test_one_with_no_snapshot_says_what_to_do(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/other": {}})
        report = lock.pin(forecast)
        (event,) = [e for e in report.events if e.status == "no_snapshot"]
        assert "has no snapshot of acme/other" in event.detail and "chartbook snapshot" in event.detail


class TestTheRestOfChartBookKnowsIt:
    def test_its_snapshot_carries_its_lineage(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        _git(forecast, "init", "--quiet", "-b", "main")
        (forecast / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(forecast)
        with pytest.raises(snapshot.SnapshotError, match="its pins do not account"):
            snapshot.make(forecast)
        lock.pin(forecast)
        taken = snapshot.make(forecast).snapshot
        assert taken.inputs[0]["location"]["kind"] == "store"
        (node,) = lineage.walk(forecast).root.children
        assert (node.label, node.pipeline, node.commit) == ("acme/rates", "acme/rates", second.commit)
        assert lineage.walk(forecast).gaps() == []

    def test_check_says_it_is_not_pinned_and_then_nothing(self, elsewhere):
        from chartbook.check import check_dependencies

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        with pytest.warns(UserWarning, match="not pinned"):
            assert check_dependencies(load_manifest(forecast), forecast) == []
        lock.pin(forecast)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert check_dependencies(load_manifest(forecast), forecast) == []

    def test_the_index_records_it(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {"commit": second.commit[:9]}})
        lock.pin(forecast)
        built = build_index(load_manifest(forecast))
        record = next(r for r in built["records"] if r["kind"] == "Pipeline")
        (dependency,) = record["dependencies"]
        assert dependency["via"] == "store"
        assert dependency["location"] == {"kind": "store", "pipeline": "acme/rates", "at": second.commit[:9], "commit": second.commit}
        schema = json.loads((Path(SCHEMAS_DIR) / "v1" / "Pipeline.json").read_text())
        jsonschema.validate(record, schema)

    def test_run_pins_it_and_builds_only_this_pipeline(self, elsewhere):
        from chartbook import run

        work, first, second = elsewhere
        script = f"{sys.executable} -c \"open('_data/built', 'w').close()\""
        forecast = _forecast(work / "forecast", {"acme/rates": {}}, scripts={"build": script})
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["acme/forecast"]
        assert (forecast / "_data" / "built").exists() and _pinned(forecast)["location"]["commit"] == second.commit


class TestAdd:
    def test_the_text_keeps_everything_else(self):
        from chartbook.manifest import with_dependency

        text = '# a pipeline\n[project]\nid = "acme/forecast"  # its ID\n\n[dependencies]\n# from the store\n"acme/yields" = {}\n'
        changed = with_dependency(text, "acme/rates", {})
        assert changed == text.replace('[dependencies]\n', '[dependencies]\n"acme/rates" = {}\n')
        changed = with_dependency("[project]\nname = 'x'\n", "rates", {"id": "acme/rates", "commit": "3f2a9c1"})
        assert changed.endswith('\n[dependencies]\n"rates" = { id = "acme/rates", commit = "3f2a9c1" }\n')
        with pytest.raises(ValueError, match="has 'acme/yields' already"):
            with_dependency(text, "acme/yields", {})
        with pytest.raises(ValueError, match="Add the entry there yourself"):
            with_dependency('dependencies = { "a/b" = {} }\n', "acme/rates", {})

    def test_the_command_declares_and_pins(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        (forecast / "chartbook.toml").write_text("# my notes\n" + (forecast / "chartbook.toml").read_text())
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["add", "acme/rates", "--as", "rates"])
        assert result.exit_code == 0, result.output
        assert 'Added to [dependencies]' in result.output and '"rates" = { id = "acme/rates" }' in result.output
        assert (forecast / "chartbook.toml").read_text().startswith("# my notes\n")
        assert data.load("rates:treasury").collect()["r"].to_list() == [4.2]
        again = CliRunner().invoke(main, ["add", "acme/rates", "--as", "rates"])
        assert again.exit_code == 1 and "already" in again.output

    def test_a_bad_commit_writes_nothing(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        before = (forecast / "chartbook.toml").read_text()
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["add", "acme/rates", "--commit", "zzz"])
        assert result.exit_code == 1 and "is not the start of a commit" in result.output
        assert (forecast / "chartbook.toml").read_text() == before


class TestAPathDependency:
    def test_in_another_repository_it_says_to_name_it_by_its_id(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        upstream = work / "theirs" / "rates"
        _rates(upstream, 4.0)
        _git(work / "theirs", "init", "--quiet", "-b", "main")
        _commit(work / "theirs")
        forecast = _forecast(work / "mine" / "forecast", {"acme/rates": {"path": "../../theirs/rates"}})
        _git(work / "mine", "init", "--quiet", "-b", "main")
        _commit(work / "mine")
        with pytest.warns(UserWarning, match='is in another git repository.*"acme/rates" = {}'):
            check_dependencies(load_manifest(forecast), forecast)

    def test_in_the_same_repository_it_says_nothing_of_it(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        _commit(work)
        with warnings.catch_warnings(record=True) as said:
            warnings.simplefilter("always")
            check_dependencies(load_manifest(forecast), forecast)
        assert not [w for w in said if "another git repository" in str(w.message)]


def _another(work: Path, name: str, value: float, remote=None, made_at=None):
    """A pipeline in a repository of its own that also calls itself `acme/rates`, snapshotted."""
    repository = work / name
    folder = repository / "rates"
    _rates(folder, value)
    _git(repository, "init", "--quiet", "-b", "main")
    if remote:
        _git(repository, "remote", "add", "origin", remote)
    (repository / ".gitignore").write_text("_data/\nchartbook.lock\n")
    (repository / "README.md").write_text(f"{name}\n")  # its own history, from its first commit
    _commit(repository)
    return snapshot.make(folder, made_at=made_at).snapshot


class TestWhatTheReviewFound:
    def test_a_snapshot_dated_after_now_is_never_the_newest(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forged = _another(work, "forger", 666.0, made_at="2099-01-01T00:00:00.000000Z")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.2]
        from chartbook.store import default_store

        plan = snapshot.plan_removals(default_store(), set(), set(), keep_days=7)
        assert (forged.path, "nothing pins it, and it is dated more than 7 days after now, so it is not taken as made") in [
            (t.path, w) for t, w in plan.remove
        ]
        assert any(t.commit == second.commit and w == "it is the newest of its pipeline" for t, w in plan.keep)

    def test_two_repositories_claiming_one_id_are_not_pinned_until_one_is_named(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates.git")
        assert real.repository == "https://github.com/acme/rates"
        _another(work, "collision", 9.0, remote="git@github.com:someone/rates.git")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        (event,) = [e for e in report.events if e.status == "no_snapshot"]
        assert "2 repositories claim the ID acme/rates" in event.detail and 'repository = "..."' in event.detail
        _forecast(forecast, {"acme/rates": {"repository": "git@github.com:acme/rates.git"}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]

    def test_an_update_keeps_to_the_repository_first_pinned(self, tmp_path):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        _another(work, "later", 9.0, remote="https://github.com/someone/rates")  # newer, from elsewhere
        lock.pin(forecast)  # a pin that moves nothing keeps the repository it was pinned from
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        report = lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == real.commit
        assert not [e for e in report.events if e.status == "moved"]

    def test_a_pipeline_cannot_depend_on_itself_by_id(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.check import check_dependencies
        from chartbook.cli import main

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/forecast": {}})
        report = lock.pin(forecast)
        assert any("cannot depend on itself" in (e.detail or "") for e in report.events)
        problems = check_dependencies(load_manifest(forecast), forecast)
        assert problems and "cannot depend on itself" in problems[0].message
        _forecast(forecast, {})
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["add", "acme/forecast"])
        assert result.exit_code == 1 and "cannot depend on itself" in result.output

    def test_a_short_name_still_answers_to_the_full_id(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"rates": {"id": "acme/rates", "commit": first.commit[:7]}})
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]
        _forecast(forecast, {"rates": {"id": "acme/rates"}})
        lock.update(forecast, ["acme/rates"])
        assert _pinned(forecast)["location"]["commit"] == second.commit

    def test_a_kept_pin_keeps_how_it_was_pinned(self, tmp_path):
        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(work)
        snapshot.make(work / "rates")
        lock.pin(forecast)
        _forecast(forecast, {"acme/rates": {}})
        lock.pin(forecast)
        entry = _pinned(forecast)
        assert entry["via"] == "path" and entry["location"]["kind"] == "path"
        assert any("pinned from" in p.message for p in lock.verify(forecast).problems)


class TestWhatTheSecondReviewFound:
    def test_a_repository_with_no_remote_is_kept_to_by_its_first_commit(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        assert second.repository == "" and second.first_commit and second.first_commit == first.first_commit
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["first_commit"] == second.first_commit
        copy = _another(work, "copy", 666.0)  # a copy of the project, newer, with no remote either
        assert copy.first_commit != second.first_commit
        report = lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit
        assert not [e for e in report.events if e.status == "moved"]
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.2]

    def test_snapshots_naming_no_repository_do_not_block_a_first_pin(self, tmp_path, monkeypatch):
        import dataclasses

        from chartbook.store import default_store

        work = tmp_path.resolve()
        older = _another(work, "before", 1.0, made_at="2026-01-01T00:00:00.000000Z")
        # As a snapshot made before snapshots recorded their repository
        snapshot._write(dataclasses.replace(older, repository="", first_commit=""), default_store())
        (older.path).unlink()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == real.commit
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]

    def test_a_failed_update_does_not_record_the_repository_it_was_told(self, tmp_path):
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _forecast(forecast, {"acme/rates": {"repository": "https://github.com/wrong/rates"}})
        lock.update(forecast)
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        # The line is taken out again, and the owner makes a newer snapshot: update takes it
        _forecast(forecast, {"acme/rates": {}})
        _rates(work / "real" / "rates", 5.0)
        (work / "real" / "rates" / "more.txt").write_text("more\n")
        _commit(work / "real", "Newer")
        newer = snapshot.make(work / "real" / "rates").snapshot
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == newer.commit

    def test_two_ways_of_writing_one_address_are_one_repository(self, tmp_path):
        from chartbook.identity import repository_key

        assert len({
            repository_key(address) for address in (
                "git@github.com:Acme/Rates.git", "https://github.com/acme/rates/", "http://GitHub.com:443/acme/rates",
                "ssh://git@github.com/acme/rates.git", "https://user:token@github.com/acme/rates",
            )
        }) == 1
        assert repository_key("https://gitlab.internal/Acme/Rates") != repository_key("https://gitlab.internal/acme/rates")
        assert repository_key("/a/path/on/disk") == "" and repository_key(None) == ""
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        # Its owner changes how the remote is written; a newer snapshot is the same repository
        _git(work / "real", "remote", "set-url", "origin", "git@github.com:Acme/Rates.git")
        from chartbook.identity import clear_git_remote_cache

        clear_git_remote_cache()
        (work / "real" / "rates" / "more.txt").write_text("more\n")
        _commit(work / "real", "Newer")
        newer = snapshot.make(work / "real" / "rates").snapshot
        assert newer.repository == "https://github.com/Acme/Rates"
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == newer.commit

    def test_a_record_dated_ahead_does_not_stop_a_new_snapshot_of_its_commit(self, tmp_path):
        import dataclasses

        from chartbook.store import default_store

        work = tmp_path.resolve()
        taken = _another(work, "real", 4.0)
        snapshot._write(dataclasses.replace(taken, made_at="2099-01-01T00:00:00.000000Z"), default_store())
        report = snapshot.make(work / "real" / "rates")
        assert not report.made and report.snapshot.made_at == taken.made_at  # the real one, not the one dated ahead
        taken.path.unlink()
        report = snapshot.make(work / "real" / "rates")
        assert report.made and not report.snapshot.made_at.startswith("2099")

    def test_a_label_is_resolved_among_its_own_repositorys_snapshots(self, tmp_path):
        import dataclasses

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        held = real.assets["treasury"]["content_hash"]
        start = held.split(":", 1)[1][:12]
        newest = dataclasses.replace(real, labels={"treasury": {"best": start}})
        # Another repository's record of the ID, holding a version with the same start
        other = dataclasses.replace(
            real, repository="https://github.com/someone/rates", made_at="2026-01-01T00:00:00.000000Z",
            assets={"treasury": {**real.assets["treasury"], "content_hash": held[:-1] + ("0" if held[-1] != "0" else "1")}},
        )
        from chartbook.store import default_store

        records, unresolved = snapshot.label_records(newest, "acme/rates", default_store(), found=[other, newest])
        assert unresolved == [] and list(records) == ["acme/rates:treasury@best"]


class TestTheManifestEdit:
    def test_a_header_inside_a_string_is_not_written_into(self):
        from chartbook.manifest import with_dependency

        text = '[project]\ndescription = """\n[dependencies]\n"""\n\n[dependencies]\n"a/b" = {}\n'
        changed = with_dependency(text, "acme/rates", {})
        assert changed.count('"acme/rates" = {}') == 1
        assert changed.index('"acme/rates" = {}') > changed.index('"""\n\n[dependencies]')

    def test_line_endings_are_kept(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main
        from chartbook.manifest import with_dependency

        crlf = '[project]\r\nid = "acme/forecast"\r\n\r\n[dependencies]\r\n'
        assert with_dependency(crlf, "acme/rates", {}) == crlf + '"acme/rates" = {}\r\n'
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        raw = (forecast / "chartbook.toml").read_bytes().replace(b"\n", b"\r\n")
        (forecast / "chartbook.toml").write_bytes(raw)
        monkeypatch.chdir(forecast)
        assert CliRunner().invoke(main, ["add", "acme/rates"]).exit_code == 0
        written = (forecast / "chartbook.toml").read_bytes()
        assert b"\r\n" in written and b"\n" not in written.replace(b"\r\n", b"")

    def test_a_manifest_with_nan_in_it_is_still_written_into(self):
        from chartbook.manifest import with_dependency

        text = '[project]\nid = "acme/forecast"\n\n[tool.x]\nmissing = nan\n\n[dependencies]\n'
        assert '"acme/rates" = {}' in with_dependency(text, "acme/rates", {})

    def test_other_forms_say_what_to_add(self):
        from chartbook.manifest import with_dependency

        for text in ('["dependencies"]\n"a/b" = {}\n', 'dependencies."a/b" = {}\n', 'dependencies = { "a/b" = {} }\n'):
            with pytest.raises(ValueError, match='Add the entry there yourself: "acme/rates" = {}'):
                with_dependency(text, "acme/rates", {})
        assert '"acme/rates" = {}' in with_dependency('[dependencies."a/b"]\npath = "../b"\n', "acme/rates", {})


class TestTheRepositoryWarning:
    def test_a_short_key_is_kept_in_the_hint(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        _rates(work / "theirs" / "rates", 4.0)
        _git(work / "theirs", "init", "--quiet", "-b", "main")
        _commit(work / "theirs")
        forecast = _forecast(work / "mine" / "forecast", {"rates": {"path": "../../theirs/rates"}})
        _git(work / "mine", "init", "--quiet", "-b", "main")
        _commit(work / "mine")
        with pytest.warns(UserWarning, match=r'"rates" = \{ id = "acme/rates" \}'):
            check_dependencies(load_manifest(forecast), forecast)

    def test_a_folder_in_no_repository_is_said_too(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        _rates(work / "loose" / "rates", 4.0)  # in no git repository
        forecast = _forecast(work / "mine" / "forecast", {"acme/rates": {"path": "../../loose/rates"}})
        _git(work / "mine", "init", "--quiet", "-b", "main")
        _commit(work / "mine")
        with pytest.warns(UserWarning, match="is in no git repository"):
            check_dependencies(load_manifest(forecast), forecast)
