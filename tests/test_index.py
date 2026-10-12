"""Tests for the index: ``chartbook.index``, and ``index.json`` from a build.

The format is specified in ``docs_src/design/index-schema.md``.
"""

import datetime
import json
import re
import warnings
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import hashing, index
from chartbook.cli import main
from chartbook.manifest import load_manifest
from chartbook.refs import AssetRef, parse_asset_ref
from tests.fixtures import create_pipeline_project

KINDS = ("Catalog", "Pipeline", "Dataframe", "Series", "Chart", "Notebook", "Note")


def _edit_toml(project_dir: Path, edit) -> None:
    """Load a project's chartbook.toml, apply ``edit(config)``, write it back."""
    toml_path = Path(project_dir) / "chartbook.toml"
    config = tomli.loads(toml_path.read_text())
    edit(config)
    toml_path.write_text(tomli_w.dumps(config))


def _add_notebook(project_dir: Path, name: str = "analysis") -> None:
    """Give a project one small notebook, declared in ``[notebooks]``."""
    notebook = {
        "cells": [{"cell_type": "markdown", "metadata": {}, "source": ["# Analysis"]}],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path = Path(project_dir) / "_output" / f"{name}.ipynb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notebook))
    _edit_toml(
        project_dir,
        lambda c: c["notebooks"].update({name: {"path": f"_output/{name}.ipynb"}}),
    )


def _build(project_dir, **kwargs) -> dict:
    return index.build_index(load_manifest(project_dir), **kwargs)


def _of_kind(built: dict, kind: str) -> list[dict]:
    return [r for r in built["records"] if r["kind"] == kind]


def _by_id(built: dict, record_id: str) -> dict:
    (record,) = [r for r in built["records"] if r.get("id") == record_id]
    return record


def _validate(built: dict) -> None:
    """Validate an index, envelope and every record, against the published schemas."""
    envelope = json.loads(index.schema_path("index").read_text())
    jsonschema.Draft202012Validator(envelope).validate(built)
    for record in built["records"]:
        schema = json.loads(index.schema_path(record["kind"]).read_text())
        jsonschema.Draft202012Validator(schema).validate(record)


@pytest.fixture
def project(pipeline_project_with_notes):
    """A pipeline, ``notes_pipeline``, with a dataframe, a chart and a note."""
    return pipeline_project_with_notes.resolve()


class TestEnvelope:
    def test_shape(self, project):
        built = _build(project)
        assert list(built) == ["schema", "generated_at", "generator", "root", "records"]
        assert built["schema"] == "chartbook/index/v1"
        assert built["generator"]["name"] == "chartbook"
        assert built["root"] == "notes_pipeline"
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", built["generated_at"])

    def test_generated_at_is_utc(self, project):
        eastern = datetime.timezone(datetime.timedelta(hours=-5))
        moment = datetime.datetime(2026, 10, 11, 17, 14, 3, tzinfo=eastern)
        assert _build(project, generated_at=moment)["generated_at"] == (
            "2026-10-11T22:14:03Z"
        )

    def test_every_record_names_its_kind_and_version(self, project):
        for record in _build(project)["records"]:
            assert record["kind"] in KINDS
            assert record["version"] == "chartbook/v1"
            assert list(record)[:2] == ["kind", "version"]

    def test_single_pipeline_has_no_catalog_record(self, project):
        assert _of_kind(_build(project), "Catalog") == []


class TestPipelineRecord:
    def test_fields(self, project):
        (record,) = _of_kind(_build(project), "Pipeline")
        assert record["id"] == "notes_pipeline"
        assert record["location"] == {"kind": "path", "value": project.as_posix()}
        assert record["docs"] == {"path": "./README.md"}
        assert record["assets"] == [
            "notes_pipeline:dataframe_0",
            "notes_pipeline:chart/chart_0_0",
            "notes_pipeline:note/note1",
        ]

    def test_build_command_is_a_script(self, project):
        _edit_toml(project, lambda c: c["project"].update(build="doit"))
        (record,) = _of_kind(_build(project), "Pipeline")
        assert record["scripts"] == {"build": "doit"}

    def test_unset_fields_are_left_out(self, project):
        (record,) = _of_kind(_build(project), "Pipeline")
        assert "scripts" not in record
        assert "dependencies" not in record

    def test_comes_before_its_assets(self, project):
        kinds = [r["kind"] for r in _build(project)["records"]]
        assert kinds[0] == "Pipeline"
        assert kinds[1] == "Dataframe"


class TestAssetRecords:
    def test_dataframe(self, project):
        record = _by_id(_build(project), "notes_pipeline:dataframe_0")
        parquet = project / "_data" / "notes_pipeline" / "dataframe_0.parquet"
        assert record["kind"] == "Dataframe"
        assert record["ref"] == {
            "pipeline": "notes_pipeline",
            "kind": "dataframe",
            "name": "dataframe_0",
        }
        assert record["pipeline"] == "notes_pipeline"
        assert record["name"] == "Dataframe 0"
        assert record["location"] == {
            "kind": "file",
            "path": "_data/notes_pipeline/dataframe_0.parquet",
            "resolved_path": str(parquet),
        }
        assert record["content_hash"] == hashing.hash_file(parquet).content_hash
        assert record["size_bytes"] == parquet.stat().st_size
        assert record["row_count"] == 10
        assert record["columns"] == [
            {"name": "date", "dtype": "date"},
            {"name": "value", "dtype": "int64"},
            {"name": "category", "dtype": "string"},
            {"name": "amount", "dtype": "float64"},
        ]
        assert record["date_col"] == "date"
        assert record["docs"] == {"path": "docs_src/dataframes/dataframe_0.md"}

    def test_chart_names_its_dataframe_as_an_input(self, project):
        record = _by_id(_build(project), "notes_pipeline:chart/chart_0_0")
        html = project / "_output" / "charts" / "chart_0_0.html"
        assert record["kind"] == "Chart"
        assert record["ref"]["kind"] == "chart"
        assert record["inputs"] == ["notes_pipeline:dataframe_0"]
        assert record["content_hash"] == hashing.hash_file(html).content_hash
        assert "dataframe" not in record

    def test_note_is_its_own_write_up(self, project):
        record = _by_id(_build(project), "notes_pipeline:note/note1")
        assert record["kind"] == "Note"
        assert record["location"]["path"] == "docs_src/note1.md"
        assert record["docs"] == {"path": "docs_src/note1.md"}
        assert record["content_hash"].startswith("sha256:")

    def test_notebook(self, project):
        _add_notebook(project)
        (record,) = _of_kind(_build(project), "Notebook")
        assert record["id"] == "notes_pipeline:notebook/analysis"
        assert record["ref"]["kind"] == "notebook"
        assert record["name"] == "Analysis"  # from the notebook's first heading
        assert record["location"]["path"] == "_output/analysis.ipynb"
        assert record["content_hash"].startswith("sha256:")

    def test_inline_docs_are_carried_as_text(self, tmp_path):
        project = create_pipeline_project(tmp_path / "inline", use_inline_docs=True)
        (record,) = _of_kind(_build(project), "Dataframe")
        assert set(record["docs"]) == {"text"}

    def test_declared_metadata_is_carried_as_it_is(self, project):
        def edit(config):
            config["dataframes"]["dataframe_0"].update(
                sources=["FRED"], license="Public domain", topic="Rates"
            )

        _edit_toml(project, edit)
        record = _by_id(_build(project), "notes_pipeline:dataframe_0")
        assert record["sources"] == ["FRED"]
        assert record["license"] == "Public domain"
        assert record["topic"] == "Rates"

    def test_undeclared_fields_are_absent_not_empty(self, project):
        record = _by_id(_build(project), "notes_pipeline:dataframe_0")
        assert "license" not in record
        assert "inputs" not in record
        assert "built_by" not in record

    def test_loader_bookkeeping_is_not_carried(self, project):
        for record in _build(project)["records"]:
            assert not [key for key in record if key.startswith("_")]
            assert "linked_charts" not in record
            assert "path" not in record

    def test_toml_dates_become_iso_strings(self, project):
        def edit(config):
            config["dataframes"]["dataframe_0"]["license_expiration"] = (
                datetime.date(2027, 1, 15)
            )

        _edit_toml(project, edit)
        built = _build(project)
        record = _by_id(built, "notes_pipeline:dataframe_0")
        assert record["license_expiration"] == "2027-01-15"
        json.dumps(built)

    def test_scoped_pipeline(self, project):
        _edit_toml(project, lambda c: c["project"].update(id="acme/rates"))
        built = _build(project)
        record = _by_id(built, "acme/rates:chart/chart_0_0")
        assert record["ref"] == {
            "scope": "acme",
            "pipeline": "rates",
            "kind": "chart",
            "name": "chart_0_0",
        }
        assert record["inputs"] == ["acme/rates:dataframe_0"]

    def test_id_and_ref_are_one_address(self, project):
        for record in _build(project)["records"]:
            if "ref" not in record:
                continue
            assert str(AssetRef.from_dict(record["ref"])) == record["id"]
            assert parse_asset_ref(record["id"]).to_dict() == record["ref"]

    def test_same_name_in_two_tables_gets_two_ids(self, project):
        def edit(config):
            config["charts"]["dataframe_0"] = dict(config["charts"]["chart_0_0"])

        _edit_toml(project, edit)
        ids = [r["id"] for r in _build(project)["records"] if "ref" in r]
        assert "notes_pipeline:dataframe_0" in ids
        assert "notes_pipeline:chart/dataframe_0" in ids
        assert len(ids) == len(set(ids))

    def test_a_key_that_is_not_an_address_is_left_out_with_a_warning(self, project):
        def edit(config):
            config["notes"]["two words"] = {"path": "docs_src/note1.md"}

        _edit_toml(project, edit)
        with pytest.warns(UserWarning, match=r"\[notes.two words\] is left out"):
            built = _build(project)
        assert [r["id"] for r in _of_kind(built, "Note")] == [
            "notes_pipeline:note/note1"
        ]


class TestFilesNotBuiltYet:
    def test_record_without_a_hash(self, project):
        (project / "_data" / "notes_pipeline" / "dataframe_0.parquet").unlink()
        record = _by_id(_build(project), "notes_pipeline:dataframe_0")
        assert record["location"]["path"] == "_data/notes_pipeline/dataframe_0.parquet"
        for absent in ("content_hash", "size_bytes", "row_count", "columns"):
            assert absent not in record

    def test_no_series_are_invented(self, project):
        (project / "_data" / "notes_pipeline" / "dataframe_0.parquet").unlink()
        assert _of_kind(_build(project), "Series") == []

    def test_a_file_that_is_not_parquet_still_has_a_hash(self, project):
        parquet = project / "_data" / "notes_pipeline" / "dataframe_0.parquet"
        parquet.write_text("not a parquet file")
        record = _by_id(_build(project), "notes_pipeline:dataframe_0")
        assert record["content_hash"].startswith("sha256:")
        assert "columns" not in record


class TestSeries:
    def test_every_column_but_the_date_is_a_series(self, project):
        series = _of_kind(_build(project), "Series")
        assert [s["id"] for s in series] == [
            "notes_pipeline:dataframe_0#value",
            "notes_pipeline:dataframe_0#category",
            "notes_pipeline:dataframe_0#amount",
        ]
        assert series[0] == {
            "kind": "Series",
            "version": "chartbook/v1",
            "id": "notes_pipeline:dataframe_0#value",
            "ref": {
                "pipeline": "notes_pipeline",
                "kind": "dataframe",
                "name": "dataframe_0",
                "part": "value",
            },
            "dataframe": "notes_pipeline:dataframe_0",
            "column": "value",
            "declared": False,
        }

    def test_series_follow_their_dataframe(self, project):
        kinds = [r["kind"] for r in _build(project)["records"]]
        assert kinds == [
            "Pipeline", "Dataframe", "Series", "Series", "Series", "Chart", "Note",
        ]  # fmt: skip

    def test_series_are_not_among_the_pipelines_assets(self, project):
        (pipeline,) = _of_kind(_build(project), "Pipeline")
        assert not [a for a in pipeline["assets"] if "#" in a]

    def test_a_declared_series_is_addressed_by_its_key(self, project):
        def edit(config):
            config["dataframes"]["dataframe_0"]["series"] = {
                "rate": {
                    "name": "The Rate",
                    "column": "value",
                    "units": "Percent",
                    "frequency": "Daily",
                    "docs_path": "docs_src/series/rate.md",
                }
            }

        _edit_toml(project, edit)
        series = _of_kind(_build(project), "Series")
        assert [(s["id"].split("#")[1], s["column"], s["declared"]) for s in series] == [
            ("rate", "value", True),
            ("category", "category", False),
            ("amount", "amount", False),
        ]
        declared = series[0]
        assert declared["name"] == "The Rate"
        assert declared["units"] == "Percent"
        assert declared["frequency"] == "Daily"
        assert declared["docs"] == {"path": "docs_src/series/rate.md"}
        assert declared["ref"]["part"] == "rate"

    def test_column_defaults_to_the_key(self, project):
        def edit(config):
            config["dataframes"]["dataframe_0"]["series"] = {
                "amount": {"name": "Amount"}
            }

        _edit_toml(project, edit)
        series = _by_id(_build(project), "notes_pipeline:dataframe_0#amount")
        assert series["declared"] is True
        assert series["column"] == "amount"

    def test_column_whose_name_is_not_an_address_has_no_series(self, project):
        parquet = project / "_data" / "notes_pipeline" / "dataframe_0.parquet"
        pl.DataFrame(
            {"date": [datetime.date(2020, 1, 1)], "10Y 2Y Spread": [1.5], "ok": [1]}
        ).write_parquet(parquet)
        built = _build(project)
        record = _by_id(built, "notes_pipeline:dataframe_0")
        assert "10Y 2Y Spread" in [c["name"] for c in record["columns"]]
        assert [s["column"] for s in _of_kind(built, "Series")] == ["ok"]

    def test_a_series_table_gives_such_a_column_an_address(self, project):
        parquet = project / "_data" / "notes_pipeline" / "dataframe_0.parquet"
        pl.DataFrame(
            {"date": [datetime.date(2020, 1, 1)], "10Y 2Y Spread": [1.5]}
        ).write_parquet(parquet)

        def edit(config):
            config["dataframes"]["dataframe_0"]["series"] = {
                "spread_10y_2y": {"column": "10Y 2Y Spread"}
            }

        _edit_toml(project, edit)
        (series,) = _of_kind(_build(project), "Series")
        assert series["id"] == "notes_pipeline:dataframe_0#spread_10y_2y"
        assert series["column"] == "10Y 2Y Spread"

    def test_a_key_is_not_reused_for_another_column(self, project):
        """`amount` names the column `value`, so the column `amount` has no address."""

        def edit(config):
            config["dataframes"]["dataframe_0"]["series"] = {
                "amount": {"column": "value"}
            }

        _edit_toml(project, edit)
        series = _of_kind(_build(project), "Series")
        assert [(s["id"].split("#")[1], s["column"]) for s in series] == [
            ("amount", "value"),
            ("category", "category"),
        ]

    def test_declared_series_of_a_missing_column_warns(self, project):
        def edit(config):
            config["dataframes"]["dataframe_0"]["series"] = {
                "dgs10": {"name": "10-Year", "column": "DGS10"}
            }

        _edit_toml(project, edit)
        with pytest.warns(UserWarning, match="names the column 'DGS10'"):
            built = _build(project)
        record = _by_id(built, "notes_pipeline:dataframe_0#dgs10")
        assert record["declared"] is True

    def test_declared_series_are_kept_when_the_file_is_not_built(self, project):
        (project / "_data" / "notes_pipeline" / "dataframe_0.parquet").unlink()

        def edit(config):
            config["dataframes"]["dataframe_0"]["series"] = {
                "dgs10": {"name": "10-Year", "column": "DGS10"}
            }

        _edit_toml(project, edit)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            (series,) = _of_kind(_build(project), "Series")
        assert series["id"] == "notes_pipeline:dataframe_0#dgs10"

    def test_date_col_that_is_not_a_column_warns(self, project):
        _edit_toml(
            project,
            lambda c: c["dataframes"]["dataframe_0"].update(date_col="DATE"),
        )
        with pytest.warns(UserWarning, match="date_col is 'DATE'"):
            series = _of_kind(_build(project), "Series")
        assert "date" in [s["column"] for s in series]


class TestSeriesTables:
    """``[dataframes.x.series.y]`` as the manifest loader reads it."""

    def _load_with(self, project, series):
        _edit_toml(
            project,
            lambda c: c["dataframes"]["dataframe_0"].update(series=series),
        )
        return load_manifest(project)

    def test_column_is_filled_in(self, project):
        manifest = self._load_with(project, {"amount": {"name": "Amount"}})
        assert manifest["dataframes"]["dataframe_0"]["series"]["amount"]["column"] == (
            "amount"
        )

    def test_must_be_a_table_of_tables(self, project):
        with pytest.raises(ValueError, match="must be a table of tables"):
            self._load_with(project, ["amount"])
        with pytest.raises(ValueError, match="'amount' must be a table"):
            self._load_with(project, {"amount": "Amount"})

    def test_key_must_be_a_legal_name(self, project):
        with pytest.raises(ValueError, match="not a legal series key") as excinfo:
            self._load_with(project, {"10Y 2Y Spread": {}})
        assert "column = '10Y 2Y Spread'" in str(excinfo.value)

    def test_one_column_is_one_series(self, project):
        with pytest.raises(ValueError, match="both name the column 'value'"):
            self._load_with(
                project, {"a": {"column": "value"}, "b": {"column": "value"}}
            )

    def test_docs_and_docs_path_exclude_each_other(self, project):
        with pytest.raises(ValueError, match="both docs_path and docs"):
            self._load_with(project, {"amount": {"docs": "x", "docs_path": "y.md"}})

    def test_check_reports_a_missing_write_up(self, project, monkeypatch):
        self._load_with(project, {"amount": {"docs_path": "docs_src/series/amount.md"}})
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["check"])
        assert result.exit_code == 1
        assert "[dataframes.dataframe_0.series.amount] docs_path: file not found" in (
            result.output
        )


class TestGlobDataframe:
    def test_hash_covers_every_part_file(self, tmp_path):
        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        (record,) = _of_kind(_build(project), "Dataframe")
        resolved = record["location"]["resolved_path"]
        assert "*" in record["location"]["path"]
        expected = hashing.hash_path(resolved)
        assert len(expected.files) > 1
        assert record["content_hash"] == expected.content_hash
        assert record["size_bytes"] == expected.size_bytes
        assert record["row_count"] == pl.scan_parquet(resolved).select(pl.len()).collect().item()
        assert "files" not in record


class TestDeterminism:
    def test_two_builds_differ_only_in_generated_at(self, catalog_project):
        first = _build(catalog_project)
        second = _build(catalog_project)
        first.pop("generated_at")
        second.pop("generated_at")
        assert json.dumps(first) == json.dumps(second)

    def test_reordering_the_manifest_does_not_reorder_the_index(self, project):
        _edit_toml(
            project,
            lambda c: c["dataframes"]["dataframe_0"].update(zeta="z", alpha="a"),
        )
        before = _build(project, generated_at=datetime.datetime(2026, 1, 1))

        def reverse(config):
            for table in ("dataframes", "charts"):
                for name, entry in config[table].items():
                    config[table][name] = dict(reversed(list(entry.items())))

        _edit_toml(project, reverse)
        after = _build(project, generated_at=datetime.datetime(2026, 1, 1))
        assert json.dumps(before) == json.dumps(after)

    def test_assets_are_in_kind_then_name_order(self, tmp_path):
        project = create_pipeline_project(
            tmp_path / "many", dataframe_count=2, charts_per_dataframe=2
        )
        (pipeline,) = _of_kind(_build(project), "Pipeline")
        assert pipeline["assets"] == [
            "test_pipeline:dataframe_0",
            "test_pipeline:dataframe_1",
            "test_pipeline:chart/chart_0_0",
            "test_pipeline:chart/chart_0_1",
            "test_pipeline:chart/chart_1_0",
            "test_pipeline:chart/chart_1_1",
        ]


class TestCatalog:
    def test_catalog_record_comes_first(self, catalog_project):
        built = _build(catalog_project)
        catalog = built["records"][0]
        assert catalog["kind"] == "Catalog"
        assert catalog["id"] == built["root"]
        assert catalog["pipelines"] == ["pipeline_a", "pipeline_b"]
        assert catalog["policy"]["mode"] == "warn"
        assert "dataframes" in catalog["policy"]["required"]

    def test_has_every_pipelines_records(self, catalog_project):
        built = _build(catalog_project)
        assert [r["id"] for r in _of_kind(built, "Pipeline")] == [
            "pipeline_a",
            "pipeline_b",
        ]
        assert [r["id"] for r in _of_kind(built, "Dataframe")] == [
            "pipeline_a:dataframe_0",
            "pipeline_b:dataframe_0",
        ]

    def test_ids_are_unique(self, catalog_project):
        ids = [r["id"] for r in _build(catalog_project)["records"]]
        assert len(ids) == len(set(ids))

    def test_skipped_pipelines_are_left_out(self, catalog_project):
        built = _build(catalog_project, skip_pipelines={"pipeline_b"})
        assert built["records"][0]["pipelines"] == ["pipeline_a"]
        assert not [r for r in built["records"] if r.get("pipeline") == "pipeline_b"]

    def test_a_catalog_key_is_the_pipelines_id(self, catalog_project):
        """A catalog may register a pipeline under a scoped ID of its choosing."""

        def edit(config):
            config["pipelines"]["acme/rates"] = config["pipelines"].pop("pipeline_a")

        _edit_toml(catalog_project, edit)
        built = _build(catalog_project)
        assert "acme/rates:dataframe_0" in [r["id"] for r in built["records"]]


class TestPublished:
    def test_no_machine_specific_paths(self, catalog_project):
        built = _build(catalog_project)
        public = index.published(built)
        text = json.dumps(public)
        assert "resolved_path" not in text
        assert str(Path(catalog_project).resolve()) not in text
        for record in _of_kind(public, "Pipeline"):
            assert record["location"] == {"kind": "path"}

    def test_everything_else_is_unchanged(self, project):
        built = _build(project)
        public = index.published(built)
        full = _by_id(built, "notes_pipeline:dataframe_0")
        shown = _by_id(public, "notes_pipeline:dataframe_0")
        assert "resolved_path" in full["location"]
        assert shown["location"] == {"kind": "file", "path": full["location"]["path"]}
        assert {k: v for k, v in shown.items() if k != "location"} == (
            {k: v for k, v in full.items() if k != "location"}
        )
        assert public["generated_at"] == built["generated_at"]


class TestSchemas:
    @pytest.mark.parametrize("name", ["index", *KINDS])
    def test_each_schema_is_a_valid_schema(self, name):
        schema = json.loads(index.schema_path(name).read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["$id"].endswith(
            "index/v1.json" if name == "index" else f"v1/{name}.json"
        )

    def test_a_pipelines_index_validates(self, tmp_path):
        project = create_pipeline_project(tmp_path / "all", include_notes=True)
        _add_notebook(project)

        def edit(config):
            config["dataframes"]["dataframe_0"]["series"] = {
                "rate": {"name": "Rate", "column": "value", "units": "Percent"}
            }

        _edit_toml(project, edit)
        built = _build(project)
        assert {r["kind"] for r in built["records"]} == set(KINDS) - {"Catalog"}
        _validate(built)
        _validate(index.published(built))

    def test_a_catalogs_index_validates(self, catalog_project):
        built = _build(catalog_project)
        _validate(built)
        _validate(index.published(built))

    def test_an_index_of_unbuilt_files_validates(self, project):
        (project / "_data" / "notes_pipeline" / "dataframe_0.parquet").unlink()
        _validate(_build(project))

    def test_the_schemas_do_reject_something(self, project):
        built = _build(project)
        del _by_id(built, "notes_pipeline:dataframe_0")["ref"]
        with pytest.raises(jsonschema.ValidationError):
            _validate(built)


class TestDtypeName:
    @pytest.mark.parametrize(
        "dtype,name",
        [
            (pl.Float64(), "float64"),
            (pl.Int32(), "int32"),
            (pl.String(), "string"),
            (pl.Boolean(), "boolean"),
            (pl.Date(), "date"),
            (pl.Datetime("ns"), "datetime[ns]"),
            (pl.Datetime("us", "UTC"), "datetime[us, UTC]"),
            (pl.Duration("ms"), "duration[ms]"),
            (pl.Decimal(10, 2), "decimal[10,2]"),
            (pl.List(pl.Int64), "list[int64]"),
            (pl.List(pl.List(pl.String)), "list[list[string]]"),
            (pl.Categorical(), "categorical"),
            (pl.Struct({"a": pl.Int8}), "struct"),
        ],
    )
    def test_names(self, dtype, name):
        assert index.dtype_name(dtype) == name


class TestWriteIndex:
    def test_round_trip(self, project, tmp_path):
        built = _build(project)
        path = index.write_index(built, tmp_path / "out" / "index.json")
        assert json.loads(path.read_text()) == built
        assert path.read_text().endswith("}\n")

    def test_an_index_that_only_differs_in_time_is_left_alone(self, project, tmp_path):
        path = tmp_path / "index.json"
        index.write_index(_build(project, generated_at=datetime.datetime(2026, 1, 1)), path)
        before = path.read_bytes()

        later = _build(project, generated_at=datetime.datetime(2026, 6, 1))
        index.write_index(later, path, only_if_changed=True)
        assert path.read_bytes() == before

        index.write_index(later, path)
        assert path.read_bytes() != before

    def test_a_changed_index_is_written_with_its_new_time(self, project, tmp_path):
        path = tmp_path / "index.json"
        index.write_index(_build(project, generated_at=datetime.datetime(2026, 1, 1)), path)
        _edit_toml(
            project, lambda c: c["dataframes"]["dataframe_0"].update(name="Renamed")
        )
        changed = _build(project, generated_at=datetime.datetime(2026, 6, 1))
        index.write_index(changed, path, only_if_changed=True)
        written = json.loads(path.read_text())
        assert written["generated_at"] == changed["generated_at"]
        assert _by_id(written, "notes_pipeline:dataframe_0")["name"] == "Renamed"

    @pytest.mark.parametrize("content", ["", "not json", "[]"])
    def test_an_unreadable_file_is_replaced(self, project, tmp_path, content):
        path = tmp_path / "index.json"
        path.write_text(content)
        built = _build(project)
        index.write_index(built, path, only_if_changed=True)
        assert json.loads(path.read_text()) == built


class TestBuildWritesTheIndex:
    """``chartbook build`` writes ``index.json`` beside the HTML."""

    def test_published_index_is_beside_the_html(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 0, result.output

        built = json.loads((pipeline_project / "docs" / "index.json").read_text())
        _validate(built)
        assert built["root"] == "test_pipeline"
        assert "test_pipeline:dataframe_0" in [r.get("id") for r in built["records"]]
        text = json.dumps(built)
        assert "resolved_path" not in text
        assert str(pipeline_project.resolve()) not in text
        # The build directory is gone, and the full index with it
        assert not (pipeline_project / "_docs").exists()

    def test_full_index_stays_in_a_kept_build_directory(
        self, pipeline_project, monkeypatch
    ):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output

        full = json.loads((pipeline_project / "_docs" / "index.json").read_text())
        record = _by_id(full, "test_pipeline:dataframe_0")
        assert Path(record["location"]["resolved_path"]).is_file()
        assert (pipeline_project / "_docs" / hashing.CACHE_FILE).is_file()
        public = json.loads((pipeline_project / "docs" / "index.json").read_text())
        assert public == index.published(full)

    def test_incremental_builds_keep_it_current(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        runner = CliRunner()
        published = pipeline_project / "docs" / "index.json"

        first = runner.invoke(main, ["build", "./docs", "-f", "--incremental"])
        assert first.exit_code == 0, first.output
        before = json.loads(published.read_text())

        # Nothing changed: the same index, read from the hash cache
        reads = []
        real = hashing._file_hex
        monkeypatch.setattr(
            hashing, "_file_hex", lambda path: (reads.append(path), real(path))[1]
        )
        untouched = published.read_bytes()
        second = runner.invoke(main, ["build", "./docs", "-f", "--incremental"])
        assert second.exit_code == 0, second.output
        assert reads == []
        # ...and since it says nothing new, the file is not rewritten at all
        assert published.read_bytes() == untouched

        # The data changes: only that file is read, and its hash moves
        parquet = pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet"
        pl.DataFrame({"date": [datetime.date(2021, 5, 5)], "value": [1]}).write_parquet(
            parquet
        )
        third = runner.invoke(main, ["build", "./docs", "-f", "--incremental"])
        assert third.exit_code == 0, third.output
        after = json.loads(published.read_text())
        assert [Path(p).name for p in reads] == ["dataframe_0.parquet"]
        changed = _by_id(after, "test_pipeline:dataframe_0")
        assert changed["content_hash"] != _by_id(before, "test_pipeline:dataframe_0")[
            "content_hash"
        ]
        assert changed["row_count"] == 1
        assert (pipeline_project / "_docs" / "index.json").is_file()

    def test_catalog_build_writes_one_index_for_all(self, catalog_project, monkeypatch):
        monkeypatch.chdir(catalog_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        built = json.loads((catalog_project / "docs" / "index.json").read_text())
        _validate(built)
        assert built["records"][0]["kind"] == "Catalog"
        assert [r["id"] for r in _of_kind(built, "Pipeline")] == [
            "pipeline_a",
            "pipeline_b",
        ]
