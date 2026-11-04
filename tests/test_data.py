"""Tests for chartbook.data — catalog-aware data loading."""

import warnings
from pathlib import Path

import polars as pl
import pytest

from chartbook import config, data


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


# --- No catalog yet ---


def test_no_catalog_is_made_over_the_store(fake_config_dir, capsys):
    """With no catalog, a read through one makes the machine's catalog over its store, says so, and finds nothing."""
    with pytest.raises(KeyError):
        data.load(pipeline="any", dataframe="any")
    made = fake_config_dir / "catalog.toml"
    assert made.is_file()
    assert capsys.readouterr().err.splitlines() == [f"Made {made}: a catalog over your store at {config.get_store_url()}."]
    import tomli

    assert tomli.loads(made.read_text(encoding="utf-8"))["stores"] == {"default": {"url": config.get_store_url()}}
    # Made once: the second read says nothing
    with pytest.raises(KeyError):
        data.load(pipeline="any", dataframe="any")
    assert capsys.readouterr().err == ""


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


def test_cli_get_docs_prints_a_dataframes_whole_page(catalog_with_write_ups):
    """A dataframe's facts, its write-up and its columns, from its snapshot's index; the write-up's own title is not said twice."""
    from click.testing import CliRunner

    from chartbook import assets
    from chartbook.cli import main

    catalog = ["--catalog", str(catalog_with_write_ups)]
    page = CliRunner().invoke(main, ["get-docs", "pipeline_w:dataframe_0", *catalog])
    assert page.exit_code == 0, page.output
    lines = page.output.splitlines()
    assert lines[:3] == ["# Dataframe 0", "", "Description for dataframe 0"]
    for fact in ("- ID: pipeline_w:dataframe_0", "- Sources: Test Source", "- Rows: 10", "- Dates: 2020-01-01 to 2020-01-01, in column date"):
        assert fact in lines, page.output
    assert lines.count("# Dataframe 0") == 1
    assert page.output.index("Documentation for dataframe 0.") < page.output.index("## Columns")
    assert "| value | int64 |" in lines and "| category | string |" in lines
    assert not page.output.endswith("\n\n")
    missing = CliRunner().invoke(main, ["get-docs", "pipeline_w:dataframe_9", *catalog])
    assert missing.exit_code == 1 and "dataframe 'dataframe_9'" in missing.output, missing.output
    same = CliRunner().invoke(main, ["data", "get-docs", "--pipeline", "pipeline_w", "--dataframe", "dataframe_0", *catalog])
    assert same.exit_code == 0 and same.output == page.output, same.output
    # The write-up alone is still the Python call's, and a chart's page is its write-up
    assert "## Columns" not in assets.get_docs("pipeline_w", "dataframe_0", catalog_path=catalog_with_write_ups)
    assert assets.get_docs_page("pipeline_w", "chart/chart_0_0", catalog_path=catalog_with_write_ups) == assets.get_docs(
        "pipeline_w", "chart/chart_0_0", catalog_path=catalog_with_write_ups
    )


def test_dataframe_page_reads_a_stored_record_as_someone_elses_text():
    """Anyone who can write to a shared store wrote the record: what does not print is a space, bars are escaped, wrong shapes are left out."""
    from types import SimpleNamespace

    from chartbook.assets import _dataframe_page

    taken = SimpleNamespace(commit="0123456789abcdef", made_at="2026-11-02T22:14:54.791033Z")
    record = {
        "id": "acme/rates:yields",
        "name": "Yields\x1b[2J",
        "description": ["not", "text"],
        "sources": ["Board", 7, "\x07"],
        "row_count": True,
        "date_range": {"first": "2020-01-01T00:00:00", "last": None},
        "columns": [{"name": "a|b\nc", "dtype": "f64"}, "not a column", {"dtype": "no name"}],
    }
    page = _dataframe_page(record, taken, "# Yields\n\nThe write-up.\n")
    lines = page.splitlines()
    assert lines[0] == "# Yields [2J"
    assert "- Sources: Board" in lines and "- Snapshot: 0123456, made 2026-11-02T22:14:54Z" in lines
    assert not any(line.startswith(("- Rows", "- Dates")) for line in lines)
    assert "not" not in lines and "The write-up." in lines
    assert lines[-1] == "| a\\|b c | f64 |" and lines.count("|---|---|") == 1
    assert _dataframe_page({"id": "acme/rates:yields", "columns": "no"}, taken, None).splitlines()[0] == "# acme/rates:yields"
    # A snapshot whose commit or time ends in a newline is not read at all
    from chartbook.snapshot import _COMMIT, _MADE_AT

    assert not _MADE_AT.match("2026-11-02T22:14:54Z\n") and not _COMMIT.match("0" * 40 + "\n")



def test_cli_get_docs_takes_a_scoped_id_and_a_repository_url(tmp_path):
    """The last colon divides pipeline and asset, as in any reference, so a repository URL's own colon is not taken for it."""
    import json

    from click.testing import CliRunner

    from chartbook.cli import _split_docs_id, main
    from tests.fixtures import create_catalog_project, publish_catalog

    root = create_catalog_project(tmp_path / "catalog_scoped", pipeline_ids=["pipeline_s"])
    manifest = root / "pipelines" / "pipeline_s" / "chartbook.toml"
    text = manifest.read_text(encoding="utf-8")
    assert text.count('id = "pipeline_s"') == 1
    manifest.write_text(text.replace('id = "pipeline_s"', 'id = "acme/pipeline_s"'), encoding="utf-8", newline="\n")
    catalog = ["--catalog", str(publish_catalog(root))]
    listed = CliRunner().invoke(main, ["ls", "--json", *catalog])
    assert listed.exit_code == 0, listed.output
    (pipeline_id,) = [r["id"] for r in json.loads(listed.output) if r["kind"] == "pipeline"]
    assert pipeline_id == "acme/pipeline_s"
    for id_given in (f"{pipeline_id}:chart/chart_0_0", f"https://github.com/{pipeline_id}:chart/chart_0_0"):
        chart = CliRunner().invoke(main, ["get-docs", id_given, *catalog])
        assert chart.exit_code == 0, chart.output
        assert "Documentation for chart 0-0." in chart.output
    readme = CliRunner().invoke(main, ["get-docs", f"https://github.com/{pipeline_id}", *catalog])
    assert readme.exit_code == 0, readme.output
    assert "This is a test pipeline." in readme.output
    # A URL alone, with a port or in git's form, is a pipeline
    assert _split_docs_id("git@github.com:acme/rates.git") == ("git@github.com:acme/rates.git", None)
    assert _split_docs_id("https://host:8443/acme/rates") == ("https://host:8443/acme/rates", None)
    assert _split_docs_id("git@github.com:acme/rates.git:model/m") == ("git@github.com:acme/rates.git", "model/m")



def _writable(stored):
    """A file the store keeps, made writable to change it as someone else writing to a shared store could."""
    import os

    os.chmod(stored.parent, 0o755)
    os.chmod(stored, 0o644)
    return stored


def test_cli_get_docs_options_hold_their_kind(catalog_with_write_ups):
    """`--dataframe chart/x` is not a chart's write-up read by another name, and an option takes a name alone."""
    from click.testing import CliRunner

    from chartbook.cli import _split_docs_id, main

    catalog = ["--catalog", str(catalog_with_write_ups)]
    for arguments, said in (
        (["--dataframe", "chart/chart_0_0"], "--dataframe chart/chart_0_0"),
        (["--chart", "other:chart_0_0"], "give its pipeline with --pipeline"),
        (["--model", "forecaster@v1"], "give its pipeline with --pipeline"),
    ):
        refused = CliRunner().invoke(main, ["get-docs", "--pipeline", "pipeline_w", *arguments, *catalog])
        assert refused.exit_code == 2 and said in refused.output, refused.output
    # An owner named like a kind, in git's form of a URL, is the URL's
    assert _split_docs_id("git@github.com:model/pipeline_s") == ("git@github.com:model/pipeline_s", None)
    assert _split_docs_id("git@github.com:yield_curve") == ("git@github.com:yield_curve", None)
    # A reference that is more than kind/name is said as written
    rev = CliRunner().invoke(main, ["data", "get-docs", "--pipeline", "pipeline_w", "--dataframe", "dataframe_0@v1", *catalog])
    assert rev.exit_code == 1 and "'dataframe_0@v1'" in rev.output and "AssetRef(" not in rev.output, rev.output


def test_get_docs_says_what_the_store_does_not_have_yet(catalog_with_write_ups):
    """A write-up a synced store has not downloaded is said in the store's words, not as a traceback."""
    from click.testing import CliRunner

    from chartbook import assets
    from chartbook.cli import main

    _writable(assets.get_docs_path("pipeline_w", "chart/chart_0_0", catalog_path=catalog_with_write_ups)).unlink()
    for arguments in (
        ["get-docs", "pipeline_w:chart/chart_0_0"],
        ["data", "get-docs", "--pipeline", "pipeline_w", "--dataframe", "dataframe_0"],
    ):
        said = CliRunner().invoke(main, [*arguments, "--catalog", str(catalog_with_write_ups)])
        assert said.exit_code == 1 and said.output.startswith("Error:"), said.output
        assert isinstance(said.exception, SystemExit)


def test_get_docs_refuses_a_stored_manifest_of_the_wrong_shape(catalog_with_write_ups):
    """Anyone who can write to a shared store wrote its chartbook.toml: tables that are not tables are said so."""
    from click.testing import CliRunner

    from chartbook import assets
    from chartbook.cli import main

    stored = assets.get_docs_path("pipeline_w", "file/filings", catalog_path=catalog_with_write_ups)
    assert stored.name == "chartbook.toml"
    size = stored.stat().st_size
    bad = 'charts = "no"\nproject = "x"\n'
    _writable(stored).write_bytes((bad + "#" * (size - len(bad) - 1) + "\n").encode("utf-8"))  # its recorded size
    for asset_id in ("pipeline_w", "pipeline_w:chart/chart_0_0"):
        said = CliRunner().invoke(main, ["get-docs", asset_id, "--catalog", str(catalog_with_write_ups)])
        assert said.exit_code == 1 and "is not a table" in said.output, said.output


@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="Windows has no named pipes in the file system")
def test_get_docs_does_not_wait_on_a_pipe_in_the_store(tmp_path):
    """A pipe where a write-up is kept is not read, which would wait until something wrote to it."""
    import os
    import threading

    from chartbook import assets
    from tests.fixtures import create_catalog_project, publish_catalog

    root = create_catalog_project(tmp_path / "catalog_pipe", pipeline_ids=["pipeline_f"])
    (root / "pipelines" / "pipeline_f" / "README.md").write_text("", encoding="utf-8", newline="\n")  # recorded as 0 bytes
    catalog = publish_catalog(root)
    stored = _writable(assets.get_docs_path("pipeline_f", None, catalog_path=catalog))
    stored.unlink()
    os.mkfifo(stored)
    result = {}

    def read():
        try:
            result["text"] = assets.get_docs("pipeline_f", None, catalog_path=catalog)
        except Exception as error:  # noqa: BLE001 - what it raised is the result
            result["error"] = error

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(10)
    if reader.is_alive():
        os.close(os.open(stored, os.O_WRONLY | os.O_NONBLOCK))  # let it go before failing
        reader.join(5)
        pytest.fail("get_docs waited on a pipe")
    assert isinstance(result.get("error"), ValueError), result


def test_get_docs_of_two_notes_of_the_same_bytes(tmp_path):
    """The store keeps the same bytes once, so either note's file may be the other's: each reads its own text."""
    from chartbook import assets
    from tests.fixtures import create_catalog_project, publish_catalog

    root = create_catalog_project(tmp_path / "catalog_notes", pipeline_ids=["pipeline_n"])
    folder = root / "pipelines" / "pipeline_n"
    for name in ("one", "two"):
        (folder / "docs_src" / f"{name}.md").write_text("Same\n", encoding="utf-8", newline="\n")
    with open(folder / "chartbook.toml", "a", encoding="utf-8", newline="\n") as manifest:
        manifest.write('\n[notes.one]\npath = "docs_src/one.md"\n\n[notes.two]\npath = "docs_src/two.md"\n')
    catalog = publish_catalog(root)
    for name in ("one", "two"):
        assert assets.get_docs_path("pipeline_n", f"note/{name}", catalog_path=catalog).read_bytes() == b"Same\n"
        assert assets.get_docs("pipeline_n", f"note/{name}", catalog_path=catalog) == "Same\n"


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
