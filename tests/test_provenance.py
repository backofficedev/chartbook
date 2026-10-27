"""The provenance panel: what a page says about an asset, from the index alone."""

import json
from pathlib import Path

import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import provenance
from chartbook.cli import main
from tests.fixtures import create_catalog_project

H = "sha256:" + "a" * 64
H2 = "sha256:" + "b" * 64
H3 = "sha256:" + "c" * 64

RECORDS = {
    "acme/rates": {
        "kind": "Pipeline", "id": "acme/rates", "scripts": {"build": "doit"},
        "assets": ["acme/rates:treasury", "acme/rates:chart/curve"],
    },
    "acme/rates:treasury": {
        "kind": "Dataframe", "id": "acme/rates:treasury", "pipeline": "acme/rates",
        "location": {"kind": "file", "path": "./_data/treasury.parquet"},
        "content_hash": H, "size_bytes": 5084406, "row_count": 16580,
        "columns": [{"name": "d"}, {"name": "r"}],
    },
    "acme/rates:treasury#r": {"kind": "Series", "id": "acme/rates:treasury#r", "dataframe": "acme/rates:treasury"},
    "acme/rates:chart/curve": {
        "kind": "Chart", "id": "acme/rates:chart/curve", "pipeline": "acme/rates",
        "location": {"kind": "file", "path": "./_output/curve.html"}, "content_hash": H2,
        "inputs": ["acme/rates:treasury"],
    },
    "acme/rates:slopes": {
        "kind": "Dataframe", "id": "acme/rates:slopes", "pipeline": "acme/rates",
        "location": {"kind": "query", "source": "local", "backend": "duckdb", "sql": "select 1"},
        "definition_hash": H3, "row_count": 3, "columns": [{"name": "x"}],
    },
    "acme/forecast": {
        "kind": "Pipeline", "id": "acme/forecast", "scripts": {"build": "python train.py"},
        "dependencies": [{"id": "acme/rates", "via": "path", "location": {"kind": "path", "commit": "0f900fc5d2d968196ef7e5b213a45738b542460c"}, "snapshot": "2026-10-14T08:24:42.137891Z", "pinned_hash": H}],
    },
    "acme/forecast:model/m": {
        "kind": "Model", "id": "acme/forecast:model/m", "pipeline": "acme/forecast",
        "location": {"kind": "file", "path": "./_models/m.json"}, "content_hash": H3, "size_bytes": 128,
        "inputs": ["acme/rates:treasury", "acme/forecast:d"],
        "pinned_inputs": {"acme/rates:treasury": H},
        "trained_with": {"acme/rates:treasury": H2, "acme/forecast:d": H},
        "stale_inputs": ["acme/rates:treasury"],
        "versions": [{"version": "cccccccccccc", "content_hash": H3, "made_at": "2026-10-14T09:00:00Z", "commit": "1234567890abcdef1234567890abcdef12345678", "labels": ["champion"]}],
    },
}


class TestPanel:
    def test_no_hash_is_not_built_only_when_nothing_is_there(self, tmp_path):
        """A file that is there and could not be read has no hash either; it is not "not built"."""
        there = tmp_path / "there.parquet"
        there.write_bytes(b"PAR1")
        records = {
            "p": {"kind": "Pipeline", "id": "p", "assets": ["p:there", "p:missing"]},
            "p:there": {
                "kind": "Dataframe", "id": "p:there", "pipeline": "p",
                "location": {"kind": "file", "path": "./there.parquet", "resolved_path": str(there)},
            },
            "p:missing": {
                "kind": "Dataframe", "id": "p:missing", "pipeline": "p",
                "location": {"kind": "file", "path": "./missing.parquet", "resolved_path": str(tmp_path / "missing.parquet")},
            },
        }
        assert provenance.panel("p:there", records)["content"] == "could not be read"
        assert provenance.panel("p:missing", records)["content"] == "not built"

    def test_a_dataframe(self):
        p = provenance.panel("acme/rates:treasury", RECORDS)
        assert p["kind"] == "Dataframe" and p["pipeline"] == "acme/rates"
        assert p["where"] == "`./_data/treasury.parquet`"
        assert p["content"] == f"`{H}` · 5,084,406 bytes · 16,580 rows · 2 columns"
        assert p["build"] == "doit"
        assert p["inputs"] == [] and p["used_by"] == ["acme/forecast:model/m", "acme/rates:chart/curve"]
        assert p["series"] == 1 and p["version"] is None

    def test_a_query_dataframe_and_a_chart(self):
        q = provenance.panel("acme/rates:slopes", RECORDS)
        assert q["where"] == "a query in source `local` (duckdb)"
        assert q["content"] == f"definition `{H3}` · 3 rows · 1 columns"
        c = provenance.panel("acme/rates:chart/curve", RECORDS)
        (made_from,) = c["inputs"]
        assert made_from["id"] == "acme/rates:treasury" and made_from["in_site"] and not made_from["cross"]
        assert made_from["words"] == f"now at `{H[:19]}…`"

    def test_a_model_with_a_pinned_input_that_moved(self):
        p = provenance.panel("acme/forecast:model/m", RECORDS)
        assert p["build"] == "python train.py"
        assert p["version"] == {"name": "cccccccccccc", "made_at": "2026-10-14T09:00:00Z", "commit": "1234567890abcdef1234567890abcdef12345678", "labels": ["champion"]}
        cross, local = p["inputs"]
        assert cross["cross"] and cross["pin"] == {"commit": "0f900fc5d2d968196ef7e5b213a45738b542460c", "snapshot": "2026-10-14T08:24:42.137891Z", "via": "path"}
        assert cross["words"] == (
            f"pinned at `{H[:19]}…`; from the snapshot at `0f900fc`, made 2026-10-14; "
            f"**moved since this was trained** (trained with `{H2[:19]}…`)"
        )
        assert local["words"] == "not in this site; as trained"
        assert p["stale"] == ["acme/rates:treasury"]

    def test_a_pinned_input_whose_upstream_moved_on_since(self):
        """Found by a reviewer: pinned and in the site, the line said nothing of
        the live upstream having moved on since the pin."""
        records = {k: dict(v) for k, v in RECORDS.items()}
        records["acme/rates:treasury"]["content_hash"] = H2
        records["acme/forecast:model/m"] = {k: v for k, v in records["acme/forecast:model/m"].items() if k not in ("trained_with", "stale_inputs")}
        cross, _ = provenance.panel("acme/forecast:model/m", records)["inputs"]
        assert cross["words"] == (
            f"pinned at `{H[:19]}…`; from the snapshot at `0f900fc`, made 2026-10-14; "
            f"now at `{H2[:19]}…` in this site: the upstream has moved on since the pin"
        )

    def test_a_pipe_in_a_cell_is_escaped(self):
        """Found by a reviewer: a build script with a pipe broke the table row."""
        records = {k: dict(v) for k, v in RECORDS.items()}
        records["acme/rates"] = {**records["acme/rates"], "scripts": {"build": "doit | tee build.log"}}
        p = provenance.panel("acme/rates:treasury", records)
        assert p["build"] == "doit \\| tee build.log"

    def test_the_reverse_map_gives_the_same_panels(self):
        """Found by a reviewer: every panel scanned every record twice."""
        reversed_index = provenance.reverse(RECORDS)
        for record_id in RECORDS:
            assert provenance.panel(record_id, RECORDS, reversed_index) == provenance.panel(record_id, RECORDS)
        assert reversed_index["used_by"]["acme/rates:treasury"] == ["acme/forecast:model/m", "acme/rates:chart/curve"]
        assert reversed_index["series"] == {"acme/rates:treasury": 1}

    def test_the_digest_moves_with_what_the_panels_say(self):
        before = provenance.digest("acme/forecast", RECORDS)
        assert before == provenance.digest("acme/forecast", RECORDS)
        records = {k: dict(v) for k, v in RECORDS.items()}
        records["acme/rates:treasury"]["content_hash"] = H2  # another pipeline's record
        assert provenance.digest("acme/forecast", records) != before
        assert provenance.digest("acme/forecast", records) != provenance.digest("acme/rates", records)

    def test_no_record_no_panel(self):
        assert provenance.panel("acme/rates:nope", RECORDS) is None
        assert provenance.panel("x", {}) is None


class TestOnThePage:
    def test_every_asset_page_carries_the_panel_from_the_index(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        built = json.loads((pipeline_project / "_docs" / "index.json").read_text(encoding="utf-8"))
        records = {r["id"]: r for r in built["records"]}
        pages = {
            "Dataframe": list((pipeline_project / "_docs" / "cb" / "dataframes").glob("*/*.md")),
            "Chart": list((pipeline_project / "_docs" / "cb" / "charts").glob("*.md")),
        }
        assert pages["Dataframe"] and pages["Chart"]
        for kind, files in pages.items():
            for page in files:
                text = page.read_text(encoding="utf-8")
                assert "## Provenance" in text, page
                assert "What this is, where it is, what made it and from what, as `index.json` records it." in text
        dataframe = [r for r in records.values() if r["kind"] == "Dataframe" and r.get("content_hash")][0]
        page = next(p for p in pages["Dataframe"] if p.stem == dataframe["id"].rsplit(":", 1)[1])
        text = page.read_text(encoding="utf-8")
        assert f"| What                           | Dataframe `{dataframe['id']}`" in text
        assert dataframe["content_hash"] in text and f"{dataframe['row_count']:,} rows" in text
        chart = [r for r in records.values() if r["kind"] == "Chart"][0]
        assert f"**Used by:** `{chart['id']}`" in text
        chart_text = [p for p in pages["Chart"] if chart["id"].rsplit("/", 1)[1] in p.stem][0].read_text(encoding="utf-8")
        assert f"- `{dataframe['id']}`: now at `{dataframe['content_hash'][:19]}…`" in chart_text


def _edit_toml(path: Path, edit) -> None:
    config = tomli.loads(path.read_text(encoding="utf-8"))
    edit(config)
    path.write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")


class TestIncrementalBuildsKeepThePanelsCurrent:
    """Found by a reviewer: a reused pipeline's pages kept panels that had read
    other pipelines' records, so after an upstream rebuild the page disagreed
    with index.json."""

    def _catalog(self, tmp_path) -> Path:
        catalog = create_catalog_project(tmp_path / "cat")

        def scope(config):
            for name in ("pipeline_a", "pipeline_b"):
                config["pipelines"][f"acme/{name}"] = config["pipelines"].pop(name)

        _edit_toml(catalog / "chartbook.toml", scope)
        a = catalog / "pipelines" / "pipeline_a"
        (a / "_models").mkdir(exist_ok=True)
        (a / "_models" / "m.json").write_text("{}", encoding="utf-8", newline="\n")

        def model(config):
            config["dependencies"] = {"acme/pipeline_b": {"path": "../pipeline_b"}}
            config["models"] = {"m": {"path": "./_models/m.json", "trained_on": ["acme/pipeline_b:dataframe_0"], "docs": "A model."}}

        _edit_toml(a / "chartbook.toml", model)
        return catalog

    def test_an_upstream_rebuild_and_a_new_user_reach_the_reused_pages(self, tmp_path, monkeypatch):
        catalog = self._catalog(tmp_path)
        monkeypatch.chdir(catalog)
        runner = CliRunner()
        model_page = catalog / "_docs" / "cb" / "models" / "acme--pipeline_a" / "m.md"
        upstream_page = catalog / "_docs" / "cb" / "dataframes" / "acme--pipeline_b" / "dataframe_0.md"
        parquet = next((catalog / "pipelines" / "pipeline_b" / "_data").rglob("dataframe_0.parquet"))

        from chartbook import index as index_module

        builds = []
        real_build = index_module.build_index
        monkeypatch.setattr(index_module, "build_index", lambda *a, **k: (builds.append(1), real_build(*a, **k))[1])

        first = runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert first.exit_code == 0, first.output
        assert len(builds) == 1  # the index is built once per build, and handed to the pages
        pipelines = {r["id"]: r for r in json.loads((catalog / "_docs" / "index.json").read_text(encoding="utf-8"))["records"] if r["kind"] == "Pipeline"}
        assert all(p["code_changed_at"].endswith("Z") for p in pipelines.values())  # a docs build dates the code
        index_1 = json.loads((catalog / "_docs" / "index.json").read_text(encoding="utf-8"))
        hash_1 = next(r for r in index_1["records"] if r["id"] == "acme/pipeline_b:dataframe_0")["content_hash"]
        # The model page, built for real, carries the panel from the index, in the catalog theme
        text = model_page.read_text(encoding="utf-8")
        assert "## Provenance" in text and f"- `acme/pipeline_b:dataframe_0`: now at `{hash_1[:19]}…`" in text
        assert "| What                           | Model `acme/pipeline_a:model/m`" in text

        # Nothing changed: both pipelines are reused
        again = runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert again.exit_code == 0 and "regenerated 0 of 2" in again.output, again.output

        # The upstream rebuilds its dataframe: pipeline_a's own files are the
        # same, and its model page must still say the new hash
        parquet.write_bytes(parquet.read_bytes() + b"\0")
        second = runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert second.exit_code == 0, second.output
        index_2 = json.loads((catalog / "_docs" / "index.json").read_text(encoding="utf-8"))
        hash_2 = next(r for r in index_2["records"] if r["id"] == "acme/pipeline_b:dataframe_0")["content_hash"]
        assert hash_2 != hash_1
        assert f"now at `{hash_2[:19]}…`" in model_page.read_text(encoding="utf-8")
        assert "regenerated 2 of 2" in second.output, second.output

        # A second model in pipeline_a uses the upstream dataframe: the
        # upstream's page, whose own files did not change, lists it
        (catalog / "pipelines" / "pipeline_a" / "_models" / "m2.json").write_text("{}", encoding="utf-8", newline="\n")
        _edit_toml(
            catalog / "pipelines" / "pipeline_a" / "chartbook.toml",
            lambda c: c["models"].update({"m2": {"path": "./_models/m2.json", "trained_on": ["acme/pipeline_b:dataframe_0"], "docs": "d"}}),
        )
        third = runner.invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert third.exit_code == 0, third.output
        assert "regenerated 2 of 2" in third.output, third.output  # pipeline_b on its panels alone
        assert "`acme/pipeline_a:model/m2`" in upstream_page.read_text(encoding="utf-8")
        assert len(builds) == 4

    def test_a_directory_that_is_not_a_build_tree_is_refused_before_any_work(self, tmp_path, monkeypatch):
        catalog = self._catalog(tmp_path)
        monkeypatch.chdir(catalog)
        (catalog / "_docs").mkdir()
        (catalog / "_docs" / "unrelated.txt").write_text("mine", encoding="utf-8", newline="\n")
        from chartbook import index as index_module

        monkeypatch.setattr(index_module, "build_index", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the index was built first")))
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f", "--incremental"])
        assert result.exit_code != 0 and "is not a ChartBook build directory" in result.output
