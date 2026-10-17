# Contributing

Thank you for your interest in contributing to chartbook!

## Development Setup

1. **Fork and Clone**
   ```bash
   git clone <your-repo-url>
   cd chartbook
   ```

2. **Install Hatch**
   ```bash
   pip install hatch
   ```

3. **Enter Development Environment**
   ```bash
   hatch shell
   ```

4. **Install in Editable Mode with All Dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

   **Important:** The quotes around `".[dev]"` are required when installing with extras locally.

   Available installation options:
   ```bash
   pip install -e .              # The package (everything included)
   pip install -e ".[dev]"       # Package + contributor toolchain (pytest, doit, jupytext, nbconvert)
   ```

## Making Changes

1. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Your Changes**
   - Write clear, documented code
   - Follow existing patterns
   - Add tests for new features

3. **Run Tests**
   ```bash
   hatch test
   ```

4. **Format Code**
   ```bash
   hatch fmt
   ```

## Changing Something Users Rely On

ChartBook is {doc}`experimental <reference/stability>`, so things may change. When you change something a user would notice — a manifest field, a command or option, a public function — add a changelog entry marked **breaking** that says what to do instead. If a file format changes, make the loader recognize the old form and refuse it with the fix; never read it as something else.

## Submitting Changes

1. **Commit Your Changes**
   ```bash
   git add .
   git commit -m "Add feature: description"
   ```

2. **Push to Your Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Create Pull Request**
   - Go to the repository
   - Create PR from your branch
   - Describe your changes

## Code Style

- Use type hints
- Write docstrings in reStructuredText format (`:param`, `:type`, `:returns:`, `:rtype:`)
- Follow PEP 8
- Keep functions focused

### Function Naming Conventions

Use consistent verb prefixes to indicate function behavior:

| Prefix | Usage | Example |
|--------|-------|---------|
| `load_*` | Reading files/config from disk (I/O) | `load_manifest()` |
| `get_*` | Retrieving values from data structures (no I/O) | `get_pipeline_ids()` |
| `find_*` | Searching across data structures | `find_latest_source_modification()` |
| `resolve_*` | Converting paths/references to final form | `resolve_platform_path()` |
| `validate_*` | Validation (returns bool or raises exception) | `validate_config_file()` |
| `normalize_*` | Standardizing data format | `normalize_tags()` |
| `create_*` | Creating new objects/files | `create_config()` |
| `build_*` | Assembling complex structures | `build_diagnostics()` |
| `generate_*` | Generating output/transformations | `generate_docs()` |
| `_*` | Private/internal functions | `_load_pipeline_manifest()` |

### Naming Principles

1. **Use consistent terminology**: Use "manifest" for the parsed `chartbook.toml` data (matching the public `load_manifest()`), and reserve "config"/"settings" for global `settings.toml` data
2. **Use plural for list returns**: `get_pipeline_ids()` not `get_pipeline_id_list()`
3. **Mark internal functions**: Prefix with underscore for module-internal functions
4. **Distinguish I/O from memory**: Use `load_*` for disk operations, `get_*` for in-memory access
5. **Be specific and descriptive**: Names should clearly indicate what the function does

## Testing

- Write tests for new features
- Ensure all tests pass
- Add integration tests when needed

### Running Tests Locally

```bash
# Run tests on current Python version
hatch test

# Run tests with coverage
hatch test --cover

# Run tests across all supported Python versions (3.10-3.13)
hatch test --all
```

The `--all` flag requires having the Python versions installed locally (e.g., via [pyenv](https://github.com/pyenv/pyenv)).

## Documentation

- Update docs for new features
- Add examples
- Keep README current

### Building Documentation

```bash
# Build the documentation (outputs to ./docs for GitHub Pages)
hatch run docs:build
```

## Building a release

The project template goes into the wheel and the sdist by `hatch_build.py`: the files git tracks in `template/`, and the commit they are at, which `chartbook init` writes into a new project's `.cruft.json`. Build a release from a clean checkout, with git at hand, and with `CHARTBOOK_BUILD_REQUIRE_GIT=1` in the environment, which `doit hatch_build` sets:

```bash
CHARTBOOK_BUILD_REQUIRE_GIT=1 hatch build
```

Without that variable, a build that cannot record the commit warns and goes on: a folder whose `.git` git cannot read (git not installed, or a folder git does not trust) or a copy with neither a `.git` nor an sdist's `PKG-INFO` ships `template/` as it is on disk and an empty `built_from.txt`, and a `template/` with changes git has not committed, or an sdist that records no commit, ships with no commit. With it, each of these stops the build.

A release also bumps the template's `_chartbook_version` in `template/cookiecutter.json` with the version in `src/chartbook/__about__.py` (a test keeps them equal). The step that installs ChartBook from GitHub, in a new project's next steps and README, is shown for a template of version 0.2.0, so it goes away by itself with the next release.

## Questions?

- Open an issue for discussion
- Check existing issues first
- Be respectful and constructive 