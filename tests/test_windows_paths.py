"""Path faults found by trying 0.5.0 on a real store and catalog on Windows.

Each is run on every system, with what Windows does simulated where the
system is not Windows.
"""

import builtins
import os
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, links, snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.resolve import resolve
from chartbook.store import FolderStore
from tests.test_several_stores import configure, pipeline


def _windows_reads_short_paths(monkeypatch, limit):
    """As Windows with long paths off reads: a path of *limit* characters or more is not there, unless asked in the ``\\?\`` form.

    Windows says only "No such file or directory" of such a path, and
    ``os.path.isfile`` says False. Its limit is 260 (a folder's, 248); a
    lower one here keeps the files of the test short enough for any disk.
    """
    monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
    monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)
    monkeypatch.setattr(store_module, "WINDOWS_PATH_LIMIT", limit)
    monkeypatch.setattr(store_module, "WINDOWS_FOLDER_LIMIT", limit - 12)
    real_stat, real_isfile, real_open = os.stat, os.path.isfile, builtins.open

    def plain(path):
        """The path Windows would be asked for, and whether it is past what it takes."""
        if isinstance(path, int):
            return path, False
        text = os.fspath(path)
        if isinstance(text, str) and text.startswith("\\\\?\\"):
            return text[4:], False
        return text, isinstance(text, str) and len(os.path.abspath(text)) >= limit

    def stat(path, *arguments, **keywords):
        text, refused = plain(path)
        if refused:
            raise FileNotFoundError(2, "No such file or directory", text)
        return real_stat(text, *arguments, **keywords)

    def isfile(path):
        text, refused = plain(path)
        return False if refused else real_isfile(text)

    def opened(path, *arguments, **keywords):
        text, refused = plain(path)
        if refused:
            raise FileNotFoundError(2, "No such file or directory", text)
        return real_open(text, *arguments, **keywords)

    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os.path, "isfile", isfile)
    monkeypatch.setattr(store_module, "open", opened, raising=False)
    monkeypatch.setattr(snapshot, "open", opened, raising=False)


def _store_whose_records_are_past_the_limit(tmp_path, monkeypatch):
    """A store with one snapshot whose record's path is past Windows' limit, and its ``chartbook.toml`` short of it.

    So it is on a real store in a long folder: ``.../_chartbook/snapshot.json``
    is longer than ``.../chartbook.toml`` beside it.
    """
    folder = pipeline(tmp_path)
    root = tmp_path.resolve() / "store"
    made = snapshot.make(folder, FolderStore(root)).snapshot
    record = Path(made.path)
    _windows_reads_short_paths(monkeypatch, len(str(record)))
    assert len(str(record.parent.parent / "chartbook.toml")) < len(str(record))
    store_module._read_records.clear()
    return root, record


def test_a_record_past_the_limit_is_read_not_passed_over(tmp_path, monkeypatch):
    """On a real store in a long folder, `store ls` and `store info` showed 2 of 16 pipelines, and said nothing of the rest."""
    root, _ = _store_whose_records_are_past_the_limit(tmp_path, monkeypatch)
    kept = FolderStore(root).records()
    assert [(record.pipeline, record.readable) for record in kept] == [("acme/upstream", True)]
    found, unreadable = snapshot.readable_snapshots(FolderStore(root))
    assert [taken.pipeline for taken in found] == ["acme/upstream"] and not unreadable


def test_gc_takes_no_file_from_a_snapshot_whose_record_is_past_the_limit(tmp_path, monkeypatch):
    """With its record unseen, a snapshot's folder a day old read as one begun and given up, and gc took its files."""
    root, record = _store_whose_records_are_past_the_limit(tmp_path, monkeypatch)
    # A day on, as the folder's times cannot be set back (a change time, a creation time)
    monkeypatch.setattr(store_module, "PENDING_FOLDER_SECONDS", 0)
    the_store = FolderStore(root)
    removed, _ = the_store.sweep(record.parent.parent.parent, dry_run=True)
    assert removed == []
    assert the_store.tidy(dry_run=True) == []


def test_store_info_warns_of_a_catalog_store_in_too_long_a_folder(tmp_path, monkeypatch):
    """The warning was said only for a store the settings name, not for a catalog's [stores]."""
    monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
    monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)
    # Short enough to make on a disk without long paths, long enough that a snapshot's paths would cross 260
    base = str(tmp_path.resolve() / "s")
    deep = Path(base + "x" * (180 - len(base)))
    deep.mkdir(parents=True)
    configure(tmp_path, monkeypatch, {"personal": {"url": str(deep)}})
    said = CliRunner().invoke(main, ["store", "info"])
    assert said.exit_code == 0, said.output
    assert "Warning: the store's folder is" in said.output and "LongPathsEnabled" in said.output


@pytest.mark.parametrize("url", ["file:///{}/My%20Drive/store", "file:///{}/My Drive/store"])
def test_a_file_url_is_read_percent_decoded(tmp_path, url):
    """`file:///C:/My%20Drive/store`, as a browser or Path.as_uri() writes it, named a folder called `My%20Drive`."""
    base = tmp_path.resolve().as_posix().lstrip("/")
    assert config.folder_of_store_url(url.format(base)) == tmp_path.resolve() / "My Drive" / "store"


def test_a_link_is_read_when_the_dependency_is_named_by_its_short_name(tmp_path):
    """`yield_curve:x` for `backofficedev/yield_curve`, as the guide writes it, read the pin, and a link was passed over."""
    upstream = pipeline(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n[dependencies]\n"acme/upstream"={}\n')
    links.add(consumer, "acme/upstream", upstream)
    with pytest.warns(links.LinkedDependencyWarning, match="pin is not in use"):
        location = resolve("upstream:dataframe_0", start_dirs=[consumer])
    assert location.path.is_file() and upstream in location.path.parents


def test_a_link_is_written_with_forward_slashes(tmp_path):
    upstream = pipeline(tmp_path)
    consumer = tmp_path / "work" / "consumer"
    consumer.mkdir(parents=True)
    (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n')
    links.add(consumer, "acme/upstream", upstream)
    assert (consumer / links.NAME).read_text(encoding="utf-8").strip() == '"acme/upstream" = "../../upstream"'
    assert links.read(consumer) == {"acme/upstream": upstream.resolve()}


def test_a_link_to_another_drive_is_written_whole(tmp_path, monkeypatch):
    """Windows has no relative path from C: to D:, and `os.path.relpath` raised."""
    upstream = pipeline(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n')

    def across_drives(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", across_drives)
    links.add(consumer, "acme/upstream", upstream)
    assert links.read(consumer) == {"acme/upstream": upstream.resolve()}


def test_views_in_use_stay_and_are_tried_again(tmp_path, monkeypatch):
    """A 0.4 process reading a view (Windows refuses to remove an open file) left all of views/, and the marker said it was done."""
    cache = tmp_path / "cache"
    for name in ("in-use", "idle"):
        (cache / "views" / name).mkdir(parents=True)
        (cache / "views" / name / "part.parquet").write_bytes(b"x")
    monkeypatch.setenv("CHARTBOOK_CACHE", str(cache))
    real = store_module._remove_tree

    def refuse_open(directory, own=False):
        if Path(directory).name == "in-use":
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(directory, own=own)

    monkeypatch.setattr(store_module, "_remove_tree", refuse_open)
    said = CliRunner().invoke(main, ["store", "info"])
    assert "1 of what ChartBook 0.4 gathered there for reading is in use" in said.output
    assert sorted(p.name for p in (cache / "views").iterdir()) == ["in-use"]
    assert not (cache / store_module.OLD_VIEWS_REMOVED).exists()
    monkeypatch.setattr(store_module, "_remove_tree", real)
    said = CliRunner().invoke(main, ["store", "info"])
    assert "Removed" in said.output and not (cache / "views").exists()
    assert (cache / store_module.OLD_VIEWS_REMOVED).is_file()


def test_the_default_site_url_is_a_file_uri(tmp_path):
    """`file://C:/x` names a host "C:"; a space is %20."""
    from chartbook.manifest import load_manifest

    folder = tmp_path / "with space"
    folder.mkdir()
    (folder / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}}), encoding="utf-8")
    site_url = load_manifest(folder)["project"]["site_url"]
    assert site_url == (folder.resolve() / "docs" / "index.html").as_uri()
    assert site_url.startswith("file:///") and " " not in site_url


def test_a_version_built_from_the_store_links_no_folder_of_its_own(tmp_path, monkeypatch):
    """A version's site, built in a temporary folder, linked that folder (`file://C:/Users/.../Temp/chartbook-version-...`)."""
    from chartbook.manifest import load_manifest

    (tmp_path / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}}), encoding="utf-8")
    monkeypatch.setenv("CHARTBOOK_UNTRUSTED_SOURCE", "1")
    assert load_manifest(tmp_path)["project"]["site_url"] == ""
    (tmp_path / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/rates", "site_url": "https://acme.github.io/rates"}}), encoding="utf-8"
    )
    assert load_manifest(tmp_path)["project"]["site_url"] == "https://acme.github.io/rates"


def test_a_version_site_too_deep_for_windows_says_why_and_is_tried_again(tmp_path, monkeypatch):
    """Built in a staging folder 34 characters longer than its own, a version's site crossed 260 under the default cache.

    Windows said "No such file or directory" of a Sphinx file, and the version was kept as one that cannot be built.
    """
    from chartbook import versions

    folder = pipeline(tmp_path)
    the_store = FolderStore(tmp_path / "store")
    taken = snapshot.make(folder, the_store).snapshot
    monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
    monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)
    monkeypatch.setattr(store_module, "WINDOWS_PATH_LIMIT", len(str(versions._kept(taken.pipeline, "x"))) + 40)
    rendered = versions.render(taken, the_store)
    assert not rendered.built and "LongPathsEnabled" in rendered.why and "[cache] path" in rendered.why
    assert (rendered.folder / "index.html").is_file()
    assert not (rendered.folder.parent / versions._DONE).exists()  # tried again once the paths fit
    monkeypatch.setattr(store_module, "long_paths_enabled", lambda: True)
    assert versions.render(taken, the_store).built


def test_a_version_too_deep_for_the_catalogs_folder_does_not_stop_the_catalog(tmp_path, monkeypatch):
    """Copying one version's site into a catalog in a long folder raised, and the whole catalog build stopped."""
    from chartbook import versions

    folder = pipeline(tmp_path)
    taken = snapshot.make(folder, FolderStore(tmp_path / "store")).snapshot
    site = tmp_path / "site"
    (site / "_sources" / "deep").mkdir(parents=True)
    (site / "index.html").write_text("<html></html>", encoding="utf-8")
    (site / "_sources" / "deep" / ("page" * 10 + ".md")).write_text("x", encoding="utf-8")
    rendered = versions.Rendered(site, built=True)
    target = tmp_path / "catalog" / "versions" / "acme--upstream" / "v"
    monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
    monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)
    monkeypatch.setattr(store_module, "WINDOWS_PATH_LIMIT", len(str(target)) + 40)
    why = versions._copy_site(rendered, target)
    assert "characters long" in why and "LongPathsEnabled" in why
    assert not target.exists()
    monkeypatch.setattr(store_module, "WINDOWS_PATH_LIMIT", 10_000)
    assert versions._copy_site(rendered, target) == "" and (target / "index.html").is_file()
    assert taken.pipeline == "acme/upstream"
