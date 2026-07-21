# Design: `chartbook.toml` Format v2

```{admonition} Status
:class: note

**Accepted** — designed 2026-07-20. This document is both the specification for
the v2 format and the permanent record of why it looks the way it does.
Implementation status is tracked in the [Implementation plan](#implementation-plan)
section at the bottom.
```

## Summary

Format v2 collapses the three v1 metadata sections — `[config]`, `[site]`, and
`[pipeline]` — into a single `[project]` table, makes every field optional with
sensible defaults, removes `chartbook_format_version`, infers the project type
from file structure, introduces scoped pipeline identities (`scope/name`), and
moves required-field policy out of the format and into the catalog. The
`[charts]`, `[dataframes]`, `[notebooks]`, and `[notes]` sections keep their
structure but their field names are de-prefixed in the same break (see
[Entity sections](#entity-sections-field-renames)) so files are migrated once.

v1 files are **not** supported by the v2 loader. A one-shot migration script
rewrites them; see [Migration](#migration).

## Motivation

The v1 format split project metadata across three sections. A survey of every
`chartbook.toml` in the wild (19 ftsfr pipeline repos, their catalog, the
cookiecutter template, and the bundled examples) showed the split never carried
its weight:

- **`[config]` held exactly two keys** (`type`, `chartbook_format_version`) in
  every file ever written. A two-key section named "config" inside a
  configuration file is pure ceremony.
- **`[site]` and `[pipeline]` overlapped in practice.** In all 19 ftsfr repos,
  `site.title` was byte-identical to `pipeline.pipeline_name`, and
  `site.author` named the same person as `pipeline.lead_pipeline_developer`.
  `logo_path` and `favicon_path` were empty strings in 18 of 19 files.
- **The split hid field-name drift.** Because unknown keys were never
  validated, `[pipeline]` existed in four incompatible dialects
  simultaneously: the code expected `os_compatibility`/`build_commands`, all
  19 ftsfr repos wrote `runs_on`, and the docs and cookiecutter template used
  `runs_on_grid_or_windows_or_other`/`software_modules_command`. The repos'
  metadata was silently dead — never rendered — while diagnostics reported the
  same information as missing.
- **`chartbook_format_version` never worked.** The check compared *minor*
  versions, a no-op while everything is 0.0.x — files stamped `0.0.2` passed
  against package 0.0.21 — and it would have rejected every existing file the
  day the package released 0.1.0.
- **Two competing identity systems.** `pipeline.id` was used by standalone
  builds, while `catalog add` generated the catalog key from the directory
  name and ignored `pipeline.id` entirely. `data.load(pipeline=...)` used the
  catalog key.
- **A stray top-level key.** `webpage_URL` was read from the manifest root,
  outside any section.

## Design principles

1. **One table for project metadata; sections only for collections.** Sections
   earn their existence by holding many entries (`[charts.*]`,
   `[dataframes.*]`), not by categorizing a handful of scalars.
2. **Everything optional, with sensible defaults.** The format defines what
   fields *mean*; it does not decide what is *required*. Requiredness is
   policy, and policy belongs to the catalog that aggregates your work (see
   [Catalog policy](#catalog-policy)). The minimal valid pipeline
   `chartbook.toml` is an empty file — its presence alone marks a directory as
   a chartbook pipeline.
3. **Infer what can be inferred; error loudly on ambiguity.** Project type and
   pipeline identity are derivable from structure (the `[pipelines]` table,
   the git remote, the directory name). When signals conflict, chartbook
   raises an error asking the user to be explicit rather than guessing.
4. **Identity is not location.** Pipelines are identified by scoped names, not
   URLs. URLs are accepted as *input* and normalized. See
   [Rationale](#rationale-identity-and-namespacing) for why.
5. **Batch format breaks.** ChartBook is currently a personal project with no
   backward-compatibility obligations. Rather than maintain a dual-format
   loader, v2 makes all pending breaking changes at once and migrates every
   known file with a one-shot script.

## Specification

### The `[project]` table

All keys are optional. Types and defaults:

| Key | Type | Default | Replaces (v1) |
|-----|------|---------|----------------|
| `type` | string: `"pipeline"` or `"catalog"` | inferred, see [Type inference](#project-type-inference) | `config.type` |
| `id` | string: `scope/name` or bare `name` | derived, see [Identity](#pipeline-identity-and-namespacing) | `pipeline.id` |
| `name` | string | directory name | `site.title` **and** `pipeline.pipeline_name` |
| `description` | string | `""` | `pipeline.pipeline_description` |
| `maintainer` | string | `""` | `pipeline.lead_pipeline_developer` and `site.author` |
| `contributors` | array of strings | `[]` | `pipeline.contributors` |
| `repo_url` | string | git remote `origin` if available, else `""` | `pipeline.git_repo_URL` |
| `site_url` | string | `file://` path to local built docs | top-level `webpage_URL` |
| `readme` | string (path) | `"./README.md"` | `pipeline.README_file_path` |
| `copyright` | string | current year | `site.copyright` |
| `logo` | string (path) | bundled default asset | `site.logo_path` |
| `favicon` | string (path) | bundled default asset | `site.favicon_path` |
| `os_compatibility` | array of strings | `[]` | `pipeline.os_compatibility`, `runs_on`, `runs_on_grid_or_windows_or_other` |
| `build` | string (multi-line allowed) | `""` | `pipeline.build_commands`, `software_modules_command` |
| `site_dir` | string (path) | `"./docs_src/site/"` when that directory exists, else disabled | `pipeline.site_dir` |
| `enable_data_download` | bool | `false` | `site.enable_data_download` |

Notes:

- There is no separate `author` key. The Sphinx `author` renders from
  `maintainer` (falling back to the first entry of `contributors`).
- `name` doubles as the site title and the human-readable pipeline name; the
  v1 survey showed these were always the same value.
- Unknown keys in `[project]` produce a **warning** naming the key and the
  closest known key. This is what prevents the `runs_on`-style dialect drift
  from recurring.

A fully populated pipeline file:

```toml
[project]
name = "CRSP Treasury"
description = "Treasury Securities Data from CRSP"
maintainer = "Jeremy Bejarano"
contributors = ["Jeremy Bejarano"]
repo_url = "https://github.com/ftsfr/crsp_treasury"
os_compatibility = ["Windows", "Linux", "macOS"]
build = """
doit
"""

[charts.treasury_returns_replication]
name = "Treasury Bond Portfolio Returns"
description = "Treasury bond portfolio returns from CRSP data"
dataframe = "ftsfr_treas_bond_portfolio_returns"
tags = ["treasury", "bonds", "returns"]
path = "./_output/treasury_returns_replication.html"
docs = """
## Treasury Bond Portfolio Returns
Monthly Treasury bond returns from CRSP, grouped by maturity bucket.
"""

[dataframes.ftsfr_treas_bond_portfolio_returns]
name = "Treasury Bond Portfolio Returns"
description = "Treasury bond portfolio returns grouped by maturity buckets"
sources = ["CRSP Treasury Database"]
providers = ["WRDS"]
tags = ["treasury", "bonds", "returns"]
path = "./_data/ftsfr_treas_bond_portfolio_returns.parquet"
date_col = "ds"
docs_path = "./docs_src/dataframes/ftsfr_treas_bond_portfolio_returns.md"
```

A minimal one — this is a complete, valid pipeline manifest:

```toml
[project]
name = "CRSP Treasury"
```

as is an empty file.

### Project type inference

Once `[pipeline]` merges into `[project]`, the only structural signal left is
the `[pipelines]` registry table, which makes inference unambiguous:

| `type` key | `[pipelines]` present | pipeline-only sections present¹ | Result |
|------------|----------------------|--------------------------------|--------|
| absent | no | any | **pipeline** |
| absent | yes | no | **catalog** |
| absent | yes | yes | **error** — ambiguous, set `type` explicitly |
| `"pipeline"` | yes | — | **error** — contradiction |
| `"catalog"` | — | yes | **error** — contradiction |
| explicit, consistent | | | as stated |

¹ `[charts]`, `[dataframes]`, `[notebooks]`, `[notes]` (non-empty).

The type is resolved **once**, at load time in `load_manifest()`, and stamped
into the internal manifest. All consumers (`catalog add` validation,
`chartbook config`, the docs builder) read the resolved type; nothing
re-inspects the raw file.

### Pipeline identity and namespacing

**Canonical identity is a scoped name**: `scope/name`, e.g.
`ftsfr/crsp_treasury`. Each component matches `[A-Za-z0-9._-]+`; lowercase is
recommended. The scope is by convention the hosting org/user (GitHub org),
but it is just a namespace string — nothing enforces the convention. A bare
unscoped `name` is also legal for local-only projects.

**Derivation precedence** (highest first):

1. Explicit `id` in `[project]`.
2. Derived: scope from the repo's git `origin` remote (or `repo_url`), name
   from the directory name.
3. Bare fallback: the directory name, unscoped.

In practice this means all existing ftsfr repos get correct scoped IDs with
zero configuration.

**Resolution** for `data.load(pipeline=...)`, `chartbook ls`, and friends,
from most convenient to most explicit:

```python
data.load(pipeline="crsp_treasury", ...)                          # bare name
data.load(pipeline="ftsfr/crsp_treasury", ...)                    # canonical
data.load(pipeline="https://github.com/ftsfr/crsp_treasury", ...) # URL, normalized
```

- A **scoped name** matches its catalog key exactly.
- A **bare name** matches any catalog entry whose name component equals it. If
  exactly one entry matches, it resolves; if several do, chartbook errors and
  lists the candidates (`ftsfr/crsp_treasury`, `other/crsp_treasury`) so the
  caller can qualify. Bare lookup keeps today's ergonomics — you never type a
  scope you don't need.
- A **URL** is normalized to a scoped name: strip scheme and host, strip a
  trailing `.git`, take the last two path segments. URLs are never stored as
  identity.

**Version pinning syntax is reserved, not implemented**: `scope/name@rev`
(e.g. `ftsfr/crsp_treasury@a1b2c3d`). The parser recognizes and rejects it
with a "not yet supported" error, so the grammar is claimed before the
[dependencies feature](#future-work) needs it.

### Catalog registry: `[pipelines]`

Catalog keys are canonical pipeline IDs. TOML requires quoting keys containing
`/`:

```toml
[project]
name = "FTSFR Catalog"

[pipelines."ftsfr/crsp_treasury"]
path = "../crsp_treasury"

[pipelines."ftsfr/fed_yield_curve"]
path = "../fed_yield_curve"
disabled = true                    # temporarily excluded from builds

[pipelines."finm33200/news_headlines"]
path = { unix = "/Users/jbejarano/GitRepositories/finm33200/news_headlines", windows = "T:/finm33200/news_headlines" }
```

Entry keys: `path` (string, or a `{ unix = ..., windows = ... }` table for
platform-specific locations — renamed from v1 `path_to_pipeline` with
capitalized `Unix`/`Windows` keys) and `disabled` (bool, default false).

`chartbook catalog add <dir>` reads the target's git remote and writes the
scoped key automatically, falling back to the bare directory name.

### Catalog policy

The format is permissive; **requiredness is catalog policy**. A catalog may
declare which fields its member pipelines must fill in:

```toml
[policy]
mode = "warn"          # "warn" (default): report in diagnostics page
                       # "strict": fail the catalog build

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
```

- With no `[policy]` section, the hardcoded recommended-field lists that
  previously lived in `diagnostics.py` serve as the default *warn-only*
  policy, so the diagnostics page keeps working as before.
- Policy is enforced only when the **catalog** builds. A pipeline built
  standalone is always permissive.
- This separates schema (what fields mean — owned by chartbook) from policy
  (what is required — owned by whoever aggregates your work), the same split
  linters use.

### Build commands

`build` is a single string with **shell-script semantics**: a multi-line value
is one script, so state carries across lines —

```toml
[project]
build = """
module load anaconda3/2024.02
conda activate ftsfr
doit
"""
```

This is deliberately *not* an array of independent commands: `conda activate`
on line 1 must affect line 3, and an array invites the wrong mental model of
each element running in a fresh shell. Today the field is documentation-only
(rendered as a code block on the pipeline page); choosing script semantics now
means a future `chartbook run` can execute the value as-is with no format
change. If variants are ever needed (setup vs. build, per-OS commands), the
natural extension is a `[project.build]` table with named keys — deferred
until actually needed.

### Custom site pages: `site_dir`

Unchanged semantics, new default. `site_dir` is the *markdown source*
directory for custom pages merged into the generated site (the built HTML
output remains `./docs/`). It now defaults to `./docs_src/site/`,
auto-enabled when that directory exists.

The default is deliberately **not** `./docs_src/` itself: that directory also
holds `chart_docs_path`/`dataframe_docs_path` fragments
(`docs_src/charts/*.md`, `docs_src/dataframes/*.md`), and since `site_dir`
copies everything recursively and auto-discovers every `.md`, a `docs_src/`
default would publish each fragment twice — once embedded in its generated
chart/dataframe page and again as an orphan standalone page. Convention:
fragments live in `docs_src/charts/` and `docs_src/dataframes/`; site pages
live in `docs_src/site/`.

### Removed: `chartbook_format_version`

Deleted with no replacement, which is safe because "absent" is
well-defined: a file without a version key **is** a v2 file (v1 files are
detected structurally by the presence of `[config]` and rejected with a
pointer to the migration script). If the format ever breaks again, a
`format_version` key gets reintroduced *at that point*, with absence defined
to mean v2 — the standard pattern for tools that add versioning late. A
version field is cheap insurance for a tool with thousands of external users;
for a format whose every instance can be migrated in one afternoon, it is
dead weight. The v1 implementation also never actually protected anything:
it compared minor versions, a no-op at 0.0.x.

### Entity sections: field renames

`[charts.*]`, `[dataframes.*]`, `[notebooks.*]`, and `[notes.*]` keep their
structure, but field names are de-prefixed — the same section-redundancy fix
applied to `[project]`. Three conventions govern the new names:

1. **The section provides the context.** Inside `[charts.gdp]`, `chart_name`
   says "chart" twice; it is just `name`. Likewise `description`, `tags`,
   `docs` everywhere.
2. **Every entity's primary artifact is `path`.** Chart → its HTML file,
   dataframe → its parquet file (what `data.load` reads), notebook → its
   `.ipynb`, note → its markdown file. Secondary artifacts get a
   `<kind>_path` name (`excel_path`).
3. **The docs pair is `docs` / `docs_path`.** `docs` holds inline markdown,
   `docs_path` references a file; exactly one is required, same rule as v1.

Renames that apply to more than one section: `topic_tags` → `tags`,
`*_docs_str` → `docs`, `*_docs_path` → `docs_path`.

**Charts** (`[charts.*]`):

| v1 | v2 |
|----|----|
| `chart_name` | `name` |
| `short_description_chart` | `description` |
| `dataframe_id` | `dataframe` |
| `topic_tags` | `tags` |
| `data_frequency` | `frequency` |
| `lag_in_data_release` | `release_lag` |
| `data_release_timing` (drift variant `data_release_dates`) | `release_timing` |
| `data_series` | `series` |
| `data_series_start_date` | `start_date` |
| `past_publications` | `publications` |
| `path_to_html_chart` | `path` |
| `path_to_excel_chart` | `excel_path` |
| `chart_docs_path` | `docs_path` |
| `chart_docs_str` | `docs` |

Unchanged: `units`, `mnemonic`, `observation_period`, `seasonal_adjustment`,
and the governance trio `date_cleared_by_iv_and_v`,
`last_legal_clearance_date`, `last_cleared_by` (domain vocabulary with no
redundancy to remove).

**Dataframes** (`[dataframes.*]`):

| v1 | v2 |
|----|----|
| `dataframe_name` | `name` |
| `short_description_df` | `description` |
| `topic_tags` | `tags` |
| `data_sources` | `sources` |
| `data_providers` | `providers` |
| `links_to_data_providers` | `provider_links` |
| `type_of_data_access` | `access_types` |
| `need_to_contact_provider` | `contact_required` |
| `data_on_pre_approved_list` | `pre_approved` |
| `data_license` | `license` |
| `license_expiration_date` | `license_expiration` |
| `provider_contact_info` | `provider_contact` |
| `restriction_on_use` | `restrictions` |
| `how_is_pulled` | `pull_method` |
| `path_to_parquet_data` | `path` |
| `path_to_excel_data` | `excel_path` |
| `dataframe_docs_path` | `docs_path` |
| `dataframe_docs_str` | `docs` |

Unchanged: `date_col`.

**Notebooks** (`[notebooks.*]`):

| v1 | v2 |
|----|----|
| `notebook_name` | `name` |
| `notebook_description` | `description` |
| `notebook_path` | `path` |
| `is_publishable` | `publishable` |

**Notes** (`[notes.*]`):

| v1 | v2 |
|----|----|
| `path_to_markdown_file` | `path` |

Semantics are untouched — these are mechanical renames only, applied by the
same migration script pass as the section consolidation.

## Rationale: identity and namespacing

*(Preserved deliberately — this is the reasoning behind the `scope/name`
decision, recorded so future changes can be weighed against it.)*

The long-term vision is a global pipeline catalog — PyPI/npm/JSR, but for
data pipelines. That raises the question of what a pipeline's identity
*is*. The design space has been thoroughly explored by package ecosystems:

- **Deno ran the URL experiment.** It launched with raw URLs as package
  identity (`import from "https://deno.land/x/..."`) and spent years walking
  it back to JSR's `@scope/name`, because URLs make poor identities: repos
  get renamed, orgs restructure, hosting moves, and every such event breaks
  every reference.
- **Go modules chose location-as-identity** (`github.com/user/repo`) and pay
  for it with permanent coupling to the hosting path plus vanity-URL
  machinery to escape it.
- **Docker's model aged best**: a short name (`ubuntu`), an optional
  namespace (`library/ubuntu`), an optional registry prefix, and well-defined
  resolution from short to fully qualified. Users type the short thing; the
  system stores the canonical thing.

ChartBook follows the Docker/JSR shape: **scoped names are canonical, URLs
are accepted as input and normalized, bare names resolve against the local
catalog when unambiguous.** Consequences of this choice:

- **Identity survives hosting changes.** `ftsfr/crsp_treasury` stays valid if
  the repo moves hosts; only the location mapping (catalog entry or future
  registry record) updates.
- **The host is deliberately not part of the ID.** Go-style
  `github.com/ftsfr/...` would buy registry independence at the cost of
  welding identity to hosting — the exact trap. If host disambiguation is
  ever needed, an *optional* registry prefix can be added later,
  Docker-style, without breaking existing IDs.
- **The local catalog is already the right indirection layer.** It maps
  ID → path today; a future registry maps ID → repo URL. The catalog then
  acts like a lockfile of installed pipelines, and
  `chartbook catalog add ftsfr/crsp_treasury` (no path) can someday fetch.
  Scope ownership/squatting is a registry problem to solve *when* a registry
  exists; locally, the catalog is the authority, so conflicts are impossible
  until then.
- **Ambiguity is an error, not a guess.** Bare-name resolution failing loudly
  when two scopes share a name matches the format's general
  infer-or-error principle.

The cost of adopting this now is near zero — a string grammar and a
three-step lookup — which is what makes it the future-proof choice: nothing
about the format changes when the registry, version pinning, or cross-pipeline
dependencies arrive.

## Future work

Kept on the table, explicitly out of scope for v2:

- **Cross-pipeline dependencies** — a `requirements.txt` for pipelines,
  pinned by commit:

  ```toml
  [dependencies]
  "ftsfr/fed_yield_curve" = { rev = "a1b2c3d" }
  "ftsfr/crsp_treasury"   = { path = "../crsp_treasury" }   # local, unpinned
  ```

  The v2 identity work exists partly to serve this: dependency declarations,
  `data.load`, and catalog keys all share one naming scheme, and the
  catalog's `path` entries are structurally path-dependencies already, so
  registration and dependency resolution can converge on one mechanism.
- **`chartbook run`** — executing the `build` field (needed the moment
  dependencies exist, so a dependency pipeline can be built automatically).
  The script semantics of `build` were chosen so this needs no format change.
- **A global registry** mapping `scope/name` → repo URL + metadata.

## Open questions

*(none — the entity field de-prefixing question was resolved in favor of
batching the renames into this break; the approved list is in
[Entity sections](#entity-sections-field-renames).)*

## Migration

No backward compatibility. The v2 loader detects v1 files (presence of
`[config]`) and fails with a message pointing at the migration script.

A one-shot script (`scripts/migrate_toml_v2.py`, deleted after use) rewrites
v1 → v2 mechanically:

| v1 | v2 |
|----|----|
| `[config] type` | `[project] type` (then usually dropped as inferable) |
| `[config] chartbook_format_version` | removed |
| `[site] title` + `[pipeline] pipeline_name` | `[project] name` (nearly always identical; on mismatch the script warns and prefers `pipeline_name`) |
| `[site] author`, `[pipeline] lead_pipeline_developer` | `[project] maintainer` |
| `[site] copyright` | `[project] copyright` (dropped if == current year) |
| `[site] logo_path` / `favicon_path` | `[project] logo` / `favicon` (dropped if empty) |
| `[site] enable_data_download` | `[project] enable_data_download` (dropped if false) |
| `[pipeline] id` | `[project] id`, scoped via git remote (dropped if it equals the derived value) |
| `[pipeline] pipeline_description` | `[project] description` |
| `[pipeline] contributors`, `git_repo_URL`, `README_file_path`, `site_dir` | `[project] contributors`, `repo_url`, `readme`, `site_dir` (defaults dropped) |
| `[pipeline] os_compatibility`, `runs_on`, `runs_on_grid_or_windows_or_other` | `[project] os_compatibility` — slash-separated OS strings split into arrays; unrecognized free text kept as a single-element array |
| `[pipeline] build_commands`, `software_modules_command` | `[project] build` (concatenated in module-command-first order) |
| top-level `webpage_URL` | `[project] site_url` |
| `[pipelines.X] path_to_pipeline` | `[pipelines."scope/X"] path` (scope from the target's git remote); `{Unix=…, Windows=…}` → `{unix=…, windows=…}` |
| all `[charts.*]` / `[dataframes.*]` / `[notebooks.*]` / `[notes.*]` fields | renamed per the [entity rename tables](#entity-sections-field-renames), including drift variants (`data_release_dates` → `release_timing`) |

Files to migrate: the 19 ftsfr pipeline repos + their catalog, the
cookiecutter template (Jinja preserved), `examples/{fred_charts,yield_curve,catalog}`,
test fixtures, `create_global_catalog()` output, and any `~/.chartbook/chartbook.toml`.
The legacy `src/chartbook/templates/chartbook.toml` (an orphaned `[theme]`/`[site]`
stub) is deleted.

(implementation-plan)=
## Implementation plan

Ordered so each phase leaves the repo green. Internal code adopts the v2
names throughout — no compatibility shims — since every consumer lives in
this repo.

**Phase 1 — Loader core** (`manifest.py`, `conf_validation.py`, `errors.py`)
- Parse `[project]`; replace `DEFAULT_CONFIG`; type-inference table with the
  three error cases; v1 detection (`[config]` present) → friendly error.
- Identity derivation (explicit `id` → git remote + dirname → bare dirname);
  reserve and reject `@rev`.
- Unknown-key warning for `[project]`.
- Internal manifest keyed by v2 names (`manifest["project"]["name"]`, resolved
  `type`, resolved `id`); `SiteConfig.from_manifest` reads
  `name`/`maintainer`/`copyright`; `get_logo_path`/`get_favicon_path` read
  `project.logo`/`favicon`; `site_dir` default-if-exists logic.

**Phase 2 — Consumers** (`markdown_generator.py`, `build_docs.py`,
`publish.py`, `diagnostics.py`, Jinja templates in `docs_src_pipeline/` and
`docs_src_catalog/`)
- Templates: `pipeline_manifest.pipeline.pipeline_name` →
  `pipeline_manifest.project.name`, etc.; render `build` as a code block;
  drop the duplicated-URL "Pipeline Web Page" row in favor of `site_url`.
- `publish.py` reads `project.readme`; diagnostics field list switches to v2
  names.

**Phase 3 — Identity resolution & CLI** (`data.py`, `cli.py`, `config.py`)
- Three-step resolution (scoped exact → bare unique-or-error → URL
  normalize) behind one helper used by `data.load`, `data.get_path`,
  `chartbook ls`.
- `catalog add`: scoped key from target's git remote; quoted-key TOML
  emission; `path` entry shape.
- `catalog init` / `create_global_catalog()` emit v2; `chartbook config`
  catalog validation uses resolved type.

**Phase 4 — Policy** (`diagnostics.py`, `build_docs.py`)
- Parse `[policy]`; current hardcoded lists become the default warn-only
  policy; `mode = "strict"` fails the catalog build; diagnostics page reports
  against the active policy.

**Phase 5 — Migration & fleet update**
- `scripts/migrate_toml_v2.py` implementing the mapping table above
  (drift-variant normalization included, `--check` dry-run mode).
- Run over: test fixtures, `examples/`, cookiecutter template + `example/`,
  all 19 ftsfr repos + catalog, `~/.chartbook/`. Delete the orphaned
  `templates/chartbook.toml`.

**Phase 6 — Tests**
- Update fixtures and assertions across `test_manifest`, `test_config`,
  `test_conf_validation`, `test_catalog_add`, `test_build_docs`,
  `test_build_command`, `test_integration`, `test_data`, `test_config_cli`,
  `test_errors`.
- New coverage: type-inference truth table (incl. the three error rows),
  identity derivation precedence, bare/scoped/URL resolution and the
  ambiguity error, `@rev` rejection, unknown-key warning, `[policy]`
  warn vs. strict, v1-file rejection message, `site_dir` default gating,
  migration script golden files.

**Phase 7 — Docs & release** (see next section), version bump, changelog
entry describing the break.

## Documentation plan

Reference material to rewrite, and where the rationale is preserved:

- **`docs_src/configuration.md`** — full rewrite as the v2 reference: the
  `[project]` key table, type-inference rules, minimal-file example, catalog
  registry and `[policy]`, `site_dir` conventions. Cross-links to this design
  doc for the "why".
- **This document** (`docs_src/design/toml-format-v2.md`) — added to the site
  toctree so the reasoning (especially the
  [namespacing rationale](#rationale-identity-and-namespacing)) is published,
  not buried in git history.
- **`docs_src/user-guide/concepts.md`** — new "Pipeline identity" section:
  scoped names, the three lookup forms, ambiguity behavior.
- **`docs_src/user-guide/catalog-projects.md`** — scoped keys, `catalog add`
  behavior, `[policy]` with the permissive-format/catalog-owns-policy framing.
- **`docs_src/user-guide/pipelines.md`**, **`build-pipeline.md`** —
  `[project]` examples, the `build` field and its script semantics.
- **`docs_src/getting-started.md`**, **`docs_src/index.md`**, **`README.md`**
  — update `data.load(...)` examples to scoped names.
- **`docs_src/cli-reference.md`** — `catalog add`/`ls` output changes.
- **Bundled skills** (`src/chartbook/skills/manifest_files.md`, `SKILL.md`,
  `catalog_system.md`) — rewritten for v2; these are what AI assistants read,
  so they must not teach the dead format.
- **`llm/llms.txt`**, **`llm/llms-full.txt`**, **`docs_src/llms-txt.md`** —
  regenerated with v2 examples.
- **`docs_src/changelog.md`** — breaking-change entry summarizing v1 → v2 and
  linking here.
- **Cookiecutter repo** (`cookiecutter_chartbook`) — template
  `chartbook.toml` (Jinja preserved), rendered `example/`, and its README.
