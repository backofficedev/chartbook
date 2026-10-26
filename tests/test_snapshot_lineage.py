"""A snapshot carries its lineage: it is made only when the pipeline's pins account for every
dependency (docs_src/design/reading-other-pipelines.md, decision 6)."""

import shutil
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import lock, snapshot
from chartbook.cli import main
from chartbook.store import default_store
from tests.fixtures import name_no_snapshot
from tests.test_model_versions import _commit, _git


@pytest.fixture
def two(tmp_path):
    """``rates``, built and snapshotted, and ``forecast``, which depends on it and has built its own data."""
    work = tmp_path.resolve()
    rates, forecast = work / "rates", work / "forecast"
    for directory in (rates, forecast):
        (directory / "_data").mkdir(parents=True)
    (rates / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/rates"},
                "dataframes": {
                    "treasury": {"path": "./_data/treasury.parquet", "docs": "A file."},
                    "bills": {"path": "./_data/bills.parquet", "docs": "Another."},
                    "later": {"path": "./_data/later.parquet", "docs": "Not built yet."},
                },
            }
        ), encoding="utf-8"
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(rates / "_data" / "treasury.parquet")
    pl.DataFrame({"d": ["2024-01-01"], "b": [3.9]}).write_parquet(rates / "_data" / "bills.parquet")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/forecast"},
                "dependencies": {"rates": {"path": "../rates"}},
                "dataframes": {"outlook": {"path": "./_data/outlook.parquet", "docs": "Its output."}},
            }
        ), encoding="utf-8"
    )
    pl.DataFrame({"d": ["2024-02-01"], "f": [4.2]}).write_parquet(forecast / "_data" / "outlook.parquet")
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n", encoding="utf-8")
    _commit(work)
    snapshot.make(rates)
    return rates, forecast


class TestASnapshotCarriesItsLineage:
    def test_no_lockfile(self, two):
        rates, forecast = two
        with pytest.raises(snapshot.SnapshotError, match="cannot have a snapshot: its pins do not account") as raised:
            snapshot.make(forecast)
        assert "does not exist" in str(raised.value) and "chartbook pin" in str(raised.value)

    def test_a_dependency_the_lockfile_does_not_list(self, two):
        rates, forecast = two
        lock.pin(forecast)
        other = forecast.parent / "other"
        shutil.copytree(rates, other)
        manifest = (forecast / "chartbook.toml").read_text(encoding="utf-8")
        (forecast / "chartbook.toml").write_text(manifest.replace('[dependencies.rates]\npath = "../rates"', '[dependencies.rates]\npath = "../rates"\n\n[dependencies.other]\npath = "../other"'), encoding="utf-8")
        _commit(forecast.parent)
        with pytest.raises(snapshot.SnapshotError, match="other: is in \\[dependencies\\] and not in the lockfile"):
            snapshot.make(forecast)

    def test_a_pin_that_names_no_snapshot(self, two):
        rates, forecast = two
        lock.pin(forecast)
        name_no_snapshot(forecast, "rates")
        with pytest.raises(snapshot.SnapshotError, match="rates: its pin names no snapshot, so nothing says which commit"):
            snapshot.make(forecast)

    def test_a_pin_the_store_does_not_have(self, two):
        rates, forecast = two
        lock.pin(forecast)
        pinned = next(
            record["content_hash"] for record in lock.read_lock(forecast / lock.LOCK_FILE).assets.values()
            if record.get("content_hash")
        )
        assert default_store().delete(pinned)
        with pytest.raises(snapshot.SnapshotError, match="the store at .* does not have it"):
            snapshot.make(forecast)

    def test_full_lineage_is_a_snapshot_and_records_it(self, two):
        rates, forecast = two
        lock.pin(forecast)
        taken = snapshot.make(forecast).snapshot
        (entry,) = taken.inputs
        assert entry["id"] == "rates" and entry["location"]["commit"] and entry.get("pinned_hash")

    def test_an_upstream_asset_not_built_does_not_stop_it(self, two):
        rates, forecast = two
        lock.pin(forecast)
        records = lock.read_lock(forecast / lock.LOCK_FILE).assets
        assert any(record_id.endswith(":later") and not record.get("content_hash") for record_id, record in records.items())
        assert snapshot.make(forecast).snapshot.assets["outlook"]["content_hash"]

    def test_a_pipeline_with_no_dependencies_is_as_before(self, two):
        rates, forecast = two
        assert snapshot.make(rates).snapshot.pipeline == "acme/rates"

    def test_the_command_says_what_to_run(self, two, monkeypatch):
        rates, forecast = two
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 1
        assert "its pins do not account for every dependency" in result.output
        assert "Run `chartbook pin`" in result.output


def _add_dependency(forecast: Path, key: str, folder: Path) -> None:
    import tomli

    manifest = tomli.loads((forecast / "chartbook.toml").read_text(encoding="utf-8"))
    manifest["dependencies"][key] = {"path": f"../{folder.name}"}
    (forecast / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")


class TestWhatTheReviewFound:
    def test_run_snapshot_refuses_before_it_builds(self, two):
        import sys

        from chartbook import run

        rates, forecast = two
        import tomli

        manifest = tomli.loads((forecast / "chartbook.toml").read_text(encoding="utf-8"))
        marker = forecast / "_data" / "built"
        manifest["scripts"] = {"build": f"{sys.executable} -c \"open('_data/built', 'w').close()\""}
        (forecast / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
        _commit(forecast.parent)
        lock.pin(forecast)
        name_no_snapshot(forecast, "rates")  # kept by the pin before the build
        report = run.run(forecast, echo=lambda *a, **k: None, snapshot=True)
        assert report.failed is not None and "it was not built" in report.reason
        assert "its pin names no snapshot" in report.reason
        assert not marker.exists()

    def test_a_dependency_with_no_snapshot_yet_is_nothing_read(self, two):
        rates, forecast = two
        fresh = forecast.parent / "fresh"
        shutil.copytree(rates, fresh)
        (fresh / "chartbook.toml").write_text((fresh / "chartbook.toml").read_text(encoding="utf-8").replace("acme/rates", "acme/fresh"), encoding="utf-8")
        _add_dependency(forecast, "fresh", fresh)
        _commit(forecast.parent)
        lock.pin(forecast)
        assert not [r for r in lock.read_lock(forecast / lock.LOCK_FILE).assets_of("fresh").values() if r.get("content_hash")]
        assert snapshot.make(forecast).snapshot.assets["outlook"]["content_hash"]

    def test_a_dependency_that_declares_nothing(self, two):
        rates, forecast = two
        empty = forecast.parent / "empty"
        empty.mkdir()
        (empty / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/empty"}}), encoding="utf-8")
        _add_dependency(forecast, "empty", empty)
        _commit(forecast.parent)
        lock.pin(forecast)
        assert snapshot.make(forecast).snapshot

    def test_a_hash_changed_by_hand(self, two):
        import json

        rates, forecast = two
        lock.pin(forecast)
        path = forecast / lock.LOCK_FILE
        document = json.loads(path.read_text(encoding="utf-8"))
        other = default_store().put(forecast / "_data" / "outlook.parquet").content_hash
        for record in document["records"]:
            if record.get("content_hash") and record.get("id", "").endswith(":treasury"):
                record["content_hash"] = other
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(snapshot.SnapshotError, match="which its snapshot at .* does not hold") as raised:
            snapshot.make(forecast)
        assert "commit chartbook.lock" in str(raised.value)

    def test_a_snapshot_the_store_does_not_have(self, two):
        import json

        rates, forecast = two
        lock.pin(forecast)
        path = forecast / lock.LOCK_FILE
        document = json.loads(path.read_text(encoding="utf-8"))
        for record in document["records"]:
            for dependency in record.get("dependencies") or []:
                dependency["snapshot"] = "2001-01-01T00:00:00Z"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(snapshot.SnapshotError, match="has no such snapshot"):
            snapshot.make(forecast)


def _lockfile(forecast: Path) -> tuple[Path, dict]:
    import json

    path = forecast / lock.LOCK_FILE
    return path, json.loads(path.read_text(encoding="utf-8"))


def _record(document: dict, ending: str) -> dict:
    return next(r for r in document["records"] if r.get("id", "").endswith(ending))


class TestWhatTheSecondReviewFound:
    def test_two_hashes_swapped(self, two):
        import json

        rates, forecast = two
        lock.pin(forecast)
        path, document = _lockfile(forecast)
        treasury, bills = _record(document, ":treasury"), _record(document, ":bills")
        treasury["content_hash"], bills["content_hash"] = bills["content_hash"], treasury["content_hash"]
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(snapshot.SnapshotError, match="does not hold as treasury"):
            snapshot.make(forecast)

    def test_a_record_dressed_as_a_label(self, two):
        import json

        rates, forecast = two
        lock.pin(forecast)
        path, document = _lockfile(forecast)
        record = _record(document, ":treasury")
        record["content_hash"] = default_store().put(forecast / "_data" / "outlook.parquet").content_hash
        record["ref"]["rev"] = "x"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(snapshot.SnapshotError, match="a version of treasury that no snapshot of it in the store holds"):
            snapshot.make(forecast)

    def test_two_pipelines_snapshotted_in_the_same_instant(self, two):
        rates, forecast = two
        twin = forecast.parent / "aaa_twin"
        shutil.copytree(rates, twin)
        (twin / "chartbook.toml").write_text((twin / "chartbook.toml").read_text(encoding="utf-8").replace("acme/rates", "acme/twin"), encoding="utf-8")
        (twin / "_data" / "treasury.parquet").write_bytes(b"other bytes")
        _commit(forecast.parent)
        moment = "2030-01-01T00:00:00.000000Z"
        snapshot.make(twin, made_at=moment)
        snapshot.make(rates, made_at=moment)
        lock.pin(forecast)
        assert snapshot.lineage_gaps(forecast) == []

    def test_a_record_that_cannot_be_read_says_why(self, two):
        import json
        import os
        import stat

        rates, forecast = two
        lock.pin(forecast)
        found, _ = snapshot.readable_snapshots(default_store())
        (held,) = [t for t in found if t.pipeline == "acme/rates"]
        os.chmod(held.path, stat.S_IRUSR | stat.S_IWUSR)
        document = json.loads(held.path.read_text(encoding="utf-8"))
        document["schema"] = "chartbook/snapshot/v99"
        held.path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(snapshot.SnapshotError, match="cannot be read"):
            snapshot.make(forecast)


class TestASnapshotIsNotGivenBackWithOtherPins:
    """`chartbook snapshot` gives back the newest snapshot at a commit when nothing changed; what the pipeline is pinned to is part of that."""

    def _moved(self, two):
        """forecast's snapshot pins rates' first snapshot; rates makes another at the same commit, and forecast updates to it."""
        rates, forecast = two
        lock.pin(forecast)
        first = snapshot.make(forecast, built_by_run=True).snapshot
        pl.DataFrame({"d": ["2024-01-01"], "r": [9.9]}).write_parquet(rates / "_data" / "treasury.parquet")
        assert snapshot.make(rates).made  # same commit, new bytes
        assert {event.status for event in lock.update(forecast).events} >= {"moved"}
        return first

    def test_a_new_snapshot_records_the_new_pins(self, two):
        rates, forecast = two
        first = self._moved(two)
        report = snapshot.make(forecast)
        assert report.made and report.snapshot.commit == first.commit
        assert report.snapshot.content() == first.content()  # forecast's own bytes are the same
        (was,), (now,) = first.inputs, report.snapshot.inputs
        assert was["snapshot"] != now["snapshot"] and now == lock.read_lock(forecast).dependencies[0]
        # The bytes were built from the old pins: the new one does not say a run built them from these
        assert not report.snapshot.built_by_run

    def test_with_the_same_pins_it_is_given_back(self, two):
        rates, forecast = two
        self._moved(two)
        made = snapshot.make(forecast).snapshot
        again = snapshot.make(forecast)
        assert not again.made and again.snapshot.path == made.path


    def test_a_run_that_builds_with_the_moved_pins_says_so(self, two):
        rates, forecast = two
        self._moved(two)
        assert snapshot.make(forecast, built_by_run=True).snapshot.built_by_run

    def test_a_clone_with_other_pins_does_not_hide_this_checkouts_own(self, two, tmp_path):
        """A clone shares the store and pins rates' newer snapshot; the main checkout, which pins the older one, makes its own again.

        The clone's snapshot is the newest at the commit, and what a pin of the
        main checkout's folder takes: given back the older one, the main
        checkout would say nothing changed while a pin read the clone's pins.
        """
        import shutil

        rates, forecast = two
        work = rates.parent
        from chartbook.identity import clear_git_remote_cache

        _git(work, "remote", "add", "origin", "https://example.org/acme/work.git")
        clear_git_remote_cache()
        lock.pin(forecast)
        mine = snapshot.make(forecast).snapshot
        # Its address and its first commit: more of its repository than a clone with a path remote says
        assert {kind for kind, _ in snapshot.identity_keys(mine)} == {"address", "first"}
        (was,) = mine.inputs
        pl.DataFrame({"d": ["2024-01-01"], "r": [9.9]}).write_parquet(rates / "_data" / "treasury.parquet")
        assert snapshot.make(rates).made  # rates' newer snapshot, at the same commit
        clone = tmp_path / "clone"
        _git(tmp_path, "clone", "--quiet", str(work), str(clone))
        shutil.copytree(forecast / "_data", clone / "forecast" / "_data")
        lock.pin(clone / "forecast")  # its own lockfile: the newer snapshot
        theirs = snapshot.make(clone / "forecast")
        assert theirs.made and theirs.snapshot.inputs[0]["snapshot"] != was["snapshot"]
        again = snapshot.make(forecast)
        assert again.made and again.snapshot.inputs == [was]
        newest = snapshot.find(default_store(), again.snapshot.commit, again.snapshot.subdirectory)[0]
        assert newest.path == again.snapshot.path
        assert not snapshot.make(forecast).made  # and then it is stable
