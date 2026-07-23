"""One-shot migration of chartbook.toml files from format v1 to v2.

Usage:
    python scripts/migrate_toml_v2.py <dir-or-file> [<dir-or-file> ...] [--check]

Each argument is a chartbook.toml or a directory containing one. With
``--check``, prints the would-be v2 output without writing.

The mapping implemented here is specified in
``docs_src/design/toml-format-v2.md`` (Migration section). This script is
intended to be deleted once the known fleet (ftsfr repos, catalog,
cookiecutter example, bundled examples) is migrated.

Note: the cookiecutter *template* chartbook.toml contains Jinja and cannot be
parsed as TOML; migrate it by hand.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import tomli
import tomli_w

# Make the in-repo package importable when running from a source checkout
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chartbook.identity import derive_pipeline_id  # noqa: E402

CHART_RENAMES = {
    "chart_name": "name",
    "short_description_chart": "description",
    "dataframe_id": "dataframe",
    "topic_tags": "tags",
    "data_frequency": "frequency",
    "lag_in_data_release": "release_lag",
    "data_release_timing": "release_timing",
    "data_release_dates": "release_timing",  # drift variant
    "data_series": "series",
    "data_series_start_date": "start_date",
    "past_publications": "publications",
    "path_to_html_chart": "path",
    "path_to_excel_chart": "excel_path",
    "chart_docs_path": "docs_path",
    "chart_docs_str": "docs",
}

DATAFRAME_RENAMES = {
    "dataframe_name": "name",
    "short_description_df": "description",
    "topic_tags": "tags",
    "data_sources": "sources",
    "data_providers": "providers",
    "links_to_data_providers": "provider_links",
    "type_of_data_access": "access_types",
    "need_to_contact_provider": "contact_required",
    "data_on_pre_approved_list": "pre_approved",
    "data_license": "license",
    "license_expiration_date": "license_expiration",
    "provider_contact_info": "provider_contact",
    "restriction_on_use": "restrictions",
    "how_is_pulled": "pull_method",
    "path_to_parquet_data": "path",
    "path_to_excel_data": "excel_path",
    "dataframe_docs_path": "docs_path",
    "dataframe_docs_str": "docs",
}

NOTEBOOK_RENAMES = {
    "notebook_name": "name",
    "notebook_description": "description",
    "notebook_path": "path",
    "is_publishable": "publishable",
}

NOTE_RENAMES = {
    "path_to_markdown_file": "path",
}

# v1 [pipeline] fields that fold into [project].build, in join order
BUILD_SOURCE_FIELDS = ("software_modules_command", "build_commands")

# v1 spellings of the OS-compatibility field, in precedence order
OS_COMPAT_SOURCE_FIELDS = (
    "os_compatibility",
    "runs_on",
    "runs_on_grid_or_windows_or_other",
)


def _is_empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _set_if(project: dict, key: str, value) -> None:
    if not _is_empty(value):
        project[key] = value


def _parse_os_compatibility(value):
    """Normalize v1 OS-compatibility values to a list of strings."""
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    # Free text with parentheticals (e.g. "Windows/Linux (WRDS required)")
    # is kept whole; plain slash-separated strings are split.
    if "(" in value:
        return [value.strip()]
    parts = [p.strip() for p in value.split("/") if p.strip()]
    return parts or None


def _rename_entities(section: dict, renames: dict) -> dict:
    out = {}
    for entity_id, entity in section.items():
        new_entity = {}
        for key, value in entity.items():
            new_key = renames.get(key, key)
            if _is_empty(value):
                continue
            new_entity[new_key] = value
        out[entity_id] = new_entity
    return out


def _build_project_table(v1: dict, base_dir: Path, project_type: str) -> dict:
    """Assemble the v2 [project] table from v1 [config]/[site]/[pipeline]."""
    site = v1.get("site", {})
    pipeline = v1.get("pipeline", {})
    project: dict = {}

    if project_type == "catalog":
        project["type"] = "catalog"

    title = site.get("title", "")
    pipeline_name = pipeline.get("pipeline_name", "")
    if title and pipeline_name and title != pipeline_name:
        print(
            f"  warning: site.title {title!r} != pipeline_name {pipeline_name!r}; "
            f"using pipeline_name and dropping the title",
            file=sys.stderr,
        )
    _set_if(project, "name", pipeline_name or title)

    _set_if(project, "description", pipeline.get("pipeline_description"))
    maintainer = pipeline.get("lead_pipeline_developer") or site.get("author")
    contributors = pipeline.get("contributors", [])
    if maintainer and contributors and maintainer == contributors[0]:
        # maintainer defaults to the first contributor at load time
        maintainer = None
    _set_if(project, "maintainer", maintainer)
    _set_if(project, "contributors", contributors)
    _set_if(project, "repo_url", pipeline.get("git_repo_URL"))
    _set_if(project, "site_url", v1.get("webpage_URL"))

    readme = pipeline.get("README_file_path", "")
    if readme and readme.lstrip("./") != "README.md":
        project["readme"] = readme

    copyright_ = site.get("copyright", "")
    if copyright_ and copyright_ != str(datetime.now().year):
        project["copyright"] = copyright_

    _set_if(project, "logo", site.get("logo_path"))
    _set_if(project, "favicon", site.get("favicon_path"))

    for field in OS_COMPAT_SOURCE_FIELDS:
        if field in pipeline:
            parsed = _parse_os_compatibility(pipeline[field])
            _set_if(project, "os_compatibility", parsed)
            break

    build_parts = [
        pipeline[f].strip()
        for f in BUILD_SOURCE_FIELDS
        if isinstance(pipeline.get(f), str) and pipeline[f].strip()
    ]
    if build_parts:
        build = "\n".join(build_parts)
        project["build"] = build + "\n" if "\n" in build else build

    site_dir = pipeline.get("site_dir", "")
    if site_dir and site_dir.strip("./") not in ("docs_src/site",):
        project["site_dir"] = site_dir

    if site.get("enable_data_download") is True:
        project["enable_data_download"] = True

    # v1 pipeline.id is dropped: identity is now derived (scope from the git
    # remote, name from the directory), and catalog keys are re-derived below.
    return project


def _migrate_pipeline(v1: dict, base_dir: Path) -> dict:
    v2: dict = {}
    project = _build_project_table(v1, base_dir, "pipeline")
    if project:
        v2["project"] = project

    if v1.get("notebooks"):
        v2["notebooks"] = _rename_entities(v1["notebooks"], NOTEBOOK_RENAMES)
    if v1.get("dataframes"):
        v2["dataframes"] = _rename_entities(v1["dataframes"], DATAFRAME_RENAMES)
    if v1.get("charts"):
        v2["charts"] = _rename_entities(v1["charts"], CHART_RENAMES)
    if v1.get("notes"):
        v2["notes"] = _rename_entities(v1["notes"], NOTE_RENAMES)
    return v2


def _migrate_catalog(v1: dict, base_dir: Path) -> dict:
    v2: dict = {}
    v2["project"] = _build_project_table(v1, base_dir, "catalog")

    pipelines_out = {}
    for old_key, entry in v1.get("pipelines", {}).items():
        path_value = entry.get("path_to_pipeline", entry.get("path"))
        new_entry: dict = {}
        target_dir = None
        if isinstance(path_value, dict):
            # Platform table: lowercase the keys
            new_entry["path"] = {
                platform.lower(): p for platform, p in path_value.items()
            }
            unix_path = path_value.get("Unix") or path_value.get("unix")
            if unix_path:
                target_dir = (base_dir / unix_path).resolve()
        elif path_value is not None:
            new_entry["path"] = path_value
            target_dir = (base_dir / path_value).resolve()

        if entry.get("disabled"):
            new_entry["disabled"] = True

        # Re-derive the key as a scoped ID from the target checkout; fall
        # back to the old key when the target is missing
        new_key = old_key
        if target_dir is not None and target_dir.is_dir():
            try:
                new_key = derive_pipeline_id({}, target_dir)
            except ValueError:
                new_key = old_key
        if new_key != old_key:
            print(f"  key: {old_key} -> {new_key}")
        pipelines_out[new_key] = new_entry

    v2["pipelines"] = pipelines_out
    return v2


def migrate_file(toml_path: Path, check: bool = False) -> bool:
    """Migrate one chartbook.toml in place. Returns True if changed."""
    with open(toml_path, "rb") as f:
        v1 = tomli.load(f)

    if "config" not in v1 and "site" not in v1 and "pipeline" not in v1:
        print(f"  already v2, skipping: {toml_path}")
        return False

    config_type = v1.get("config", {}).get("type", "pipeline")
    base_dir = toml_path.parent

    if config_type == "catalog":
        v2 = _migrate_catalog(v1, base_dir)
    else:
        v2 = _migrate_pipeline(v1, base_dir)

    output = tomli_w.dumps(v2, multiline_strings=True)
    if check:
        print(f"--- {toml_path} (dry run) ---")
        print(output)
        return True

    toml_path.write_text(output, encoding="utf-8")
    print(f"  migrated: {toml_path}")
    return True


def main(argv: list[str]) -> int:
    check = "--check" in argv
    targets = [a for a in argv if not a.startswith("-")]
    if not targets:
        print(__doc__)
        return 1

    for target in targets:
        path = Path(target).expanduser()
        toml_path = path / "chartbook.toml" if path.is_dir() else path
        if not toml_path.is_file():
            print(f"  not found, skipping: {toml_path}", file=sys.stderr)
            continue
        migrate_file(toml_path, check=check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
