"""Tests for versions of a model, and the labels that name them.

This is part 4d of step 4 of ``docs_src/design/overview.md``, and slice M4
of ``docs_src/design/models.md``. Decided by the maintainer on 2026-10-13:
a version is made by a snapshot, and it is named by the start of its
content hash, with labels in the manifest as the names people use.

One pipeline runs through these tests: ``forecast``, with one model whose
bytes and scores the test sets, in a repository of its own.
"""

import json
import subprocess
import warnings
from pathlib import Path

import jsonschema
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import check, index, models, snapshot
from chartbook.cli import main
from chartbook.errors import AssetNotDeclaredError, VersionNotFoundError
from chartbook.identity import UnsupportedRevisionError
from chartbook.manifest import load_manifest, validate_aliases
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


def _commit(repository: Path) -> str:
    if not (repository / ".git").exists():
        (repository / ".gitignore").write_text("chartbook.lock\n_models/\n_output/\n_docs*/\ndocs/\n")
        _git(repository, "init", "--quiet", "-b", "main")
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "--allow-empty", "-m", "Work")
    return _git(repository, "rev-parse", "HEAD")


def _manifest(directory: Path, aliases=None) -> None:
    model = {
        "path": "./_models/m.json",
        "metrics_path": "./_output/metrics.json",
        "docs": "A small model.",
    }
    if aliases is not None:
        model["aliases"] = aliases
    (directory / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/forecast"}, "models": {"m": model}})
    )


def _train(directory: Path, weights: bytes, rmse: float) -> None:
    """What the pipeline's own code does: write the model and its scores."""
    (directory / "_models").mkdir(exist_ok=True)
    (directory / "_models" / "m.json").write_bytes(weights)
    (directory / "_output").mkdir(exist_ok=True)
    (directory / "_output" / "metrics.json").write_text(json.dumps({"rmse": rmse}))


def _version(directory: Path) -> str:
    """Make a snapshot, and return the name of the version it made of the model."""
    report = snapshot.make(directory)
    ((model, name),) = report.new_versions
    assert model == "model/m"
    return name


@pytest.fixture
def forecast(tmp_path):
    """A pipeline with one model, trained once, committed, with no snapshot yet."""
    directory = tmp_path.resolve() / "forecast"
    directory.mkdir()
    (directory / "README.md").write_text("# Forecast\n")
    _manifest(directory)
    _train(directory, b"weights-1", 0.30)
    _commit(directory)
    return directory


class TestAVersionIsMadeByASnapshot:
    def test_the_first_snapshot_makes_the_first_version(self, forecast):
        report = snapshot.make(forecast)
        ((model, name),) = report.new_versions
        record = report.snapshot.assets["model/m"]
        assert model == "model/m"
        assert name == record["content_hash"].split(":")[1][:12]
        assert len(name) == snapshot.VERSION_DIGITS == 12
        assert [v.name for v in models.versions("m", project_dir=forecast)] == [name]

    def test_retraining_makes_no_version_until_a_snapshot_does(self, forecast):
        """Twenty retrains in an afternoon are not twenty versions."""
        first = _version(forecast)
        for attempt in range(3):
            _train(forecast, f"attempt-{attempt}".encode(), 0.29)
        assert [v.name for v in models.versions("m", project_dir=forecast)] == [first]
        second = _version(forecast)
        assert [v.name for v in models.versions("m", project_dir=forecast)] == [first, second]

    def test_the_same_bytes_again_are_the_same_version(self, forecast):
        first = _version(forecast)
        (forecast / "notes.md").write_text("a commit that changes no model\n")
        _commit(forecast)
        again = snapshot.make(forecast)
        assert again.made and again.new_versions == []
        assert [v.name for v in models.versions("m", project_dir=forecast)] == [first]

    def test_a_version_keeps_its_scores_and_its_commit(self, forecast):
        first_commit = _git(forecast, "rev-parse", "HEAD")
        _version(forecast)
        _train(forecast, b"weights-2", 0.21)  # the metrics file is written over
        (forecast / "train.py").write_text("print('better')\n")
        second_commit = _commit(forecast)
        _version(forecast)
        first, second = models.versions("m", project_dir=forecast)
        assert (first.metrics, first.commit) == ({"rmse": 0.30}, first_commit)
        assert (second.metrics, second.commit) == ({"rmse": 0.21}, second_commit)
        assert first.made_at < second.made_at
        assert first.content_hash != second.content_hash

    def test_one_at_a_commit_that_was_amended_away_is_still_a_version(self, forecast):
        """Amending right after a snapshot is routine; the version stays."""
        name = _version(forecast)
        (forecast / "notes.md").write_text("fixed a typo\n")
        _git(forecast, "add", "-A")
        _git(forecast, "commit", "--quiet", "--amend", "--no-edit")
        assert [v.name for v in models.versions("m", project_dir=forecast)] == [name]
        assert models.path(f"m@{name}", project_dir=forecast).read_bytes() == b"weights-1"

    def test_one_made_on_another_branch_is_still_a_version(self, forecast):
        on_main = _version(forecast)
        _git(forecast, "checkout", "--quiet", "-b", "experiment")
        _train(forecast, b"experimental", 0.50)
        (forecast / "train.py").write_text("print('experiment')\n")
        _commit(forecast)
        on_branch = _version(forecast)
        _git(forecast, "checkout", "--quiet", "main")
        names = [v.name for v in models.versions("m", project_dir=forecast)]
        assert names == [on_main, on_branch]

    def test_another_pipelines_snapshots_are_not_this_ones(self, forecast, tmp_path):
        """Two repositories, each with a pipeline at its top, share one store."""
        other = tmp_path.resolve() / "other"
        other.mkdir()
        (other / "README.md").write_text("# Another project\n")
        _manifest(other)
        _train(other, b"another-model", 0.9)
        _commit(other)
        _version(other)
        assert models.versions("m", project_dir=forecast) == []

    def test_a_clone_at_the_same_commit_has_the_same_versions(self, forecast, tmp_path):
        """A commit is the same commit wherever it is checked out, so its snapshots are too."""
        name = _version(forecast)
        clone = tmp_path.resolve() / "clone"
        _git(forecast, "clone", "--quiet", str(forecast), str(clone))
        assert [v.name for v in models.versions("m", project_dir=clone)] == [name]
        assert models.path(f"m@{name}", project_dir=clone).read_bytes() == b"weights-1"

    def test_a_pipeline_that_is_not_in_git_has_none(self, tmp_path):
        directory = tmp_path / "loose"
        directory.mkdir()
        _manifest(directory)
        _train(directory, b"weights", 0.3)
        assert models.versions("m", project_dir=directory) == []

    def test_a_name_is_twelve_digits_and_more_only_when_two_would_share_them(self):
        one = "sha256:7f3a9c2e41b0aaaa" + "0" * 48
        two = "sha256:7f3a9c2e41b0bbbb" + "0" * 48
        other = "sha256:b2c91d0a77f3" + "0" * 52
        assert snapshot.version_name(one) == "7f3a9c2e41b0"
        assert snapshot.version_name(one, [one, other]) == "7f3a9c2e41b0"
        assert snapshot.version_name(one, [one, two]) == "7f3a9c2e41b0a"
        assert snapshot.version_name(two, [one, two]) == "7f3a9c2e41b0b"


class TestNamingAVersion:
    def test_the_plain_name_is_what_is_in_the_folder_now(self, forecast):
        _version(forecast)
        _train(forecast, b"being tuned", 0.25)
        path = models.path("m", project_dir=forecast)
        assert path == forecast / "_models" / "m.json"
        assert path.read_bytes() == b"being tuned"

    def test_by_the_start_of_its_hash(self, forecast):
        name = _version(forecast)
        _train(forecast, b"being tuned", 0.25)
        path = models.path(f"m@{name}", project_dir=forecast)
        assert path.read_bytes() == b"weights-1"
        assert default_store().root in path.parents and path.name == "m.json"

    def test_by_less_of_it_by_more_of_it_and_by_all_of_it(self, forecast):
        """What is typed may be any start that names one version, four digits or more."""
        name = _version(forecast)
        (version,) = models.versions("m", project_dir=forecast)
        whole = version.content_hash
        short = models.path(f"m@{name}", project_dir=forecast)
        assert models.path(f"m@{name[:4]}", project_dir=forecast) == short
        assert models.path(f"m@{name[:7]}", project_dir=forecast) == short
        assert models.path(f"m@{whole.split(':')[1][:20]}", project_dir=forecast) == short
        assert models.path(f"m@{whole.split(':')[1]}", project_dir=forecast) == short
        assert models.path(f"m@{whole}", project_dir=forecast) == short

    def test_a_version_never_changes(self, forecast):
        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        second = _version(forecast)
        assert models.path(f"m@{first}", project_dir=forecast).read_bytes() == b"weights-1"
        assert models.path(f"m@{second}", project_dir=forecast).read_bytes() == b"weights-2"

    def test_one_that_is_not_on_this_machine(self, forecast):
        name = _version(forecast)
        with pytest.raises(VersionNotFoundError) as e:
            models.path("m@000000000000", project_dir=forecast)
        assert e.value.reason == "no_such_version"
        assert str(e.value) == (
            f"No version 000000000000 of model/m is on this machine. Its versions here "
            f"are: {name}. A version is made by a snapshot: `chartbook run --snapshot`."
        )

    def test_another_algorithm_is_not_a_version(self, forecast):
        name = _version(forecast)
        (version,) = models.versions("m", project_dir=forecast)
        digits = version.content_hash.split(":")[1]
        with pytest.raises(VersionNotFoundError, match="names a md5 one"):
            models.path(f"m@md5:{digits[:12]}", project_dir=forecast)
        assert models.path(f"m@sha256:{digits}", project_dir=forecast).read_bytes() == b"weights-1"

    def test_a_label_that_is_not_text_is_not_a_label(self, forecast):
        name = _version(forecast)
        (forecast / "chartbook.toml").write_text(
            (forecast / "chartbook.toml").read_text() + '\n[models.m.aliases]\nflag = true\n'
        )
        with pytest.raises(VersionNotFoundError) as e:
            models.path("m@flag", project_dir=forecast)
        assert "its labels in [models.m.aliases] are: (none)" in str(e.value)

    def test_something_that_is_neither_a_label_nor_a_hash(self, forecast):
        _version(forecast)
        with pytest.raises(VersionNotFoundError) as e:
            models.path("m@v3", project_dir=forecast)
        assert "'v3' is not a label of model/m" in str(e.value)
        assert "its labels in [models.m.aliases] are: (none)" in str(e.value)

    def test_a_start_that_two_versions_share(self, forecast, monkeypatch):
        """Twelve digits are all but always enough. When they are not, it says so,

        and it never picks one of the two.
        """
        taken = snapshot.make(forecast).snapshot
        twins = [
            ("sha256:7f3a9c2e41b0a" + "0" * 51, taken),
            ("sha256:7f3a9c2e41b0b" + "0" * 51, taken),
        ]
        monkeypatch.setattr(snapshot, "versions_of", lambda *a, **k: twins)
        with pytest.raises(VersionNotFoundError) as e:
            models.path("m@7f3a9c2e41b0", project_dir=forecast)
        assert e.value.reason == "ambiguous"
        assert (
            "7f3a9c2e41b0 is the start of 2 versions of model/m: "
            "7f3a9c2e41b0a, 7f3a9c2e41b0b."
        ) in str(e.value)
        assert "Give more digits." in str(e.value)

        # One more digit names one of them
        monkeypatch.setattr(default_store().__class__, "has", lambda self, h: False)
        with pytest.raises(VersionNotFoundError) as e:
            models.path("m@7f3a9c2e41b0a", project_dir=forecast)
        assert e.value.reason == "not_in_store"  # found, which is the point

    def test_one_whose_bytes_the_store_has_lost(self, forecast):
        name = _version(forecast)
        (version,) = models.versions("m", project_dir=forecast)
        default_store().delete(version.content_hash)
        with pytest.raises(VersionNotFoundError) as e:
            models.path(f"m@{name}", project_dir=forecast)
        assert e.value.reason == "not_in_store"

    def test_a_pipeline_with_no_snapshots(self, forecast):
        with pytest.raises(VersionNotFoundError, match="Its versions here are: \\(none\\)"):
            models.path("m@7f3a9c2", project_dir=forecast)

    def test_a_model_that_is_a_folder(self, tmp_path):
        directory = tmp_path.resolve() / "encoder"
        (directory / "_models" / "enc").mkdir(parents=True)
        (directory / "_models" / "enc" / "weights.bin").write_bytes(b"w")
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps({"models": {"enc": {"path": "./_models/enc"}}})
        )
        (directory / ".gitignore").write_text("")
        _git(directory, "init", "--quiet", "-b", "main")
        _git(directory, "add", "-A")
        _git(directory, "commit", "--quiet", "-m", "A model kept in git")
        ((_, name),) = snapshot.make(directory).new_versions
        held = models.path(f"enc@{name}", project_dir=directory)
        assert held.is_dir() and (held / "weights.bin").read_bytes() == b"w"

    def test_only_models_have_versions_so_far(self, forecast):
        from chartbook import data

        with pytest.raises(UnsupportedRevisionError, match="kept for models only"):
            data.path("rates@7f3a9c2", project_dir=forecast)

    def test_a_version_of_a_pipeline_that_is_not_a_dependency(self, forecast):
        from chartbook.errors import DependencyNotDeclaredError

        with pytest.raises(DependencyNotDeclaredError, match="not declared in \\[dependencies\\]"):
            models.path("other:m@champion", project_dir=forecast)


def _serve(forecast: Path, key: str = "forecast") -> Path:
    """A pipeline beside ``forecast`` that depends on it, to serve its model."""
    serve = forecast.parent / "serve"
    serve.mkdir()
    (serve / "README.md").write_text("# Serve\n")
    (serve / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/serve"}, "dependencies": {key: {"path": "../forecast"}}})
    )
    return serve


def _labelled(forecast: Path) -> tuple[str, str]:
    """Two versions, the first labelled champion, the label in the newest snapshot."""
    first = _version(forecast)
    _train(forecast, b"weights-2", 0.21)
    _manifest(forecast, {"champion": first})
    _commit(forecast)
    second = _version(forecast)
    return first, second


def _label_statuses(report) -> dict:
    return {event.asset: event.status for event in report.events if event.asset}


@pytest.fixture
def trained(tmp_path):
    """``rates`` has a dataframe; ``forecast`` depends on it, has a dataframe of
    its own, and a model trained on both. One repository, committed."""
    work = tmp_path.resolve() / "work"
    rates = work / "rates"
    forecast = work / "forecast"
    for directory in (rates, forecast):
        directory.mkdir(parents=True)
        (directory / "README.md").write_text("# A pipeline\n")
    (rates / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
    )
    (rates / "_data").mkdir()
    (rates / "_data" / "treasury.parquet").write_bytes(b"t1")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/forecast"},
                "dependencies": {"rates": {"path": "../rates"}},
                "dataframes": {"d": {"path": "./_data/d.parquet", "docs": "d"}},
                "models": {"m": {"path": "./_models/m.json", "trained_on": ["d", "rates:treasury"], "docs": "A model."}},
            }
        )
    )
    (forecast / "_data").mkdir()
    (forecast / "_data" / "d.parquet").write_bytes(b"d1")
    (forecast / "_models").mkdir()
    (forecast / "_models" / "m.json").write_bytes(b"weights-1")
    (work / ".gitignore").write_text("_data/\n_models/\n_output/\n_docs/\ndocs/\n")
    _git(work, "init", "--quiet", "-b", "main")
    _commit(work)
    return rates, forecast


class TestStaleness:
    """A model is out of date when what it was trained on has moved."""

    MODEL = {"path": "./_models/m.json"}

    def test_what_a_model_was_trained_on_is_recorded_and_compared(self, trained, monkeypatch):
        from chartbook import lock

        rates, forecast = trained
        snapshot.make(rates)
        lock.pin(forecast)
        _commit(forecast.parent)
        taken = snapshot.make(forecast).snapshot
        record = taken.assets["model/m"]
        locked = lock.read_lock(forecast / lock.LOCK_FILE)
        assert record["trained_on"] == {
            "d": taken.assets["d"]["content_hash"],
            "rates:treasury": locked.assets["rates:treasury"]["content_hash"],
        }
        found = models.staleness(forecast, "m", self.MODEL)
        assert found is not None and found.stale == [] and found.now == found.trained_with
        # The upstream moves and this pipeline updates: the model is out of date
        (rates / "_data" / "treasury.parquet").write_bytes(b"t2")
        snapshot.make(rates)
        lock.update(forecast)
        assert models.staleness(forecast, "m", self.MODEL).stale == ["rates:treasury"]
        # ...and so when its own dataframe is rebuilt
        (forecast / "_data" / "d.parquet").write_bytes(b"d2")
        assert set(models.staleness(forecast, "m", self.MODEL).stale) == {"d", "rates:treasury"}
        # The index, check and the page say so
        built = index.build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r["id"] == "acme/forecast:model/m"]
        assert set(record["stale_inputs"]) == {"d", "rates:treasury"}
        (pipeline_record,) = [r for r in built["records"] if r["kind"] == "Pipeline"]
        assert "code_changed_at" not in pipeline_record  # only a docs build works the code times out
        assert set(record["trained_with"]) == {"d", "rates:treasury"}
        schema = json.loads(index.schema_path("Model").read_text())
        jsonschema.validate(record, schema)
        with pytest.warns(UserWarning, match=r"^chartbook.toml: \[models.m\] trained_on: out of date: version [0-9a-f]{12} was trained on inputs that have since moved .*rates:treasury was sha256:.*chartbook run. retrains it"):
            check.check_model_staleness(load_manifest(forecast), forecast)
        # Past versions say which data made them
        (version,) = models.versions_in(forecast, "m")
        assert version.trained_on == taken.assets["model/m"]["trained_on"]
        assert record["versions"][0]["trained_on"] == version.trained_on
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        page = (forecast / "_docs" / "cb" / "models" / "acme--forecast" / "m.md").read_text()
        assert "**Out of date.** This file is version `" in page
        assert "- `rates:treasury`: trained with `sha256:" in page and "`chartbook run` retrains it." in page
        # Retrained: new bytes are no version yet, so nothing is said; a snapshot makes them one, up to date
        (forecast / "_models" / "m.json").write_bytes(b"weights-2")
        assert models.staleness(forecast, "m", self.MODEL) is None
        _commit(forecast.parent)
        snapshot.make(forecast)
        found = models.staleness(forecast, "m", self.MODEL)
        assert found.stale == [] and found.version != taken.assets["model/m"]["content_hash"][7:19]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            check.check_model_staleness(load_manifest(forecast), forecast)
        built = index.build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r["id"] == "acme/forecast:model/m"]
        assert record["stale_inputs"] == []

    def test_a_version_keeps_the_inputs_it_was_first_made_with(self, trained):
        """Found by a reviewer: a later snapshot of the same bytes wrote the inputs
        as they were then, so the record did not mean "trained with", and `pin`
        copied it into a dependant's lockfile."""
        from chartbook import lock

        rates, forecast = trained
        snapshot.make(rates)
        lock.pin(forecast)
        _commit(forecast.parent)
        first = snapshot.make(forecast).snapshot
        then = first.assets["model/m"]["trained_on"]
        # The upstream moves, this pipeline updates and declares ready without retraining
        (rates / "_data" / "treasury.parquet").write_bytes(b"t2")
        snapshot.make(rates)
        lock.update(forecast)
        _commit(forecast.parent)
        second = snapshot.make(forecast).snapshot
        assert second.assets["model/m"]["trained_on"] == then
        assert models.staleness(forecast, "m", self.MODEL).stale == ["rates:treasury"]
        # A dependant's lockfile does not carry the owner's record
        serve = _serve(forecast)
        lock.pin(serve)
        record = lock.read_lock(serve / lock.LOCK_FILE).assets["forecast:model/m"]
        assert "trained_on" not in record

    def test_nothing_is_said_without_a_snapshot_or_without_inputs(self, trained, forecast):
        rates, with_inputs = trained
        assert models.staleness(with_inputs, "m", self.MODEL) is None  # no snapshot holds these bytes
        _version(forecast)  # the plain fixture: a model with no trained_on
        assert models.staleness(forecast, "m", self.MODEL) is None
        assert models.staleness(forecast, "m", {"path": "./nowhere.json"}) is None


class TestAnotherPipelinesVersion:
    """``other:model/m@champion``: the label is looked up when pinning and frozen
    in the lockfile, so a build is repeatable; ``chartbook update`` moves it."""

    def test_a_label_is_pinned_from_the_snapshot_and_resolves(self, forecast):
        from chartbook import lock

        first, second = _labelled(forecast)
        serve = _serve(forecast)
        report = lock.pin(serve)
        assert _label_statuses(report)["forecast:model/m@champion"] == "pinned"
        assert models.path("forecast:m@champion", project_dir=serve).read_bytes() == b"weights-1"
        assert models.path("forecast:m", project_dir=serve).read_bytes() == b"weights-2"
        # A version by the start of its hash is found among the dependency's
        # snapshots in the store; nothing of its folder is read
        assert models.path(f"forecast:m@{first}", project_dir=serve).read_bytes() == b"weights-1"
        assert models.path(f"forecast:m@{second}", project_dir=serve).read_bytes() == b"weights-2"
        record = lock.read_lock(serve / lock.LOCK_FILE).assets["forecast:model/m@champion"]
        assert record["label"] == "champion" and record["ref"]["rev"] == "champion"
        assert record["content_hash"].split(":", 1)[1].startswith(first)
        assert lock.verify(serve).problems == []
        # The lockfile is source: pinning again changes nothing
        assert lock.pin(serve).written is False

    def test_a_label_not_given_when_pinned_says_so(self, forecast):
        from chartbook import lock
        from chartbook.errors import AssetNotPinnedError

        _version(forecast)
        serve = _serve(forecast)
        lock.pin(serve)
        with pytest.raises(AssetNotPinnedError, match="'champion' was not a label of forecast:model/m when") as e:
            models.path("forecast:m@champion", project_dir=serve)
        assert "Its labels then: (none)" in str(e.value) and "`chartbook update forecast`" in str(e.value)
        with pytest.raises(AssetNotPinnedError, match="No snapshot of .acme/forecast. in the store names a version deadbeef of forecast:model/m"):
            models.path("forecast:m@deadbeef", project_dir=serve)

    def test_pin_keeps_a_label_and_update_moves_it(self, forecast):
        from chartbook import lock

        first, second = _labelled(forecast)
        serve = _serve(forecast)
        lock.pin(serve)
        # The owner promotes the second version, and declares it ready
        _manifest(forecast, {"champion": second})
        _commit(forecast)
        _train(forecast, b"weights-3", 0.10)
        snapshot.make(forecast)
        report = lock.pin(serve)
        assert _label_statuses(report)["forecast:model/m@champion"] == "stale"
        assert models.path("forecast:m@champion", project_dir=serve).read_bytes() == b"weights-1"
        report = lock.update(serve)
        assert _label_statuses(report)["forecast:model/m@champion"] == "moved"
        assert models.path("forecast:m@champion", project_dir=serve).read_bytes() == b"weights-2"
        # The owner takes the label away: the next update drops its pin
        _manifest(forecast)
        _commit(forecast)
        _train(forecast, b"weights-4", 0.05)
        snapshot.make(forecast)
        report = lock.update(serve)
        assert _label_statuses(report)["forecast:model/m@champion"] == "dropped"
        assert "forecast:model/m@champion" not in lock.read_lock(serve / lock.LOCK_FILE).assets

    def test_a_label_whose_version_the_store_has_lost(self, forecast):
        from chartbook import lock
        from chartbook.errors import AssetNotPinnedError

        first, _ = _labelled(forecast)
        store = default_store()
        (lost,) = [h for h, _ in snapshot.versions_of(forecast, "model/m") if h.split(":", 1)[1].startswith(first)]
        store.delete(lost)
        serve = _serve(forecast)
        report = lock.pin(serve)
        event = next(e for e in report.events if e.asset == "forecast:model/m@champion")
        assert event.status == "not_built"
        assert event.detail == f"the label names version {first}, and a snapshot names it, and its bytes are not in the store"
        (problem,) = lock.verify(serve).problems
        assert problem.asset == "forecast:model/m@champion"
        assert "is a label pinned without its bytes: the label names version" in problem.message
        # Resolution says the same, not "declared and not built"
        with pytest.raises(AssetNotPinnedError, match="was pinned without its bytes.*bytes are not in the store"):
            models.path("forecast:m@champion", project_dir=serve)
        # ...and so does every later pin, not only the first, whichever way it goes
        again = lock.pin(serve)
        assert _label_statuses(again)["forecast:model/m@champion"] == "not_built"
        updated = lock.update(serve)
        assert _label_statuses(updated)["forecast:model/m@champion"] == "not_built"

    def test_a_git_dependency_has_no_versions(self, forecast):
        """Found by a reviewer: the messages gave a git dependency the remedies of a
        path one, and a dependency that became a git one kept its labels for ever."""
        from chartbook import lock
        from chartbook.errors import AssetNotPinnedError

        first, _ = _labelled(forecast)
        serve = _serve(forecast)
        lock.pin(serve)  # as a path dependency: the label is pinned
        (serve / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/serve"}, "dependencies": {"forecast": {"git": str(forecast)}}})
        )
        report = lock.update(serve)
        assert _label_statuses(report)["forecast:model/m@champion"] == "let_go"
        assert "forecast:model/m@champion" not in lock.read_lock(serve / lock.LOCK_FILE).assets
        for reference in ("forecast:m@champion", f"forecast:m@{first}"):
            with pytest.raises(AssetNotPinnedError, match="a git dependency has no versions"):
                models.path(reference, project_dir=serve)
        assert lock.verify(serve).problems == []

    def test_the_owner_hears_which_labels_a_snapshot_did_not_record(self, forecast, monkeypatch):
        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        _manifest(forecast, {"my label": first, "deadbeef": first, "champion": first})
        _commit(forecast)
        report = snapshot.make(forecast)
        assert report.skipped_labels == [("model/m", "deadbeef"), ("model/m", "my label")]
        monkeypatch.chdir(forecast)
        _train(forecast, b"weights-3", 0.1)
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 0, result.output
        assert "label not recorded: model/m 'my label'" in result.output
        assert "label not recorded: model/m 'deadbeef'" in result.output

    def test_the_remedy_for_a_byteless_label_depends_on_why(self):
        from chartbook.lock import label_remedy

        assert "more digits" in label_remedy("the label names version abcd, and 2 versions share that start", "f")
        assert "made a snapshot that holds that version" in label_remedy("...its bytes are not in the store", "f")

    def test_a_dependency_declared_with_a_scope(self, forecast):
        """Found by a reviewer: the exact-version lookup kept the scope on the local name."""
        from chartbook import lock

        first, _ = _labelled(forecast)
        serve = _serve(forecast, key="acme/forecast")
        lock.pin(serve)
        for reference in (f"acme/forecast:m@{first}", f"forecast:m@{first}", "acme/forecast:m@champion", "forecast:m@champion"):
            assert models.path(reference, project_dir=serve).read_bytes() == b"weights-1", reference

    def test_a_label_the_owner_spells_illegally_is_not_recorded(self, forecast):
        """Found by a reviewer: `check` refuses it, `snapshot` recorded it, and every
        dependant's `pin` then crashed with no lockfile written."""
        from chartbook import lock

        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        _manifest(forecast, {"my label": first, "deadbeef": first, "champion": first})
        _commit(forecast)
        taken = snapshot.make(forecast).snapshot
        assert taken.labels == {"model/m": {"champion": first}}
        serve = _serve(forecast)
        report = lock.pin(serve)
        assert _label_statuses(report)["forecast:model/m@champion"] == "pinned"
        assert (serve / lock.LOCK_FILE).exists()

    def test_an_exact_version_through_a_pin_that_names_no_snapshot_says_why(self, forecast):
        """A lockfile from before every pin came from a snapshot, or changed by hand."""
        from chartbook import lock
        from chartbook.errors import AssetNotPinnedError

        first = _version(forecast)
        serve = _serve(forecast)
        lock.pin(serve)
        name_no_snapshot(serve, "forecast")
        with pytest.raises(AssetNotPinnedError, match="the pin of 'forecast' in the lockfile names no snapshot") as e:
            models.path(f"forecast:m@{first}", project_dir=serve)
        assert "`chartbook update forecast` pins it from a snapshot" in str(e.value)

    def test_a_labelled_version_pinned_keeps_the_snapshot_that_holds_it(self, forecast):
        """The lockfile pins the version by label, so gc keeps a snapshot holding it, as it keeps
        the snapshot the lockfile pins by moment. Found by a reviewer: gc kept the bytes (the
        lockfile's root names them) and removed the only snapshot holding them, after which
        `serve` could not make a snapshot, its lineage having a gap."""
        from chartbook import lock

        first, _ = _labelled(forecast)
        serve = _serve(forecast)
        lock.pin(serve)
        # The owner takes the label away and makes a snapshot, so nothing but
        # this lockfile keeps the first version
        _manifest(forecast)
        _commit(forecast)
        _train(forecast, b"weights-3", 0.1)
        snapshot.make(forecast)
        store = default_store()
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)

        def holds_first(taken) -> bool:
            return taken.assets["model/m"]["content_hash"].split(":", 1)[1].startswith(first)

        assert [why for t, why in plan.snapshots_kept if holds_first(t)] == ["a lockfile pins a labelled version in it"]
        assert not any(holds_first(t) for t, _ in plan.snapshots_delete)
        assert not any(h.split(":", 1)[1].startswith(first) for h, _ in plan.delete)
        lock.run_gc(plan, store)
        assert snapshot.lineage_gaps(serve, store) == []
        assert models.path("forecast:m@champion", project_dir=serve).read_bytes() == b"weights-1"
        assert models.path(f"forecast:m@{first}", project_dir=serve).read_bytes() == b"weights-1"

    def test_what_a_label_pins_is_a_root_for_gc(self, forecast):
        from chartbook import lock

        first, _ = _labelled(forecast)
        serve = _serve(forecast)
        lock.pin(serve)
        (root,) = [r for r in default_store().roots() if r.lockfile == serve / lock.LOCK_FILE]
        assert any(h.split(":", 1)[1].startswith(first) for h in root.hashes)
        # Sharpened by a reviewer: the owner takes the label away, so the newest
        # snapshot no longer keeps the version; the lockfile's root does
        _manifest(forecast)
        _commit(forecast)
        _train(forecast, b"weights-3", 0.1)
        snapshot.make(forecast)
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        assert not any(h.split(":", 1)[1].startswith(first) for h, _ in plan.delete)

    def test_the_command_line(self, forecast, monkeypatch):
        from chartbook import lock

        first, _ = _labelled(forecast)
        serve = _serve(forecast)
        lock.pin(serve)
        monkeypatch.chdir(serve)
        result = CliRunner().invoke(main, ["path", "forecast:model/m@champion"])
        assert result.exit_code == 0, result.output
        assert Path(result.output.strip()).read_bytes() == b"weights-1"


class TestLabels:
    """A label is a name for a version, and promoting is changing one line."""

    def test_a_label_points_at_a_version(self, forecast):
        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        second = _version(forecast)
        _manifest(forecast, {"champion": first, "challenger": second})
        assert models.path("m@champion", project_dir=forecast).read_bytes() == b"weights-1"
        assert models.path("m@challenger", project_dir=forecast).read_bytes() == b"weights-2"

    def test_promoting_is_one_line(self, forecast):
        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        second = _version(forecast)
        _manifest(forecast, {"champion": first})
        before = models.path("m@champion", project_dir=forecast)
        _manifest(forecast, {"champion": second})
        after = models.path("m@champion", project_dir=forecast)
        assert before.read_bytes() == b"weights-1" and after.read_bytes() == b"weights-2"

    def test_versions_say_which_labels_point_at_them(self, forecast):
        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        _version(forecast)
        _manifest(forecast, {"champion": first, "last-quarter": first})
        one, two = models.versions("m", project_dir=forecast)
        assert one.labels == ("champion", "last-quarter") and two.labels == ()

    def test_a_label_whose_version_is_not_here(self, forecast):
        name = _version(forecast)
        _manifest(forecast, {"champion": "000000000000"})
        with pytest.raises(VersionNotFoundError) as e:
            models.path("m@champion", project_dir=forecast)
        assert str(e.value).startswith(
            "No version 000000000000 of model/m is on this machine (the label 'champion' "
            "points at it)."
        )
        assert name in str(e.value)

    @pytest.mark.parametrize(
        "aliases, message",
        [
            ("7f3a9c2e41b0", "'aliases' must be a table of labels"),
            ({"my label": "7f3a9c2e41b0"}, "is not a legal label"),
            ({"7f3a9c2e41b0": "b2c91d0a77f3"}, "looks like a version"),
            ({"beef": "b2c91d0a77f3"}, "looks like a version"),
            ({"champion": "v3"}, "must point at a version"),
            ({"champion": "7f3a9c2"}, "at least 12 digits"),  # git's seven is too few
            ({"champion": 3}, "must point at a version"),
            ({"champion": "7F3A9C2E41B0"}, "must point at a version"),
        ],
    )
    def test_a_malformed_table_is_refused(self, aliases, message):
        with pytest.raises(ValueError, match=message):
            validate_aliases(aliases, "[models.m]")

    def test_a_well_formed_table(self):
        aliases = {
            "champion": "7f3a9c2e41b0",
            "old.one": "sha256:" + "ab" * 32,  # all of it
            "abc": "b2c91d0a77f3",  # three hex digits are a name, not a start
            "bee-keeper": "b2c91d0a77f3",
        }
        assert validate_aliases(aliases, "[models.m]") == aliases

    def test_the_loader_reads_them_and_names_the_file(self, forecast):
        _manifest(forecast, {"champion": "7f3a9c2e41b0"})
        assert load_manifest(forecast)["models"]["m"]["aliases"] == {"champion": "7f3a9c2e41b0"}
        _manifest(forecast, {"champion": "nope"})
        with pytest.raises(ValueError, match="must point at a version"):
            load_manifest(forecast)


class TestListing:
    def test_versions_oldest_first_with_what_was_kept(self, forecast):
        first = _version(forecast)
        (version,) = models.versions("m", project_dir=forecast)
        assert version.name == first and version.built_by_run is False
        assert version.to_dict() == {
            "version": first,
            "content_hash": version.content_hash,
            "made_at": version.made_at,
            "commit": version.commit,
            "metrics": {"rmse": 0.30},
        }

    def test_a_model_the_manifest_does_not_declare(self, forecast):
        with pytest.raises(AssetNotDeclaredError):
            models.versions("nope", project_dir=forecast)

    def test_another_pipelines_model(self, forecast):
        with pytest.raises(ValueError, match="one of this pipeline's own models"):
            models.versions("other:m", project_dir=forecast)


class TestTheIndex:
    def test_the_model_record_lists_its_versions_and_labels(self, forecast):
        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        second = _version(forecast)
        _manifest(forecast, {"champion": second})
        built = index.build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r["kind"] == "Model"]
        assert record["aliases"] == {"champion": second}
        assert [v["version"] for v in record["versions"]] == [first, second]
        assert record["versions"][1]["labels"] == ["champion"]
        assert record["versions"][0]["metrics"] == {"rmse": 0.30}
        assert "labels" not in record["versions"][0]
        jsonschema.validate(record, json.loads(index.schema_path("Model").read_text()))

    def test_a_model_with_no_snapshot_has_no_versions_field(self, forecast):
        built = index.build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r["kind"] == "Model"]
        assert "versions" not in record


class TestCheck:
    def _warnings(self, forecast):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            problems = check.check_model_labels(load_manifest(forecast), forecast)
        return problems, [str(w.message) for w in caught]

    def test_a_label_that_points_at_a_version_here_is_fine(self, forecast):
        _manifest(forecast, {"champion": _version(forecast)})
        assert self._warnings(forecast) == ([], [])

    def test_a_label_whose_version_is_not_here_is_a_warning(self, forecast):
        """It may be right: the version may be in the store of another machine."""
        _version(forecast)
        _manifest(forecast, {"champion": "000000000000"})
        problems, said = self._warnings(forecast)
        assert problems == []
        (line,) = said
        assert "[models.m.aliases] champion: not checked." in line
        assert "No version 000000000000 of model/m is on this machine" in line

    def test_no_labels_nothing_to_say(self, forecast):
        assert self._warnings(forecast) == ([], [])


class TestCommands:
    def _run(self, *arguments):
        return CliRunner().invoke(main, [str(argument) for argument in arguments])

    def test_snapshot_says_when_it_makes_a_version(self, forecast, monkeypatch):
        monkeypatch.chdir(forecast)
        result = self._run("snapshot")
        assert result.exit_code == 0, result.output
        (version,) = models.versions("m", project_dir=forecast)
        assert f"  model/m: new version {version.name}" in result.output.splitlines()

        again = self._run("snapshot")  # nothing new, so nothing to say
        assert "new version" not in again.output

    def test_path_takes_a_version_and_a_label(self, forecast, monkeypatch):
        name = _version(forecast)
        _manifest(forecast, {"champion": name})
        monkeypatch.chdir(forecast)
        by_hash = self._run("path", f"model/m@{name}")
        by_label = self._run("path", "model/m@champion")
        assert by_hash.exit_code == 0, by_hash.output
        assert by_hash.output == by_label.output
        assert Path(by_hash.output.strip()).read_bytes() == b"weights-1"

    def test_path_with_a_version_that_is_not_here_is_a_clean_error(self, forecast, monkeypatch):
        _version(forecast)
        monkeypatch.chdir(forecast)
        result = self._run("path", "model/m@0000000")
        assert result.exit_code == 1
        assert "No version 0000000 of model/m is on this machine." in result.output
        assert self._run("path", "model/m@000").exit_code == 1  # too short to be a start

    def test_the_models_page_lists_its_versions(self, forecast, monkeypatch):
        first = _version(forecast)
        _train(forecast, b"weights-2", 0.21)
        second = _version(forecast)
        _manifest(forecast, {"champion": second})
        monkeypatch.chdir(forecast)
        result = self._run("docs", "generate", "./docs", "-f", "--keep-build-dirs")
        assert result.exit_code == 0, result.output
        text = (forecast / "_docs" / "cb" / "models" / "acme--forecast" / "m.md").read_text()
        assert "## Versions" in text
        rows = [line for line in text.splitlines() if line.startswith(f"| `{second}`")]
        assert rows and "`champion`" in rows[0] and "0.21" in rows[0]
        assert text.index(f"| `{second}`") < text.index(f"| `{first}`")  # newest first


class TestALabelPinnedKeepsItsSnapshot:
    """A reviewer's repro. ``maker`` labels v1 champion and snapshots (S1), then builds v2 with
    champion still v1 (S2); ``user`` pins S2 by its moment, so ``acme/maker:model/m@champion``
    is v1, which S1 alone holds; ``maker`` moves champion to v2 (S3). After ``--keep-days``, gc
    kept S2 and S3 and removed S1, and ``user`` could not make a snapshot: ``lineage_gaps`` said
    its lockfile was changed by hand. A lockfile that pins a version by label now keeps a
    snapshot holding it, as a pin by moment keeps its snapshot; so does a note of the lockfile.
    """

    @pytest.fixture
    def pinned(self, tmp_path):
        import hashlib

        from chartbook import lock

        work = tmp_path.resolve()
        maker, user = work / "maker", work / "user"
        maker.mkdir()
        user.mkdir()
        (maker / "_output").mkdir()
        v1, v2 = b"model-v1", b"model-v2"

        def manifest(champion: str, note: str) -> None:
            (maker / "chartbook.toml").write_text(tomli_w.dumps({
                "project": {"id": "acme/maker"},
                "models": {"m": {"path": "./_output/m.json", "docs": "d", "aliases": {"champion": champion}}},
            }))
            (maker / "NOTE.md").write_text(note)

        def version(data: bytes) -> str:
            return hashlib.sha256(data).hexdigest()[:12]

        (maker / "_output" / "m.json").write_bytes(v1)
        manifest(version(v1), "one")
        _commit(work)
        first = snapshot.make(maker).snapshot
        (maker / "_output" / "m.json").write_bytes(v2)
        manifest(version(v1), "two")
        _commit(work)
        second = snapshot.make(maker).snapshot
        (user / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/user"}, "dependencies": {"acme/maker": {"path": "../maker"}}})
        )
        _commit(work)
        assert lock.pin(user).problems == []
        locked = lock.read_lock(user)
        champion = locked.assets["acme/maker:model/m@champion"]["content_hash"]
        assert locked.snapshots() == {(second.commit, second.made_at)}
        assert champion == first.assets["model/m"]["content_hash"] != second.assets["model/m"]["content_hash"]
        assert locked.labelled() == {(second.commit, second.made_at, "model/m", champion)}
        manifest(version(v2), "three")
        _commit(work)
        third = snapshot.make(maker).snapshot
        return user, first, second, third, champion

    def test_gc_keeps_the_snapshot_the_label_was_resolved_from(self, pinned):
        from chartbook import lock

        user, first, second, third, champion = pinned
        store = default_store()
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        kept = {taken.made_at: why for taken, why in plan.snapshots_kept}
        assert kept[first.made_at] == "a lockfile pins a labelled version in it"
        assert kept[second.made_at] == "a lockfile pins it"
        assert kept[third.made_at] == "it is the newest of its pipeline"
        assert plan.snapshots_delete == [] and champion not in {h for h, _ in plan.delete}
        lock.run_gc(plan, store)
        assert snapshot.lineage_gaps(user, store) == []
        assert lock.verify(user, store).problems == []
        assert models.path("acme/maker:m@champion", project_dir=user).read_bytes() == b"model-v1"
        # A lockfile's pin is not a name: --aggressive keeps it too
        aggressive = lock.plan_gc(store, recent_seconds=0, keep_days=0, aggressive=True)
        assert first.made_at in {taken.made_at for taken, _ in aggressive.snapshots_kept}

    def test_the_note_of_the_lockfile_keeps_it_too(self, pinned):
        """The lockfile cannot be found (its drive unplugged), or is another machine's: its note records the version."""
        import shutil

        from chartbook import lock

        user, first, second, third, champion = pinned
        store = default_store()
        (note,) = store.roots()
        assert note.labelled == ((second.commit, second.made_at, "model/m", champion),)
        shutil.move(user, user.with_name("unplugged"))
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        kept = {taken.made_at: why for taken, why in plan.snapshots_kept}
        assert kept[first.made_at] == "a lockfile that cannot be found pins a labelled version in it"
        assert kept[second.made_at] == "a lockfile that cannot be found pins it"
        # Another machine's note of the same lockfile, which is never read here
        store.remove_root(user / lock.LOCK_FILE)
        store.add_root(user / lock.LOCK_FILE, note.hashes, note.snapshots, machine="machine-b", labelled=note.labelled)
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0, forget_missing=True)
        kept = {taken.made_at: why for taken, why in plan.snapshots_kept}
        assert kept[first.made_at] == "a lockfile not read here, another machine's, pins a labelled version in it"
        assert plan.snapshots_delete == []

    def test_a_pin_that_names_no_snapshot_still_keeps_one_holding_the_version(self, pinned):
        """With no moment to go by, the version is looked for among every pipeline's snapshots."""
        from chartbook import lock

        user, first, second, third, champion = pinned
        name_no_snapshot(user, "acme/maker")
        locked = lock.read_lock(user)
        assert locked.labelled() == {("", "", "model/m", champion)}
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        kept = {taken.made_at: why for taken, why in plan.snapshots_kept}
        assert kept[first.made_at] == "a lockfile pins a labelled version in it"
