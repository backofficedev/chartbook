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

from chartbook import sitefiles
from chartbook.build_docs import generate_docs, get_docs_src_path
from chartbook.manifest import load_manifest
from chartbook.writers.sphinx import freshness_fact
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
    """Write one pipeline's pages the way a build does: from the index, by the writer."""
    sitefiles.write_site(
        docs_build_dir,
        base_dir=project,
        pipeline_theme="pipeline",
        docs_src_dir=get_docs_src_path("pipeline"),
    )
    return load_manifest(project)["project"]["id"]


class TestFreshnessFact:
    def test_fields(self):
        moment = datetime(2024, 3, 5, 14, 7, 9, tzinfo=timezone.utc)
        fact = freshness_fact("Data updated", moment)
        assert fact["label"] == "Data updated"
        assert fact["date"] == "2024-03-05"
        assert fact["title"] == "2024-03-05 14:07 UTC"
        # ISO 8601 with a UTC offset, so a browser in any timezone agrees
        parsed = datetime.fromisoformat(fact["iso"])
        assert parsed.utcoffset() is not None
        assert parsed.astimezone(timezone.utc) == moment.astimezone(timezone.utc)

    def test_unknown_moment_gives_no_fact(self):
        assert freshness_fact("Data updated", None) is None

    def test_a_time_in_another_zone_is_said_in_utc(self):
        """Found by a new user: the front page said local and UTC times side by side,
        unlabelled. Every time on the site is in UTC and says so."""
        from datetime import timedelta

        chicago = timezone(timedelta(hours=-6))
        fact = freshness_fact("Data updated", datetime(2024, 3, 5, 23, 7, 9, tzinfo=chicago))
        assert fact["title"] == "2024-03-06 05:07 UTC"
        assert fact["date"] == "2024-03-06"
        assert fact["iso"] == "2024-03-06T05:07:09+00:00"


class TestGeneratedPages:
    def test_dataframe_page_says_when_its_data_changed(self, pipeline_project, tmp_path):
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
        # Only facts about this dataframe. When the pipeline's code changed is
        # said once, on the pipeline's own page.
        assert list(facts) == ["Data updated"]
        assert facts["Data updated"] == data_moment.astimezone()
        assert "Code updated" not in page
        assert "Date of Last Code Update" not in page

    def test_freshness_sits_directly_under_the_title(self, pipeline_project, tmp_path):
        pipeline_id = _generate(pipeline_project, tmp_path / "_docs")
        page = (
            tmp_path / "_docs" / "cb" / "dataframes" / pipeline_id / "dataframe_0.md"
        ).read_text()
        lines = [l for l in page.splitlines() if l.strip()]
        assert lines[0].startswith("# Dataframe: ")
        assert lines[1] == "```{raw} html"
        assert 'class="cb-freshness"' in lines[2]

    def test_chart_page_says_when_the_chart_and_its_data_changed(
        self, pipeline_project, tmp_path
    ):
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
        assert list(facts) == ["Chart updated", "Data updated"]
        assert facts["Chart updated"] == chart_moment.astimezone()
        assert facts["Data updated"] == data_moment.astimezone()
        assert "Code updated" not in page
        assert "Date of Last Code Update" not in page
        # Shown before the chart itself, not in the tables at the bottom
        assert page.index('class="cb-freshness"') < page.index("## Chart")
        # In chart listings, a chart is dated by when it was itself written, in UTC
        in_utc = chart_moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        assert page.startswith(f'---\ndate: "{in_utc}"')

    def test_asset_pages_do_not_change_when_only_the_code_does(
        self, pipeline_project, tmp_path
    ):
        """What keeps one edit from re-rendering every page of a pipeline."""
        first, second = tmp_path / "first", tmp_path / "second"
        pipeline_id = _generate(pipeline_project, first)
        source_file = pipeline_project / "src" / "dummy.py"
        source_file.write_text("# edited\n")
        os.utime(source_file, (source_file.stat().st_atime, source_file.stat().st_mtime + 3600))
        _generate(pipeline_project, second)
        for relative in (
            Path("cb") / "dataframes" / pipeline_id / "dataframe_0.md",
            Path("cb") / "charts" / f"{pipeline_id}.chart_0_0.md",
        ):
            assert (first / relative).read_text() == (second / relative).read_text()

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
        in_utc = datetime(2024, 3, 5, 12, 0, 0).astimezone(timezone.utc)
        assert match["title"] == in_utc.strftime("%Y-%m-%d %H:%M UTC")
        # ...and the text shown if the script never runs is the date itself
        assert match["date"] == in_utc.strftime("%Y-%m-%d")

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
            assert facts["Data updated"] == moment.astimezone()

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
            assert "Code updated" not in html

        # The pipeline's own page is where the code's date is given
        if theme == "pipeline":
            front_page = (output_dir / "index.html").read_text()
            assert 'Code updated <time class="cb-relative-time"' in front_page
            assert "Date of Last Code Update" in front_page
        else:
            assert "Date of Last Code Update" in (
                output_dir / "cb" / "pipelines.html"
            ).read_text()

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
