"""`chartbook index diff`: what changed between two builds, from their index.json files."""

import json
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import index, indexdiff
from chartbook.cli import main
from chartbook.manifest import load_manifest


def _manifest(directory: Path, dataframes: dict, charts: dict = None) -> None:
    table = {"project": {"id": "acme/rates"}, "dataframes": dataframes}
    if charts:
        table["charts"] = charts
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table))


RATES = {"rates": {"path": "./_data/rates.parquet", "docs": "Rates."}}


@pytest.fixture
def before(tmp_path):
    """A pipeline with one dataframe, built, and its index."""
    directory = tmp_path.resolve() / "rates"
    directory.mkdir()
    (directory / "README.md").write_text("# Rates\n")
    (directory / "_data").mkdir()
    _manifest(directory, RATES)
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(directory / "_data" / "rates.parquet")
    return directory, index.build_index(load_manifest(directory))


def _changes(found) -> dict:
    return {(c.kind, c.id): c for c in found.changed}


class TestDiff:
    def test_nothing_changed_but_the_time(self, before):
        directory, first = before
        second = index.build_index(load_manifest(directory))
        second["generated_at"] = "2030-01-01T00:00:00Z"
        found = indexdiff.diff(first, second)
        assert found.empty and indexdiff.format_diff(found) == "Nothing changed."
        # The full index and the published one compare as equals
        assert indexdiff.diff(first, index.published(second)).empty

    def test_data_changed_added_and_removed(self, before):
        directory, first = before
        pl.DataFrame({"d": ["2024-01-01", "2024-01-02"], "r": [4.1, 4.2]}).write_parquet(
            directory / "_data" / "rates.parquet"
        )
        _manifest(
            directory,
            {**RATES, "spreads": {"path": "./_data/spreads.parquet", "docs": "Spreads."}},
            {"curve": {"path": "./_output/curve.html", "dataframe": "rates", "docs": "A chart."}},
        )
        second = index.build_index(load_manifest(directory))
        found = indexdiff.diff(first, second)
        assert [r["id"] for r in found.added] == ["acme/rates:chart/curve", "acme/rates:spreads"]
        assert found.removed == []
        changes = _changes(found)
        # The dataframe's data moved; the pipeline lists two more assets. A
        # series record carries no hash, so none changed
        assert set(changes) == {("Dataframe", "acme/rates:rates"), ("Pipeline", "acme/rates")}
        rates = changes[("Dataframe", "acme/rates:rates")]
        assert rates.words == ["data changed"]
        assert set(rates.fields) >= {"content_hash", "row_count", "size_bytes"}
        assert rates.fields["row_count"] == (1, 2)
        assert changes[("Pipeline", "acme/rates")].words == ["assets changed"]
        text = indexdiff.format_diff(found)
        assert "Added 2:\n  Chart acme/rates:chart/curve\n  Dataframe acme/rates:spreads" in text
        assert "Changed 2:\n  Dataframe acme/rates:rates: data changed\n    content_hash: sha256:" in text
        assert "    row_count: 1 -> 2" in text and "  Pipeline acme/rates: assets changed" in text
        # ...and the other way round, the additions are removals
        back = indexdiff.diff(second, first)
        assert [r["id"] for r in back.removed] == ["acme/rates:chart/curve", "acme/rates:spreads"]

    def test_declared_differently_and_columns(self, before):
        directory, first = before
        _manifest(directory, {"rates": {**RATES["rates"], "docs": "Treasury rates, daily."}})
        pl.DataFrame({"d": ["2024-01-01"], "spread": [0.1]}).write_parquet(directory / "_data" / "rates.parquet")
        second = index.build_index(load_manifest(directory))
        found = indexdiff.diff(first, second)
        change = _changes(found)[("Dataframe", "acme/rates:rates")]
        assert change.words == ["data changed", "declared differently: docs"]
        text = indexdiff.format_diff(found)
        assert "    columns added: spread" in text and "    columns gone: r" in text

    def test_words_for_pins_versions_labels_and_staleness(self):
        change = indexdiff.Change(
            "Model",
            "acme/f:model/m",
            {
                "versions": ([{"version": "a"}, {"version": "x"}], [{"version": "a"}, {"version": "b"}]),
                "aliases": ({}, {"champion": "b"}),
                "stale_inputs": ([], ["x:y"]),
                "metrics": ({"rmse": 1}, {"rmse": 2}),
                "pinned_inputs": ({"x:y": "sha256:a"}, {"x:y": "sha256:b"}),
                "trained_with": ({"x:y": "sha256:a"}, {"x:y": "sha256:b"}),
                "name": ("Old", "New"),
            },
        )
        assert change.words == [
            "1 new version(s)",
            "1 version(s) gone",
            "labels moved",
            "out of date",
            "scores changed",
            "pins moved",
            "trained on other data",
            "declared differently: name",
        ]
        assert indexdiff.Change("Model", "m", {"stale_inputs": (["x"], [])}).words == ["up to date again"]
        # A chart is a rendering: its hash moving is not its data moving
        assert indexdiff.Change("Chart", "c", {"content_hash": ("sha256:a", "sha256:b")}).words == ["rendered differently"]
        assert indexdiff.Change("Notebook", "n", {"content_hash": ("sha256:a", "sha256:b")}).words == ["rendered differently"]
        # Pins moved only when a pinned hash did
        pinned = indexdiff.Change("Pipeline", "p", {"dependencies": ([{"id": "x", "pinned_hash": "a"}], [{"id": "x", "pinned_hash": "b"}])})
        relocated = indexdiff.Change("Pipeline", "p", {"dependencies": ([{"id": "x", "pinned_hash": "a", "location": 1}], [{"id": "x", "pinned_hash": "a", "location": 2}])})
        assert pinned.words == ["pins moved"] and relocated.words == ["dependencies changed"]
        assert indexdiff.Change("Pipeline", "p", {"dependencies": (None, [])}).words == ["dependencies changed"]

    def test_long_lists_are_printed_whole_and_versions_named(self):
        found = indexdiff.IndexDiff(
            changed=[
                indexdiff.Change(
                    "Model", "m",
                    {
                        "stale_inputs": ([], ["backofficedev/yield_curve:fed_yield_curve", "backofficedev/yield_curve:treasury_rates"]),
                        "versions": ([{"version": "aaaaaaaaaaaa"}], [{"version": "bbbbbbbbbbbb"}]),
                    },
                )
            ]
        )
        text = indexdiff.format_diff(found)
        assert '["backofficedev/yield_curve:fed_yield_curve", "backofficedev/yield_curve:treasury_rates"]' in text
        assert "    new: bbbbbbbbbbbb" in text and "    gone: aaaaaaaaaaaa" in text

    def test_the_envelope_is_compared_too(self, before):
        directory, first = before
        other = dict(first, root="someone/else", schema="chartbook/index/v2")
        found = indexdiff.diff(first, other)
        assert not found.empty and set(found.envelope) == {"root", "schema"}
        text = indexdiff.format_diff(found)
        assert text.startswith("The root differs: ") and "different layouts" in text

    def test_to_dict_is_json(self, before):
        directory, first = before
        pl.DataFrame({"d": ["x"], "r": [1.0]}).write_parquet(directory / "_data" / "rates.parquet")
        second = index.build_index(load_manifest(directory))
        document = json.loads(json.dumps(indexdiff.diff(first, second).to_dict(), default=str))
        (changed,) = [c for c in document["changed"] if c["kind"] == "Dataframe"]
        assert changed["id"] == "acme/rates:rates" and "data changed" in changed["words"]
        assert set(changed["fields"]["content_hash"]) == {"before", "after"}
        assert document["envelope"] == {}


class TestCommand:
    def test_two_files_or_two_folders(self, before, tmp_path):
        directory, first = before
        index.write_index(index.published(first), tmp_path / "old" / "index.json")
        pl.DataFrame({"d": ["x"], "r": [1.0]}).write_parquet(directory / "_data" / "rates.parquet")
        index.write_index(index.build_index(load_manifest(directory)), tmp_path / "new" / "index.json")
        result = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "old"), str(tmp_path / "new" / "index.json")])
        assert result.exit_code == 0, result.output
        assert "  Dataframe acme/rates:rates: data changed" in result.output
        with_code = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "old"), str(tmp_path / "new"), "--exit-code"])
        assert with_code.exit_code == 1
        same = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "old"), str(tmp_path / "old"), "--exit-code"])
        assert same.exit_code == 0 and same.output.strip() == "Nothing changed."
        as_json = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "old"), str(tmp_path / "new"), "--json"])
        assert "acme/rates:rates" in [c["id"] for c in json.loads(as_json.output)["changed"]]

    def test_not_an_index(self, tmp_path):
        (tmp_path / "x.json").write_text("{}")
        (tmp_path / "y.json").write_text("not json")
        (tmp_path / "z.json").write_text(json.dumps({"records": [1]}))
        (tmp_path / "empty").mkdir()
        result = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "x.json"), str(tmp_path / "x.json")])
        assert result.exit_code == 2 and "is not an index" in result.output
        result = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "y.json"), str(tmp_path / "x.json")])
        assert result.exit_code == 2 and "is not JSON" in result.output
        result = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "z.json"), str(tmp_path / "z.json")])
        assert result.exit_code == 2 and "record 0 has no kind and id" in result.output
        result = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "empty"), str(tmp_path / "x.json")])
        assert result.exit_code == 2 and "index.json" in result.output


class TestStableChartFiles:
    def test_the_plotting_helpers_write_the_same_html_twice(self, tmp_path):
        """Found by a reviewer: Plotly embeds a fresh id on every render unless
        given a div_id, so a chart's hash in the index moved with nothing changed."""
        import plotly.graph_objects as go

        figure = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
        figure.write_html(str(tmp_path / "a.html"), include_plotlyjs="cdn", div_id="chart")
        figure.write_html(str(tmp_path / "b.html"), include_plotlyjs="cdn", div_id="chart")
        assert (tmp_path / "a.html").read_bytes() == (tmp_path / "b.html").read_bytes()
        from chartbook.plotting import _output

        assert 'div_id=f"chartbook-{chart_id}"' in Path(_output.__file__).read_text()
