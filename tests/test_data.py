"""Tests for chartbook.data — catalog-aware data loading."""

import warnings
from pathlib import Path

import polars as pl
import pytest

from chartbook import config, data
from chartbook.errors import CatalogNotConfiguredError


@pytest.fixture
def fake_config_dir(tmp_path, monkeypatch):
    """Redirect the global config directory to a temporary path."""
    fake_dir = tmp_path / ".chartbook_data_tests"
    monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
    monkeypatch.setattr(
        config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
    )
    return fake_dir


@pytest.fixture(autouse=True)
def published_catalogs(request):
    from tests.fixtures import publish_catalog
    for name in ("catalog_project", "catalog_project_inline_docs", "catalog_project_glob"):
        if name in request.fixturenames:
            publish_catalog(request.getfixturevalue(name))


# --- Loading with explicit catalog_path ---


def test_load_pandas(catalog_project):
    """Load as pandas DataFrame with explicit format and catalog_path."""
    import pandas as pd

    df = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="pandas",
        catalog_path=catalog_project,
    )
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0


def test_load_default_format_is_polars_lazyframe(catalog_project):
    """Default format returns polars LazyFrame."""
    result = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert len(df) > 0


def test_load_polars(catalog_project):
    """Load as polars LazyFrame with format='polars'."""
    lf = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="polars",
        catalog_path=catalog_project,
    )
    assert isinstance(lf, pl.LazyFrame)
    df = lf.collect()
    assert len(df) > 0


def test_load_polars_eager(catalog_project):
    """Load as polars eager DataFrame with format='polars_eager'."""
    df = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="polars_eager",
        catalog_path=catalog_project,
    )
    assert isinstance(df, pl.DataFrame)
    assert len(df) > 0


def test_load_polars_lazyframe_deprecated(catalog_project):
    """format='polars-lazyframe' emits deprecation warning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        lf = data.load(
            pipeline="pipeline_a",
            dataframe="dataframe_0",
            format="polars-lazyframe",
            catalog_path=catalog_project,
        )
        assert isinstance(lf, pl.LazyFrame)
        w = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
        assert len(w) == 1
        assert "deprecated" in str(w[0].message).lower()


# --- catalog_path as directory ---


def test_catalog_path_as_directory(catalog_project):
    """catalog_path can be a directory; chartbook.toml is inferred."""
    lf = data.load(
        pipeline="pipeline_b",
        dataframe="dataframe_0",
        catalog_path=catalog_project,  # directory, not file
    )
    assert isinstance(lf, pl.LazyFrame)


# --- Error cases ---


def test_pipeline_not_found(catalog_project):
    """KeyError with helpful message when pipeline is not in the catalog."""
    with pytest.raises(KeyError, match="not_a_pipeline"):
        data.load(
            pipeline="not_a_pipeline",
            dataframe="dataframe_0",
            catalog_path=catalog_project,
        )


def test_pipeline_not_found_lists_available(catalog_project):
    """KeyError message lists available pipelines."""
    with pytest.raises(KeyError, match="pipeline_a"):
        data.load(
            pipeline="missing",
            dataframe="dataframe_0",
            catalog_path=catalog_project,
        )


def test_dataframe_not_found(catalog_project):
    """KeyError with helpful message when dataframe is not in the pipeline."""
    with pytest.raises(KeyError, match="not_a_df"):
        data.load(
            pipeline="pipeline_a",
            dataframe="not_a_df",
            catalog_path=catalog_project,
        )


def test_dataframe_not_found_lists_available(catalog_project):
    """KeyError message lists available dataframes."""
    with pytest.raises(KeyError, match="dataframe_0"):
        data.load(
            pipeline="pipeline_a",
            dataframe="missing_df",
            catalog_path=catalog_project,
        )


def test_invalid_format(catalog_project):
    """ValueError for unsupported format string."""
    with pytest.raises(ValueError, match="Invalid format"):
        data.load(
            pipeline="pipeline_a",
            dataframe="dataframe_0",
            format="csv",
            catalog_path=catalog_project,
        )


# --- CatalogNotConfiguredError ---


def test_no_catalog_configured_raises(fake_config_dir):
    """CatalogNotConfiguredError when no catalog is configured and no path given."""
    with pytest.raises(CatalogNotConfiguredError, match="chartbook config"):
        data.load(pipeline="any", dataframe="any")


# --- Loading via global config ---


def test_load_via_global_config(fake_config_dir, catalog_project):
    """data.load() uses the catalog from global settings when no path is given."""
    config.set_default_catalog_path(catalog_project)
    lf = data.load(pipeline="pipeline_a", dataframe="dataframe_0")
    assert isinstance(lf, pl.LazyFrame)
    df = lf.collect()
    assert len(df) > 0


# --- get_data_path ---


def test_get_data_path_returns_resolved_path(catalog_project):
    """get_data_path returns an absolute Path to the parquet file."""
    path = data.get_data_path(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert path.suffix == ".parquet"
    assert path.exists()


# --- get_docs_path ---


def test_get_docs_path_returns_md_file(catalog_project):
    """get_docs_path returns an absolute Path to the markdown file."""
    path = data.get_docs_path(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert path.suffix == ".md"
    assert path.exists()


# --- get_docs ---


def test_get_docs_returns_markdown_content(catalog_project):
    """get_docs returns the markdown content as a string."""
    docs = data.get_docs(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(docs, str)
    assert "Dataframe 0" in docs
    assert "Documentation for dataframe 0" in docs


# --- Inline docs (dataframe_docs_str) ---


def test_get_docs_path_returns_toml_for_inline(catalog_project_inline_docs):
    """get_docs_path returns path to chartbook.toml for inline docs."""
    path = data.get_docs_path(
        pipeline="pipeline_inline",
        dataframe="dataframe_0",
        catalog_path=catalog_project_inline_docs,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert path.name == "chartbook.toml"
    assert path.exists()


def test_get_docs_returns_inline_content(catalog_project_inline_docs):
    """get_docs returns the inline string content directly."""
    docs = data.get_docs(
        pipeline="pipeline_inline",
        dataframe="dataframe_0",
        catalog_path=catalog_project_inline_docs,
    )
    assert isinstance(docs, str)
    assert "Dataframe 0" in docs
    assert "Inline documentation for dataframe 0" in docs


# --- Every asset's write-up, and the README (assets.get_docs) ---


@pytest.fixture
def catalog_with_write_ups(tmp_path):
    """A catalog of one pipeline with a write-up of every kind that has one: a chart, a model, a files asset, a note."""
    from tests.fixtures import create_catalog_project, publish_catalog

    root = create_catalog_project(tmp_path / "catalog_write_ups", pipeline_ids=["pipeline_w"])
    folder = root / "pipelines" / "pipeline_w"
    (folder / "_models").mkdir()
    (folder / "_models" / "forecaster.bin").write_bytes(b"weights")
    (folder / "_data" / "filings").mkdir(parents=True)
    (folder / "_data" / "filings" / "10-K.htm").write_text("<html></html>\n", encoding="utf-8", newline="\n")
    (folder / "docs_src" / "models").mkdir()
    (folder / "docs_src" / "models" / "forecaster.md").write_text(
        "# Forecaster\n\nDocumentation for the forecaster.\n", encoding="utf-8", newline="\n"
    )
    (folder / "docs_src" / "methodology.md").write_text("# Methodology\n\nHow it was done.\n", encoding="utf-8", newline="\n")
    with open(folder / "chartbook.toml", "a", encoding="utf-8", newline="\n") as manifest:
        manifest.write(
            '\n[models.forecaster]\npath = "_models/forecaster.bin"\ndocs_path = "docs_src/models/forecaster.md"\n'
            '\n[files.filings]\npath = "_data/filings"\ndocs = "One filing a year, as the SEC sends it."\n'
            '\n[notes.methodology]\npath = "docs_src/methodology.md"\n'
        )
    return publish_catalog(root)


@pytest.mark.parametrize(
    ("asset", "expected"),
    [
        (None, "This is a test pipeline."),
        ("dataframe_0", "Documentation for dataframe 0."),
        ("chart/chart_0_0", "Documentation for chart 0-0."),
        ("model/forecaster", "Documentation for the forecaster."),
        ("file/filings", "One filing a year, as the SEC sends it."),
        ("note/methodology", "How it was done."),
    ],
)
def test_get_docs_reads_every_kind_of_write_up(catalog_with_write_ups, asset, expected):
    """A chart's, model's and files asset's write-up, a note's text and, with no asset, the README: what each page shows."""
    from chartbook import assets

    assert expected in assets.get_docs("pipeline_w", asset, catalog_path=catalog_with_write_ups)


def test_get_docs_path_is_where_the_store_keeps_it(catalog_with_write_ups):
    """A write-up in a file is read from the snapshot, not from the pipeline's folder; inline docs name the manifest."""
    from chartbook import assets

    folder = catalog_with_write_ups / "pipelines" / "pipeline_w"
    chart = assets.get_docs_path("pipeline_w", "chart/chart_0_0", catalog_path=catalog_with_write_ups)
    assert chart.name == "chart_0_0.md" and chart.is_file()
    assert not chart.is_relative_to(folder)
    inline = assets.get_docs_path("pipeline_w", "file/filings", catalog_path=catalog_with_write_ups)
    assert inline.name == "chartbook.toml"


def test_get_docs_says_what_has_no_write_up(catalog_with_write_ups):
    """A notebook has none of its own; an asset not declared is a KeyError; a reference to another pipeline is refused."""
    from chartbook import assets

    with pytest.raises(ValueError, match="notebook"):
        assets.get_docs("pipeline_w", "notebook/analysis", catalog_path=catalog_with_write_ups)
    with pytest.raises(KeyError, match="chart 'missing'"):
        assets.get_docs("pipeline_w", "chart/missing", catalog_path=catalog_with_write_ups)
    with pytest.raises(ValueError, match="kind/name"):
        assets.get_docs("pipeline_w", "other:chart/chart_0_0", catalog_path=catalog_with_write_ups)


def test_cli_get_docs_takes_an_id_or_keywords(catalog_with_write_ups):
    """`chartbook get-docs` reads an asset by the ID `chartbook ls` prints, or by --pipeline and its kind; a bare name is the README."""
    from click.testing import CliRunner

    from chartbook.cli import main

    catalog = ["--catalog", str(catalog_with_write_ups)]
    for arguments in (["pipeline_w:chart/chart_0_0"], ["--pipeline", "pipeline_w", "--chart", "chart_0_0"]):
        chart = CliRunner().invoke(main, ["get-docs", *arguments, *catalog])
        assert chart.exit_code == 0, chart.output
        assert "Documentation for chart 0-0." in chart.output
    for arguments in (["pipeline_w"], ["--pipeline", "pipeline_w"]):
        readme = CliRunner().invoke(main, ["get-docs", *arguments, *catalog])
        assert readme.exit_code == 0, readme.output
        assert "This is a test pipeline." in readme.output
    frame = CliRunner().invoke(main, ["get-docs", "pipeline_w:dataframe_0", *catalog])
    assert "Documentation for dataframe 0." in frame.output
    path = CliRunner().invoke(main, ["get-docs", "pipeline_w:model/forecaster", "--path", *catalog])
    assert path.exit_code == 0, path.output
    assert path.output.strip().endswith("forecaster.md")
    # Said once, and one asset at a time
    for arguments, said in (
        (["--pipeline", "pipeline_w", "--chart", "chart_0_0", "--model", "forecaster"], "Name one asset, not 2"),
        (["pipeline_w:chart/chart_0_0", "--pipeline", "pipeline_w"], "Give the pipeline once"),
        (["pipeline_w:chart/chart_0_0", "--model", "forecaster"], "names its asset already"),
        ([], "Name a pipeline"),
    ):
        refused = CliRunner().invoke(main, ["get-docs", *arguments, *catalog])
        assert refused.exit_code == 2 and said in refused.output, refused.output
    notebook = CliRunner().invoke(main, ["get-docs", "pipeline_w:notebook/analysis", *catalog])
    assert notebook.exit_code == 1 and "no write-up of its own" in notebook.output


# --- Glob pattern / hive-partitioned support ---


def test_load_polars_glob_returns_lazyframe(catalog_project_glob):
    """Load glob path as polars LazyFrame (default)."""
    lf = data.load(
        pipeline="pipeline_glob",
        dataframe="dataframe_0",
        catalog_path=catalog_project_glob,
    )
    assert isinstance(lf, pl.LazyFrame)
    df = lf.collect()
    assert len(df) > 0
    # Hive partition column should be present
    assert "category" in df.columns


def test_glob_polars_eager_reads_it_as_polars_does(catalog_project_glob):
    """A glob in polars_eager is the LazyFrame collected (#135; it raised "Glob patterns" before)."""
    lazy = data.load(pipeline="pipeline_glob", dataframe="dataframe_0", catalog_path=catalog_project_glob).collect()
    eager = data.load(
        pipeline="pipeline_glob",
        dataframe="dataframe_0",
        format="polars_eager",
        catalog_path=catalog_project_glob,
    )
    assert isinstance(eager, pl.DataFrame)
    assert "category" in eager.columns
    assert eager.sort("date", "category").equals(lazy.sort("date", "category"))


def test_glob_pandas_reads_it_as_polars_does(catalog_project_glob):
    """A glob in pandas is the LazyFrame collected and converted, hive keys and all."""
    import pandas as pd

    lazy = data.load(pipeline="pipeline_glob", dataframe="dataframe_0", catalog_path=catalog_project_glob).collect()
    df = data.load(
        pipeline="pipeline_glob",
        dataframe="dataframe_0",
        format="pandas",
        catalog_path=catalog_project_glob,
    )
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == lazy.columns
    assert len(df) == lazy.height and sorted(df["category"]) == sorted(lazy["category"])


def test_get_data_path_has_no_one_path_for_a_glob(catalog_project_glob):
    """A glob read from the store is several files kept once, so it has files and no one path; load reads them."""
    from chartbook.errors import NoSinglePathError

    with pytest.raises(NoSinglePathError, match="'pipeline_glob:dataframe_0' is a dataset of") as e:
        data.get_data_path(pipeline="pipeline_glob", dataframe="dataframe_0", catalog_path=catalog_project_glob)
    assert "data.load('pipeline_glob:dataframe_0')" in str(e.value)
    frame = data.load(pipeline="pipeline_glob", dataframe="dataframe_0", catalog_path=catalog_project_glob).collect()
    assert frame.height > 0
