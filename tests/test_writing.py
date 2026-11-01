"""Writing a pipeline's own outputs by name: data.path makes the folder, and data.scratch goes where [project] says.

``docs_src/design/plan-data-reads.md``, step 3.
"""

from pathlib import Path

import polars as pl
import pytest
import tomli_w

from chartbook import assets, data, models


def _pipeline(work: Path, project: dict | None = None) -> Path:
    folder = work / "rates"
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": "rates", **(project or {})},
            "dataframes": {
                "merged": {"path": "./_data/merged.parquet", "docs": "d"},
                "articles": {"path": "./_data/articles", "docs": "d"},
                "parts": {"path": "./_data/parts/**/*.parquet", "docs": "d"},
            },
            "charts": {"curve": {"path": "./_output/charts/curve.html", "dataframe": "merged", "docs": "d"}},
            "models": {"ar1": {"path": "./_models/ar1"}, "pickled": {"path": "./_models/pickled.pkl"}},
        }),
        encoding="utf-8", newline="\n",
    )
    return folder


class TestThePathIsReadyToWriteInto:
    def test_a_files_parent_folder_is_made(self, tmp_path):
        folder = _pipeline(tmp_path.resolve())
        path = data.path("merged", project_dir=folder)
        assert path == folder / "_data" / "merged.parquet" and not path.exists() and path.parent.is_dir()
        pl.DataFrame({"n": [1]}).write_parquet(path)  # the first write of a new pipeline
        assert data.load("merged", project_dir=folder).collect().shape == (1, 1)

    def test_a_folder_datasets_parent_is_made_and_polars_makes_the_folder(self, tmp_path):
        folder = _pipeline(tmp_path.resolve())
        path = data.path("articles", project_dir=folder)
        assert path == folder / "_data" / "articles" and path.parent.is_dir() and not path.exists()
        pl.DataFrame({"year": [2023, 2024], "n": [1, 2]}).write_parquet(path, partition_by="year")
        assert sorted(p.name for p in path.iterdir()) == ["year=2023", "year=2024"]
        assert data.load("articles", project_dir=folder).collect().shape == (2, 2)

    def test_a_file_with_no_ending_stays_a_file(self, tmp_path):
        """Found by a review: a path with no ending may be a parquet file, as the reference says."""
        folder = _pipeline(tmp_path.resolve())
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "rates"}, "dataframes": {"gdp": {"path": "./_data/gdp", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        path = data.path("gdp", project_dir=folder)
        assert not path.exists() and path.parent.is_dir()
        pl.DataFrame({"n": [1]}).write_parquet(path)
        assert data.load("gdp", project_dir=folder).collect().shape == (1, 1)

    def test_a_globs_folder_is_made(self, tmp_path):
        folder = _pipeline(tmp_path.resolve())
        path = data.path("parts", project_dir=folder)
        assert "**" in str(path) and (folder / "_data" / "parts").is_dir()

    def test_charts_and_models_too(self, tmp_path):
        folder = _pipeline(tmp_path.resolve())
        assert assets.path("chart/curve", project_dir=folder).parent == folder / "_output" / "charts"
        assert (folder / "_output" / "charts").is_dir()
        assert models.path("ar1", project_dir=folder).parent.is_dir() and not (folder / "_models" / "ar1").exists()
        assert models.path("pickled", project_dir=folder).parent.is_dir() and not (folder / "_models" / "pickled.pkl").exists()

    def test_nothing_is_made_where_a_file_stands(self, tmp_path):
        folder = _pipeline(tmp_path.resolve())
        (folder / "_data").mkdir()
        (folder / "_data" / "articles").write_bytes(b"a file where a folder was declared")
        assert data.path("articles", project_dir=folder).is_file()  # left to the write to say so

    def test_nothing_is_made_outside_the_pipeline_or_for_another_pipelines_asset(self, tmp_path):
        from chartbook import links

        work = tmp_path.resolve()
        folder = _pipeline(work)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "rates"},
                "dataframes": {"out": {"path": "../shared/out.parquet", "docs": "d"}},
                "dependencies": {"acme/other": {}},
            }),
            encoding="utf-8", newline="\n",
        )
        assert data.path("out", project_dir=folder) == work / "shared" / "out.parquet" and not (work / "shared").exists()
        other = work / "other"
        other.mkdir()
        (other / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/other"}, "dataframes": {"df": {"path": "./_data/df.parquet", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        links.add(folder, "acme/other", other)
        with pytest.warns(links.LinkedDependencyWarning):
            assert data.path("acme/other:df", project_dir=folder) == other / "_data" / "df.parquet"
        assert not (other / "_data").exists()  # another pipeline's folder is its own

    def test_a_pipeline_folder_named_with_a_bracket_is_no_glob(self, tmp_path):
        work = tmp_path.resolve() / "Research [2026]"
        work.mkdir()
        folder = _pipeline(work)
        path = data.path("merged", project_dir=folder)
        assert path.parent == folder / "_data" and path.parent.is_dir()
        parts = data.path("parts", project_dir=folder)
        assert (folder / "_data" / "parts").is_dir() and "**" in str(parts)


class TestScratch:
    def test_the_default_is_under_data(self, tmp_path):
        folder = _pipeline(tmp_path.resolve())
        scratch = data.scratch(project_dir=folder)
        assert scratch == folder / "_data" / "_scratch" and scratch.is_dir()
        assert (scratch / ".gitignore").read_text(encoding="utf-8") == "*\n"

    def test_the_project_may_name_it(self, tmp_path):
        folder = _pipeline(tmp_path.resolve(), {"scratch": "./_tmp/scratch"})
        scratch = data.scratch(project_dir=folder)
        assert scratch == folder / "_tmp" / "scratch" and scratch.is_dir() and (scratch / ".gitignore").is_file()

    @pytest.mark.parametrize("declared", ["../elsewhere", "/tmp/x", ".", ""])
    def test_a_path_outside_the_pipeline_is_refused(self, tmp_path, declared):
        from chartbook.manifest import load_manifest

        folder = _pipeline(tmp_path.resolve(), {"scratch": declared})
        if declared == "":
            assert data.scratch(project_dir=folder) == folder / "_data" / "_scratch"
            return
        with pytest.raises(ValueError, match="scratch = .* is not a plain path inside the pipeline"):
            data.scratch(project_dir=folder)
        with pytest.raises(ValueError, match="scratch = .* is not a plain path inside the pipeline"):
            load_manifest(folder)  # and the manifest refuses it, so `chartbook check` says so too

    @pytest.mark.parametrize("declared, asset", [
        ("./_data/articles/_tmp", "dataframes.articles"),
        ("./_data/articles", "dataframes.articles"),
        ("./_data/merged.parquet/x", "dataframes.merged"),
        ("./_models/ar1/scratch", "models.ar1"),
    ])
    def test_one_inside_a_declared_asset_is_refused(self, tmp_path, declared, asset):
        """Its files would be hashed with the asset and go to the store with it (found reviewing 0.5.0)."""
        from chartbook.manifest import load_manifest

        folder = _pipeline(tmp_path.resolve(), {"scratch": declared})
        with pytest.raises(ValueError, match=rf"is inside \[{asset}\] path"):
            data.scratch(project_dir=folder)
        with pytest.raises(ValueError, match=rf"is inside \[{asset}\] path"):
            load_manifest(folder)
        assert not (folder / "_data").exists()

    def test_one_beside_the_data_or_under_a_globs_folder_is_taken(self, tmp_path):
        folder = _pipeline(tmp_path.resolve(), {"scratch": "./_data/_tmp"})
        assert data.scratch(project_dir=folder) == folder / "_data" / "_tmp"
