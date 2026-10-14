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
        # The dataframe's series change with it, and the pipeline lists one more asset
        (change,) = [c for c in found.changed if c.kind == "Dataframe"]
        assert change.id == "acme/rates:rates" and change.words == ["data changed"]
        assert {c.kind for c in found.changed} <= {"Dataframe", "Series", "Pipeline"}
        assert set(change.fields) >= {"content_hash", "row_count", "size_bytes"}
        assert change.fields["row_count"] == (1, 2)
        text = indexdiff.format_diff(found)
        assert "Added 2:\n  Chart acme/rates:chart/curve\n  Dataframe acme/rates:spreads" in text
        assert "  Dataframe acme/rates:rates: data changed\n    content_hash: sha256:" in text
        assert "    row_count: 1 -> 2" in text
        # ...and the other way round, the additions are removals
        back = indexdiff.diff(second, first)
        assert [r["id"] for r in back.removed] == ["acme/rates:chart/curve", "acme/rates:spreads"]

    def test_declared_differently(self, before):
        directory, first = before
        _manifest(directory, {"rates": {**RATES["rates"], "docs": "Treasury rates, daily."}})
        second = index.build_index(load_manifest(directory))
        (change,) = [c for c in indexdiff.diff(first, second).changed if c.kind == "Dataframe"]
        assert change.words == ["declared differently: docs"]

    def test_words_for_pins_versions_labels_and_staleness(self):
        change = indexdiff.Change(
            "Model",
            "acme/f:model/m",
            {
                "dependencies": ([], [{"id": "x"}]),
                "versions": ([{"version": "a"}], [{"version": "a"}, {"version": "b"}]),
                "aliases": ({}, {"champion": "b"}),
                "stale_inputs": ([], ["x:y"]),
                "metrics": ({"rmse": 1}, {"rmse": 2}),
                "name": ("Old", "New"),
            },
        )
        assert change.words == [
            "pins moved",
            "1 new version(s)",
            "labels moved",
            "out of date",
            "scores changed",
            "declared differently: name",
        ]
        back = indexdiff.Change("Model", "m", {"stale_inputs": (["x"], [])})
        assert back.words == ["up to date again"]

    def test_to_dict_is_json(self, before):
        directory, first = before
        pl.DataFrame({"d": ["x"], "r": [1.0]}).write_parquet(directory / "_data" / "rates.parquet")
        second = index.build_index(load_manifest(directory))
        document = json.loads(json.dumps(indexdiff.diff(first, second).to_dict(), default=str))
        (changed,) = [c for c in document["changed"] if c["kind"] == "Dataframe"]
        assert changed["id"] == "acme/rates:rates" and "data changed" in changed["words"]
        assert set(changed["fields"]["content_hash"]) == {"before", "after"}


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
        result = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "x.json"), str(tmp_path / "x.json")])
        assert result.exit_code == 2 and "is not an index" in result.output
        result = CliRunner().invoke(main, ["index", "diff", str(tmp_path / "y.json"), str(tmp_path / "x.json")])
        assert result.exit_code == 2 and "is not JSON" in result.output
