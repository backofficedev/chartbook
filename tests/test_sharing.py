"""`chartbook store export` and `store import`: one pipeline's snapshots, sent to someone else and taken in."""

import shutil
import subprocess
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import lock, sharing, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore


def _git(directory, *arguments):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments], cwd=directory, check=True, capture_output=True)


def _commit(directory, message="work"):
    _git(directory, "add", "-A")
    _git(directory, "commit", "-qm", message)


@pytest.fixture
def two_snapshots(tmp_path, monkeypatch):
    """acme/rates with two snapshots in this machine's store: the second adds a year to a folder and changes a file."""
    monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path.resolve() / "mine"))
    rates = tmp_path.resolve() / "rates"
    (rates / "_data" / "years").mkdir(parents=True)
    (rates / "_data" / "years" / "2025.txt").write_bytes(b"2025")
    (rates / "_data" / "latest.txt").write_bytes(b"one")
    (rates / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {
        "years": {"path": "./_data/years", "docs": "d"}, "latest": {"path": "./_data/latest.txt", "docs": "d"},
    }}), encoding="utf-8")
    (rates / ".gitignore").write_text("_data/\n", encoding="utf-8")
    _git(rates, "init", "-q", "-b", "main")
    _commit(rates)
    first = snapshot.make(rates, made_at="2026-10-01T10:00:00.000000Z").snapshot
    (rates / "_data" / "years" / "2026.txt").write_bytes(b"2026")
    (rates / "_data" / "latest.txt").write_bytes(b"two")
    second = snapshot.make(rates, made_at="2026-10-02T10:00:00.000000Z").snapshot
    return FolderStore(tmp_path.resolve() / "mine"), first, second, rates


def _files(folder: Path) -> list:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


class TestExport:
    def test_every_snapshot_each_file_once(self, two_snapshots, tmp_path):
        store, first, second, rates = two_snapshots
        done = sharing.export(store, "acme/rates", tmp_path / "out")
        assert len(done.copied) == 2 and done.refused == []
        sent = tmp_path / "out" / "pipelines" / "acme+rates"
        assert _files(sent) == _files(store.pipeline_path("acme/rates"))  # laid out as the store keeps it

    def test_the_newest_alone_is_a_complete_snapshot(self, two_snapshots, tmp_path):
        store, first, second, rates = two_snapshots
        sharing.export(store, "acme/rates", tmp_path / "out", "latest")
        (folder,) = (tmp_path / "out" / "pipelines" / "acme+rates").iterdir()
        assert folder.name == "2026-10-02T100000Z_" + second.commit[:12]
        assert {"_data/years/2025.txt", "_data/years/2026.txt", "_data/latest.txt"} <= set(_files(folder))

    def test_one_asked_for(self, two_snapshots, tmp_path):
        store, first, second, rates = two_snapshots
        done = sharing.export(store, "acme/rates", tmp_path / "out", [f"{first.commit[:7]}@{first.made_at}"])
        assert done.copied == [("acme/rates", first.commit, first.made_at)]
        both = sharing.export(store, "acme/rates", tmp_path / "both", [first.commit[:7]])
        assert len(both.copied) == 2  # two snapshots of one commit: new data, no new code
        with pytest.raises(sharing.SharingError, match="no snapshot of acme/rates at 0000000"):
            sharing.export(store, "acme/rates", tmp_path / "out2", ["0000000"])

    def test_a_pipeline_the_store_has_none_of(self, two_snapshots, tmp_path):
        store, *_ = two_snapshots
        with pytest.raises(sharing.SharingError, match="no snapshot of acme/other"):
            sharing.export(store, "acme/other", tmp_path / "out")


class TestImport:
    def test_a_collaborator_takes_it_in_and_pins_it_by_its_id(self, two_snapshots, tmp_path, monkeypatch):
        store, first, second, rates = two_snapshots
        sharing.export(store, "acme/rates", tmp_path / "out")
        theirs = FolderStore(tmp_path.resolve() / "theirs")
        done = sharing.import_snapshots(theirs, tmp_path / "out")
        assert len(done.copied) == 2 and done.size_bytes > 0
        assert theirs.verify() == []
        found = snapshot.readable_snapshots(theirs)[0]
        assert [(t.commit, t.made_at) for t in found] == [(first.commit, first.made_at), (second.commit, second.made_at)]
        # Their own pipeline pins it by its ID, from their store, with no folder of it
        monkeypatch.setenv("CHARTBOOK_STORE", str(theirs.root))
        forecast = tmp_path.resolve() / "forecast"
        forecast.mkdir()
        (forecast / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "bob/forecast"}, "dependencies": {"acme/rates": {}}}), encoding="utf-8")
        report = lock.pin(forecast, theirs)
        assert report.problems == []
        (entry,) = lock.read_lock(forecast).dependencies
        assert entry["location"]["commit"] == second.commit and entry["pinned_from"] == "acme/rates"

    def test_what_the_store_has_is_not_copied_again(self, two_snapshots, tmp_path):
        store, first, second, rates = two_snapshots
        sharing.export(store, "acme/rates", tmp_path / "old", [f"{first.commit}@{first.made_at}"])
        theirs = FolderStore(tmp_path.resolve() / "theirs")
        sharing.import_snapshots(theirs, tmp_path / "old")
        sharing.export(store, "acme/rates", tmp_path / "new")
        done = sharing.import_snapshots(theirs, tmp_path / "new")
        assert done.there == [("acme/rates", first.commit, first.made_at)] and len(done.copied) == 1
        # Only what is new: the year, the changed file, and the snapshot's own index and record
        newer = theirs.pipeline_path("acme/rates") / ("2026-10-02T100000Z_" + second.commit[:12])
        assert _files(newer) == ["_chartbook/index.json", "_chartbook/snapshot.json", "_data/latest.txt", "_data/years/2026.txt"]
        assert theirs.verify() == []

    def test_a_folder_copied_by_hand_and_a_file_not_what_its_record_says(self, two_snapshots, tmp_path):
        store, first, second, rates = two_snapshots
        sent = tmp_path / "acme+rates"
        shutil.copytree(store.pipeline_path("acme/rates"), sent)
        changed = next(sent.rglob("2026.txt"))
        changed.chmod(0o644)
        changed.write_bytes(b"XXXX")  # the same size, other bytes
        theirs = FolderStore(tmp_path.resolve() / "theirs")
        done = sharing.import_snapshots(theirs, sent)
        assert done.copied == [("acme/rates", first.commit, first.made_at)]
        ((what, why),) = done.refused
        assert second.commit[:7] in what and "2026.txt is not what its record says" in why
        assert theirs.verify() == [] and len(snapshot.readable_snapshots(theirs)[0]) == 1

    def test_not_from_inside_the_store(self, two_snapshots):
        store, *_ = two_snapshots
        with pytest.raises(sharing.SharingError, match="in the store it would be imported into"):
            sharing.import_snapshots(store, store.pipeline_path("acme/rates"))


class TestTheCommands:
    def test_export_then_import(self, two_snapshots, tmp_path, monkeypatch):
        store, first, second, rates = two_snapshots
        said = CliRunner().invoke(main, ["store", "export", "acme/rates", "--latest", "--to", str(tmp_path / "out")])
        assert said.exit_code == 0, said.output
        assert "Exported 1 snapshot(s)" in said.output and "store import" in said.output
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path.resolve() / "theirs"))
        said = CliRunner().invoke(main, ["store", "import", str(tmp_path / "out")])
        assert said.exit_code == 0, said.output
        assert "Imported 1 snapshot(s)" in said.output
        again = CliRunner().invoke(main, ["store", "import", str(tmp_path / "out")])
        assert again.exit_code == 0 and "1 snapshot(s) were there already" in again.output
