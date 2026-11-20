"""``chartbook catalog open`` asks before it opens a site that is behind (``docs_src/design/one-command.md``).

A run makes a snapshot, and builds no catalog: the catalog's site is built
when it is looked at. So the command that looks works out, when it is
typed, whether the site shows what the stores have now, by comparing the
snapshots the site was built from (the ``index.json`` beside it) with
those in the stores. A site that was never built is behind by all of it.
At a terminal it asks whether to build first; where nothing can ask, it
opens what there is and says how far behind it is.
"""

import json
import webbrowser

import pytest
from click.testing import CliRunner

from chartbook import cli, config, snapshot, versions
from chartbook.cli import main
from chartbook.store import StoreError, default_store
from tests.test_lock_by_kind import _git
from tests.test_several_stores import pipeline

ASKS = " Build it before opening? [Y/n]: "
NEVER = "The catalog's site has not been built yet."


@pytest.fixture(autouse=True)
def opened(monkeypatch):
    """No browser is opened by a test: what would have been is kept here."""
    urls = []
    monkeypatch.setattr(webbrowser, "open", lambda url: urls.append(url) or True)
    return urls


@pytest.fixture
def stored(tmp_path):
    """A pipeline with one snapshot in the machine's (scratch) store, and a catalog over that store with no site yet."""
    folder = pipeline(tmp_path)
    snapshot.make(folder, default_store(), made_at="2026-11-01T10:00:00Z")
    assert CliRunner().invoke(main, ["catalog", "init"]).exit_code == 0
    return folder


def _catalog():
    return config.get_global_catalog_path()


def _site(*shown) -> None:
    """A built site beside the catalog, as a build that listed these snapshots would have left its index."""
    docs = _catalog().parent / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text("<html></html>", encoding="utf-8", newline="\n")
    by_pipeline: dict = {}
    for taken in shown:
        by_pipeline.setdefault(taken.pipeline, []).append({"commit": taken.commit, "made_at": taken.made_at})
    records = [{"kind": "Pipeline", "id": name, "snapshots": entries} for name, entries in by_pipeline.items()]
    (docs / "index.json").write_text(json.dumps({"records": records}), encoding="utf-8", newline="\n")


def _in_the_store() -> list:
    return snapshot.readable_snapshots(default_store())[0]


def _another(folder, made_at: str):
    """A snapshot of a later commit of the pipeline."""
    _git(folder, "commit", "--quiet", "--allow-empty", "-m", f"Work of {made_at[:10]}")
    return snapshot.make(folder, default_store(), made_at=made_at).snapshot


class TestHowFarBehind:
    def test_a_site_that_was_never_built(self, stored):
        found = versions.behind(_catalog())
        assert found == versions.Behind(built=False, missing=1, gone=0) and found
        assert found.said() == NEVER

    def test_a_catalog_with_nothing_in_its_stores_and_no_site(self, tmp_path):
        """Nothing to show, and still no site to open: behind, by having none."""
        assert CliRunner().invoke(main, ["catalog", "init"]).exit_code == 0
        found = versions.behind(_catalog())
        assert found == versions.Behind(built=False) and found and found.said() == NEVER

    def test_a_site_that_shows_what_the_stores_have(self, stored):
        _site(*_in_the_store())
        found = versions.behind(_catalog())
        assert found == versions.Behind(built=True) and not found and found.said() == ""

    def test_snapshots_made_since(self, stored):
        _site(*_in_the_store())
        _another(stored, "2026-11-02T10:00:00Z")
        assert versions.behind(_catalog()).said() == "The catalog's site is behind your stores: 1 snapshot is not in it yet."
        _another(stored, "2026-11-03T10:00:00Z")
        assert versions.behind(_catalog()).said() == "The catalog's site is behind your stores: 2 snapshots are not in it yet."

    def test_snapshots_gone_since(self, stored):
        """Cleared from the store, here or on another machine: the site still has their pages."""
        first = _in_the_store()
        second = _another(stored, "2026-11-02T10:00:00Z")
        _site(*first, second)
        default_store().remove_snapshot(second.path)
        assert versions.behind(_catalog()) == versions.Behind(built=True, missing=0, gone=1)
        assert versions.behind(_catalog()).said() == "The catalog's site is behind your stores: 1 snapshot it shows is no longer in them."

    def test_both(self, stored):
        first = _in_the_store()
        second = _another(stored, "2026-11-02T10:00:00Z")
        third = _another(stored, "2026-11-03T10:00:00Z")
        _site(*first, second, third)
        for taken in (second, third):
            default_store().remove_snapshot(taken.path)
        _another(stored, "2026-11-04T10:00:00Z")
        assert versions.behind(_catalog()).said() == (
            "The catalog's site is behind your stores: 1 snapshot is not in it yet, and 2 it shows are no longer in them."
        )

    def test_a_pipeline_the_catalog_does_not_show_is_not_counted(self, stored):
        _site()
        path = _catalog()
        path.write_text(path.read_text(encoding="utf-8") + '\n[pipelines."acme/upstream"]\ndisabled = true\n', encoding="utf-8", newline="\n")
        assert not versions.behind(path)

    def test_a_site_with_no_index_beside_it_shows_nothing_that_can_be_told(self, stored):
        _site(*_in_the_store())
        (_catalog().parent / "docs" / "index.json").write_text("not json", encoding="utf-8", newline="\n")
        assert versions.behind(_catalog()) == versions.Behind(built=True, missing=1, gone=0)


class TestAtATerminal:
    @pytest.fixture(autouse=True)
    def _a_person(self, monkeypatch):
        monkeypatch.setattr(cli, "_can_ask", lambda: True)

    def test_yes_builds_it_and_opens_it(self, stored, opened):
        """A site that was never built is asked for the same way, where the command used to stop with an error."""
        result = CliRunner().invoke(main, ["catalog", "open"], input="\n")
        assert result.exit_code == 0, result.output
        index = _catalog().parent / "docs" / "index.html"
        said = result.output.splitlines()
        assert said[0] == NEVER + ASKS
        assert f"Catalog site generated: {index}" in said and said[-1] == f"Opening {index}"
        assert "Run 'chartbook catalog open' to open it in your browser." not in said  # it is being opened
        assert opened == [index.as_uri()]
        assert not versions.behind(_catalog())
        # Up to date now: nothing is asked
        again = CliRunner().invoke(main, ["catalog", "open"], input="")
        assert again.exit_code == 0 and again.output.splitlines() == [f"Opening {index}"]
        # Until the stores move on
        _another(stored, "2026-11-02T10:00:00Z")
        behind = CliRunner().invoke(main, ["catalog", "open"], input="n\n")
        assert behind.exit_code == 0
        assert behind.output.splitlines() == [
            "The catalog's site is behind your stores: 1 snapshot is not in it yet." + ASKS + "n",
            f"Opening {index}",  # as it is
        ]
        assert versions.behind(_catalog()).missing == 1 and len(opened) == 3

    def test_no_with_nothing_built_opens_nothing(self, stored, opened):
        result = CliRunner().invoke(main, ["catalog", "open"], input="n\n")
        assert result.exit_code == 0
        assert result.output.splitlines() == [NEVER + ASKS + "n", "Nothing to open. `chartbook catalog build` builds it."]
        assert opened == [] and not (_catalog().parent / "docs").exists()

    def test_with_stores_that_cannot_be_read_and_nothing_built_it_still_asks(self, stored, opened, monkeypatch):
        def away(catalog):
            raise StoreError("the store cannot be reached")

        monkeypatch.setattr(versions, "behind", away)
        result = CliRunner().invoke(main, ["catalog", "open"], input="n\n")
        assert result.exit_code == 0 and opened == []
        assert result.output.splitlines() == [NEVER + ASKS + "n", "Nothing to open. `chartbook catalog build` builds it."]

    def test_the_end_of_input_stops_it(self, stored, opened):
        _site()
        result = CliRunner().invoke(main, ["catalog", "open"], input="")
        assert result.exit_code == 1 and opened == []

    def test_a_site_that_is_not_behind_is_opened_with_no_question(self, stored, opened, monkeypatch):
        _site(*_in_the_store())
        monkeypatch.setattr(cli, "_confirm", lambda *a, **k: pytest.fail("asked"))
        result = CliRunner().invoke(main, ["catalog", "open"])
        assert result.exit_code == 0 and len(opened) == 1


class TestWhereNothingCanAsk:
    def test_it_opens_what_there_is_and_says_how_far_behind(self, stored, opened):
        _site()
        result = CliRunner().invoke(main, ["catalog", "open"])
        index = _catalog().parent / "docs" / "index.html"
        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "The catalog's site is behind your stores: 1 snapshot is not in it yet. Opening it as it is: "
            "`chartbook catalog build` brings it up to date.",
            f"Opening {index}",
        ]
        assert opened == [index.as_uri()]

    def test_with_nothing_built_it_says_what_builds_it(self, stored, opened):
        result = CliRunner().invoke(main, ["catalog", "open"])
        assert result.exit_code == 1 and opened == []
        assert result.output.splitlines() == ["Error: The catalog's site has not been built yet. `chartbook catalog build` builds it."]

    def test_stores_that_cannot_be_read_now_do_not_stop_it(self, stored, opened, monkeypatch):
        """A drive that is away: what there is is opened, and nothing is said of what cannot be told."""
        _site()

        def away(catalog):
            raise StoreError("the store cannot be reached")

        monkeypatch.setattr(versions, "behind", away)
        result = CliRunner().invoke(main, ["catalog", "open"])
        assert result.exit_code == 0 and len(opened) == 1
        assert result.output.splitlines() == [f"Opening {_catalog().parent / 'docs' / 'index.html'}"]
