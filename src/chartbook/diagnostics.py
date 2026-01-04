"""Utilities for generating metadata diagnostics reports."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chartbook.manifest import get_pipeline_ids, get_pipeline_manifest

PIPELINE_FIELDS: list[str] = [
    "id",
    "pipeline_name",
    "pipeline_description",
    "lead_pipeline_developer",
    "contributors",
    "build_commands",
    "os_compatibility",
    "git_repo_URL",
    "README_file_path",
]

DATAFRAME_FIELDS: list[str] = [
    "dataframe_name",
    "short_description_df",
    "data_sources",
    "data_providers",
    "links_to_data_providers",
    "topic_tags",
    "how_is_pulled",
    "path_to_parquet_data",
    "date_col",
]

# Mutually exclusive doc fields for dataframes (exactly one required)
DATAFRAME_DOCS_FIELDS: tuple[str, str] = ("dataframe_docs_path", "dataframe_docs_str")

CHART_FIELDS: list[str] = [
    "chart_name",
    "short_description_chart",
    "dataframe_id",
    "topic_tags",
    "data_frequency",
    "observation_period",
    "lag_in_data_release",
    "data_release_timing",
    "units",
    "path_to_html_chart",
]

# Mutually exclusive doc fields for charts (exactly one required)
CHART_DOCS_FIELDS: tuple[str, str] = ("chart_docs_path", "chart_docs_str")

# Optional chart fields (not required for diagnostics)
OPTIONAL_CHART_FIELDS: list[str] = [
    "data_series",
]


@dataclass
class DiagnosticRow:
    object_type: str
    object_name: str
    metadata_complete: bool
    identifier: str
    pipeline_id: str
    missing_fields: str
    page_link: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "Name": self.object_name,
            "Metadata Complete": self.metadata_complete,
            "Object Type": self.object_type,
            "Identifier": self.identifier,
            "Pipeline": self.pipeline_id,
            "Missing Fields": self.missing_fields,
            "Page Link": self.page_link,
        }


def _value_is_missing(value: Any) -> bool:
    """Return True if a metadata value should be treated as missing."""

    if value is None:
        return True

    if isinstance(value, str):
        return value.strip() == ""

    if isinstance(value, (list, tuple, set)):
        if len(value) == 0:
            return True
        return all(_value_is_missing(item) for item in value)

    if isinstance(value, dict):
        return len(value) == 0

    return False


def _collect_missing_fields(
    spec: dict[str, Any], required_fields: Iterable[str]
) -> list[str]:
    missing: list[str] = []
    for field in required_fields:
        if field not in spec or _value_is_missing(spec[field]):
            missing.append(field)
    return missing


def _check_mutually_exclusive_doc_fields(
    spec: dict[str, Any], doc_fields: tuple[str, str]
) -> list[str]:
    """Check mutually exclusive doc fields (exactly one must be provided).

    :param spec: The object specification dict.
    :param doc_fields: Tuple of (path_field, str_field) names.
    :returns: List of missing field descriptors (empty if valid).
    """
    path_key, str_key = doc_fields
    has_path = path_key in spec and not _value_is_missing(spec[path_key])
    has_str = str_key in spec and not _value_is_missing(spec[str_key])

    # Exactly one must be present
    if has_path or has_str:
        return []  # Valid - one is provided
    else:
        return [f"{path_key} or {str_key}"]  # Neither provided


def _build_page_link(object_type: str, identifier: str, pipeline_id: str) -> str:
    """Build relative page link for manual concatenation with homepage URL.

    Returns paths relative to homepage (index.html) like:
    - ../charts/{pipeline_id}.{chart_id}.html
    - ../dataframes/{pipeline_id}/{dataframe_id}.html
    - ../index.html (for pipelines)
    """
    if object_type == "chart":
        return f"../charts/{pipeline_id}.{identifier}.html"
    elif object_type == "dataframe":
        return f"../dataframes/{pipeline_id}/{identifier}.html"
    elif object_type == "pipeline":
        return "../index.html"
    else:
        return ""


def build_diagnostics(manifest: dict[str, Any]) -> list[DiagnosticRow]:
    """Generate diagnostics rows for all pipelines, dataframes, and charts."""

    diagnostics: list[DiagnosticRow] = []
    pipeline_ids = get_pipeline_ids(manifest)

    for pipeline_id in pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_meta = pipeline_manifest.get("pipeline", {})

        pipeline_missing = _collect_missing_fields(pipeline_meta, PIPELINE_FIELDS)
        diagnostics.append(
            DiagnosticRow(
                object_type="pipeline",
                object_name=pipeline_meta.get("pipeline_name", pipeline_id),
                metadata_complete=len(pipeline_missing) == 0,
                identifier=pipeline_id,
                pipeline_id=pipeline_id,
                missing_fields=", ".join(pipeline_missing),
                page_link=_build_page_link("pipeline", pipeline_id, pipeline_id),
            )
        )

        dataframes = pipeline_manifest.get("dataframes", {})
        for dataframe_id, dataframe_meta in dataframes.items():
            dataframe_missing = _collect_missing_fields(
                dataframe_meta, DATAFRAME_FIELDS
            )
            # Check mutually exclusive doc fields
            dataframe_missing.extend(
                _check_mutually_exclusive_doc_fields(
                    dataframe_meta, DATAFRAME_DOCS_FIELDS
                )
            )
            diagnostics.append(
                DiagnosticRow(
                    object_type="dataframe",
                    object_name=dataframe_meta.get("dataframe_name", dataframe_id),
                    metadata_complete=len(dataframe_missing) == 0,
                    identifier=dataframe_id,
                    pipeline_id=pipeline_id,
                    missing_fields=", ".join(dataframe_missing),
                    page_link=_build_page_link("dataframe", dataframe_id, pipeline_id),
                )
            )

        charts = pipeline_manifest.get("charts", {})
        for chart_id, chart_meta in charts.items():
            chart_missing = _collect_missing_fields(chart_meta, CHART_FIELDS)
            # Check mutually exclusive doc fields
            chart_missing.extend(
                _check_mutually_exclusive_doc_fields(chart_meta, CHART_DOCS_FIELDS)
            )
            diagnostics.append(
                DiagnosticRow(
                    object_type="chart",
                    object_name=chart_meta.get("chart_name", chart_id),
                    metadata_complete=len(chart_missing) == 0,
                    identifier=chart_id,
                    pipeline_id=pipeline_id,
                    missing_fields=", ".join(chart_missing),
                    page_link=_build_page_link("chart", chart_id, pipeline_id),
                )
            )

    return diagnostics


def write_diagnostics_csv(diagnostics: list[DiagnosticRow], output_path: Path) -> None:
    """Write diagnostics rows to a CSV file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not diagnostics:
        # Write empty file with headers only
        fieldnames = [
            "Name",
            "Metadata Complete",
            "Object Type",
            "Identifier",
            "Pipeline",
            "Missing Fields",
            "Page Link",
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        return

    rows = [row.to_dict() for row in diagnostics]
    fieldnames = list(rows[0].keys())

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_metadata_diagnostics(
    manifest: dict[str, Any], docs_build_dir: Path
) -> Path:
    """Create the metadata diagnostics CSV file inside the docs build directory."""

    diagnostics = build_diagnostics(manifest)
    diagnostics_dir = docs_build_dir / "_static" / "diagnostics"
    diagnostics_path = diagnostics_dir / "chartbook_metadata_diagnostics.csv"
    write_diagnostics_csv(diagnostics, diagnostics_path)
    return diagnostics_path
