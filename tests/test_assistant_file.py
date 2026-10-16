"""Every site has an assistant file, `llms.txt`, written from its index
(docs_src/design/versioned-catalog.md, step 4)."""

import re
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook.cli import main
from tests.fixtures import create_pipeline_project
from tests import test_versioned_catalog as versioned
from tests.test_versioned_catalog import (  # noqa: F401  (catalog is a fixture)
    _build,
    _elsewhere_with,
    _show_from_the_store,
    catalog,
)

_LINK = re.compile(r"(?<!\\)\[(?:[^\]\\]|\\.)*\]\(([^)\s]+)\)")


def _links(text: str) -> list[str]:
    return _LINK.findall(text)


def _all_resolve(site: Path, text: str) -> list[str]:
    """The links of an assistant file that do not lead to a file in the site."""
    return [link for link in _links(text) if not (site / link).is_file()]


class TestACatalogsFile:
    def test_it_lists_every_page_and_every_version(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch)
        site = root / "docs"
        text = (site / "llms.txt").read_text()
        assert text.startswith("# ")
        assert "## Pipelines" in text and "## Dataframes" in text
        assert "[index.json](index.json)" in text
        assert _links(text) and _all_resolve(site, text) == []
        line = next(line for line in text.splitlines() if "`pipeline_a`" in line)
        assert line.startswith("- [") and "cb/pipelines/pipeline_a_README.html" in line
        # Newest first, each linking the version site's own file, which is there
        versions = [link for link in _links(line) if link.startswith("versions/")]
        assert len(versions) == 2 and all(link.endswith("/llms.txt") for link in versions)
        assert second.commit[:7] in versions[0] and first.commit[:7] in versions[1]
        own = (site / versions[0]).read_text()
        assert f"This site is the snapshot of `pipeline_a` at commit `{second.commit[:7]}`" in own
        assert _all_resolve((site / versions[0]).parent, own) == []
        # Each dataframe by its ID
        assert re.search(r"^- \[.*\]\(cb/dataframes/pipeline_a/[^)]+\.html\): `pipeline_a:", text, re.M)

    def test_a_pipeline_from_the_store_says_so_and_its_words_make_no_link(self, catalog, tmp_path, monkeypatch):
        root, first, second = catalog
        secret = tmp_path / "secret.txt"
        fields = {k: v.replace("SECRET", str(secret)) for k, v in versioned.TestWhatTheStoreOnlyReviewFound.HOSTILE.items()}
        fields["description"] += " [a link](https://example.org) <https://example.org>"
        _elsewhere_with(tmp_path, **fields)
        _show_from_the_store(root)
        _build(root, monkeypatch)
        site = root / "docs"
        text = (site / "llms.txt").read_text()
        line = next(line for line in text.splitlines() if "`pipeline_c`" in line)
        assert "not on this machine" in line
        assert "\n" not in line.strip()
        # Only the links the writer made: the page and the version; all in the site
        assert _all_resolve(site, text) == []
        assert not any("example.org" in link or "javascript" in link for link in _links(text))

    def test_with_mkdocs_too(self, catalog, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = catalog
        manifest = tomli.loads((root / "chartbook.toml").read_text())
        manifest["project"]["writer"] = "mkdocs"
        (root / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        _build(root, monkeypatch)
        site = root / "docs"
        text = (site / "llms.txt").read_text()
        assert "`pipeline_a`" in text and _all_resolve(site, text) == []


class TestAPipelinesFile:
    def _site(self, tmp_path, monkeypatch, *arguments) -> Path:
        project = create_pipeline_project(tmp_path / "rates", pipeline_id="rates", pipeline_name="Rates")
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f", *arguments])
        assert result.exit_code == 0, result.output
        return project / "docs"

    def test_it_lists_the_pipelines_pages(self, tmp_path, monkeypatch):
        site = self._site(tmp_path, monkeypatch)
        text = (site / "llms.txt").read_text()
        assert text.startswith("# Rates\n")
        assert "- [Rates](index.html): `rates`. Description for Rates.\n" in text
        assert "## Dataframes" in text and _all_resolve(site, text) == []
        assert "This site is the snapshot" not in text and "versions/" not in text

    def test_an_incremental_build_keeps_it_and_leaves_it_alone(self, tmp_path, monkeypatch):
        site = self._site(tmp_path, monkeypatch, "--incremental")
        written = (site / "llms.txt").stat().st_mtime_ns
        result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--incremental"])
        assert result.exit_code == 0, result.output
        assert (site / "llms.txt").stat().st_mtime_ns == written


class TestTheLineText:
    def test_one_line_cut_at_a_word(self):
        from chartbook.writers.sphinx import _one_line

        assert _one_line("Rates\n\n and  more") == "Rates and more"
        assert _one_line("word " * 100, 20) == "word word word word…"
        assert _one_line("word " * 100, 21) == "word word word word…"
        assert _one_line("a" * 50, 10) == "a" * 9 + "…"
        assert _one_line(None) == ""

    def test_link_text_starts_no_link(self):
        from chartbook.writers.sphinx import _link_text

        assert _link_text("[a](b) <c> `d`") == "\\[a\\](b) \\<c\\> \\`d\\`"
        assert _link_text("yield_curve") == "yield_curve"
