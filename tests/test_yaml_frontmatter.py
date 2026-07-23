"""Tests for YAML frontmatter safety in generated chart documentation."""

from pathlib import Path

import pytest
import yaml

from chartbook.markdown_generator import _validate_generated_frontmatter, _yaml_escape_filter


class TestGeneratedFrontmatterValidation:
    """Tests for _validate_generated_frontmatter()."""

    def test_valid_frontmatter_passes(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text('---\ndate: "2026-01-01"\ntags: "source1, source2"\ncategory: "Topic"\n---\n# Hello\n')
        _validate_generated_frontmatter(md_file, "pipeline1", "chart1")

    def test_malformed_frontmatter_exits(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("---\ndate: 2026-01-01\ntags: Constructed: CDS-bond basis\ncategory: test\n---\n# Hello\n")
        with pytest.raises(SystemExit):
            _validate_generated_frontmatter(md_file, "pipeline1", "chart1")

    def test_no_frontmatter_passes(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Just a heading\nNo frontmatter here.\n")
        _validate_generated_frontmatter(md_file, "pipeline1", "chart1")

    def test_incomplete_frontmatter_passes(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("---\ndate: 2026-01-01\nNo closing delimiter\n")
        _validate_generated_frontmatter(md_file, "pipeline1", "chart1")


class TestYamlEscapeFilter:
    """Tests for the _yaml_escape_filter Jinja2 filter."""

    def test_plain_text_unchanged(self):
        assert _yaml_escape_filter("hello world") == "hello world"

    def test_double_quotes_escaped(self):
        assert _yaml_escape_filter('He said "hello"') == 'He said \\"hello\\"'

    def test_backslashes_escaped(self):
        assert _yaml_escape_filter("path\\to\\file") == "path\\\\to\\\\file"

    def test_colon_unchanged(self):
        assert _yaml_escape_filter("key: value") == "key: value"

    def test_non_string_converted(self):
        assert _yaml_escape_filter(42) == "42"


class TestQuotedTemplateProducesValidYAML:
    """Verify that the quoted + escaped template approach produces valid YAML."""

    @pytest.mark.parametrize(
        "value",
        [
            "Constructed: CDS-bond basis",
            "S&P Capital IQ",
            "Source [v2]",
            "Source {internal}",
            "100% coverage",
            "CDS\u2013bond basis",
            "CDS\u2014bond basis",
            "!important source",
            "#1 data provider",
            "key: value: nested",
            'He said "hello"',
            "It's a test",
            "Line1, Line2",
            "Plain text",
        ],
    )
    def test_escaped_quoted_value_produces_valid_yaml(self, value):
        """Escaped + quoted interpolation must produce parseable YAML for any value."""
        escaped = _yaml_escape_filter(value)
        frontmatter = f'---\ndate: "2026-01-01"\ntags: "{escaped}"\ncategory: "test"\n---'
        parts = frontmatter.split("---", 2)
        parsed = yaml.safe_load(parts[1])
        assert parsed["tags"] == value
        assert parsed["category"] == "test"

    @pytest.mark.parametrize(
        "value",
        [
            "Constructed: CDS-bond basis",
            "!important source",
            "#1 data provider",
        ],
    )
    def test_unquoted_value_breaks_yaml(self, value):
        """Confirm that unquoted values with special chars produce invalid or wrong YAML."""
        frontmatter = f"---\ndate: 2026-01-01\ntags: {value}\ncategory: test\n---"
        parts = frontmatter.split("---", 2)
        try:
            parsed = yaml.safe_load(parts[1])
            assert parsed.get("tags") != value
        except yaml.YAMLError:
            pass  # Expected for truly broken YAML
