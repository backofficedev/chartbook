"""`chartbook lineage`: every snapshot upstream of a pipeline, walked through the pins, and checked."""

import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import lineage, lock, snapshot
from chartbook.cli import main
from chartbook.store import default_store
from tests.fixtures import name_no_snapshot
from tests.test_model_versions import _commit, _git


def _pipeline(folder: Path, pipeline_id: str, name: str, dependencies: dict) -> None:
    (folder / "_data").mkdir(parents=True)
    manifest = {
        "project": {"id": pipeline_id},
        "dataframes": {name: {"path": f"./_data/{name}.parquet", "docs": "A file."}},
    }
    if dependencies:
        manifest["dependencies"] = {key: {"path": f"../{path}"} for key, path in dependencies.items()}
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    pl.DataFrame({"d": ["2024-01-01"], name: [1.0]}).write_parquet(folder / "_data" / f"{name}.parquet")


@pytest.fixture
def chain(tmp_path):
    """``fred`` <- ``rates`` <- ``forecast``: fred and rates snapshotted, each pinned by the next."""
    work = tmp_path.resolve()
    fred, rates, forecast = work / "fred", work / "rates", work / "forecast"
    _pipeline(fred, "acme/fred", "series", {})
    _pipeline(rates, "acme/rates", "treasury", {"fred": "fred"})
    _pipeline(forecast, "acme/forecast", "outlook", {"rates": "rates"})
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(work)
    snapshot.make(fred)
    lock.pin(rates)
    snapshot.make(rates)
    lock.pin(forecast)
    return fred, rates, forecast


def _snapshot_of(pipeline: str):
    found, _ = snapshot.readable_snapshots(default_store())
    (taken,) = [t for t in found if t.pipeline == pipeline]
    return taken


def _rewrite(taken, change) -> None:
    os.chmod(taken.path, stat.S_IRUSR | stat.S_IWUSR)
    document = json.loads(taken.path.read_text())
    change(document)
    taken.path.write_text(json.dumps(document))


class TestTheWalk:
    def test_a_whole_chain_has_no_gaps(self, chain):
        fred, rates, forecast = chain
        found = lineage.walk(forecast)
        assert found.gaps() == [] and found.snapshots == 2
        (rates_node,) = found.root.children
        assert (rates_node.label, rates_node.pipeline, rates_node.kind) == ("rates", "acme/rates", "snapshot")
        (fred_node,) = rates_node.children
        assert (fred_node.label, fred_node.pipeline) == ("fred", "acme/fred")

    def test_a_snapshot_made_before_pins_were_checked(self, chain):
        fred, rates, forecast = chain
        _rewrite(_snapshot_of("acme/rates"), lambda d: d.pop("inputs", None))
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].pipeline == "acme/rates" and "declares the dependency 'fred'" in gap[1]

    def test_a_recorded_hash_that_does_not_match(self, chain):
        fred, rates, forecast = chain

        def tamper(document):
            document["inputs"][0]["pinned_hash"] = "sha256:" + "0" * 64

        _rewrite(_snapshot_of("acme/rates"), tamper)
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].label == "fred" and gap[0].kind == "mismatch" and "that snapshot gives another" in gap[1]

    def test_an_upstream_snapshot_gone(self, chain):
        fred, rates, forecast = chain
        taken = _snapshot_of("acme/fred")
        os.chmod(taken.path, stat.S_IRUSR | stat.S_IWUSR)
        taken.path.unlink()
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].label == "fred" and "is not in the store" in gap[1]

    def test_an_object_gone_and_one_changed(self, chain):
        fred, rates, forecast = chain
        store = default_store()
        series = _snapshot_of("acme/fred").assets["series"]["content_hash"]
        held = Path(store.get(series))
        for file in held.rglob("*"):
            os.chmod(file, stat.S_IRUSR | stat.S_IWUSR)
            file.write_bytes(b"changed")
        assert lineage.walk(forecast).gaps() == []  # present, and not read again
        (gap,) = lineage.walk(forecast, rehash=True).gaps()
        assert "is not what its name says" in gap[1]
        assert store.delete(series)
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].pipeline == "acme/fred" and "which the store does not have" in gap[1]

    def test_a_snapshot_met_twice_is_walked_once(self, chain):
        fred, rates, forecast = chain
        manifest = (forecast / "chartbook.toml").read_text()
        (forecast / "chartbook.toml").write_text(manifest + '\n[dependencies.fred]\npath = "../fred"\n')
        _commit(forecast.parent)
        lock.pin(forecast)
        found = lineage.walk(forecast)
        assert found.gaps() == [] and found.snapshots == 2
        seen = [n for n in found.root.children if n.label == "fred"] + [
            n for c in found.root.children for n in c.children if n.label == "fred"
        ]
        assert sorted(n.seen for n in seen) == [False, True]


class TestDeepSnapshots:
    def test_deep_refuses_what_upstream_lacks_and_shallow_does_not(self, chain):
        fred, rates, forecast = chain
        _rewrite(_snapshot_of("acme/rates"), lambda d: d.pop("inputs", None))
        with pytest.raises(snapshot.SnapshotError, match="with --deep: a snapshot upstream has a gap"):
            snapshot.make(forecast, deep=True)
        assert snapshot.make(forecast).snapshot.pipeline == "acme/forecast"


class TestTheCommand:
    def test_it_draws_the_graph(self, chain, monkeypatch):
        fred, rates, forecast = chain
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["lineage"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == "acme/forecast (this folder)"
        assert lines[1].startswith("└── rates: acme/rates ") and lines[2].startswith("    └── fred: acme/fred ")
        assert lines[-1] == "2 snapshot(s) upstream; no gaps."

    def test_check_fails_on_a_gap_and_json_says_it(self, chain, monkeypatch):
        fred, rates, forecast = chain
        _rewrite(_snapshot_of("acme/rates"), lambda d: d.pop("inputs", None))
        monkeypatch.chdir(forecast)
        assert CliRunner().invoke(main, ["lineage"]).exit_code == 0
        checked = CliRunner().invoke(main, ["lineage", "--check"])
        assert checked.exit_code == 1 and "gap: its manifest declares the dependency 'fred'" in checked.output
        shown = json.loads(CliRunner().invoke(main, ["lineage", "--json"]).output)
        assert shown["gaps"] == 1 and shown["root"]["children"][0]["gaps"]

    def test_a_pin_that_names_no_snapshot(self, chain, monkeypatch):
        """In this pipeline's lockfile, or in a snapshot's record of its inputs: one changed by hand."""
        fred, rates, forecast = chain
        name_no_snapshot(forecast, "rates")
        monkeypatch.chdir(forecast)
        shown = json.loads(CliRunner().invoke(main, ["lineage", "--json"]).output)
        (node,) = shown["root"]["children"]
        assert (node["label"], node["kind"]) == ("rates", "no_snapshot")
        assert "└── rates: its pin names no snapshot" in CliRunner().invoke(main, ["lineage"]).output

        lock.update(forecast)  # which names its snapshot again
        _rewrite(
            _snapshot_of("acme/rates"),
            lambda d: [d["inputs"][0]["location"].pop("commit"), d["inputs"][0].pop("snapshot")],
        )
        shown = json.loads(CliRunner().invoke(main, ["lineage", "--json"]).output)
        (upstream,) = shown["root"]["children"][0]["children"]
        assert (upstream["label"], upstream["kind"]) == ("fred", "no_snapshot")
        assert upstream["gaps"] == ["its pin named no snapshot, so nothing says which commit its bytes came from"]

    def test_rehash_says_how_many(self, chain, monkeypatch):
        fred, rates, forecast = chain
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["lineage", "--rehash"])
        assert result.exit_code == 0 and "object(s) hashed again; no gaps." in result.output


def _model_pipeline(folder: Path, aliases=None) -> None:
    model = {"path": "./_models/m.json", "metrics_path": "./_output/metrics.json", "docs": "A model."}
    if aliases:
        model["aliases"] = aliases
    (folder / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/model"}, "models": {"m": model}}))


def _train(folder: Path, weights: bytes) -> None:
    (folder / "_models").mkdir(exist_ok=True)
    (folder / "_models" / "m.json").write_bytes(weights)
    (folder / "_output").mkdir(exist_ok=True)
    (folder / "_output" / "metrics.json").write_text(json.dumps({"rmse": 0.3}))


@pytest.fixture
def labelled(tmp_path):
    """``model`` <- ``serve`` (pins model's `champion` label) <- ``top``."""
    work = tmp_path.resolve()
    model, serve, top = work / "model", work / "serve", work / "top"
    model.mkdir()
    _model_pipeline(model)
    _train(model, b"w1")
    _pipeline(serve, "acme/serve", "served", {"model": "model"})
    _pipeline(top, "acme/top", "topdf", {"serve": "serve"})
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n_models/\n_output/\n")
    _commit(work)
    first = snapshot.make(model).new_versions[0][1]
    _train(model, b"w2")
    _model_pipeline(model, {"champion": first})
    _commit(work)
    snapshot.make(model)
    lock.pin(serve)
    snapshot.make(serve)
    lock.pin(top)
    return work, model, serve, top, first


class TestWhatTheReviewFound:
    def test_gc_keeps_what_a_kept_snapshot_was_made_from(self, chain):
        fred, rates, forecast = chain
        (fred / "_data" / "series.parquet").unlink()
        pl.DataFrame({"d": ["2024-02-01"], "series": [2.0]}).write_parquet(fred / "_data" / "series.parquet")
        snapshot.make(fred)                   # f2
        lock.update(rates)
        snapshot.make(rates)                  # r2, from f2; forecast stays on r1, from f1
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0, keep_lineage=True)
        kept = {(t.pipeline, why) for t, why in plan.snapshots_kept}
        assert ("acme/fred", "a snapshot that is kept was made from it") in kept
        lock.run_gc(plan, default_store())
        assert lineage.walk(forecast).gaps() == []
        assert snapshot.make(forecast, deep=True).snapshot

    def test_a_moved_label_and_gc_leave_no_false_gap(self, labelled):
        work, model, serve, top, first = labelled
        assert lineage.walk(top).gaps() == []
        found, _ = snapshot.readable_snapshots(default_store())
        newest = max((t for t in found if t.pipeline == "acme/model"), key=lambda t: t.made_at)
        second = newest.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        _model_pipeline(model, {"champion": second})
        _commit(work)
        _train(model, b"w3")
        snapshot.make(model)
        lock.run_gc(lock.plan_gc(default_store(), recent_seconds=0, keep_days=0, keep_lineage=True), default_store())
        assert lineage.walk(top).gaps() == []

    def test_a_record_that_cannot_be_read_elsewhere_does_not_stop_the_walk(self, labelled):
        work, model, serve, top, first = labelled
        record = _snapshot_of("acme/serve").path
        stranger = record.with_name("20991231T000000.000000Z.json")
        document = json.loads(record.read_text())
        document["schema"] = "chartbook/snapshot/v99"
        stranger.write_text(json.dumps(document))
        assert lineage.walk(top).gaps() == []

    def test_rehash_reads_the_versions_labels_pinned(self, labelled):
        work, model, serve, top, first = labelled
        store = default_store()
        (version,) = [h for h in store.hashes() if h.split(":", 1)[1].startswith(first)]
        for file in Path(store.get(version)).rglob("*"):
            os.chmod(file, stat.S_IRUSR | stat.S_IWUSR)
            file.write_bytes(b"changed")
        assert any("is not what its name says" in gap for _, gap in lineage.walk(top, rehash=True).gaps())

    @pytest.mark.parametrize(
        "change",
        [
            lambda d: d["inputs"][0].update(location="here"),
            lambda d: d["inputs"][0]["location"].update(commit=5),
            lambda d: d["inputs"][0].update(pinned_hash={"a": 1}),
            lambda d: d["inputs"][0].update(id="a:b"),
            lambda d: next(r for r in d["records"] if r.get("content_hash")).update(content_hash="abc"),
            lambda d: d["inputs"][0].update(snapshot=7),
        ],
        ids=["location-text", "commit-number", "hash-table", "id-with-colon", "short-hash", "time-number"],
    )
    def test_a_record_not_as_written_is_a_gap_not_a_crash(self, chain, monkeypatch, change):
        fred, rates, forecast = chain
        _rewrite(_snapshot_of("acme/rates"), change)
        found = lineage.walk(forecast)
        assert found.gaps()
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["lineage", "--check"])
        assert result.exit_code == 1 and "gap:" in result.output, result.output


class TestWhatTheThirdReviewFound:
    def test_gc_keeps_a_label_version_a_kept_snapshot_was_made_from(self, labelled):
        work, model, serve, top, first = labelled
        found, _ = snapshot.readable_snapshots(default_store())
        newest = max((t for t in found if t.pipeline == "acme/model"), key=lambda t: t.made_at)
        second = newest.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        _model_pipeline(model, {"champion": second})
        _commit(work)
        _train(model, b"w3")
        snapshot.make(model)
        lock.update(serve)                    # serve's lockfile moves on; top still pins serve's old snapshot
        lock.run_gc(lock.plan_gc(default_store(), recent_seconds=0, keep_days=0, keep_lineage=True), default_store())
        assert lineage.walk(top).gaps() == []

    def test_a_second_object_with_the_same_start_does_not_make_a_gap(self, labelled):
        work, model, serve, top, first = labelled
        store = default_store()
        (version,) = [h for h in store.hashes() if h.split(":", 1)[1].startswith(first)]
        # The version's snapshot is let go of by hand, so the walk looks among the objects
        found, _ = snapshot.readable_snapshots(store)
        (maker,) = [t for t in found if t.pipeline == "acme/model" and t.assets["model/m"]["content_hash"] == version]
        os.chmod(maker.path, stat.S_IRUSR | stat.S_IWUSR)
        maker.path.unlink()
        twin = Path(store.get(version)).parent / (version.split(":", 1)[1][2:12] + "f" * 52)
        import shutil

        shutil.copytree(store.get(version), twin)
        assert len([h for h in store.hashes() if h.split(":", 1)[1].startswith(first)]) == 2
        assert lineage.walk(top).gaps() == []


class TestWhatTheMaintainerAsked:
    """gc favors letting go; a snapshot says how strictly its lineage was checked, for audit."""

    def test_by_default_gc_lets_old_lineage_go_and_the_walk_says_why(self, chain):
        fred, rates, forecast = chain
        (fred / "_data" / "series.parquet").unlink()
        pl.DataFrame({"d": ["2024-02-01"], "series": [2.0]}).write_parquet(fred / "_data" / "series.parquet")
        snapshot.make(fred)
        lock.update(rates)
        snapshot.make(rates)
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        assert any(t.pipeline == "acme/fred" for t, _ in plan.snapshots_delete)
        lock.run_gc(plan, default_store())
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].label == "fred" and "--keep-lineage" in gap[1]
        # A plain snapshot needs only its own pins, which are whole
        assert snapshot.make(forecast).snapshot

    def test_a_snapshot_records_how_its_lineage_was_checked(self, chain):
        fred, rates, forecast = chain
        assert _snapshot_of("acme/rates").built_with["lineage"] == "pins"
        taken = snapshot.make(forecast, deep=True).snapshot
        assert taken.built_with["lineage"] == "deep"
        assert snapshot.read(taken.path).built_with["lineage"] == "deep"
        (rates_node,) = lineage.walk(forecast).root.children
        assert rates_node.checked == "pins" and rates_node.to_dict()["checked"] == "pins"

    def test_the_tree_says_it(self, chain, monkeypatch):
        fred, rates, forecast = chain
        monkeypatch.chdir(forecast)
        lines = CliRunner().invoke(main, ["lineage"]).output.splitlines()
        assert lines[1].endswith(", pins checked")
        _rewrite(_snapshot_of("acme/rates"), lambda d: d["built_with"].pop("lineage"))
        lines = CliRunner().invoke(main, ["lineage"]).output.splitlines()
        assert lines[1].endswith(", made before pins were checked")

    def test_the_command_takes_keep_lineage(self, chain, monkeypatch):
        fred, rates, forecast = chain
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run", "--keep-lineage"])
        assert result.exit_code == 0, result.output


class TestNames:
    def test_the_tree_and_the_versions_page_say_a_versions_tags(self, chain, monkeypatch):
        fred, rates, forecast = chain
        _git(forecast.parent, "tag", "paper-2026")
        # Tagged after it was built: the same bytes, made again to record the tag
        report = snapshot.make(fred)
        assert report.made and report.snapshot.tags == ["paper-2026"]
        assert not snapshot.make(fred).made  # and only once
        lock.update(rates)
        monkeypatch.chdir(rates)
        output = CliRunner().invoke(main, ["lineage"]).output
        assert "└── fred: acme/fred " in output and ", tagged paper-2026, made " in output, output
        shown = json.loads(CliRunner().invoke(main, ["lineage", "--json"]).output)
        assert shown["root"]["children"][0]["tags"] == ["paper-2026"]
        # The catalog's index lists the snapshot's tags, for its Versions page
        from chartbook.index import _add_snapshots

        records = [{"kind": "Pipeline", "id": "acme/fred", "location": {"kind": "store"}}]
        _add_snapshots(records)
        assert any(entry.get("tags") == ["paper-2026"] for entry in records[0]["snapshots"])
