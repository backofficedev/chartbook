# Working with AI Agents

Coding agents are great at writing analysis scripts, but they struggle in real data projects: they guess file paths, lose track of which CSV is current, or rebuild tables that another team member already cleaned.

ChartBook turns your team's pipelines into a **living skills and data catalog** for your agents—while snapshots give you the **audit trail** to verify everything they build.

```{raw} html
<video class="cb-terminal" autoplay loop muted playsinline aria-label="A terminal: chartbook ls --json listing every asset, chartbook get-docs printing a model's write-up, chartbook add pinning the yield curve, and chartbook lineage checking it">
<source src="../_static/tapes/agent.webm" type="video/webm">
<source src="../_static/tapes/agent.mp4" type="video/mp4">
</video>
```

## 1. Teach your agent ChartBook (one command)

Run this once inside any pipeline folder:

```bash
chartbook install agents
```

This does two things automatically:
- **Claude Code:** Installs a ChartBook skill so Claude knows when and how to search your catalog, read dataset schemas, pin dependencies, and verify lineage.
- **Cursor, Codex, and other agents:** Writes a concise ChartBook section into your project's `AGENTS.md` (wrapped in marker comments so future upgrades update cleanly without touching your own notes). Commit `AGENTS.md` so the whole team gets it.

:::{note}
Want only the Claude Code skill? Run `chartbook install claude-skill`. Every catalog site also publishes an [`llms.txt`](https://llmstxt.org/) at its root for web-based or RAG agents.
:::

## 2. How an agent uses your catalog

An agent works through your catalog progressively, keeping its context window lean—one short listing first, documentation only for the assets that matter, and data last:

| Step | What the agent runs | What it gets |
|---|---|---|
| **Discover** | `chartbook ls --json` | Compact list of every pipeline, dataset, chart, and model with descriptions |
| **Inspect** | `chartbook get-docs <id>` | Full documentation, data sources, date ranges, row counts, and column schema |
| **Load & Pin** | `chartbook add <pipeline>` + `data.load(...)` | Clean data pinned to an exact snapshot in `chartbook.lock` |
| **Verify** | `chartbook lineage --json` | Full upstream chain, checked by commit and content hash |

### Discover what exists

```console
$ chartbook ls --json
[
  {"kind": "pipeline", "id": "tutorial/treasury_curve", "name": "Treasury Curve",
   "description": "The Federal Reserve Board's zero-coupon Treasury yield curve, daily since 1961."},
  {"kind": "chart", "id": "tutorial/treasury_curve:chart/yields", "name": "Treasury Yields Since 1961",
   "description": "The 2-, 10- and 30-year zero-coupon yields", "pipeline": "tutorial/treasury_curve"},
  {"kind": "dataframe", "id": "tutorial/treasury_curve:zero_coupon_yields", ...}
]
```

Filter to a single kind anytime with `chartbook ls dataframes --json` (or `charts`, `models`, `notebooks`, `files`).

### Read schemas and docs without loading gigabytes

```console
$ chartbook get-docs treasury_curve:zero_coupon_yields
```

`chartbook get-docs` prints the exact same facts a human sees on the catalog website—sources, license, row count, date coverage, write-up, and column names/types—without touching the underlying parquet file.

- Pass a pipeline name (`treasury_curve`) to read its README.
- Pass `pipeline:dataframe` (`treasury_curve:zero_coupon_yields`) to read a dataframe's full spec.
- Pass `pipeline:kind/name` (`rate_outlook:model/spread_ar1`) for charts, models, notes, or files.

### Load clean, pinned data

Once the agent finds the dataset it needs, it adds the dependency and loads it by name:

```bash
chartbook add tutorial/treasury_curve
```

```python
from chartbook import data

yields = data.load("treasury_curve:zero_coupon_yields", format="pandas")
```

Working in R, Stata, or a shell script? `chartbook path treasury_curve:zero_coupon_yields` prints the exact path to the pinned file.

## 3. How *you* verify what your agents built

Letting agents build larger, multi-pipeline projects only works if you can trust the numbers at the end. ChartBook gives you three built-in guardrails:

1. **Agents build; humans approve snapshots.** `chartbook run` builds and checks outputs locally, but never publishes to a shared store. The installed agent instructions explicitly tell agents *not* to run `chartbook snapshot` without your go-ahead.
2. **Every dependency change is a clean `git diff`.** Because `chartbook.lock` pins exact snapshots and content hashes, reviewing an agent's pull request shows immediately which datasets it pulled in and whether any upstream numbers moved.
3. **One-command audit trail.** Run `chartbook lineage` to trace every upstream snapshot back to its source and verify every hash:

```console
$ chartbook lineage
tutorial/rate_outlook (this folder)
├── tutorial/macro_basics: tutorial/macro_basics 59a435b, made 2026-11-02 22:14:54 UTC, pins checked
└── tutorial/treasury_curve: tutorial/treasury_curve 59a435b, made 2026-11-02 22:14:45 UTC, pins checked
2 snapshot(s) upstream; no gaps.
```

```{image} ../_static/diagrams/provenance-light.svg
:alt: Upstream source data flowing through verified snapshots and pins into charts and models
:class: only-light
:align: center
```

```{image} ../_static/diagrams/provenance-dark.svg
:alt: Upstream source data flowing through verified snapshots and pins into charts and models
:class: only-dark
:align: center
```

Run `chartbook lineage --check` in CI to fail automatically if any upstream link is broken or unverified.

## Next steps

- {doc}`../tutorials/explore-a-catalog` — try these commands live on a three-pipeline catalog
- {doc}`depending-on-pipelines` — how snapshots, pins, and `chartbook.lock` connect larger projects
- {doc}`../reference/cli` — full CLI reference for `ls`, `get-docs`, `lineage`, and `install agents`
