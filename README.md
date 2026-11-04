# ChartBook

**Data pipelines with provenance.** Know exactly where every number came from.

[![PyPI - Version](https://img.shields.io/pypi/v/chartbook?logo=pypi)](https://pypi.org/project/chartbook)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/chartbook?logo=python)](https://pypi.org/project/chartbook)
[![GitHub Stars](https://img.shields.io/github/stars/backofficedev/chartbook?style=flat&logo=github)](https://github.com/backofficedev/chartbook)
[![Documentation](https://img.shields.io/badge/docs-backofficedev.github.io%2Fchartbook-blue)](https://backofficedev.github.io/chartbook/)

ChartBook connects your team's data pipelines, in any language, so each one builds on another's
exact, versioned output. Every chart traces back to its sources, every input is verified by hash,
and everything lands in one catalog your team browses and your agents build on.

```bash
pip install chartbook
```

One install has everything: the command line, data loading, plotting and the site builder.

## What it does

- **Depend.** Build on another pipeline's exact output, the way you depend on a package.
  `chartbook add acme/rates` pins its newest snapshot in `chartbook.lock`, and what you read
  changes only when you run `chartbook update`.
- **Trace.** Every dataframe, chart and model records what it was made from, by content hash.
  `chartbook lineage` walks the chain back to the first source and checks every hash on the way.
- **Rebuild.** A snapshot keeps the exact bytes a pipeline made, labelled with its commit.
  `chartbook restore` puts back an output that took a day to compute.
- **Discover.** Many pipelines become one catalog: a searchable website for your team, and an
  index, an `llms.txt` and a command line your agents work from.

## A pipeline, in three files

A pipeline is a folder in git: a manifest that says what it makes, the code that makes it, and a
README. The [Quickstart](https://backofficedev.github.io/chartbook/getting-started.html) builds
this one in five minutes.

`chartbook.toml`:

```toml
[project]
name = "My Pipeline"
description = "A demo pipeline: two random walks and a chart of them"

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

`src/build_chart.py` asks the manifest where `walks` goes instead of repeating the path:

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

Then, in the folder:

```bash
python src/build_chart.py      # writes _data/walks.parquet and the chart
chartbook docs build           # writes the site, and index.json beside it
chartbook docs open
git add -A && git commit -m "First pipeline"
chartbook snapshot             # the build, by hash, into your store, labelled with the commit
```

Once it has a snapshot, any other pipeline can read that dataset by name, pinned to the exact
bytes this one made:

```python
from chartbook import data

walks = data.load("my_pipeline:walks")   # the pinned copy, never the other folder
```

## For your team and for your agents

A catalog is one site over every snapshot in your stores. A person browses it; an agent asks the
command line the same questions and gets the same answers.

| | Your team, in the browser | Your agents, from the command line |
|---|---|---|
| **What is there?** | The catalog's home page and search | `chartbook ls --json`, or the site's `llms.txt` |
| **What is it?** | The dataset's or chart's page | `chartbook get-docs yield_curve:repo_public` |
| **Use it** | Copy the snippet on the page | `data.load("yield_curve:repo_public")`, `chartbook path`, `chartbook add yield_curve` |
| **Can I trust it?** | The Provenance table and the Versions page | `chartbook lineage --json`, and `chartbook.lock` in git |

`chartbook install claude-skill` teaches Claude Code all of this.

## Documentation

Full documentation is at [backofficedev.github.io/chartbook](https://backofficedev.github.io/chartbook).

- [Quickstart](https://backofficedev.github.io/chartbook/getting-started.html): a pipeline, its site and its first snapshot in five minutes
- [Explore a Catalog](https://backofficedev.github.io/chartbook/tutorials/explore-a-catalog.html): build three public-data pipelines that build on one another, browse them, and depend on one
- [Depending on Another Pipeline](https://backofficedev.github.io/chartbook/guide/depending-on-pipelines.html): snapshots, pins and the lockfile
- [Vocabulary](https://backofficedev.github.io/chartbook/guide/vocabulary.html): a manifest asks, a lockfile records what was got, a snapshot records what was made, and an index records what a site shows
- [CLI Reference](https://backofficedev.github.io/chartbook/reference/cli.html) and [Configuration Reference](https://backofficedev.github.io/chartbook/reference/configuration.html)

## Contributing

Contributions are welcome. See [CONTRIBUTING](https://backofficedev.github.io/chartbook/contributing.html) for guidelines.

To work on ChartBook itself you need [uv](https://docs.astral.sh/uv/) and nothing else. From a clone:

```bash
uv sync          # the project, editable, and its dev toolchain, from uv.lock
uv run doit      # notebooks, docs, examples, the package, then the test matrix
```

`uv run doit build_package` is the same without the tests, and `uv run doit test` is the suite on one Python.

## License

Modified BSD License
