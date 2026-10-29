"""Security validation for user-provided configuration values.

This module provides validation for values that will be inserted into
conf.py templates. Since conf.py is executed as Python code by Sphinx,
all user input must be validated to prevent code injection attacks.
"""

from __future__ import annotations

import os
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

    # Maps SiteConfig attribute -> the chartbook.toml key it comes from,
    # used in validation error messages.
    TOML_KEYS: ClassVar[dict[str, str]] = {
        "title": "project.name",
        "author": "project.maintainer",
        "copyright": "project.copyright",
    }

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
    # \s takes in a line break, which ends the Python string the value is
    # rendered into: _validate_text_field refuses one before this is asked.
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
        toml_key = self.TOML_KEYS.get(field_name, f"project.{field_name}")
        if not isinstance(value, str):
            raise ValidationError(
                message=f"Field must be a string, got {type(value).__name__}",
                field_name=toml_key,
                invalid_value=repr(value),
                hint="Ensure the value is a quoted string in chartbook.toml.",
            )

        if not allow_empty and not value.strip():
            raise ValidationError(
                message="Field cannot be empty",
                field_name=toml_key,
                invalid_value=value,
                hint=f"Provide a non-empty value for {toml_key} in chartbook.toml.",
            )

        if len(value) > self.MAX_TEXT_LENGTH:
            raise ValidationError(
                message=f"Field exceeds maximum length of {self.MAX_TEXT_LENGTH} characters",
                field_name=toml_key,
                invalid_value=value,
                hint=f"Shorten the value to {self.MAX_TEXT_LENGTH} characters or less.",
            )

        # The value is rendered into a one-line Python string in conf.py: a
        # line break would end it early, and Sphinx would stop on the file.
        # Before the blank check: a value that is only a line break is blank
        if "\n" in value or "\r" in value:
            raise ValidationError(
                message="Field must be one line",
                field_name=toml_key,
                invalid_value=value,
                hint=(
                    f"{toml_key} is written into the site's configuration as one line. "
                    "Remove the line break."
                ),
            )

        # Empty strings pass validation (if allowed)
        if not value.strip():
            return

        if not self.SAFE_TEXT_PATTERN.match(value):
            raise ValidationError(
                message="Field contains invalid characters",
                field_name=toml_key,
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
                field_name="project.type",
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
                field_name="project.type",
                invalid_value=pipeline_theme,
                hint="project.type must be either 'catalog' or 'pipeline'.",
            )

        project = manifest.get("project", {})

        return cls(
            title=project.get("name") or "chartbook",
            author=project.get("maintainer", ""),
            copyright=project.get("copyright") or str(datetime.now().year),
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


#: Kinds of missing file that are things a pipeline *builds*: data, rendered
#: charts, executed notebooks, trained models with their scores, and the
#: files of a files asset. They are normally git-ignored, so on a fresh
#: checkout that has not run the pipeline they are all absent.
OUTPUT_FILE_TYPES = frozenset(
    {"dataframe", "chart", "notebook", "model", "model_metrics", "file"}
)


def validate_source_files(manifest: dict, base_dir) -> list:
    """Validate that all source files referenced in the manifest exist.

    Checks for the existence of:
    - Dataframe parquet files (path)
    - Dataframe documentation files (docs_path, when mode="path")
    - Chart HTML files (path)
    - Chart documentation files (docs_path, when mode="path")
    - Notebook files (path)
    - Note markdown files (path)
    - Model files or directories (path), metrics files (metrics_path) and
      write-ups (docs_path)
    - The files of a files asset (path: a file, a folder that holds at
      least one file, or a glob that matches one) and its write-up
      (docs_path)
    - Each pipeline's README (project.readme)
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
            parquet_path = dataframe_config.get("path")
            if parquet_path and parquet_path.strip():
                from chartbook.utils import is_glob_pattern

                if is_glob_pattern(parquet_path):
                    from chartbook.hashing import find_files

                    full_pattern = str(
                        (pipeline_base_dir / parquet_path).as_posix()
                    )
                    # The files the index hashes and a site shows: a glob
                    # that matches only folders has none
                    found = find_files(full_pattern)
                    if found is None or not found.files:
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
                docs_path = dataframe_config.get("docs_path")
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
            chart_path = chart_config.get("path")
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
                docs_path = chart_config.get("docs_path")
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
            notebook_path = notebook_config.get("path")
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
            md_path = note_config.get("path")
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

        # Check model files: the model, its metrics and its write-up
        for model_id, model_config in (pipeline_manifest.get("models") or {}).items():
            for key, file_type in (
                ("path", "model"),
                ("metrics_path", "model_metrics"),
                ("docs_path", "model_docs"),
            ):
                declared = model_config.get(key)
                if declared and declared.strip():
                    full_path = (pipeline_base_dir / declared).resolve()
                    if not full_path.exists():
                        missing_files.append(
                            MissingFile(
                                file_path=full_path,
                                file_type=file_type,
                                item_id=model_id,
                                pipeline_id=pipeline_id,
                            )
                        )

        # Check files assets: the path must name at least one file, as the
        # snapshot and the index count them
        for files_id, files_config in (pipeline_manifest.get("files") or {}).items():
            declared = files_config.get("path")
            if declared and declared.strip():
                from chartbook.hashing import find_files

                full_path = Path(os.path.normpath(pipeline_base_dir / declared))
                found = find_files(full_path)
                if found is None or not found.files:
                    missing_files.append(
                        MissingFile(file_path=full_path, file_type="file", item_id=files_id, pipeline_id=pipeline_id)
                    )
            docs_path = files_config.get("docs_path")
            if docs_path and docs_path.strip():
                full_path = (pipeline_base_dir / docs_path).resolve()
                if not full_path.exists():
                    missing_files.append(
                        MissingFile(file_path=full_path, file_type="file_docs", item_id=files_id, pipeline_id=pipeline_id)
                    )

        # Check the README (project.readme; ./README.md unless set)
        readme = pipeline_manifest.get("project", {}).get("readme") or "README.md"
        readme_path = (pipeline_base_dir / readme).resolve()
        if not readme_path.exists():
            missing_files.append(
                MissingFile(
                    file_path=readme_path,
                    file_type="readme",
                    item_id=readme,
                    pipeline_id=pipeline_id,
                )
            )

    # Check user-specified logo and favicon (site-level, outside pipeline loop)
    logo_path = manifest.get("project", {}).get("logo", "")
    if logo_path:
        full_logo = (base_dir / logo_path).resolve()
        if not full_logo.exists():
            missing_files.append(
                MissingFile(
                    file_path=full_logo,
                    file_type="logo",
                    item_id="project.logo",
                    pipeline_id="(project)",
                )
            )

    favicon_path = manifest.get("project", {}).get("favicon", "")
    if favicon_path:
        full_favicon = (base_dir / favicon_path).resolve()
        if not full_favicon.exists():
            missing_files.append(
                MissingFile(
                    file_path=full_favicon,
                    file_type="favicon",
                    item_id="project.favicon",
                    pipeline_id="(project)",
                )
            )

    return missing_files


def built_nothing(manifest: dict, missing_files: list) -> bool:
    """Whether the missing files are every output of one pipeline, and nothing else.

    That is a pipeline that has not been built yet: a project just made by
    ``chartbook init``, or a fresh clone, whose build makes its data,
    charts, notebooks and models. A pipeline that has some of them and
    lacks others has been built, and what it lacks is a mistake to report,
    as is a missing write-up, note or README, which nothing builds.

    :param manifest: The manifest dictionary from chartbook.toml.
    :type manifest: dict
    :param missing_files: What :func:`validate_source_files` found missing.
    :type missing_files: list[MissingFile]
    :rtype: bool
    """
    from chartbook.manifest import get_pipeline_manifest

    pipelines = {missing.pipeline_id for missing in missing_files}
    if len(pipelines) != 1 or any(m.file_type not in OUTPUT_FILE_TYPES for m in missing_files):
        return False
    pipeline_manifest = get_pipeline_manifest(manifest, pipelines.pop())
    # Every path a build makes, as validate_source_files counts them
    declared = 0
    for section, keys in (
        ("dataframes", ("path",)),
        ("charts", ("path",)),
        ("notebooks", ("path",)),
        ("models", ("path", "metrics_path")),
        ("files", ("path",)),
    ):
        for entry in (pipeline_manifest.get(section) or {}).values():
            declared += sum(1 for key in keys if (entry.get(key) or "").strip())
    return len(missing_files) == declared
