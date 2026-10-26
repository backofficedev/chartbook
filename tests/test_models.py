"""Tests for models as assets: ``[models]``, ``chartbook.models``, the model
page, the ``Model`` record, and ``check``.

The design is ``docs_src/design/models.md``; this is its first slice,
"declared models". Versions, labels and parts are not built and not tested.
"""

import json
import os
import re
from pathlib import Path

import jsonschema
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import assets, data, hashing, index, models
from chartbook.check import run_checks
from chartbook.cli import main
from chartbook.diagnostics import build_diagnostics
from chartbook.errors import AssetNotDeclaredError, DependencyNotDeclaredError
from chartbook.identity import UnsupportedRevisionError
from chartbook.incremental import pipeline_fingerprint, pipeline_owned_paths
from chartbook.manifest import load_manifest, resolve_project_type
from chartbook.refs import AssetRef, KindMismatchError
from chartbook.resolve import UnsupportedReferenceError
from tests.fixtures import create_catalog_project, create_pipeline_project
from tests.fixtures import remove_tree

METRICS = {"rmse": 0.2123456789, "mae": 0.17, "n_train": 5120, "converged": True}


def _edit_toml(project_dir: Path, edit) -> None:
    """Load a project's chartbook.toml, apply ``edit(config)``, write it back."""
    toml_path = Path(project_dir) / "chartbook.toml"
    config = tomli.loads(toml_path.read_text(encoding="utf-8"))
    edit(config)
    toml_path.write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")


def add_models(project_dir: Path) -> Path:
    """Give a pipeline two models: one a file with everything, one a bare directory.

    ``forecaster`` is a file with a name, a write-up, scores and the
    dataframe it was trained on. ``encoder`` is a directory of two files
    with nothing declared but its path.
    """
    project_dir = Path(project_dir)
    (project_dir / "_models" / "encoder" / "weights").mkdir(parents=True)
    (project_dir / "_models" / "encoder" / "config.json").write_text("{}", encoding="utf-8", newline="\n")
    (project_dir / "_models" / "encoder" / "weights" / "best.pt").write_bytes(b"w" * 3000)
    (project_dir / "_models" / "forecaster.json").write_text('{"slope": 0.99}', encoding="utf-8", newline="\n")
    (project_dir / "_output").mkdir(exist_ok=True)
    (project_dir / "_output" / "forecaster_metrics.json").write_text(json.dumps(METRICS), encoding="utf-8", newline="\n")
    (project_dir / "docs_src" / "models").mkdir(parents=True, exist_ok=True)
    (project_dir / "docs_src" / "models" / "forecaster.md").write_text(
        "Predicts the rate, **for testing**.\n", encoding="utf-8", newline="\n"
    )

    def edit(config):
        config["models"] = {
            "forecaster": {
                "name": "Rate Forecaster",
                "description": "Forecasts the rate one month ahead.",
                "path": "./_models/forecaster.json",
                "trained_on": ["dataframe_0"],
                "metrics_path": "./_output/forecaster_metrics.json",
                "docs_path": "docs_src/models/forecaster.md",
                "tags": ["forecast"],
            },
            "encoder": {"path": "./_models/encoder"},
        }

    _edit_toml(project_dir, edit)
    return project_dir


@pytest.fixture
def project(pipeline_project):
    """The ``test_pipeline`` fixture pipeline, with two models."""
    return add_models(pipeline_project.resolve())


def _page_text(html_file: Path) -> str:
    """The readable text of a built page's article."""
    page = html_file.read_text(encoding="utf-8")
    article = page[page.find("<article") : page.find("</article>")]
    article = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", article, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", article))


class TestModelsTable:
    """``[models.<id>]`` as the manifest loader reads it."""

    def _load_with(self, project, **fields):
        def edit(config):
            config["models"] = {"m": {"path": "./_models/m.json", **fields}}

        _edit_toml(project, edit)
        return load_manifest(project)["models"]["m"]

    def test_only_a_path_is_required(self, pipeline_project):
        model = self._load_with(pipeline_project)
        assert model["_resolved_path"] == pipeline_project / "_models" / "m.json"
        assert model["_trained_on"] == []

    def test_trained_on_names_this_pipelines_dataframes(self, pipeline_project):
        model = self._load_with(pipeline_project, trained_on=["dataframe_0"])
        assert model["_trained_on"] == [AssetRef(name="dataframe_0")]
        explicit = self._load_with(pipeline_project, trained_on=["dataframe/dataframe_0"])
        assert explicit["_trained_on"] == [AssetRef(name="dataframe_0")]

    def test_trained_on_another_pipelines_dataframe(self, pipeline_project):
        """Taken as written, when the other pipeline is a declared dependency."""
        _edit_toml(
            pipeline_project,
            lambda c: c.update(dependencies={"acme/rates": {"path": "../rates"}}),
        )
        model = self._load_with(
            pipeline_project,
            trained_on=["dataframe_0", "rates:treasury", "acme/rates:treasury"],
        )
        assert [str(ref) for ref in model["_trained_on"]] == [
            "dataframe_0",
            "rates:treasury",
            "acme/rates:treasury",
        ]
        assert [ref.is_local for ref in model["_trained_on"]] == [True, False, False]

    def test_tags_are_normalized_like_everything_else(self, pipeline_project):
        assert self._load_with(pipeline_project, tags=["yield curve"])["tags"] == [
            "Yield Curve"
        ]

    def test_a_pipeline_without_models_has_an_empty_table(self, pipeline_project):
        assert load_manifest(pipeline_project)["models"] == {}

    def test_models_alone_make_a_manifest_a_pipeline(self):
        raw = {"models": {"m": {"path": "./m.json"}}}
        assert resolve_project_type(raw) == "pipeline"

    def test_path_is_required(self, pipeline_project):
        with pytest.raises(ValueError, match=r"\[models.m\] has no 'path'"):
            self._load_with(pipeline_project, path="")

    def test_key_must_be_a_legal_name(self, pipeline_project):
        _edit_toml(
            pipeline_project,
            lambda c: c.update(models={"two words": {"path": "./m.json"}}),
        )
        with pytest.raises(ValueError, match="not a legal model key"):
            load_manifest(pipeline_project)

    def test_trained_on_must_be_a_list(self, pipeline_project):
        with pytest.raises(ValueError, match="must be a list of dataframes"):
            self._load_with(pipeline_project, trained_on="dataframe_0")

    def test_trained_on_an_undeclared_dataframe(self, pipeline_project):
        with pytest.raises(ValueError) as excinfo:
            self._load_with(pipeline_project, trained_on=["nope"])
        message = str(excinfo.value)
        assert "[models.m]: trained_on names the dataframe 'nope'" in message
        assert "dataframe_0" in message
        assert "write '<pipeline>:nope'" in message

    def test_trained_on_something_that_is_not_a_dataframe(self, pipeline_project):
        with pytest.raises(ValueError, match="A model is trained on dataframes"):
            self._load_with(pipeline_project, trained_on=["chart/chart_0_0"])

    @pytest.mark.parametrize("reference", ["dataframe_0#value", "rates:treasury#dgs10"])
    def test_trained_on_a_series_is_reserved(self, pipeline_project, reference):
        with pytest.raises(UnsupportedReferenceError, match="not yet supported") as e:
            self._load_with(pipeline_project, trained_on=[reference])
        assert str(e.value).startswith("[models.m]: trained_on:")

    def test_trained_on_another_pipelines_chart_is_refused(self, pipeline_project):
        with pytest.raises(ValueError, match="A model is trained on dataframes"):
            self._load_with(pipeline_project, trained_on=["rates:chart/curve"])

    def test_trained_on_a_version_is_reserved(self, pipeline_project):
        with pytest.raises(UnsupportedRevisionError, match="not yet supported"):
            self._load_with(pipeline_project, trained_on=["dataframe_0@v2"])

    def test_docs_and_docs_path_exclude_each_other(self, pipeline_project):
        with pytest.raises(ValueError, match="both docs_path and docs"):
            self._load_with(pipeline_project, docs="x", docs_path="y.md")

    def test_a_write_up_is_optional(self, pipeline_project):
        assert "docs" not in self._load_with(pipeline_project)

    def test_metrics_path_must_be_a_path(self, pipeline_project):
        with pytest.raises(ValueError, match="'metrics_path' must be a path"):
            self._load_with(pipeline_project, metrics_path=3)

    def test_must_be_a_table_of_tables(self, pipeline_project):
        _edit_toml(pipeline_project, lambda c: c.update(models={"m": "./m.json"}))
        with pytest.raises(ValueError, match="must be a table"):
            load_manifest(pipeline_project)


class TestPath:
    def test_models_path(self, project):
        assert models.path("forecaster", project_dir=project) == (
            project / "_models" / "forecaster.json"
        )

    def test_is_assets_path_with_the_kind_fixed(self, project):
        expected = models.path("forecaster", project_dir=project)
        assert assets.path("model/forecaster", project_dir=project) == expected
        assert assets.path("forecaster", kind="model", project_dir=project) == expected
        assert models.path("model/forecaster", project_dir=project) == expected

    def test_a_directory_model(self, project):
        path = models.path("encoder", project_dir=project)
        assert path == project / "_models" / "encoder"
        assert path.is_dir()

    def test_the_file_need_not_exist(self, project):
        (project / "_models" / "forecaster.json").unlink()
        assert not models.path("forecaster", project_dir=project).exists()

    def test_calling_file_wins_over_cwd(self, project, tmp_path, monkeypatch):
        import runpy

        script = project / "src" / "where.py"
        script.write_text(
            "from chartbook import models\nRESULT = models.path('forecaster')\n", encoding="utf-8", newline="\n"
        )
        monkeypatch.chdir(tmp_path)
        assert runpy.run_path(str(script))["RESULT"] == (
            project / "_models" / "forecaster.json"
        )

    def test_undeclared_model_names_the_table_to_add(self, project):
        with pytest.raises(AssetNotDeclaredError) as excinfo:
            models.path("classifier", project_dir=project)
        message = str(excinfo.value)
        assert "No model named 'classifier' is declared" in message
        assert "[models.classifier]" in message
        assert "models: encoder, forecaster" in message

    def test_a_dataframes_name_is_not_a_model(self, project):
        with pytest.raises(AssetNotDeclaredError, match="declared as a dataframe"):
            models.path("dataframe_0", project_dir=project)

    def test_models_path_refuses_another_kind(self, project):
        with pytest.raises(KindMismatchError) as excinfo:
            models.path("chart/chart_0_0", project_dir=project)
        assert "models.path() answers for models only" in str(excinfo.value)

    def test_data_path_refuses_a_model(self, project):
        with pytest.raises(KindMismatchError, match="names a model"):
            data.path("model/forecaster", project_dir=project)
        with pytest.raises(AssetNotDeclaredError, match="declared as a model"):
            data.path("forecaster", project_dir=project)

    def test_parts_are_not_yet_supported_and_a_version_has_to_exist(self, project):
        """Versions resolve now (tests/test_model_versions.py). This project has none."""
        from chartbook.errors import VersionNotFoundError

        with pytest.raises(VersionNotFoundError):
            models.path("forecaster@champion", project_dir=project)
        with pytest.raises(UnsupportedReferenceError):
            models.path("encoder#weights/best.pt", project_dir=project)

    def test_is_exported_from_the_package(self):
        import chartbook

        assert chartbook.models is models

    def test_command_line(self, project, monkeypatch):
        monkeypatch.chdir(project)
        runner = CliRunner()
        by_prefix = runner.invoke(main, ["path", "model/forecaster"])
        by_option = runner.invoke(main, ["path", "forecaster", "--kind", "model"])
        assert by_prefix.exit_code == 0, by_prefix.output
        assert by_prefix.stdout == f"{project / '_models' / 'forecaster.json'}\n"
        assert by_option.stdout == by_prefix.stdout


class TestReadMetrics:
    def _write(self, tmp_path, content) -> Path:
        path = tmp_path / "metrics.json"
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8", newline="\n")
        return path

    def test_flat_object_of_scores(self, tmp_path):
        scores = {"rmse": 0.2, "n": 10, "note": "holdout", "converged": True}
        assert models.read_metrics(self._write(tmp_path, scores)) == scores

    def test_not_json(self, tmp_path):
        with pytest.raises(ValueError, match="is not valid JSON"):
            models.read_metrics(self._write(tmp_path, "rmse: 0.2"))

    def test_not_an_object(self, tmp_path):
        with pytest.raises(ValueError, match="must hold one JSON object"):
            models.read_metrics(self._write(tmp_path, [0.2, 0.3]))

    def test_nested_values_are_refused(self, tmp_path):
        nested = {"rmse": 0.2, "confusion": [[1, 2], [3, 4]], "by_class": {"a": 1}}
        with pytest.raises(ValueError) as excinfo:
            models.read_metrics(self._write(tmp_path, nested))
        assert "'confusion', 'by_class' must be a number" in str(excinfo.value)

    def test_missing_file(self, tmp_path):
        with pytest.raises(OSError):
            models.read_metrics(tmp_path / "nope.json")


class TestModelRecord:
    def _models(self, built) -> dict:
        return {r["ref"]["name"]: r for r in built["records"] if r["kind"] == "Model"}

    def _validate(self, record) -> None:
        schema = json.loads(index.schema_path("Model").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(record)

    def test_a_file_model(self, project):
        built = index.build_index(load_manifest(project))
        record = self._models(built)["forecaster"]
        model_file = project / "_models" / "forecaster.json"
        assert record["id"] == "test_pipeline:model/forecaster"
        assert record["ref"] == {
            "pipeline": "test_pipeline",
            "kind": "model",
            "name": "forecaster",
        }
        assert record["name"] == "Rate Forecaster"
        assert {k: v for k, v in record["location"].items() if k != "modified_at"} == {
            "kind": "file",
            "path": "./_models/forecaster.json",
            "resolved_path": str(model_file),
        }
        assert record["content_hash"] == hashing.hash_file(model_file).content_hash
        assert record["size_bytes"] == model_file.stat().st_size
        assert record["inputs"] == ["test_pipeline:dataframe_0"]
        assert record["metrics"] == METRICS
        assert record["tags"] == ["Forecast"]
        assert record["docs"]["path"] == "docs_src/models/forecaster.md"
        assert record["docs"]["content_hash"].startswith("sha256:")
        assert "files" not in record
        self._validate(record)

    def test_what_the_record_restates_is_not_repeated(self, project):
        record = self._models(index.build_index(load_manifest(project)))["forecaster"]
        for restated in ("trained_on", "path", "docs_path"):
            assert restated not in record
        # Where the scores come from stays as declared (a policy may require it);
        # `metrics` holds what the file said
        assert record["metrics_path"] == "./_output/forecaster_metrics.json"

    def test_a_directory_model_lists_its_files(self, project):
        record = self._models(index.build_index(load_manifest(project)))["encoder"]
        expected = hashing.hash_directory(project / "_models" / "encoder")
        assert record["content_hash"] == expected.content_hash
        assert record["size_bytes"] == 3002
        assert record["files"] == [
            {
                "path": "config.json",
                "size_bytes": 2,
                "content_hash": hashing.hash_file(
                    project / "_models" / "encoder" / "config.json"
                ).content_hash,
            },
            {
                "path": "weights/best.pt",
                "size_bytes": 3000,
                "content_hash": expected.files[1].content_hash,
            },
        ]
        self._validate(record)

    def test_undeclared_things_are_absent(self, project):
        record = self._models(index.build_index(load_manifest(project)))["encoder"]
        for absent in ("name", "inputs", "metrics", "docs", "tags"):
            assert absent not in record

    def test_trained_on_nothing_is_present_and_empty(self, project):
        _edit_toml(project, lambda c: c["models"]["encoder"].update(trained_on=[]))
        record = self._models(index.build_index(load_manifest(project)))["encoder"]
        assert record["inputs"] == []

    def test_a_model_not_built_yet(self, project):
        (project / "_models" / "forecaster.json").unlink()
        (project / "_output" / "forecaster_metrics.json").unlink()
        record = self._models(index.build_index(load_manifest(project)))["forecaster"]
        assert record["location"]["path"] == "./_models/forecaster.json"
        for absent in ("content_hash", "size_bytes", "metrics"):
            assert absent not in record
        assert record["inputs"] == ["test_pipeline:dataframe_0"]
        self._validate(record)

    def test_malformed_metrics_are_left_out_with_a_warning(self, project):
        (project / "_output" / "forecaster_metrics.json").write_text('{"a": [1, 2]}', encoding="utf-8", newline="\n")
        with pytest.warns(UserWarning, match=r"\[models.forecaster\]: its metrics"):
            built = index.build_index(load_manifest(project))
        assert "metrics" not in self._models(built)["forecaster"]

    def test_models_are_among_the_pipelines_assets_after_the_rest(self, project):
        built = index.build_index(load_manifest(project))
        (pipeline,) = [r for r in built["records"] if r["kind"] == "Pipeline"]
        assert pipeline["assets"] == [
            "test_pipeline:dataframe_0",
            "test_pipeline:chart/chart_0_0",
            "test_pipeline:model/encoder",
            "test_pipeline:model/forecaster",
        ]

    def test_published_index_validates_and_has_no_local_path(self, project):
        public = index.published(index.build_index(load_manifest(project)))
        for record in self._models(public).values():
            assert "resolved_path" not in record["location"]
            self._validate(record)
        assert str(project) not in json.dumps(public)

    def test_scoped_pipeline(self, project):
        _edit_toml(project, lambda c: c["project"].update(id="acme/rates"))
        record = self._models(index.build_index(load_manifest(project)))["forecaster"]
        assert record["id"] == "acme/rates:model/forecaster"
        assert record["inputs"] == ["acme/rates:dataframe_0"]


class TestModelPage:
    """A built site has a page per model."""

    @pytest.fixture
    def site(self, project, monkeypatch):
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        return project / "docs"

    def test_page_of_a_documented_model(self, site):
        text = _page_text(site / "cb" / "models" / "test_pipeline" / "forecaster.html")
        assert "Model: test_pipeline:model/forecaster - Rate Forecaster" in text
        assert "Model updated" in text
        assert "Predicts the rate, for testing ." in text
        assert "Scores" in text
        assert "rmse 0.212346" in text
        assert "n_train 5120" in text
        assert "converged true" in text
        assert "Trained On" in text
        assert "test_pipeline:dataframe_0 - Dataframe 0" in text
        assert "chartbook path model/forecaster" in text
        assert "./_models/forecaster.json" in text
        assert "Files" not in text

    def test_it_links_to_the_dataframe_it_was_trained_on(self, site):
        page = (site / "cb" / "models" / "test_pipeline" / "forecaster.html").read_text(encoding="utf-8")
        assert 'href="../../dataframes/test_pipeline/dataframe_0.html"' in page
        assert (site / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.html").is_file()

    def test_page_of_a_bare_directory_model(self, site):
        text = _page_text(site / "cb" / "models" / "test_pipeline" / "encoder.html")
        assert "Model: test_pipeline:model/encoder - encoder" in text
        assert "Not declared" in text
        assert "Files" in text
        assert "config.json 2 bytes" in text
        assert "weights/best.pt 2.9 KB" in text
        assert "Scores" not in text

    def test_the_page_shows_no_local_path(self, site, project):
        page = (site / "cb" / "models" / "test_pipeline" / "forecaster.html").read_text(encoding="utf-8")
        article = page[page.find("<article") : page.find("</article>")]
        assert str(project / "_models") not in article

    def test_the_pipelines_front_page_lists_its_models(self, site):
        front = (site / "index.html").read_text(encoding="utf-8")
        assert "Pipeline Models" in front
        assert 'href="cb/models/test_pipeline/forecaster.html"' in front
        assert 'href="cb/models/test_pipeline/encoder.html"' in front

    def test_a_pipeline_without_models_is_unchanged(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert "Pipeline Models" not in (pipeline_project / "docs" / "index.html").read_text(encoding="utf-8")
        assert not (pipeline_project / "docs" / "cb" / "models").exists()

    def test_malformed_metrics_do_not_break_the_build(self, project, monkeypatch):
        (project / "_output" / "forecaster_metrics.json").write_text("not json", encoding="utf-8", newline="\n")
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        text = _page_text(
            project / "docs" / "cb" / "models" / "test_pipeline" / "forecaster.html"
        )
        assert "Scores" not in text


class TestCatalogSite:
    def _build(self, catalog, monkeypatch):
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        return catalog / "docs"

    def test_catalog_lists_models_across_pipelines(self, tmp_path, monkeypatch):
        catalog = create_catalog_project(tmp_path / "cat")
        add_models(catalog / "pipelines" / "pipeline_a")
        site = self._build(catalog, monkeypatch)

        listing = (site / "cb" / "models.html").read_text(encoding="utf-8")
        assert 'href="models/pipeline_a/forecaster.html"' in listing
        assert (site / "cb" / "models" / "pipeline_a" / "forecaster.html").is_file()
        assert "Models" in (site / "index.html").read_text(encoding="utf-8")
        assert not (site / "cb" / "models" / "pipeline_b").exists()

        built = json.loads((site / "index.json").read_text(encoding="utf-8"))
        assert [r["id"] for r in built["records"] if r["kind"] == "Model"] == [
            "pipeline_a:model/encoder",
            "pipeline_a:model/forecaster",
        ]

    def test_a_catalog_without_models_has_no_models_page(self, catalog_project, monkeypatch):
        site = self._build(catalog_project, monkeypatch)
        assert not (site / "cb" / "models.html").exists()
        assert "cb/models" not in (site / "index.html").read_text(encoding="utf-8")


class TestCheck:
    def _problems(self, project, **kwargs):
        manifest = load_manifest(project)
        return [
            (p.table, p.field, p.message)
            for p in run_checks(manifest, project, **kwargs)
            if p.table.startswith("models.")
        ]

    def test_missing_files_are_reported_by_field(self, project):
        (project / "_models" / "forecaster.json").unlink()
        (project / "_output" / "forecaster_metrics.json").unlink()
        (project / "docs_src" / "models" / "forecaster.md").unlink()
        found = {(table, field) for table, field, _ in self._problems(project)}
        assert ("models.forecaster", "path") in found
        assert ("models.forecaster", "metrics_path") in found
        assert ("models.forecaster", "docs_path") in found

    def test_skip_outputs_leaves_out_what_training_produces(self, project):
        (project / "_models" / "forecaster.json").unlink()
        (project / "_output" / "forecaster_metrics.json").unlink()
        (project / "docs_src" / "models" / "forecaster.md").unlink()
        found = {
            (table, field)
            for table, field, _ in self._problems(project, skip_outputs=True)
            if table == "models.forecaster"
        }
        # The write-up is kept in the repository; the model and its scores are built
        assert found == {("models.forecaster", "docs_path")}

    def test_a_missing_directory_model(self, project):
        import shutil

        remove_tree(project / "_models" / "encoder")
        assert ("models.encoder", "path") in {
            (table, field) for table, field, _ in self._problems(project)
        }

    def test_malformed_metrics_are_reported(self, project):
        (project / "_output" / "forecaster_metrics.json").write_text('{"curve": [1, 2]}', encoding="utf-8", newline="\n")
        (problem,) = [p for p in self._problems(project) if p[1] == "metrics_path"]
        assert "'curve' must be a number" in problem[2]

    def test_default_policy_recommends_lineage(self, project):
        missing = sorted(
            field for table, field, _ in self._problems(project) if table == "models.encoder"
        )
        assert missing == ["description", "docs", "name", "trained_on"]
        assert not [p for p in self._problems(project) if p[0] == "models.forecaster"]

    def test_a_write_up_counts_whichever_way_it_is_given(self, project):
        _edit_toml(project, lambda c: c["models"]["encoder"].update(docs="An encoder."))
        missing = [f for t, f, _ in self._problems(project) if t == "models.encoder"]
        assert "docs" not in missing

    def test_a_catalog_policy_can_set_what_models_require(self, tmp_path):
        catalog = create_catalog_project(tmp_path / "cat")
        add_models(catalog / "pipelines" / "pipeline_a")

        def edit(config):
            config.setdefault("policy", {})["required"] = {"models": ["name", "owner"]}

        _edit_toml(catalog, edit)
        manifest = load_manifest(catalog)
        assert manifest["policy"]["required"]["models"] == ["name", "owner"]
        found = sorted(
            (p.table, p.field)
            for p in run_checks(manifest, catalog)
            if p.table.startswith("models.")
        )
        assert found == [
            ("models.encoder", "name"),
            ("models.encoder", "owner"),
            ("models.forecaster", "owner"),
        ]

    def test_summary_counts_models_only_where_there_are_some(
        self, pipeline_project, monkeypatch
    ):
        def complete(config):
            config["project"].update(
                description="d", build="doit", os_compatibility=["Linux"],
                repo_url="https://example.com/r", contributors=["A"], maintainer="A",
            )  # fmt: skip
            config["dataframes"]["dataframe_0"].update(
                provider_links=["https://example.com"], pull_method="API"
            )
            config["charts"]["chart_0_0"].update(
                frequency="Daily", observation_period="Day", release_lag="None",
                release_timing="Daily", units="Percent",
            )  # fmt: skip

        _edit_toml(pipeline_project, complete)
        monkeypatch.chdir(pipeline_project)
        without = CliRunner().invoke(main, ["check"])
        assert without.exit_code == 0, without.output
        assert "models" not in without.output

        add_models(pipeline_project)
        _edit_toml(
            pipeline_project,
            lambda c: c["models"]["encoder"].update(
                name="Encoder", description="d", trained_on=["dataframe_0"], docs="An encoder."
            ),
        )
        with_models = CliRunner().invoke(main, ["check"])
        assert with_models.exit_code == 0, with_models.output
        assert "1 notebooks, 2 models)" in with_models.output or (
            "0 notebooks, 2 models)" in with_models.output
        )

    def test_diagnostics_have_a_row_per_model(self, project):
        rows = {
            row.identifier: row
            for row in build_diagnostics(load_manifest(project))
            if row.object_type == "model"
        }
        assert set(rows) == {"forecaster", "encoder"}
        assert rows["forecaster"].metadata_complete
        assert rows["forecaster"].object_name == "Rate Forecaster"
        assert rows["forecaster"].page_link == "./models/test_pipeline/forecaster.html"
        assert rows["encoder"].missing_fields == "name, description, trained_on, docs"


class TestIncremental:
    def _fingerprint(self, project) -> str:
        manifest = load_manifest(project)
        return pipeline_fingerprint(manifest["project"]["id"], manifest)

    @staticmethod
    def _touch(path: Path, seconds: int = 60) -> None:
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 10**9))

    def test_a_models_files_are_build_inputs(self, project):
        before = self._fingerprint(project)
        self._touch(project / "_output" / "forecaster_metrics.json")
        after_metrics = self._fingerprint(project)
        assert after_metrics != before

        self._touch(project / "_models" / "forecaster.json")
        after_model = self._fingerprint(project)
        assert after_model != after_metrics

        self._touch(project / "docs_src" / "models" / "forecaster.md")
        assert self._fingerprint(project) != after_model

    def test_a_file_inside_a_directory_model_is_an_input(self, project):
        before = self._fingerprint(project)
        self._touch(project / "_models" / "encoder" / "weights" / "best.pt")
        changed = self._fingerprint(project)
        assert changed != before
        (project / "_models" / "encoder" / "vocab.txt").write_text("a b c", encoding="utf-8", newline="\n")
        assert self._fingerprint(project) != changed

    def test_model_pages_belong_to_their_pipeline(self, project):
        manifest = load_manifest(project)
        owned = pipeline_owned_paths("test_pipeline", manifest)
        assert Path("cb") / "models" / "test_pipeline" in owned

    def test_second_incremental_build_keeps_the_model_pages(self, project, monkeypatch):
        monkeypatch.chdir(project)
        runner = CliRunner()
        first = runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert first.exit_code == 0, first.output
        page = project / "_docs" / "cb" / "models" / "test_pipeline" / "forecaster.md"
        written_at = page.stat().st_mtime_ns

        second = runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert second.exit_code == 0, second.output
        assert "regenerated 0 of 1 pipeline(s)" in second.output
        assert page.stat().st_mtime_ns == written_at
        assert (project / "docs" / "cb" / "models" / "test_pipeline" / "forecaster.html").is_file()

    def test_new_scores_reach_the_page(self, project, monkeypatch):
        monkeypatch.chdir(project)
        runner = CliRunner()
        assert runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"]).exit_code == 0

        metrics_file = project / "_output" / "forecaster_metrics.json"
        metrics_file.write_text(json.dumps({"rmse": 0.05}), encoding="utf-8", newline="\n")
        self._touch(metrics_file)
        result = runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert result.exit_code == 0, result.output
        assert "regenerated 1 of 1 pipeline(s)" in result.output
        text = _page_text(
            project / "docs" / "cb" / "models" / "test_pipeline" / "forecaster.html"
        )
        assert "rmse 0.05" in text
        assert "n_train" not in text
        built = json.loads((project / "docs" / "index.json").read_text(encoding="utf-8"))
        (record,) = [r for r in built["records"] if r.get("id", "").endswith("forecaster")]
        assert record["metrics"] == {"rmse": 0.05}


def _scoped_catalog(tmp_path) -> Path:
    """A catalog that knows its two pipelines as ``acme/pipeline_a`` and ``acme/pipeline_b``."""
    catalog = create_catalog_project(tmp_path / "cat")

    def scope(config):
        for name in ("pipeline_a", "pipeline_b"):
            config["pipelines"][f"acme/{name}"] = config["pipelines"].pop(name)

    _edit_toml(catalog, scope)
    return catalog


class TestTrainedOnAnotherPipeline:
    """A model's training data may be another pipeline's dataframe.

    The other pipeline has to be one that ``[dependencies]`` declares. The
    input is then recorded, shown, linked where the other pipeline is in
    the same site, and checked. Declaring is tested in
    ``test_dependencies.py``, and reading the pinned copy in
    ``test_pinned_refs.py``.
    """

    def _add_model(self, pipeline_dir, trained_on, **dependencies):
        (pipeline_dir / "_models").mkdir(exist_ok=True)
        (pipeline_dir / "_models" / "m.json").write_text("{}", encoding="utf-8", newline="\n")

        def edit(config):
            config["models"] = {"m": {"path": "./_models/m.json", "trained_on": trained_on}}
            if dependencies:
                config["dependencies"] = dependencies

        _edit_toml(pipeline_dir, edit)

    def _model_record(self, built) -> dict:
        (record,) = [r for r in built["records"] if r["kind"] == "Model"]
        return record

    def test_a_pipeline_that_is_not_a_dependency_does_not_load(self, pipeline_project):
        self._add_model(pipeline_project, ["rates:treasury"])
        with pytest.raises(ValueError) as e:
            load_manifest(pipeline_project)
        message = str(e.value)
        assert "[models.m]: trained_on names 'rates:treasury'" in message
        assert "which [dependencies] does not declare" in message
        assert 'add "rates" = { path = "../rates" } under [dependencies]' in message

    def test_alone_the_input_is_recorded_by_the_dependencys_name(self, pipeline_project):
        self._add_model(
            pipeline_project,
            ["dataframe_0", "rates:treasury"],
            **{"acme/rates": {"path": "../rates"}},
        )
        record = self._model_record(index.build_index(load_manifest(pipeline_project)))
        assert record["inputs"] == ["test_pipeline:dataframe_0", "acme/rates:treasury"]

    def test_in_a_catalog_the_input_gets_the_id_it_has_there(self, tmp_path):
        catalog = _scoped_catalog(tmp_path)
        self._add_model(
            catalog / "pipelines" / "pipeline_a",
            ["pipeline_b:dataframe_0"],
            pipeline_b={"path": "../pipeline_b"},
        )
        built = index.build_index(load_manifest(catalog))
        record = self._model_record(built)
        assert record["id"] == "acme/pipeline_a:model/m"
        assert record["inputs"] == ["acme/pipeline_b:dataframe_0"]
        # ...which is the ID of a record in the same index
        assert "acme/pipeline_b:dataframe_0" in [r.get("id") for r in built["records"]]

    def test_a_catalog_page_links_to_the_other_pipelines_dataframe(
        self, tmp_path, monkeypatch
    ):
        catalog = _scoped_catalog(tmp_path)
        self._add_model(
            catalog / "pipelines" / "pipeline_a",
            ["pipeline_b:dataframe_0", "elsewhere:rates"],
            pipeline_b={"path": "../pipeline_b"},
            elsewhere={"git": "https://example.org/acme/elsewhere.git"},
        )
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output

        page_file = catalog / "docs" / "cb" / "models" / "acme--pipeline_a" / "m.html"
        page = page_file.read_text(encoding="utf-8")
        assert 'href="../../dataframes/acme--pipeline_b/dataframe_0.html"' in page
        assert (
            catalog / "docs" / "cb" / "dataframes" / "acme--pipeline_b" / "dataframe_0.html"
        ).is_file()
        text = _page_text(page_file)
        assert "acme/pipeline_b:dataframe_0 - Dataframe 0" in text
        assert "elsewhere:rates (in another pipeline, which is not part of this site)" in text

    def test_alone_the_page_names_it_without_a_link(self, pipeline_project, monkeypatch):
        self._add_model(pipeline_project, ["rates:treasury"], rates={"path": "../rates"})
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        page_file = pipeline_project / "docs" / "cb" / "models" / "test_pipeline" / "m.html"
        assert "rates:treasury (in another pipeline" in _page_text(page_file)
        assert "dataframes/rates" not in page_file.read_text(encoding="utf-8")

    def test_check_catches_a_dataframe_the_other_pipeline_does_not_have(self, tmp_path):
        catalog = _scoped_catalog(tmp_path)
        self._add_model(
            catalog / "pipelines" / "pipeline_a",
            ["pipeline_b:no_such_table"],
            pipeline_b={"path": "../pipeline_b"},
        )
        problems = [
            p
            for p in run_checks(load_manifest(catalog), catalog)
            if p.field == "trained_on" and "does not declare" in p.message
        ]
        (problem,) = problems
        assert problem.table == "models.m"
        assert "'pipeline_b:no_such_table'" in problem.message
        assert "'acme/pipeline_b'" in problem.message
        assert "dataframe_0" in problem.message

    def test_check_says_nothing_about_a_pipeline_it_cannot_see(self, pipeline_project):
        """A git dependency is not fetched, so there is no manifest to read."""
        self._add_model(
            pipeline_project,
            ["rates:treasury"],
            rates={"git": "https://example.org/acme/rates.git"},
        )
        assert not [
            p
            for p in run_checks(load_manifest(pipeline_project), pipeline_project)
            if "does not declare" in p.message
        ]

    def test_asking_for_a_model_in_an_undeclared_pipeline_says_what_to_add(
        self, pipeline_project
    ):
        with pytest.raises(DependencyNotDeclaredError, match=r"\$ chartbook pin"):
            models.path("rates:m", project_dir=pipeline_project)
        with pytest.raises(DependencyNotDeclaredError):
            data.path("rates:treasury", project_dir=pipeline_project)


class TestPolicy:
    """Who decides what a model must say: the defaults, a catalog, or the pipeline."""

    def _model_problems(self, project):
        return sorted(
            (p.table, p.field)
            for p in run_checks(load_manifest(project), project)
            if p.table.startswith("models.") and "required by" in p.message
        )

    def test_a_catalog_can_drop_the_write_up(self, tmp_path):
        catalog = create_catalog_project(tmp_path / "cat")
        add_models(catalog / "pipelines" / "pipeline_a")
        _edit_toml(
            catalog,
            lambda c: c.setdefault("policy", {}).update(required={"models": ["name"]}),
        )
        assert self._model_problems(catalog) == [("models.encoder", "name")]

    def test_a_pipeline_may_set_its_own_policy(self, project):
        """It applies when the pipeline is checked alone."""
        _edit_toml(project, lambda c: c.update(policy={"required": {"models": ["path"]}}))
        manifest = load_manifest(project)
        assert manifest["policy"]["mode"] == "warn"
        assert manifest["policy"]["required"]["models"] == ["path"]
        # Kinds it does not mention keep the default lists
        assert "sources" in manifest["policy"]["required"]["dataframes"]
        assert self._model_problems(project) == []

    def test_a_pipelines_policy_does_not_bind_the_catalog(self, tmp_path):
        catalog = create_catalog_project(tmp_path / "cat")
        pipeline = add_models(catalog / "pipelines" / "pipeline_a")
        _edit_toml(pipeline, lambda c: c.update(policy={"required": {"models": []}}))
        assert ("models.encoder", "name") in self._model_problems(catalog)

    def test_a_pipeline_with_a_policy_builds(self, project, monkeypatch):
        _edit_toml(project, lambda c: c.update(policy={"required": {"models": ["path"]}}))
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output

    def test_a_strict_pipeline_policy_fails_its_own_build(self, project, monkeypatch):
        _edit_toml(
            project,
            lambda c: c.update(
                policy={"mode": "strict", "required": {"models": ["name"]}}
            ),
        )
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 1
        assert "The policy is 'strict'" in result.output
        assert "model 'test_pipeline:encoder' missing: name" in result.output

    def test_an_invalid_pipeline_policy_is_refused(self, project):
        _edit_toml(project, lambda c: c.update(policy={"mode": "loud"}))
        with pytest.raises(ValueError, match="invalid policy.mode 'loud'"):
            load_manifest(project)
