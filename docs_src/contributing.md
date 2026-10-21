# Contributing

Thank you for your interest in contributing to chartbook!

## Development Setup

1. **Fork and Clone**
   ```bash
   git clone <your-repo-url>
   cd chartbook
   ```

2. **Install uv**, once per machine: [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/).

3. **Sync the environment**
   ```bash
   uv sync
   ```

   That makes `.venv` from `uv.lock`: the package in editable mode and the `dev` dependency group (doit, hatch, pytest, jupytext, nbconvert, and what the integration tests need). `.python-version` names the Python; uv fetches it if the machine has none.

4. **Run everything**
   ```bash
   uv run doit
   ```

   `uv run` puts the environment's tools first on the path for that command and its subprocesses, so the nested doit of the examples, `sphinx-build` and `hatch` are the project's own. Nothing to activate. Plain `doit` runs the notebooks, the package docs, the three example pipelines and their catalog, the wheel and sdist, and then the test matrix; `uv run doit build_package` stops before the tests, and `uv run doit list` shows every task.

   The example catalog is built only from folders you have trusted: once, `uv run chartbook trust --members` in `examples/catalog`.

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
   uv run doit test        # the suite on the default Python
   uv run pytest tests/test_x.py -q   # one file
   ```

4. **Format Code**
   ```bash
   uv run hatch fmt
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
uv run doit test          # the suite on the default Python (hatch test -v; JUnit report in _build/test-results/junit.xml)
uv run doit test_all      # the matrix: Python 3.10 to 3.13, and Sphinx 7 and 8 on 3.13
uv run pytest -q          # the suite in the uv environment itself, as CI runs it
uv run hatch test --cover # with coverage
```

The matrix is hatch's: `[tool.hatch.envs.hatch-test]` in `pyproject.toml` defines the six environments, which hatch builds in its own environment folder (its data directory, or wherever `[dirs.env] virtual` in hatch's config says; `.hatch/` is git-ignored for that), resolving their dependencies itself. uv owns `.venv` and `uv.lock`, and the `dev` group carries hatch, so `uv run doit` reaches both. The matrix needs the Python versions; hatch downloads any it does not find on the path. A test keeps the `dev` group a superset of what the matrix environments get, so `uv run pytest` and `hatch test` see the same packages.

## Documentation

- Update docs for new features
- Add examples
- Keep README current

### Building Documentation

```bash
uv run doit sphinx        # the notebooks, then the site into ./docs (for GitHub Pages)
```

## Building a release

The project template goes into the wheel and the sdist by `hatch_build.py`: the files git tracks in `template/`, and the commit they are at, which `chartbook init` writes into a new project's `.cruft.json`. Build a release from a clean checkout, with git at hand:

```bash
uv build                  # or: uv run doit build_package, which builds the examples first
```

A build that cannot record the commit stops and says what to do: a folder whose `.git` git cannot read (git not installed, or a folder git does not trust), a copy with neither a `.git` nor an sdist's `PKG-INFO` (a source zip), a `template/` with changes git has not committed, or an sdist that records no commit. An editable install skips the hook, and `pip install chartbook` from PyPI runs no build, so only a build of the package itself meets this.

A release also bumps the template's `_chartbook_version` in `template/cookiecutter.json` and the skill's `chartbook-version` in `src/chartbook/skills/SKILL.md` (and its two copies) with the version in `src/chartbook/__about__.py` (tests keep them equal).

Publishing is by hand, never a doit task: after the tag, from the clean checkout at that commit,

```bash
uv build
uv publish                # PyPI; the token from UV_PUBLISH_TOKEN, or --token
```

## Questions?

- Open an issue for discussion
- Check existing issues first
- Be respectful and constructive 