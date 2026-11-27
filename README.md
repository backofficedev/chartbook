# ChartBook

**Composable data pipelines for humans and agents.**

Give your coding agents a living catalog of every dataset, chart, and model. Snapshot pipelines like packages, compose them safely, and verify every number they touch.

[![PyPI - Version](https://img.shields.io/pypi/v/chartbook?logo=pypi)](https://pypi.org/project/chartbook)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/chartbook?logo=python)](https://pypi.org/project/chartbook)
[![GitHub Stars](https://img.shields.io/github/stars/backofficedev/chartbook?style=flat&logo=github)](https://github.com/backofficedev/chartbook)
[![Documentation](https://img.shields.io/badge/docs-backofficedev.github.io%2Fchartbook-blue)](https://backofficedev.github.io/chartbook/)

```bash
pip install chartbook
```

One install includes everything: the CLI, data loading, plotting, and the catalog site builder.

## Why ChartBook

- **A skills catalog for your agents.** Run `chartbook install agents` once and your coding agents (Claude Code, Cursor, Codex) can search every dataset, read column schemas and docs, and load data cleanly—no hallucinated paths or reinvented ETL.
- **Snapshot pipelines like packages.** Split large analyses into small, independent repos. `chartbook snapshot` freezes a committed build; downstream projects pin it in `chartbook.lock` and update only when you run `chartbook pin --update`.
- **Verify everything agents build.** Every dataset, chart, and model records its exact commit, upstream pins, and content hashes. Inspect results in the browsable catalog or audit the entire chain with `chartbook lineage`.
- **Works with any stack.** Keep your existing Python scripts, R, Stata, SQL, DuckDB, or Makefiles. ChartBook runs whatever build command you declare.

## Four commands cover 95% of your day

| Command | What it does |
|---|---|
| `chartbook run` | Pins any new dependencies, runs your build script, and verifies every declared output |
| `chartbook snapshot` | Freezes a committed build into your store so other pipelines, teammates, and agents can use it |
| `chartbook pin --update` | Moves your lockfile forward to the newest upstream snapshots when *you* choose |
| `chartbook catalog open` | Opens one searchable website covering every pipeline, dataset, chart, and version in your stores |

Two one-time helpers: `chartbook install agents` teaches your coding agent ChartBook, and `chartbook init` scaffolds a batteries-included project template if you want one.

## Minimal by design: a pipeline in three files

A pipeline is just a git folder with a `chartbook.toml` manifest, your code, and a `README.md`. The [5-Minute Quickstart](https://backofficedev.github.io/chartbook/getting-started.html) walks through this example.

`chartbook.toml`:

```toml
[project]
name = "My Pipeline"
description = "A demo pipeline: two random walks and a chart of them"

[scripts]
build = "python src/build_chart.py"

[dataframes.walks]
name = "Random Walks"
description = "Two simulated random walk series"
sources = ["Simulated"]
path = "./_data/walks.parquet"
date_col = "date"
docs = "365 daily observations of two cumulative-sum series."

[charts.random_walks]
name = "Two Random Walks"
description = "Cumulative sums of daily standard-normal draws"
dataframe = "walks"
path = "./_output/random_walks.html"
docs = "Both series are pure noise. Any pattern you see is your brain's doing."
```

`src/build_chart.py`:

```python
import numpy as np
import pandas as pd

import chartbook
from chartbook import data

rng = np.random.default_rng(seed=42)
df = pd.DataFrame({
    "date": pd.date_range("2024-01-01", periods=365, freq="D"),
    "walk_a": rng.standard_normal(365).cumsum() + 100,
    "walk_b": rng.standard_normal(365).cumsum() + 100,
})
df.to_parquet(data.path("walks"))  # chartbook.toml says where "walks" goes

chartbook.plotting.line(
    df, x="date", y=["walk_a", "walk_b"], title="Two Random Walks",
).save(chart_id="random_walks", output_dir="_output")
```

Run it, commit, snapshot, and browse:

```bash
chartbook run
git add -A && git commit -m "First pipeline"
chartbook snapshot
chartbook catalog open
```

Any other pipeline—or any coding agent—can now load that dataset by name, pinned to those exact bytes:

```python
from chartbook import data

walks = data.load("my_pipeline:walks")
```

## One catalog for your team and your agents

| Question | Your team, in the browser | Your agents, in the terminal |
|---|---|---|
| **What exists?** | Catalog home page & search | `chartbook ls --json` or `llms.txt` |
| **What is it?** | Dataset or chart page | `chartbook get-docs yield_curve:repo_public` |
| **How do I use it?** | Copy-paste snippet on the page | `data.load("yield_curve:repo_public")` or `chartbook path` |
| **Can I trust it?** | Provenance table & Versions page | `chartbook lineage --json` & `chartbook.lock` |

## Documentation

Full documentation is at [backofficedev.github.io/chartbook](https://backofficedev.github.io/chartbook).

- [Quickstart](https://backofficedev.github.io/chartbook/getting-started.html) — build, snapshot, and browse your first pipeline in 5 minutes
- [Working with AI Agents](https://backofficedev.github.io/chartbook/guide/agents.html) — turn your catalog into a skills layer for coding agents
- [Linking Pipelines Together](https://backofficedev.github.io/chartbook/guide/depending-on-pipelines.html) — snapshots, pins, and `chartbook.lock`
- [Explore a Catalog](https://backofficedev.github.io/chartbook/tutorials/explore-a-catalog.html) — hands-on tutorial connecting three public-data pipelines
- [CLI Reference](https://backofficedev.github.io/chartbook/reference/cli.html) and [Configuration Reference](https://backofficedev.github.io/chartbook/reference/configuration.html)

## Contributing

Contributions are welcome. See [CONTRIBUTING](https://backofficedev.github.io/chartbook/contributing.html) for guidelines.

To work on ChartBook itself you only need [uv](https://docs.astral.sh/uv/):

```bash
uv sync          # install editable package and dev toolchain from uv.lock
uv run doit      # run notebooks, docs, examples, package build, and test matrix
```

`uv run doit build_package` skips the test matrix, and `uv run doit test` runs the suite on one Python.

## License

Modified BSD License
