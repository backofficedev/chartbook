"""Security validation for user-provided configuration values.

This module provides validation for values that will be inserted into
conf.py templates. Since conf.py is executed as Python code by Sphinx,
all user input must be validated to prevent code injection attacks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from chartbook.errors import ValidationError


@dataclass
class SiteConfig:
    """Validated site configuration for conf.py template rendering.

    All string values are validated against security patterns to prevent
    Python code injection when rendered into conf.py templates.

    Attributes:
        title: Project title (alphanumeric, spaces, basic punctuation).
        author: Author name (alphanumeric, spaces, basic punctuation).
        copyright: Copyright text (alphanumeric, spaces, basic punctuation).
        sphinx_theme: Sphinx theme name (must be from allowed list).
    """

    title: str
    author: str
    copyright: str
    sphinx_theme: str

    # Class-level constants
    ALLOWED_THEMES: ClassVar[frozenset[str]] = frozenset(
        {
            "pydata_sphinx_theme",
            "sphinx_book_theme",
        }
    )

    # Regex pattern for safe text values
    # Allows: alphanumeric, spaces, common punctuation for names/titles,
    #         and Latin-1 accented characters (U+00C0 to U+00FF)
    # Disallows: quotes, backslashes, semicolons, parentheses, brackets, etc.
    SAFE_TEXT_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"^[a-zA-Z0-9\s\-_.,!?&:'\u00C0-\u00FF]+$"
    )

    # Maximum length for any text field
    MAX_TEXT_LENGTH: ClassVar[int] = 200

    def __post_init__(self) -> None:
        """Validate all fields after initialization."""
        self._validate_text_field("title", self.title, allow_empty=False)
        self._validate_text_field("author", self.author, allow_empty=True)
        self._validate_text_field("copyright", self.copyright, allow_empty=True)
        self._validate_theme(self.sphinx_theme)

    def _validate_text_field(
        self,
        field_name: str,
        value: str,
        allow_empty: bool = False,
    ) -> None:
        """Validate a text field for security.

        Args:
            field_name: Name of the field (for error messages).
            value: The value to validate.
            allow_empty: Whether empty strings are allowed.

        Raises:
            ValidationError: If validation fails.
        """
        if not isinstance(value, str):
            raise ValidationError(
                message=f"Field must be a string, got {type(value).__name__}",
                field_name=f"site.{field_name}",
                invalid_value=repr(value),
                hint="Ensure the value is a quoted string in chartbook.toml.",
            )

        if not allow_empty and not value.strip():
            raise ValidationError(
                message="Field cannot be empty",
                field_name=f"site.{field_name}",
                invalid_value=value,
                hint=f"Provide a non-empty value for site.{field_name} in chartbook.toml.",
            )

        if len(value) > self.MAX_TEXT_LENGTH:
            raise ValidationError(
                message=f"Field exceeds maximum length of {self.MAX_TEXT_LENGTH} characters",
                field_name=f"site.{field_name}",
                invalid_value=value,
                hint=f"Shorten the value to {self.MAX_TEXT_LENGTH} characters or less.",
            )

        # Empty strings pass validation (if allowed)
        if not value.strip():
            return

        if not self.SAFE_TEXT_PATTERN.match(value):
            raise ValidationError(
                message="Field contains invalid characters",
                field_name=f"site.{field_name}",
                invalid_value=value,
                hint=(
                    "Only alphanumeric characters, spaces, accented letters "
                    "(e.g., e, n, u), and basic punctuation (-_.,!?&:') are allowed. "
                    "Remove quotes, semicolons, parentheses, or other special characters."
                ),
            )

    def _validate_theme(self, theme: str) -> None:
        """Validate the sphinx theme is from allowed list.

        Args:
            theme: Theme name to validate.

        Raises:
            ValidationError: If theme is not in allowed list.
        """
        if theme not in self.ALLOWED_THEMES:
            raise ValidationError(
                message=f"Invalid sphinx theme: {theme!r}",
                field_name="config.type",
                invalid_value=theme,
                hint=f"Allowed themes: {', '.join(sorted(self.ALLOWED_THEMES))}",
            )

    @classmethod
    def from_manifest(cls, manifest: dict, pipeline_theme: str) -> SiteConfig:
        """Create a validated SiteConfig from manifest dictionary.

        Args:
            manifest: The manifest dictionary from chartbook.toml.
            pipeline_theme: Either "catalog" or "pipeline".

        Returns:
            Validated SiteConfig instance.

        Raises:
            ValidationError: If any value fails validation.
        """
        theme_mapping = {
            "catalog": "pydata_sphinx_theme",
            "pipeline": "sphinx_book_theme",
        }

        sphinx_theme = theme_mapping.get(pipeline_theme)
        if sphinx_theme is None:
            raise ValidationError(
                message=f"Invalid pipeline theme: {pipeline_theme!r}",
                field_name="config.type",
                invalid_value=pipeline_theme,
                hint="config.type must be either 'catalog' or 'pipeline'.",
            )

        site = manifest.get("site", {})

        return cls(
            title=site.get("title", "chartbook"),
            author=site.get("author", ""),
            copyright=site.get("copyright", ""),
            sphinx_theme=sphinx_theme,
        )


def validate_conf_py_values(manifest: dict, pipeline_theme: str) -> SiteConfig:
    """Validate configuration values intended for conf.py template.

    This is the main entry point for validation. It ensures all values
    that will be inserted into conf.py are safe from code injection.

    Args:
        manifest: The manifest dictionary from chartbook.toml.
        pipeline_theme: Either "catalog" or "pipeline".

    Returns:
        Validated SiteConfig instance with all values safe for templating.

    Raises:
        ValidationError: If any value fails security validation.
    """
    return SiteConfig.from_manifest(manifest, pipeline_theme)
