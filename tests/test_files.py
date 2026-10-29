"""Tests for files assets: ``[files]``, ``assets.files``, ``assets.index``,
``chartbook.files``, the ``File`` record and page, and ``check`` (#133);
and a dataframe of many parts, with its files listed (#135).

A files asset is a file, a folder or a glob of files that ChartBook keeps
and never reads, but for a bounded preview on its page.
"""

import base64
import gzip
import json
import os
import re
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import assets, files, hashing, index, lock, snapshot
from chartbook.check import run_checks
from chartbook.cli import main
from chartbook.diagnostics import build_diagnostics
from chartbook.errors import AssetNotDeclaredError
from chartbook.incremental import pipeline_owned_paths
from chartbook.manifest import load_manifest, resolve_project_type
from chartbook.refs import AssetRef, KindMismatchError
from chartbook.resolve import UnsupportedReferenceError
from tests.test_model_versions import _commit, _git

#: A one-pixel PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _edit_toml(project_dir: Path, edit) -> None:
    """Load a project's chartbook.toml, apply ``edit(config)``, write it back."""
    toml_path = Path(project_dir) / "chartbook.toml"
    config = tomli.loads(toml_path.read_text(encoding="utf-8"))
    edit(config)
    toml_path.write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")


def _releases(folder: Path, years=(2024, 2025)) -> None:
    """One gzipped JSON-lines file a year, in ``year=`` folders, as an archive kept in its source's format."""
    for year in years:
        (folder / f"year={year}").mkdir(parents=True, exist_ok=True)
        with gzip.open(folder / f"year={year}" / "releases.jsonl.gz", "wt", encoding="utf-8") as f:
            for i in range(3):
                f.write(json.dumps({"year": year, "i": i, "nested": {"a": [1, 2]}}) + "\n")


def add_files(project_dir: Path) -> Path:
    """Give a pipeline three files assets: a folder of releases, a glob of text, and a picture.

    ``releases`` is documented and governed; ``notes`` is a glob; ``picture``
    is one image file with nothing declared but its path.
    """
    project_dir = Path(project_dir)
    _releases(project_dir / "_data" / "releases")
    (project_dir / "_data" / "releases" / ".DS_Store").write_bytes(b"finder")
    (project_dir / "_data" / "notes").mkdir(parents=True)
    for name in ("b.txt", "a.txt", "skip.csv"):
        (project_dir / "_data" / "notes" / name).write_text(f"{name}\nsecond line\n", encoding="utf-8", newline="\n")
    (project_dir / "_data" / "picture.png").write_bytes(PNG)

    def edit(config):
        config["files"] = {
            "releases": {
                "name": "Earnings Releases",
                "description": "One file a year, as the API sends them.",
                "path": "./_data/releases",
                "sources": ["Vendor API"],
                "providers": ["Vendor"],
                "license": "Licensed to the department",
                "restrictions": "Research use only",
                "tags": ["raw data"],
                "docs": "Each line is one release, as JSON.",
            },
            "notes": {"path": "./_data/notes/*.txt"},
            "picture": {"path": "./_data/picture.png"},
        }

    _edit_toml(project_dir, edit)
    return project_dir


@pytest.fixture
def project(pipeline_project):
    """The ``test_pipeline`` fixture pipeline, with three files assets."""
    return add_files(pipeline_project.resolve())


class TestFilesTable:
    """``[files.<id>]`` as the manifest loader reads it."""

    def _load_with(self, project, **fields):
        _edit_toml(project, lambda config: config.update(files={"f": {"path": "./_data/f/", **fields}}))
        return load_manifest(project)["files"]["f"]

    def test_only_a_path_is_required(self, pipeline_project):
        entry = self._load_with(pipeline_project)
        assert entry["_resolved_path"] == pipeline_project / "_data" / "f"
        assert entry["_is_glob"] is False
        assert self._load_with(pipeline_project, path="./_data/*.gz")["_is_glob"] is True

    def test_tags_are_normalized_and_other_fields_kept(self, pipeline_project):
        entry = self._load_with(pipeline_project, tags=["raw data"], license="CC-BY", my_field=3)
        assert entry["tags"] == ["Raw Data"]
        assert entry["license"] == "CC-BY" and entry["my_field"] == 3

    def test_path_is_required(self, pipeline_project):
        _edit_toml(pipeline_project, lambda config: config.update(files={"f": {"description": "x"}}))
        with pytest.raises(ValueError, match=r"\[files\.f\] has no 'path'"):
            load_manifest(pipeline_project)

    def test_key_must_be_a_legal_name(self, pipeline_project):
        _edit_toml(pipeline_project, lambda config: config.update(files={"two words": {"path": "./x"}}))
        with pytest.raises(ValueError, match="not a legal files asset key"):
            load_manifest(pipeline_project)

    def test_docs_and_docs_path_exclude_each_other(self, pipeline_project):
        with pytest.raises(ValueError, match="both docs_path and docs"):
            self._load_with(pipeline_project, docs="x", docs_path="./docs_src/x.md")

    @pytest.mark.parametrize("field, value", [("tags", "raw"), ("sources", "API"), ("path", 3)])
    def test_fields_are_of_their_type(self, pipeline_project, field, value):
        with pytest.raises(ValueError, match=r"\[files\.f\]"):
            self._load_with(pipeline_project, **{field: value})

    def test_keep_is_true_or_left_out(self, pipeline_project):
        assert self._load_with(pipeline_project, keep=True)["keep"] is True
        with pytest.raises(ValueError, match="keep = False"):
            self._load_with(pipeline_project, keep=False)

    def test_must_be_a_table_of_tables(self, pipeline_project):
        _edit_toml(pipeline_project, lambda config: config.update(files={"f": "./x"}))
        with pytest.raises(ValueError, match=r"\[files\.f\] must be a table"):
            load_manifest(pipeline_project)

    def test_files_alone_make_a_manifest_a_pipeline(self):
        assert resolve_project_type({"files": {"f": {"path": "./x"}}}) == "pipeline"
        with pytest.raises(ValueError, match=r"\[files\]"):
            resolve_project_type({"project": {"type": "catalog"}, "files": {"f": {"path": "./x"}}})


class TestAddresses:
    def test_a_reference_names_a_files_asset(self):
        ref = assets.parse("dep:file/releases")
        assert (ref.pipeline, ref.kind, ref.name, ref.table) == ("dep", "file", "releases", "files")
        assert str(AssetRef(kind="file", name="x")) == "file/x"

    def test_path_of_each_kind_of_path(self, project):
        assert assets.path("file/releases", project_dir=project) == project / "_data" / "releases"
        assert assets.path("notes", kind="file", project_dir=project) == project / "_data" / "notes" / "*.txt"
        assert files.path("picture", project_dir=project) == project / "_data" / "picture.png"

    def test_files_path_answers_for_files_only(self, project):
        with pytest.raises(KindMismatchError, match=r"files\.path\(\) answers for files assets only"):
            files.path("chart/chart_0_0", project_dir=project)

    def test_an_undeclared_name_says_what_to_add(self, project):
        with pytest.raises(AssetNotDeclaredError, match=r"\[files\.missing\]") as caught:
            assets.path("file/missing", project_dir=project)
        assert "./_data/missing/" in str(caught.value)

    def test_a_dataframes_name_is_not_a_files_asset(self, project):
        with pytest.raises(AssetNotDeclaredError, match="declared as a dataframe"):
            files.path("dataframe_0", project_dir=project)

    def test_one_file_of_it_is_not_an_address(self, project):
        with pytest.raises(UnsupportedReferenceError, match=r"assets\.files\('file/notes'\)"):
            assets.path("file/notes#a.txt", project_dir=project)

    def test_is_exported_from_the_package(self):
        import chartbook

        assert chartbook.files is files
        assert {"files", "index"} <= set(assets.__all__)

    def test_command_line(self, project, monkeypatch):
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["path", "file/notes"])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == str(project / "_data" / "notes" / "*.txt")
        result = CliRunner().invoke(main, ["path", "notes", "--kind", "file", "--files"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [str(project / "_data" / "notes" / n) for n in ("a.txt", "b.txt")]


class TestAssetsFiles:
    def test_a_folders_files_sorted_and_without_what_the_system_wrote(self, project):
        found = assets.files("file/releases", project_dir=project)
        assert found == [
            project / "_data" / "releases" / "year=2024" / "releases.jsonl.gz",
            project / "_data" / "releases" / "year=2025" / "releases.jsonl.gz",
        ]

    def test_a_globs_matches(self, project):
        assert [p.name for p in assets.files("file/notes", project_dir=project)] == ["a.txt", "b.txt"]

    def test_one_file(self, project):
        assert assets.files("file/picture", project_dir=project) == [project / "_data" / "picture.png"]

    def test_a_dataframe_of_many_parts(self, pipeline_project):
        """#135: a consumer reads a large dataset a file at a time without expanding its glob."""
        project = pipeline_project.resolve()
        _panel(project)
        found = assets.files("panel", project_dir=project)
        assert [p.relative_to(project / "_data" / "panel").as_posix() for p in found] == [
            "year=2024/part-0.parquet", "year=2025/part-0.parquet",
        ]
        assert assets.files("dataframe_0", project_dir=project) == [project / "_data" / "test_pipeline" / "dataframe_0.parquet"]

    def test_nothing_there_is_an_error(self, project):
        _edit_toml(project, lambda config: config["files"].update(gone={"path": "./_data/gone/*.txt"}))
        with pytest.raises(FileNotFoundError, match="has no files"):
            assets.files("file/gone", project_dir=project)


class TestAssetsIndex:
    def test_one_row_per_file_with_the_folders_keys(self, project):
        frame = assets.index("file/releases", project_dir=project)
        assert isinstance(frame, pl.LazyFrame)
        table = frame.collect()
        assert table.columns == ["path", "size_bytes", "sha256", "year"]
        assert table.schema["size_bytes"] == pl.Int64 and table.schema["year"] == pl.String
        assert table["year"].to_list() == ["2024", "2025"]
        first = project / "_data" / "releases" / "year=2024" / "releases.jsonl.gz"
        assert table["path"].to_list()[0] == str(first)
        assert table["size_bytes"].to_list()[0] == first.stat().st_size
        assert table["sha256"].to_list()[0] == hashing.hash_file(first).content_hash.split(":", 1)[1]
        # The rows are the files, in the same order
        assert table["path"].to_list() == [str(p) for p in assets.files("file/releases", project_dir=project)]

    def test_picks_files_before_opening_any(self, project):
        chosen = assets.index("file/releases", project_dir=project).filter(pl.col("year") == "2025").collect()
        assert [Path(p).parent.name for p in chosen["path"]] == ["year=2025"]

    def test_one_file_has_no_key_columns(self, project):
        table = assets.index("file/picture", project_dir=project).collect()
        assert table.columns == ["path", "size_bytes", "sha256"] and table.height == 1

    def test_a_local_asset_is_hashed_once_and_cached(self, project, monkeypatch):
        assets.index("file/notes", project_dir=project).collect()
        cached = list((Path(os.environ["CHARTBOOK_CACHE"]) / "hashes").glob("*.json"))
        assert len(cached) == 1
        # Unchanged files are not read again
        monkeypatch.setattr(hashing, "_file_hex", lambda path: pytest.fail(f"{path} was read again"))
        assert assets.index("file/notes", project_dir=project).collect().height == 2

    def test_works_for_a_dataframe(self, pipeline_project):
        project = pipeline_project.resolve()
        _panel(project)
        assert assets.index("panel", project_dir=project).collect()["year"].to_list() == ["2024", "2025"]


class TestPreview:
    def test_extension_keeps_what_is_compressed(self):
        assert files.extension("EARNINGS_2014Q1.jsonl.gz") == ".jsonl.gz"
        assert files.extension("REPORT.PDF") == ".pdf"
        assert files.extension("000000_0") == ""
        assert files.count_by_extension(["a.txt", "b.TXT", "c.jsonl.gz", "d"]) == {"": 1, ".jsonl.gz": 1, ".txt": 2}

    def test_partitions_are_folders_only(self):
        assert files.partitions("year=2024/q=1/x=y.htm") == {"year": "2024", "q": "1"}
        assert files.partitions("plain/x.htm") == {}
        assert files.partitions("=v/x") == {}

    def test_json_lines_in_gzip_are_pretty_printed(self, tmp_path):
        _releases(tmp_path)
        text = files.preview_text(tmp_path / "year=2024" / "releases.jsonl.gz")
        assert text.splitlines()[:3] == ["{", '  "year": 2024,', '  "i": 0,']

    def test_a_large_gzip_is_decompressed_no_further_than_the_limit(self, tmp_path, monkeypatch):
        big = tmp_path / "big.jsonl.gz"
        with gzip.open(big, "wt", encoding="utf-8") as f:
            for i in range(100_000):
                f.write(json.dumps({"i": i, "padding": "x" * 50}) + "\n")
        inflated = []
        real = files.zlib.decompressobj

        class Counting:
            def __init__(self, *args):
                self.inner = real(*args)

            def decompress(self, data, max_length=0):
                out = self.inner.decompress(data, max_length)
                inflated.append(len(out))
                return out

            def __getattr__(self, name):
                return getattr(self.inner, name)

        monkeypatch.setattr(files.zlib, "decompressobj", Counting)
        text = files.preview_text(big)
        assert sum(inflated) <= files.PREVIEW_BYTES
        assert text.endswith("…") and len(text.splitlines()) <= files.PREVIEW_LINES + 1

    def test_binary_is_not_text(self, tmp_path):
        (tmp_path / "x.txt").write_bytes(b"\x00\x01\x02binary")
        assert files.preview_text(tmp_path / "x.txt") is None
        (tmp_path / "y.txt").write_bytes(b"\xff\xfe\xfa not utf-8")
        assert files.preview_text(tmp_path / "y.txt") is None

    def test_what_a_page_previews(self, tmp_path):
        (tmp_path / "a.npy").write_bytes(b"\x93NUMPY")
        (tmp_path / "b.png").write_bytes(PNG)
        listed = [{"path": "a.npy", "size_bytes": 6}, {"path": "b.png", "size_bytes": len(PNG)}]
        assert files.preview_of(listed, tmp_path)["kind"] == "image"
        assert files.preview_of(listed[:1], tmp_path) is None
        too_big = [{"path": "b.png", "size_bytes": files.THUMBNAIL_BYTES + 1}]
        assert files.preview_of(too_big, tmp_path) is None
        (tmp_path / "c.svg").write_text("<svg/>", encoding="utf-8")
        assert files.preview_of([{"path": "c.svg", "size_bytes": 6}], tmp_path) is None


def _panel(project: Path) -> None:
    """A dataframe of two parquet parts in ``year=`` folders, declared as a glob."""
    for year, rows in ((2024, 4), (2025, 5)):
        folder = project / "_data" / "panel" / f"year={year}"
        folder.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"x": list(range(rows))}).write_parquet(folder / "part-0.parquet")
    _edit_toml(
        project,
        lambda config: config["dataframes"].update(panel={"path": "./_data/panel/**/*.parquet", "docs": "A panel."}),
    )


def _records(project: Path) -> dict:
    built = index.build_index(load_manifest(project))
    return {record["id"]: record for record in built["records"]}


def _valid(record: dict) -> None:
    schema = json.loads(index.schema_path(record["kind"]).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(record)


class TestFileRecord:
    def test_a_folder(self, project):
        record = _records(project)["test_pipeline:file/releases"]
        _valid(record)
        assert record["kind"] == "File" and record["ref"] == {"pipeline": "test_pipeline", "kind": "file", "name": "releases"}
        assert record["file_count"] == 2 and record["extensions"] == {".jsonl.gz": 2}
        assert [f["path"] for f in record["files"]] == ["year=2024/releases.jsonl.gz", "year=2025/releases.jsonl.gz"]
        assert record["files"][0]["partitions"] == {"year": "2024"}
        assert record["content_hash"] == hashing.hash_path(project / "_data" / "releases").content_hash
        assert record["license"] == "Licensed to the department" and record["restrictions"] == "Research use only"
        assert record["docs"]["text"] == "Each line is one release, as JSON."

    def test_one_file_lists_itself(self, project):
        record = _records(project)["test_pipeline:file/picture"]
        _valid(record)
        assert record["file_count"] == 1 and record["extensions"] == {".png": 1}
        assert record["files"] == [{"path": "picture.png", "size_bytes": len(PNG), "content_hash": record["content_hash"]}]

    def test_the_listing_stops_at_its_limit(self, project, monkeypatch):
        monkeypatch.setattr(index, "FILES_LISTED", 1)
        record = _records(project)["test_pipeline:file/releases"]
        assert record["file_count"] == 2 and len(record["files"]) == 1

    def test_not_built(self, project):
        _edit_toml(project, lambda config: config["files"].update(gone={"path": "./_data/gone/*.txt"}))
        record = _records(project)["test_pipeline:file/gone"]
        _valid(record)
        assert "content_hash" not in record and "files" not in record

    def test_files_come_after_the_other_kinds(self, project):
        pipeline = _records(project)["test_pipeline"]
        assert pipeline["assets"][-3:] == ["test_pipeline:file/notes", "test_pipeline:file/picture", "test_pipeline:file/releases"]

    def test_a_dataframe_of_many_parts_lists_them_with_their_rows(self, pipeline_project):
        """#135: from each parquet footer; no data is read."""
        project = pipeline_project.resolve()
        _panel(project)
        records = _records(project)
        panel = records["test_pipeline:panel"]
        _valid(panel)
        assert panel["file_count"] == 2 and panel["row_count"] == 9
        assert [(f["path"], f["row_count"], f["partitions"]) for f in panel["files"]] == [
            ("year=2024/part-0.parquet", 4, {"year": "2024"}),
            ("year=2025/part-0.parquet", 5, {"year": "2025"}),
        ]
        # One file is not parts
        assert "files" not in records["test_pipeline:dataframe_0"]


class TestCheck:
    def _problems(self, project, **options):
        return [p.format(project) for p in run_checks(load_manifest(project), project, **options)]

    def test_a_path_that_matches_no_file_fails(self, project):
        _edit_toml(project, lambda config: config["files"].update(gone={"path": "./_data/gone/*.txt"}))
        (project / "_data" / "empty").mkdir()
        _edit_toml(project, lambda config: config["files"].update(empty={"path": "./_data/empty"}))
        problems = self._problems(project)
        assert any(re.search(r"\[files\.gone\] path: no files match .*gone", p) for p in problems)
        assert any(re.search(r"\[files\.empty\] path: the folder holds no file", p) for p in problems)
        assert not any("files.releases] path" in p for p in problems)
        # With --skip-outputs, as for a dataframe
        assert not any("] path:" in p for p in self._problems(project, skip_outputs=True))

    def test_a_missing_write_up_and_an_expired_license(self, project):
        def edit(config):
            config["files"]["notes"].update(docs_path="./docs_src/files/notes.md", license_expiration="2020-01-01")

        _edit_toml(project, edit)
        problems = self._problems(project)
        assert any("[files.notes] docs_path: file not found" in p for p in problems)
        assert any("[files.notes] license_expiration: license expired on 2020-01-01" in p for p in problems)

    def test_the_policy_may_name_files(self, project):
        _edit_toml(project, lambda config: config.update(policy={"required": {"files": ["license"]}}))
        problems = self._problems(project)
        assert any("[files.notes] license: required by" in p for p in problems)
        assert not any("[files.releases] license" in p for p in problems)

    def test_summary_counts_files_assets(self, project, monkeypatch):
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["check", "--skip-outputs"])
        assert "3 files assets" in result.output

    def test_diagnostics_have_a_row_per_files_asset(self, project):
        rows = [r for r in build_diagnostics(load_manifest(project)) if r.object_type == "file"]
        assert [r.identifier for r in rows] == ["notes", "picture", "releases"]
        assert rows[0].page_link == "./files/test_pipeline/notes.html"


def _page_text(html_file: Path) -> str:
    """The readable text of a built page's article."""
    page = html_file.read_text(encoding="utf-8")
    article = page[page.find("<article") : page.find("</article>")]
    article = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", article, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", article))


class TestPages:
    @pytest.fixture(scope="class")
    def site(self, tmp_path_factory):
        """One build of a pipeline with files assets and a dataframe of parts, shared by the tests here."""
        from tests.fixtures import create_pipeline_project

        project = add_files(create_pipeline_project(tmp_path_factory.mktemp("site") / "p").resolve())
        _panel(project)
        before = Path.cwd()
        os.chdir(project)
        try:
            result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        finally:
            os.chdir(before)
        assert result.exit_code == 0, result.output
        return project

    def test_the_page_of_a_folder(self, site):
        text = _page_text(site / "docs" / "cb" / "files" / "test_pipeline" / "releases.html")
        assert "Earnings Releases" in text and "Each line is one release, as JSON." in text
        assert "2 files" in text and ".jsonl.gz" in text
        assert "year=2024/releases.jsonl.gz" in text
        assert "In key=value folders, by year" in text
        assert '"year": 2024,' in text.replace("&quot;", '"')  # the preview, pretty-printed
        assert "Licensed to the department" in text and "Research use only" in text
        assert 'assets.files("file/releases")' in text.replace("&quot;", '"')

    def test_an_image_is_shown_from_the_site(self, site):
        page = (site / "docs" / "cb" / "files" / "test_pipeline" / "picture.html").read_text(encoding="utf-8")
        shown = re.search(r'<img[^>]*class="cb-thumbnail"[^>]*>', page) or re.search(r'<img[^>]*src="[^"]*picture\.png"[^>]*>', page)
        assert shown and "picture.png" in shown.group(0)
        source = re.search(r'src="([^"]+)"', shown.group(0)).group(1)
        assert (site / "docs" / "cb" / "files" / "test_pipeline" / source).resolve().read_bytes() == PNG

    def test_the_page_shows_no_local_path(self, site):
        page = (site / "docs" / "cb" / "files" / "test_pipeline" / "releases.html").read_text(encoding="utf-8")
        article = page[page.find("<article") : page.find("</article>")]
        assert str(site / "_data") not in article

    def test_the_front_page_and_llms_txt_list_them(self, site):
        front = (site / "docs" / "index.html").read_text(encoding="utf-8")
        assert "cb/files/test_pipeline/releases.html" in front
        listed = (site / "docs" / "llms.txt").read_text(encoding="utf-8")
        assert "## Files" in listed
        assert "- [Earnings Releases](cb/files/test_pipeline/releases.html): `test_pipeline:file/releases`." in listed

    def test_the_published_index_validates(self, site):
        published = json.loads((site / "docs" / "index.json").read_text(encoding="utf-8"))
        for record in published["records"]:
            if record["kind"] in ("File", "Dataframe"):
                _valid(record)

    def test_a_dataframe_page_lists_its_parts(self, site):
        """#135 item 3: each file with its size and rows, and the partition keys."""
        text = _page_text(site / "docs" / "cb" / "dataframes" / "test_pipeline" / "panel.html")
        assert "Parts" in text and "2 files" in text and "9 rows" in text
        assert re.search(r"year=2024/part-0\.parquet \d+ bytes 4 2024", text)
        assert re.search(r"year=2025/part-0\.parquet \d+ bytes 5 2025", text)

    def test_pages_belong_to_their_pipeline(self, site):
        manifest = load_manifest(site)
        assert Path("cb") / "files" / "test_pipeline" in pipeline_owned_paths("test_pipeline", manifest)


class TestCatalog:
    def test_a_catalog_lists_files_only_when_some_pipeline_has_them(self, catalog_project, monkeypatch):
        catalog = catalog_project.resolve()
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert not (catalog / "docs" / "cb" / "files.html").exists()
        add_files(catalog / "pipelines" / "pipeline_a")
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        listing = (catalog / "docs" / "cb" / "files.html").read_text(encoding="utf-8")
        assert "files/pipeline_a/releases.html" in listing


@pytest.fixture
def two(tmp_path):
    """``filings`` keeps a folder of releases and a glob of text; ``study`` depends on it. Both committed, in one repository."""
    work = tmp_path.resolve() / "work"
    filings, study = work / "filings", work / "study"
    for directory in (filings, study):
        directory.mkdir(parents=True)
        (directory / "README.md").write_text("# A pipeline\n", encoding="utf-8", newline="\n")
    _releases(filings / "_data" / "releases")
    (filings / "_data" / "text" / "2024").mkdir(parents=True)
    (filings / "_data" / "text" / "2024" / "10-K.txt").write_text("Annual report\n", encoding="utf-8", newline="\n")
    (filings / "_data" / "text" / "2024" / "skip.csv").write_text("a,b\n", encoding="utf-8", newline="\n")
    (filings / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/filings"},
                "files": {"releases": {"path": "./_data/releases", "keep": True}, "text": {"path": "./_data/text/**/*.txt"}},
            }
        ),
        encoding="utf-8", newline="\n",
    )
    (study / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/study"}, "dependencies": {"filings": {"path": "../filings"}}}),
        encoding="utf-8", newline="\n",
    )
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n_docs*/\ndocs/\n", encoding="utf-8", newline="\n")
    _commit(work)
    return filings, study


class TestAcrossPipelines:
    def test_snapshot_pin_and_read_another_pipelines_files(self, two, monkeypatch):
        filings, study = two
        report = snapshot.make(filings)
        record = report.snapshot.assets["file/releases"]
        assert record["kind"] == "File" and record["keep"] is True
        assert record["content_hash"] == hashing.hash_path(filings / "_data" / "releases").content_hash
        lock.pin(study)
        assert lock.read_lock(study / "chartbook.lock").assets["filings:file/releases"]["content_hash"] == record["content_hash"]
        found = assets.files("filings:file/releases", project_dir=study)
        assert [p.relative_to(found[0].parent.parent).as_posix() for p in found] == [
            "year=2024/releases.jsonl.gz", "year=2025/releases.jsonl.gz",
        ]
        assert str(filings) not in str(found[0])  # the pinned copy, in the store
        originals = sorted((filings / "_data" / "releases").rglob("*.gz"))
        hexes = [hashing.hash_file(p).content_hash.split(":", 1)[1] for p in originals]
        # Every size and hash from the store's record: nothing is read
        monkeypatch.setattr(hashing, "_file_hex", lambda path: pytest.fail(f"{path} was read"))
        table = assets.index("filings:file/releases", project_dir=study).collect()
        assert table["year"].to_list() == ["2024", "2025"]
        assert table["path"].to_list() == [str(p) for p in found]
        assert table["sha256"].to_list() == hexes
        assert table["size_bytes"].to_list() == [p.stat().st_size for p in originals]

    def test_a_pinned_glob(self, two):
        filings, study = two
        snapshot.make(filings)
        lock.pin(study)
        found = assets.files("filings:file/text", project_dir=study)
        assert [p.name for p in found] == ["10-K.txt"] and found[0].parent.name == "2024"
        assert found[0].read_text(encoding="utf-8") == "Annual report\n"
        table = assets.index("filings:file/text", project_dir=study).collect()
        assert table["path"].to_list() == [str(found[0])]
        assert table["size_bytes"].to_list() == [len("Annual report\n")]

    def test_the_pin_does_not_move_with_the_folder(self, two):
        filings, study = two
        snapshot.make(filings)
        lock.pin(study)
        _releases(filings / "_data" / "releases", years=(2026,))
        assert len(assets.files("filings:file/releases", project_dir=study)) == 2
        assert len(assets.files("file/releases", project_dir=filings)) == 3

    def test_restore_puts_a_kept_files_asset_back(self, two):
        filings, _ = two
        snapshot.make(filings)
        before = {p.name: p.read_bytes() for p in (filings / "_data" / "releases").rglob("*.gz")}
        import shutil

        shutil.rmtree(filings / "_data" / "releases")
        restored = snapshot.restore(filings)
        assert [name for name, *_ in restored.put_back] == ["file/releases"]
        assert {p.name: p.read_bytes() for p in (filings / "_data" / "releases").rglob("*.gz")} == before


class TestMkDocs:
    def test_a_site_with_files_is_built_with_mkdocs(self, project, monkeypatch):
        """The files page is plain Markdown, shared with the Sphinx writer; MkDocs lists it and resolves its links."""
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        _edit_toml(project, lambda config: config["project"].update(writer="mkdocs"))
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        assert "contains a link" not in result.output, result.output
        site = project / "docs"
        page = (site / "cb" / "files" / "test_pipeline" / "picture.html").read_text(encoding="utf-8")
        assert 'class="cb-thumbnail"' in page and "_static/test_pipeline/files/picture.png" in page
        assert (site / "_static" / "test_pipeline" / "files" / "picture.png").read_bytes() == PNG
        nav = (project / "_docs" / "mkdocs.yml").read_text(encoding="utf-8")
        assert "cb/files/test_pipeline/releases.md" in nav
        assert "## Files" not in (site / "index.html").read_text(encoding="utf-8")  # rendered, not raw
        assert "cb/files/test_pipeline/releases.html" in (site / "index.html").read_text(encoding="utf-8")
