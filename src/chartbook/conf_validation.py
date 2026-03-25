"""Security validation for user-provided configuration values.

This module provides validation for values that will be inserted into
conf.py templates. Since conf.py is executed as Python code by Sphinx,
all user input must be validated to prevent code injection attacks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
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

        :param field_name: Name of the field (for error messages).
        :type field_name: str
        :param value: The value to validate.
        :type value: str
        :param allow_empty: Whether empty strings are allowed.
        :type allow_empty: bool
        :raises ValidationError: If validation fails.
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

        :param theme: Theme name to validate.
        :type theme: str
        :raises ValidationError: If theme is not in allowed list.
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

        :param manifest: The manifest dictionary from chartbook.toml.
        :type manifest: dict
        :param pipeline_theme: Either "catalog" or "pipeline".
        :type pipeline_theme: str
        :returns: Validated SiteConfig instance.
        :rtype: SiteConfig
        :raises ValidationError: If any value fails validation.
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
            copyright=site.get("copyright") if "copyright" in site else str(datetime.now().year),
            sphinx_theme=sphinx_theme,
        )


def validate_conf_py_values(manifest: dict, pipeline_theme: str) -> SiteConfig:
    """Validate configuration values intended for conf.py template.

    This is the main entry point for validation. It ensures all values
    that will be inserted into conf.py are safe from code injection.

    :param manifest: The manifest dictionary from chartbook.toml.
    :type manifest: dict
    :param pipeline_theme: Either "catalog" or "pipeline".
    :type pipeline_theme: str
    :returns: Validated SiteConfig instance with all values safe for templating.
    :rtype: SiteConfig
    :raises ValidationError: If any value fails security validation.
    """
    return SiteConfig.from_manifest(manifest, pipeline_theme)


def validate_source_files(manifest: dict, base_dir) -> list:
    """Validate that all source files referenced in the manifest exist.

    Checks for the existence of:
    - Dataframe parquet files (path_to_parquet_data)
    - Dataframe documentation files (dataframe_docs_path, when mode="path")
    - Chart HTML files (path_to_html_chart)
    - Chart documentation files (chart_docs_path, when mode="path")
    - Notebook files (notebook_path)
    - Note markdown files (path_to_markdown_file)
    - README.md per pipeline
    - User-specified logo and favicon files

    :param manifest: The manifest dictionary from chartbook.toml.
    :type manifest: dict
    :param base_dir: The base directory of the project.
    :type base_dir: Path
    :returns: List of MissingFile objects for any files that don't exist.
    :rtype: list[MissingFile]
    """
    from pathlib import Path

    from chartbook.errors import MissingFile
    from chartbook.manifest import get_pipeline_ids, get_pipeline_manifest

    base_dir = Path(base_dir).resolve()
    missing_files = []

    pipeline_ids = get_pipeline_ids(manifest)

    for pipeline_id in pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_base_dir = Path(pipeline_manifest.get("pipeline_base_dir", base_dir))

        # Check dataframe files
        for dataframe_id, dataframe_config in pipeline_manifest.get("dataframes", {}).items():
            parquet_path = dataframe_config.get("path_to_parquet_data")
            if parquet_path and parquet_path.strip():
                from chartbook.utils import is_glob_pattern

                if is_glob_pattern(parquet_path):
                    import glob as glob_module

                    full_pattern = str(
                        (pipeline_base_dir / parquet_path).as_posix()
                    )
                    matching_files = glob_module.glob(
                        full_pattern, recursive=True
                    )
                    if not matching_files:
                        missing_files.append(
                            MissingFile(
                                file_path=Path(full_pattern),
                                file_type="dataframe",
                                item_id=dataframe_id,
                                pipeline_id=pipeline_id,
                            )
                        )
                else:
                    full_path = (pipeline_base_dir / parquet_path).resolve()
                    if not full_path.exists():
                        missing_files.append(
                            MissingFile(
                                file_path=full_path,
                                file_type="dataframe",
                                item_id=dataframe_id,
                                pipeline_id=pipeline_id,
                            )
                        )

            # Check dataframe documentation files (path mode only)
            doc_mode = dataframe_config.get("_doc_mode", "path")
            if doc_mode == "path":
                docs_path = dataframe_config.get("dataframe_docs_path")
                if docs_path and docs_path.strip():
                    full_path = (pipeline_base_dir / docs_path).resolve()
                    if not full_path.exists():
                        missing_files.append(
                            MissingFile(
                                file_path=full_path,
                                file_type="dataframe_docs",
                                item_id=dataframe_id,
                                pipeline_id=pipeline_id,
                            )
                        )

        # Check chart files
        for chart_id, chart_config in pipeline_manifest.get("charts", {}).items():
            chart_path = chart_config.get("path_to_html_chart")
            if chart_path and chart_path.strip():
                full_path = (pipeline_base_dir / chart_path).resolve()
                if not full_path.exists():
                    missing_files.append(
                        MissingFile(
                            file_path=full_path,
                            file_type="chart",
                            item_id=chart_id,
                            pipeline_id=pipeline_id,
                        )
                    )

            # Check chart documentation files (path mode only)
            doc_mode = chart_config.get("_doc_mode", "path")
            if doc_mode == "path":
                docs_path = chart_config.get("chart_docs_path")
                if docs_path and docs_path.strip():
                    full_path = (pipeline_base_dir / docs_path).resolve()
                    if not full_path.exists():
                        missing_files.append(
                            MissingFile(
                                file_path=full_path,
                                file_type="chart_docs",
                                item_id=chart_id,
                                pipeline_id=pipeline_id,
                            )
                        )

        # Check notebook files
        for notebook_id, notebook_config in pipeline_manifest.get("notebooks", {}).items():
            notebook_path = notebook_config.get("notebook_path")
            if notebook_path and notebook_path.strip():
                full_path = (pipeline_base_dir / notebook_path).resolve()
                if not full_path.exists():
                    missing_files.append(
                        MissingFile(
                            file_path=full_path,
                            file_type="notebook",
                            item_id=notebook_id,
                            pipeline_id=pipeline_id,
                        )
                    )

        # Check note markdown files
        for note_id, note_config in pipeline_manifest.get("notes", {}).items():
            md_path = note_config.get("path_to_markdown_file")
            if md_path and md_path.strip():
                full_path = (pipeline_base_dir / md_path).resolve()
                if not full_path.exists():
                    missing_files.append(
                        MissingFile(
                            file_path=full_path,
                            file_type="note",
                            item_id=note_id,
                            pipeline_id=pipeline_id,
                        )
                    )

        # Check README.md
        readme_path = (pipeline_base_dir / "README.md").resolve()
        if not readme_path.exists():
            missing_files.append(
                MissingFile(
                    file_path=readme_path,
                    file_type="readme",
                    item_id="README.md",
                    pipeline_id=pipeline_id,
                )
            )

    # Check user-specified logo and favicon (site-level, outside pipeline loop)
    logo_path = manifest.get("site", {}).get("logo_path", "")
    if logo_path:
        full_logo = (base_dir / logo_path).resolve()
        if not full_logo.exists():
            missing_files.append(
                MissingFile(
                    file_path=full_logo,
                    file_type="logo",
                    item_id="site.logo_path",
                    pipeline_id="(site)",
                )
            )

    favicon_path = manifest.get("site", {}).get("favicon_path", "")
    if favicon_path:
        full_favicon = (base_dir / favicon_path).resolve()
        if not full_favicon.exists():
            missing_files.append(
                MissingFile(
                    file_path=full_favicon,
                    file_type="favicon",
                    item_id="site.favicon_path",
                    pipeline_id="(site)",
                )
            )

    return missing_files
