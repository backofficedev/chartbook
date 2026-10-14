"""The provenance panel: what a page says about an asset, from the index alone."""

import json
from pathlib import Path

from click.testing import CliRunner

from chartbook import provenance
from chartbook.cli import main

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

    def test_no_record_no_panel(self):
        assert provenance.panel("acme/rates:nope", RECORDS) is None
        assert provenance.panel("x", {}) is None


class TestOnThePage:
    def test_every_asset_page_carries_the_panel_from_the_index(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        built = json.loads((pipeline_project / "_docs" / "index.json").read_text())
        records = {r["id"]: r for r in built["records"]}
        pages = {
            "Dataframe": list((pipeline_project / "_docs" / "cb" / "dataframes").glob("*/*.md")),
            "Chart": list((pipeline_project / "_docs" / "cb" / "charts").glob("*.md")),
        }
        assert pages["Dataframe"] and pages["Chart"]
        for kind, files in pages.items():
            for page in files:
                text = page.read_text()
                assert "## Provenance" in text, page
                assert "What this is, where it is, what made it and from what, as `index.json` records it." in text
        dataframe = [r for r in records.values() if r["kind"] == "Dataframe" and r.get("content_hash")][0]
        page = next(p for p in pages["Dataframe"] if p.stem == dataframe["id"].rsplit(":", 1)[1])
        text = page.read_text()
        assert f"| What                           | Dataframe `{dataframe['id']}`" in text
        assert dataframe["content_hash"] in text and f"{dataframe['row_count']:,} rows" in text
        chart = [r for r in records.values() if r["kind"] == "Chart"][0]
        assert f"**Used by:** `{chart['id']}`" in text
        chart_text = [p for p in pages["Chart"] if chart["id"].rsplit("/", 1)[1] in p.stem][0].read_text()
        assert f"- `{dataframe['id']}`: now at `{dataframe['content_hash'][:19]}…`" in chart_text
