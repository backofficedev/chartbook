"""Tests for the validation module."""

import pytest

from chartbook.errors import ValidationError
from chartbook.validation import SiteConfig, validate_conf_py_values


class TestSiteConfig:
    """Tests for SiteConfig dataclass validation."""

    def test_valid_config_creation(self):
        """Test creating a valid SiteConfig."""
        config = SiteConfig(
            title="My Project",
            author="John Doe",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert config.title == "My Project"
        assert config.author == "John Doe"
        assert config.copyright == "2024"
        assert config.sphinx_theme == "pydata_sphinx_theme"

    def test_empty_title_raises(self):
        """Test that empty title raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="",
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "cannot be empty" in str(exc_info.value)
        assert exc_info.value.field_name == "site.title"

    def test_whitespace_only_title_raises(self):
        """Test that whitespace-only title raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="   ",
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "cannot be empty" in str(exc_info.value)

    def test_empty_author_allowed(self):
        """Test that empty author is allowed."""
        config = SiteConfig(
            title="Test",
            author="",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert config.author == ""

    def test_empty_copyright_allowed(self):
        """Test that empty copyright is allowed."""
        config = SiteConfig(
            title="Test",
            author="Test Author",
            copyright="",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert config.copyright == ""

    def test_code_injection_in_title_blocked(self):
        """Test that code injection attempts in title are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title='Test"; import os; os.system("rm -rf /")',
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "invalid characters" in str(exc_info.value)
        assert exc_info.value.field_name == "site.title"

    def test_double_quotes_blocked(self):
        """Test that double quotes are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title='Test "quoted" title',
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "invalid characters" in str(exc_info.value)

    def test_semicolon_blocked(self):
        """Test that semicolons are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="Test; malicious",
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "invalid characters" in str(exc_info.value)

    def test_parentheses_blocked(self):
        """Test that parentheses are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="Test()",
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "invalid characters" in str(exc_info.value)

    def test_brackets_blocked(self):
        """Test that brackets are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="Test[]",
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "invalid characters" in str(exc_info.value)

    def test_curly_braces_blocked(self):
        """Test that curly braces are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="Test{}",
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "invalid characters" in str(exc_info.value)

    def test_backslash_blocked(self):
        """Test that backslashes are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="Test\\nNewline",
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "invalid characters" in str(exc_info.value)

    def test_invalid_theme_blocked(self):
        """Test that invalid themes are blocked."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="Test",
                author="Test",
                copyright="2024",
                sphinx_theme="malicious_theme",
            )
        assert "Invalid sphinx theme" in str(exc_info.value)
        assert exc_info.value.field_name == "config.type"

    def test_max_length_exceeded(self):
        """Test that exceeding max length raises error."""
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig(
                title="A" * 201,
                author="Test",
                copyright="2024",
                sphinx_theme="pydata_sphinx_theme",
            )
        assert "exceeds maximum length" in str(exc_info.value)
        assert exc_info.value.field_name == "site.title"

    def test_max_length_boundary(self):
        """Test that exactly max length is allowed."""
        config = SiteConfig(
            title="A" * 200,
            author="Test",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert len(config.title) == 200

    def test_allowed_punctuation(self):
        """Test that allowed punctuation passes validation."""
        config = SiteConfig(
            title="My Project - Version 1.0, Beta!",
            author="John O'Brien & Co.",
            copyright="2024: All Rights Reserved",
            sphinx_theme="sphinx_book_theme",
        )
        assert "O'Brien" in config.author
        assert "-" in config.title
        assert "," in config.title
        assert "!" in config.title
        assert "&" in config.author
        assert ":" in config.copyright

    def test_single_quotes_allowed(self):
        """Test that single quotes are allowed (for names like O'Brien)."""
        config = SiteConfig(
            title="Test's Title",
            author="O'Brien",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert "'" in config.title
        assert "'" in config.author

    def test_accented_characters_allowed(self):
        """Test that accented Latin characters are allowed."""
        config = SiteConfig(
            title="Analyse des Donnees",
            author="Jose Garcia",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert "e" in config.title
        assert "e" in config.author

    def test_more_accented_characters(self):
        """Test various accented Latin-1 characters."""
        config = SiteConfig(
            title="Uber die Wissenschaft",
            author="Francois Muller",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert config.title == "Uber die Wissenschaft"
        assert config.author == "Francois Muller"

    def test_pydata_sphinx_theme_allowed(self):
        """Test that pydata_sphinx_theme is allowed."""
        config = SiteConfig(
            title="Test",
            author="Test",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert config.sphinx_theme == "pydata_sphinx_theme"

    def test_sphinx_book_theme_allowed(self):
        """Test that sphinx_book_theme is allowed."""
        config = SiteConfig(
            title="Test",
            author="Test",
            copyright="2024",
            sphinx_theme="sphinx_book_theme",
        )
        assert config.sphinx_theme == "sphinx_book_theme"


class TestSiteConfigFromManifest:
    """Tests for SiteConfig.from_manifest class method."""

    def test_from_manifest_catalog_theme(self):
        """Test creating config from manifest with catalog theme."""
        manifest = {
            "site": {
                "title": "My Catalog",
                "author": "Test Author",
                "copyright": "2024",
            }
        }
        config = SiteConfig.from_manifest(manifest, "catalog")
        assert config.title == "My Catalog"
        assert config.author == "Test Author"
        assert config.copyright == "2024"
        assert config.sphinx_theme == "pydata_sphinx_theme"

    def test_from_manifest_pipeline_theme(self):
        """Test creating config from manifest with pipeline theme."""
        manifest = {
            "site": {
                "title": "My Pipeline",
                "author": "Test Author",
                "copyright": "2024",
            }
        }
        config = SiteConfig.from_manifest(manifest, "pipeline")
        assert config.title == "My Pipeline"
        assert config.sphinx_theme == "sphinx_book_theme"

    def test_from_manifest_invalid_pipeline_theme(self):
        """Test that invalid pipeline theme raises error."""
        manifest = {"site": {"title": "Test", "author": "", "copyright": ""}}
        with pytest.raises(ValidationError) as exc_info:
            SiteConfig.from_manifest(manifest, "invalid")
        assert "Invalid pipeline theme" in str(exc_info.value)

    def test_from_manifest_missing_site_uses_defaults(self):
        """Test that missing site section uses defaults."""
        manifest = {}
        config = SiteConfig.from_manifest(manifest, "catalog")
        assert config.title == "chartbook"
        assert config.author == ""
        assert config.copyright == ""

    def test_from_manifest_partial_site_uses_defaults(self):
        """Test that partial site section uses defaults for missing fields."""
        manifest = {
            "site": {
                "title": "Custom Title",
            }
        }
        config = SiteConfig.from_manifest(manifest, "pipeline")
        assert config.title == "Custom Title"
        assert config.author == ""
        assert config.copyright == ""


class TestValidateConfPyValues:
    """Tests for the main validation entry point."""

    def test_validate_returns_site_config(self):
        """Test that validate_conf_py_values returns SiteConfig."""
        specs = {
            "site": {
                "title": "Test Project",
                "author": "Test Author",
                "copyright": "2024",
            }
        }
        result = validate_conf_py_values(specs, "pipeline")
        assert isinstance(result, SiteConfig)
        assert result.title == "Test Project"
        assert result.sphinx_theme == "sphinx_book_theme"

    def test_validate_with_catalog_theme(self):
        """Test validation with catalog theme."""
        specs = {
            "site": {
                "title": "My Catalog",
                "author": "Author",
                "copyright": "2024",
            }
        }
        result = validate_conf_py_values(specs, "catalog")
        assert result.sphinx_theme == "pydata_sphinx_theme"

    def test_validate_raises_on_invalid_input(self):
        """Test that validation raises on invalid input."""
        specs = {
            "site": {
                "title": 'Invalid"; title',
                "author": "Author",
                "copyright": "2024",
            }
        }
        with pytest.raises(ValidationError):
            validate_conf_py_values(specs, "pipeline")


class TestSecurityPatterns:
    """Tests specifically for security-related validation."""

    def test_python_function_call_injection(self):
        """Test that Python function calls are blocked via parentheses."""
        # Note: The string "import os" alone is safe because it's rendered
        # inside a string literal. The danger is when combined with quotes
        # or parentheses that could escape the string context.
        malicious_values = [
            "__import__('os')",  # Has parentheses and quotes
            "exec('code')",  # Has parentheses and quotes
            "eval(input())",  # Has parentheses
        ]
        for value in malicious_values:
            with pytest.raises(ValidationError):
                SiteConfig(
                    title=value,
                    author="Test",
                    copyright="2024",
                    sphinx_theme="pydata_sphinx_theme",
                )

    def test_safe_words_that_look_dangerous(self):
        """Test that words like 'import' are allowed when not in code context."""
        # These are safe because they're just words in a string literal
        config = SiteConfig(
            title="Data Import Tools",
            author="Import Export Team",
            copyright="2024",
            sphinx_theme="pydata_sphinx_theme",
        )
        assert "Import" in config.title
        assert "Import" in config.author

    def test_template_injection(self):
        """Test that template-like syntax is blocked."""
        malicious_values = [
            "{{ config }}",
            "{% if True %}",
            "${variable}",
        ]
        for value in malicious_values:
            with pytest.raises(ValidationError):
                SiteConfig(
                    title=value,
                    author="Test",
                    copyright="2024",
                    sphinx_theme="pydata_sphinx_theme",
                )

    def test_escape_sequence_injection(self):
        """Test that escape sequences are blocked."""
        malicious_values = [
            "test\\x00null",
            "test\\n\\r",
        ]
        for value in malicious_values:
            with pytest.raises(ValidationError):
                SiteConfig(
                    title=value,
                    author="Test",
                    copyright="2024",
                    sphinx_theme="pydata_sphinx_theme",
                )
