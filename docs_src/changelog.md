# Changelog

All notable changes to chartbook will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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