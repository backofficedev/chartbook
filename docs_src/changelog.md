# Changelog

All notable changes to chartbook will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.8] - 2026-02-17

### Added
- New `--strip-mathjax2/--no-strip-mathjax2` CLI flag for `chartbook build` (enabled by default). Automatically strips Plotly's MathJax 2 script tags from notebook cell outputs during the build, preventing them from conflicting with Sphinx's MathJax 3 and crashing LaTeX math rendering in the generated HTML.

## [0.0.7] - 2026-02-02

### Changed
- Configuration fields in `chartbook.toml` are now more forgiving with sensible defaults:
  - `logo_path` and `favicon_path` are now optional; missing values use default assets
  - `chartbook_format_version` defaults to current version instead of failing validation
  - `copyright` auto-generates current year when the key is missing (explicit empty string `""` still respected)
  - `charts`, `dataframes`, and `notebooks` sections are now optional (default to empty)
- Minimal `chartbook.toml` now only requires `[config]` section with `type = "pipeline"`

## [0.0.6] - 2026-02-01

### Added
- `data.get_docs(pipeline, dataframe)` returns the documentation content for a dataframe as a string (works with both `dataframe_docs_path` and `dataframe_docs_str` modes)
- `data.get_docs_path(pipeline, dataframe)` returns the path to the documentation source file (`.md` file for path mode, `chartbook.toml` for inline mode)
- New `chartbook ls` CLI command to list catalog objects:
  - `chartbook ls` lists all pipelines, dataframes, and charts in a tree format
  - `chartbook ls pipelines` lists pipelines only
  - `chartbook ls dataframes` lists all dataframes across pipelines
  - `chartbook ls charts` lists all charts across pipelines
  - Supports `--catalog` option to override the default catalog
- New `chartbook data` CLI command group for data operations:
  - `chartbook data get-path --pipeline <id> --dataframe <id>` prints the parquet file path
  - `chartbook data get-docs --pipeline <id> --dataframe <id>` prints the documentation content
  - `chartbook data get-docs-path --pipeline <id> --dataframe <id>` prints the documentation source path
  - All commands support `--catalog` option to override the default catalog

### Changed
- `data.get_path()` renamed to `data.get_data_path()` for clarity
- Data download links (Parquet/Excel) are now disabled by default in generated documentation. Set `enable_data_download = true` in the `[site]` section of `chartbook.toml` to enable them.

### Fixed
- Fixed "Linked Charts" not rendering correctly in dataframe documentation pages. The linked charts are now displayed as a bulleted list below the metadata table instead of inside a table cell.
- Extended full-width page layout to dataframe, pipeline, and diagnostics pages (previously only chart pages had full-width styling).
- Fixed Git Repo URL in pipeline manifest displaying a broken icon (box character) by converting it to a proper markdown link.

## [0.0.5] - 2026-01-26

### Added
- Catalog-aware data loading: `data.load(pipeline="yield_curve", dataframe="repo_public")` loads dataframes from registered pipelines in a catalog
- `data.get_path()` returns the resolved parquet path for a pipeline's dataframe
- `polars-lazyframe` format option for `data.load()` (returns `pl.scan_parquet`)
- New `chartbook config` CLI command to set the default catalog path in `~/.chartbook/settings.toml`
- New `chartbook.config` module for reading/writing global settings
- `CatalogNotConfiguredError` exception with actionable message when no catalog is configured

### Changed
- `data.load()` and `data.get_path()` now use `pipeline` and `dataframe` parameters (replaces `pipeline_id`, `dataframe_id`, `base_dir`)
- `tomli` and `tomli_w` moved from the `[data]` optional dependency group to base dependencies

## [0.0.4] - 2026-01-22

### Added
- New `--warn-missing` CLI flag for `chartbook build` to warn instead of error when source files are missing.

### Fixed
- Fixed notebook rendering in Sphinx documentation where notebooks were not appearing in the generated docs. The `notebook_list` was incorrectly using dictionary keys instead of the actual notebook paths, resulting in toctree entries missing the `.ipynb` extension.
- Build process now validates that all source files (notebooks, charts, dataframes) specified in `chartbook.toml` exist before starting the build. Missing files now produce a clear error message with the file path and the `chartbook.toml` entry that references it. Use `--warn-missing` to continue with warnings instead.

### Changed
- Standardized all docstrings across the codebase to use Sphinx-style format with `:param`, `:type`, `:returns`, and `:rtype` tags for improved API documentation rendering

## [0.0.3] - 2026-01-16

### Added
- New `chartbook.env` module (renamed from `chartbook.settings`) for project path management
  - `get_project_root()` function with configurable `start`, `markers`, `max_levels`, and `use_cache` parameters
  - `get_os_type()` function for cross-platform scripts (returns "nix", "windows", or "unknown")
  - `get()` function (renamed from `config()`) for reading environment variables and `.env` files
  - `clear_cache()` function to reset cached project root lookups
  - `ProjectRootNotFoundError` exception with helpful error messages
  - Backwards compatibility alias: `config = get`

## [0.0.2] - 2026-01-03

### Added
- New `chartbook.plotting` submodule for creating charts directly from DataFrames
  - Simple, consistent API for common chart types: `line()`, `bar()`, `scatter()`, `pie()`, and `area()`
  - `dual()` function for dual-axis charts combining different chart types on left and right y-axes
  - Built-in support for chart overlays: NBER recession shading, horizontal/vertical reference lines, shaded regions, confidence bands, and regression lines
  - `ChartResult` object with `.show()` for inline display and `.save(chart_id)` for multi-format export (HTML, PNG, SVG)
  - Global configuration via `configure()` for default output directory, backends, NBER recessions, and styling
  - `set_style()` for applying matplotlib styles, including a bundled "chartbook" style
  - Support for both Plotly (interactive) and Matplotlib backends
  - Rich annotation support: titles, captions, notes, and source attribution


### Added
- Initial release