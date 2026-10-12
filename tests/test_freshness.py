"""Tests for the freshness line on asset pages.

A page says when its data, chart and code last changed, as timestamps in
``<time>`` elements. Turning those into "2 days ago" is done in the browser
by ``chartbook-freshness.js``, because the page is static.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chartbook import markdown_generator
from chartbook.build_docs import generate_docs, get_docs_src_path
from chartbook.manifest import load_manifest
from chartbook.markdown_generator import data_last_modified, freshness_fact
from tests.fixtures import create_pipeline_project

TIME_TAG = re.compile(
    r'(?P<label>[A-Z][a-z]+ updated) <time class="cb-relative-time" '
    r'datetime="(?P<iso>[^"]+)" title="(?P<title>[^"]+)">(?P<date>[^<]+)</time>'
)


def _set_mtime(path: Path, moment: datetime) -> None:
    os.utime(path, (moment.timestamp(), moment.timestamp()))


def _facts(page_text: str) -> dict:
    """The freshness line of a generated page, as ``{label: datetime}``."""
    line = next(l for l in page_text.splitlines() if 'class="cb-freshness"' in l)
    return {
        m["label"]: datetime.fromisoformat(m["iso"]) for m in TIME_TAG.finditer(line)
    }


def _generate(project: Path, docs_build_dir: Path):
    """Generate one pipeline's asset pages the way a build does."""
    manifest = load_manifest(project)
    pipeline_id = manifest["project"]["id"]
    markdown_generator.generate_pipeline_docs(
        pipeline_id,
        manifest,
        pipeline_base_dir=project,
        docs_build_dir=docs_build_dir,
        pipeline_theme="pipeline",
        docs_src_dir=get_docs_src_path("pipeline"),
    )
    return pipeline_id


class TestDataLastModified:
    def test_single_file(self, tmp_path):
        data_file = tmp_path / "data.parquet"
        data_file.write_text("x")
        moment = datetime(2024, 3, 5, 12, 0, 0)
        _set_mtime(data_file, moment)
        assert data_last_modified(data_file) == moment

    def test_partitioned_data_uses_the_newest_part(self, tmp_path):
        older, newer = datetime(2024, 1, 1, 9, 0, 0), datetime(2024, 6, 1, 9, 0, 0)
        for name, moment in (("a", older), ("b", newer)):
            part = tmp_path / f"part={name}" / "data.parquet"
            part.parent.mkdir()
            part.write_text("x")
            _set_mtime(part, moment)
        assert data_last_modified(tmp_path / "**" / "*.parquet") == newer

    def test_missing_data_is_unknown(self, tmp_path):
        assert data_last_modified(tmp_path / "nope.parquet") is None
        assert data_last_modified(tmp_path / "nope" / "*.parquet") is None


class TestFreshnessFact:
    def test_fields(self):
        moment = datetime(2024, 3, 5, 14, 7, 9)
        fact = freshness_fact("Data updated", moment)
        assert fact["label"] == "Data updated"
        assert fact["date"] == "2024-03-05"
        assert fact["title"].startswith("2024-03-05 14:07")
        # ISO 8601 with a UTC offset, so a browser in any timezone agrees
        parsed = datetime.fromisoformat(fact["iso"])
        assert parsed.utcoffset() is not None
        assert parsed.astimezone(timezone.utc) == moment.astimezone(timezone.utc)

    def test_unknown_moment_gives_no_fact(self):
        assert freshness_fact("Data updated", None) is None


class TestGeneratedPages:
    def test_dataframe_page_says_when_its_data_and_code_changed(self, pipeline_project, tmp_path):
        data_moment = datetime(2024, 3, 5, 12, 0, 0)
        _set_mtime(
            pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet",
            data_moment,
        )
        pipeline_id = _generate(pipeline_project, tmp_path / "_docs")
        page = (
            tmp_path / "_docs" / "cb" / "dataframes" / pipeline_id / "dataframe_0.md"
        ).read_text()

        facts = _facts(page)
        assert list(facts) == ["Data updated", "Code updated"]
        assert facts["Data updated"].replace(tzinfo=None) == data_moment
        code_moment = datetime.strptime(
            load_manifest(pipeline_project)["source_last_modified_date"],
            "%Y-%m-%d %H:%M:%S",
        )
        assert facts["Code updated"].replace(tzinfo=None) == code_moment

    def test_freshness_sits_directly_under_the_title(self, pipeline_project, tmp_path):
        pipeline_id = _generate(pipeline_project, tmp_path / "_docs")
        page = (
            tmp_path / "_docs" / "cb" / "dataframes" / pipeline_id / "dataframe_0.md"
        ).read_text()
        lines = [l for l in page.splitlines() if l.strip()]
        assert lines[0].startswith("# Dataframe: ")
        assert lines[1] == "```{raw} html"
        assert 'class="cb-freshness"' in lines[2]

    def test_chart_page_says_when_chart_data_and_code_changed(self, pipeline_project, tmp_path):
        chart_moment = datetime(2024, 4, 1, 8, 30, 0)
        data_moment = datetime(2024, 3, 5, 12, 0, 0)
        _set_mtime(pipeline_project / "_output" / "charts" / "chart_0_0.html", chart_moment)
        _set_mtime(
            pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet",
            data_moment,
        )
        pipeline_id = _generate(pipeline_project, tmp_path / "_docs")
        page = (tmp_path / "_docs" / "cb" / "charts" / f"{pipeline_id}.chart_0_0.md").read_text()

        facts = _facts(page)
        assert list(facts) == ["Chart updated", "Data updated", "Code updated"]
        assert facts["Chart updated"].replace(tzinfo=None) == chart_moment
        assert facts["Data updated"].replace(tzinfo=None) == data_moment
        # Shown before the chart itself, not in the tables at the bottom
        assert page.index('class="cb-freshness"') < page.index("## Chart")

    def test_absolute_time_is_available_on_hover(self, pipeline_project, tmp_path):
        _set_mtime(
            pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet",
            datetime(2024, 3, 5, 12, 0, 0),
        )
        pipeline_id = _generate(pipeline_project, tmp_path / "_docs")
        page = (
            tmp_path / "_docs" / "cb" / "dataframes" / pipeline_id / "dataframe_0.md"
        ).read_text()
        match = TIME_TAG.search(page)
        assert match["title"].startswith("2024-03-05 12:00")
        # ...and the text shown if the script never runs is the date itself
        assert match["date"] == "2024-03-05"

    def test_partitioned_dataframe_reports_real_data_time(self, tmp_path):
        """A glob path used to be stamped with the build time."""
        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        moment = datetime(2024, 2, 2, 2, 2, 2)
        for part in (project / "_data").rglob("*.parquet"):
            _set_mtime(part, moment)
        pipeline_id = _generate(project, tmp_path / "_docs")
        for page_path in (
            tmp_path / "_docs" / "cb" / "dataframes" / pipeline_id / "dataframe_0.md",
            tmp_path / "_docs" / "cb" / "charts" / f"{pipeline_id}.chart_0_0.md",
        ):
            facts = _facts(page_path.read_text())
            assert facts["Data updated"].replace(tzinfo=None) == moment

    def test_pages_do_not_change_between_builds(self, pipeline_project, tmp_path):
        """No "ago" text is baked in, so an unchanged project yields identical pages."""
        first, second = tmp_path / "first", tmp_path / "second"
        pipeline_id = _generate(pipeline_project, first)
        _generate(pipeline_project, second)
        for relative in (
            Path("cb") / "dataframes" / pipeline_id / "dataframe_0.md",
            Path("cb") / "charts" / f"{pipeline_id}.chart_0_0.md",
        ):
            text = (first / relative).read_text()
            assert text == (second / relative).read_text()
            assert " ago" not in text

    def test_chart_frontmatter_still_parses(self, pipeline_project, tmp_path):
        import yaml

        pipeline_id = _generate(pipeline_project, tmp_path / "_docs")
        page = (tmp_path / "_docs" / "cb" / "charts" / f"{pipeline_id}.chart_0_0.md").read_text()
        frontmatter = yaml.safe_load(page.split("---", 2)[1])
        assert set(frontmatter) == {"date", "tags", "category"}


class TestBuiltSite:
    @pytest.mark.parametrize("theme", ["pipeline", "catalog"])
    def test_time_elements_and_script_reach_the_html(
        self, theme, pipeline_project, catalog_project, monkeypatch
    ):
        project = pipeline_project if theme == "pipeline" else catalog_project
        monkeypatch.chdir(project)
        output_dir = project / "docs"
        generate_docs(output_dir=output_dir, project_dir=project)

        script = output_dir / "_static" / "chartbook-freshness.js"
        assert script.is_file()
        assert "cb-relative-time" in script.read_text()

        pages = list((output_dir / "cb" / "dataframes").rglob("dataframe_0.html"))
        pages += list((output_dir / "cb" / "charts").glob("*chart_0_0.html"))
        assert len(pages) >= 2
        for page in pages:
            html = page.read_text()
            assert '<p class="cb-freshness">' in html
            assert TIME_TAG.search(html), page
            assert "_static/chartbook-freshness.js" in html

    def test_script_is_identical_in_both_themes(self):
        scripts = [
            (get_docs_src_path(theme) / "_static" / "chartbook-freshness.js").read_text()
            for theme in ("pipeline", "catalog")
        ]
        assert scripts[0] == scripts[1]
        # Relative wording, worked out from the element's timestamp at read time
        assert "Date.now()" in scripts[0]
        assert "' ago'" in scripts[0]
        assert "getAttribute('datetime')" in scripts[0]
