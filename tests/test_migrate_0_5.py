"""`chartbook store migrate` moves a folder store of ChartBook 0.5 to this version's layout.

``docs_src/design/snapshots-and-increments.md``, "Moving a store to this
layout": per pipeline, the newest snapshot its owner made becomes complete
under ``snapshots/``, every other one its owner made an increment on it
under ``increments/``, and every one a pin made complete too. Files change
folder by rename and are not read; only the copies the result needs are.
"""

import hashlib
import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lock, migrate_0_5, snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.gitcache import GitCache
from chartbook.store import FolderStore, StoreError
from tests.fixtures import _git
from tests.store_of_0_5 import cleared_as_0_5, laid_out_as_0_5

TIMES = ("2025-10-01T09:15:00.000000Z", "2025-11-01T09:15:00.000000Z", "2025-12-01T09:15:00.000000Z", "2026-01-01T09:15:00.000000Z")


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _commit(folder: Path, message: str = "Work") -> None:
    if not (folder / ".git").exists():
        _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "--allow-empty", "-m", message)


def _pipeline(folder: Path, pipeline: str, tracked: bool = False) -> Path:
    """A pipeline with a table, a dataset in parts and a chart; its data in git only where a `git` dependency is to pin it."""
    (folder / "_data" / "parts").mkdir(parents=True)
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": pipeline},
            "dataframes": {
                "treasury": {"path": "./_data/treasury.parquet", "docs": "d"},
                "parts": {"path": "./_data/parts/", "docs": "d"},
            },
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / "README.md").write_text(f"# {pipeline}\n", encoding="utf-8", newline="\n")
    if not tracked:
        (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    pl.DataFrame({"day": [0, 1, 2], "of": [pipeline] * 3}).write_parquet(folder / "_data" / "treasury.parquet")
    pl.DataFrame({"year": [2020]}).write_parquet(folder / "_data" / "parts" / "2020.parquet")
    (folder / "_output" / "curve.html").write_text("<p>one</p>\n", encoding="utf-8", newline="\n")
    _commit(folder)
    return folder


def _reader(folder: Path, reads: dict) -> Path:
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": f"acme/{folder.name}"}, "dependencies": reads}), encoding="utf-8", newline="\n"
    )
    return folder


@pytest.fixture
def of_0_5(work, store):
    """A store of 0.5 with every shape a real one has (the maintainer's own was counted, 2026-11-20).

    - ``acme/rates``: four snapshots its owner made, each with a part more
      and another chart, the oldest then cleared by the ``store gc`` of 0.5:
      a folder with ``CLEARED.txt`` and no record, which still holds the
      table and a part that the later records name;
    - ``acme/once``: one snapshot;
    - ``acme/upstream``: one its owner made and one a pin made from its
      repository, in the same tree;
    - ``acme/pinned``: only a snapshot a pin made;
    - readers that pin each, so ``roots/`` has their notes; ``origins/``;
      an empty ``tmp/``; the mark of the move from 0.2; a ``README.txt`` in
      each pipeline's folder; and a ``.DS_Store`` at the top, in
      ``pipelines/``, in a pipeline's folder, in a snapshot's folder and in
      a snapshot's ``_chartbook/``.

    :returns: The store's folder, and the readers by what they read.
    """
    rates = _pipeline(work / "rates", "acme/rates")
    readers = {}
    for number, made_at in enumerate(TIMES):
        pl.DataFrame({"year": [2020 + number]}).write_parquet(rates / "_data" / "parts" / f"{2020 + number}.parquet")
        (rates / "_output" / "curve.html").write_text(f"<p>{number}</p>\n", encoding="utf-8", newline="\n")
        snapshot.make(rates, store=FolderStore(store.root), made_at=made_at)
        if number in (1, 3):
            readers[f"rates{number}"] = _reader(work / f"reads-rates-{number}", {"acme/rates": {"path": "../rates"}})
            assert lock.pin(readers[f"rates{number}"], FolderStore(store.root)).problems == []
    snapshot.make(_pipeline(work / "once", "acme/once"), store=FolderStore(store.root), made_at=TIMES[0])
    cache = GitCache(work / "gitcache")
    for name in ("upstream", "pinned"):
        _pipeline(work / name, f"acme/{name}", tracked=True)
        readers[name] = _reader(work / f"reads-{name}", {f"acme/{name}": {"git": f"../{name}"}})
        assert lock.pin(readers[name], FolderStore(store.root), git_cache=cache).problems == []
    (work / "upstream" / "README.md").write_text("# acme/upstream, on\n", encoding="utf-8", newline="\n")
    _commit(work / "upstream")
    snapshot.make(work / "upstream", store=FolderStore(store.root), made_at=TIMES[2])
    old = laid_out_as_0_5(store.root)
    oldest = min((taken for taken in snapshot.all_snapshots(old) if taken.pipeline == "acme/rates"), key=lambda taken: taken.made_at)
    cleared_as_0_5(oldest.path)
    root = store.root
    (root / "tmp").mkdir(exist_ok=True)
    (root / "snapshots" / ("0" * 40)).mkdir(parents=True)
    (root / "snapshots" / ("0" * 40) / "MOVED.txt").write_text("moved\n", encoding="utf-8", newline="\n")
    newest = max(p for p in (root / "pipelines" / "acme+rates").iterdir() if (p / "_chartbook" / "snapshot.json").is_file())
    for place in (root, root / "pipelines", root / "pipelines" / "acme+rates", newest, newest / "_chartbook"):
        (place / ".DS_Store").write_bytes(b"\x00Bud1")
    store_module._read_records.clear()
    store_module._found_whole.clear()
    return root, readers


def _tree(root: Path) -> dict:
    """Every file under a folder, by its path, with the hash of its bytes."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _read_through(root: Path) -> dict:
    """Every asset of every record, as the store hands its files out: by pipeline, time and file, the hash of its bytes."""
    store_module._read_records.clear()
    store_module._found_whole.clear()
    fresh, found = FolderStore(root), {}
    for record in fresh.records():
        assert record.readable, record.path
        for asset in record.assets:
            for file in asset.files:
                found[(record.pipeline, record.made_at, file.path)] = hashlib.sha256(file.location.read_bytes()).hexdigest()
    return found


class TestTheFixtureIsAStoreOf05WithEveryShape:
    def test_shape_by_shape(self, of_0_5):
        root, _ = of_0_5
        assert json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v2"}
        assert sorted(p.name for p in root.iterdir()) == [".DS_Store", "origins", "pipelines", "roots", "snapshots", "store.json", "tmp"]
        assert list((root / "tmp").iterdir()) == [] and (root / "snapshots" / ("0" * 40)).is_dir()
        assert len(list((root / "roots").iterdir())) == 4 and any((root / "origins").rglob("*.txt"))
        folders = {p.parent.name: sorted(q.name for q in p.parent.iterdir() if q.is_dir()) for p in (root / "pipelines").glob("*/README.txt")}
        assert sorted(folders) == ["acme+once", "acme+pinned", "acme+rates", "acme+upstream"]
        records = {name: [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "pipelines" / name).glob("*/_chartbook/snapshot.json"))] for name in folders}
        assert {name: [record.get("made_by", "owner") for record in found] for name, found in records.items()} == {
            "acme+once": ["owner"], "acme+pinned": ["pin"], "acme+rates": ["owner"] * 3, "acme+upstream": ["owner", "pin"] or ["pin", "owner"],
        } or sorted(records["acme+upstream"][i].get("made_by", "owner") for i in (0, 1)) == ["owner", "pin"]
        cleared = [p.parent.parent for p in (root / "pipelines" / "acme+rates").glob("*/_chartbook/CLEARED.txt")]
        assert len(cleared) == 1 and not (cleared[0] / "_chartbook" / "snapshot.json").exists()
        assert (cleared[0] / "_data" / "treasury.parquet").is_file()  # which the later records name
        entries = [entry for found in records.values() for record in found for part in migrate_0_5._parts(record) for entry in part["stored"]["files"]]
        assert all("kept_in" in entry for entry in entries) and any(entry["kept_in"] == cleared[0].name for entry in entries)
        assert all(set(part["stored"]) in ({"at", "single", "files"}, {"at", "files"}) for found in records.values() for record in found for part in migrate_0_5._parts(record))
        assert all(record["schema"] == "chartbook/snapshot/v2" for found in records.values() for record in found)
        assert len(list(root.rglob(".DS_Store"))) == 5
        # And it is whole as 0.5 left it: no file a record names is missing
        assert FolderStore(root).verify() == []


class TestAfterAMove:
    def test_the_layout_and_every_asset_read_as_the_same_bytes(self, of_0_5):
        root, readers = of_0_5
        before = _read_through(root)
        documents = {p.parent.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in root.glob("pipelines/*/*/_chartbook/snapshot.json")}
        done = migrate_0_5.run(root)
        assert json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}
        assert not any((root / name).exists() for name in ("pipelines", "roots", "origins", "tmp")) and not (root / migrate_0_5.JOURNAL).exists()
        assert not (root / "snapshots" / ("0" * 40)).exists()
        assert _read_through(root) == before
        fresh = FolderStore(root)
        records = fresh.records()
        assert all(fresh.holes_of(record.path) == [] for record in records) and fresh.verify() == []
        # Per pipeline: the newest its owner made is complete, the others it made are increments on it, a pin's is complete
        rates = [record for record in records if record.pipeline == "acme/rates"]
        newest = max(rates, key=lambda record: record.made_at)
        assert [(record.increment, record.builds_on) for record in rates] == [(True, newest.folder.name), (True, newest.folder.name), (False, "")]
        assert sorted((record.pipeline, record.made_by, record.increment) for record in records if record.pipeline != "acme/rates") == [
            ("acme/once", "snapshot", False), ("acme/pinned", "pin", False), ("acme/upstream", "pin", False), ("acme/upstream", "snapshot", False),
        ]
        assert (done.pipelines, done.snapshots, done.complete, done.by_pins, done.increments, done.folders_gone) == (4, 7, 5, 2, 2, 1)
        # A record is rewritten only in `stored`
        for record in records:
            now = json.loads(record.path.read_text(encoding="utf-8"))
            was = documents[record.folder.name]
            strip = lambda document: {k: ({n: v for n, v in part.items() if n != "stored"} if isinstance(part, dict) else [{n: v for n, v in one.items() if n != "stored"} for one in part] if k == "records" else part) for k, part in document.items() if k != "stored"}  # noqa: E731
            assert strip(now) == strip(was), record.path
        # What no record names is not removed: it is aside, at its old path
        aside = sorted(p.relative_to(root / "_chartbook" / "left-by-0.5").as_posix() for p in (root / "_chartbook" / "left-by-0.5").rglob("*") if p.is_file())
        assert len(aside) == 4 and all(path.endswith(".DS_Store") and path.startswith("pipelines") for path in aside) and done.aside == 4
        assert (root / ".DS_Store").is_file()
