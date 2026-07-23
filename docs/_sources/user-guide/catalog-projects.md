# Catalog Projects

A catalog project aggregates multiple pipelines into a unified documentation site.

## Overview

Catalog projects allow you to:
- Combine multiple analytics pipelines
- Create a centralized chart catalog
- Maintain consistent documentation
- Share analytics across teams

## Configuration

A catalog is a `chartbook.toml` with a `[pipelines]` table — its presence is what identifies the project as a catalog (no explicit `type` needed). Entry keys are scoped pipeline IDs (`scope/name`), which must be quoted in TOML because they contain `/`:

```toml
[project]
name = "Company Analytics Catalog"
maintainer = "Data Science Team"

[pipelines."acme/sales"]
path = "../pipelines/sales"

[pipelines."acme/marketing"]
path = "../pipelines/marketing"

[pipelines."acme/finance"]
path = "../pipelines/finance"
disabled = true                    # temporarily excluded from builds
```

Each entry supports two keys:

| Key | Type | Description |
|-----|------|-------------|
| `path` | string or platform table | Location of the pipeline directory |
| `disabled` | bool (default `false`) | Temporarily exclude the pipeline from catalog builds without removing it |

## Adding Pipelines

You rarely write catalog entries by hand. `chartbook catalog add <dir>` reads the target pipeline's git `origin` remote and derives the scoped key automatically (falling back to the bare directory name when there is no remote):

```console
$ chartbook catalog add ../crsp_treasury
  Added 'ftsfr/crsp_treasury': CRSP Treasury (../crsp_treasury)
```

See {doc}`../cli-reference` for the full command reference and {doc}`concepts` for how scoped identities work.

## Auto-Discovery with `members`

For a local catalog, you can skip explicit entries entirely: declare membership as path patterns, and any pipeline dropped into a matched directory joins the catalog automatically —

```toml
[pipelines]
members = [
    "../GitRepositories/ftsfr_repos/*",
    "../GitRepositories/finm33200/news_headlines",
]
disabled = ["ftsfr/sovereign_bonds"]
```

How it behaves:

- Patterns resolve relative to the catalog directory; a plain path is just a glob that matches one thing. Each matched directory holding a pipeline `chartbook.toml` joins under its **derived** scoped ID.
- Glob matches are forgiving: non-pipeline directories and other catalogs are skipped silently, and the catalog never discovers itself. A *literal* member path that is missing or broken is a hard error — you named it explicitly.
- v1-format members and two members deriving the same ID are hard errors, with "To fix" suggestions (migrate the file, exclude a path, or give one repo an explicit `[project] id`).
- `disabled` lists pipeline IDs to switch off — member-discovered pipelines have no entry to flag, so `chartbook catalog disable <id>` maintains this list for them. Unknown IDs warn with a did-you-mean suggestion.
- `exclude = [...]` removes paths from matching before anything else.
- Explicit entries coexist with `members`; an explicit entry pointing at a directory a pattern matched **wins**, which is how you rename a pipeline within your catalog.
- `members`, `exclude`, and `disabled` are reserved keys in `[pipelines]` and cannot be used as bare pipeline IDs.

`chartbook catalog add` on a path already covered by a pattern reports the coverage instead of adding a redundant entry.

Auto-discovery is designed for the **local** catalog, where "everything in this directory is mine" is exactly right. Publishing to a shared or public catalog should remain an explicit act with explicit entries.

## Platform-Specific Paths

When a pipeline lives at different locations on different operating systems, give `path` as a table with `unix` and `windows` keys:

```toml
[pipelines."acme/monthly"]
path = { unix = "/data/pipelines/monthly", windows = "T:/pipelines/monthly" }
```

## Catalog Policy

The `chartbook.toml` format itself is permissive — every field is optional. **Requiredness is catalog policy**: the catalog that aggregates your work decides which fields its member pipelines must fill in, the same way a linter config decides which rules apply to a codebase. Declare policy with a `[policy]` section:

```toml
[policy]
mode = "warn"          # "warn" (default): report in the diagnostics page
                       # "strict": fail the catalog build

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
```

- `[policy.required]` lists required fields per object type: `project`, `dataframes`, `charts`, `notebooks`.
- With `mode = "warn"` (the default), missing fields are reported on the catalog's diagnostics page but the build succeeds.
- With `mode = "strict"`, missing fields fail the catalog build.
- With no `[policy]` section at all, a built-in recommended-field list serves as the default warn-only policy, so the diagnostics page works out of the box.

Policy is enforced only when the **catalog** builds. A pipeline built standalone is always permissive.

## Best Practices

- Organize pipelines by business domain
- Use consistent naming conventions
- Document pipeline relationships
- Use `disabled = true` instead of deleting entries you may want back

For examples, see {doc}`../examples/chartbook-example`.
