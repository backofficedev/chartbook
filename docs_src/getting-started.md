# Getting Started

## Install

ChartBook needs Python 3.10 or newer.

```console
pip install "chartbook[all]"
```

`[all]` includes everything: the site-building CLI, the plotting module, data loading, and the `chartbook init` scaffolder. For an isolated CLI install, `pipx install "chartbook[all]"` works the same way.

````{dropdown} Smaller installs
:icon: package

| Install | What you get |
|---------|--------------|
| `chartbook[data]` | `data.load()` and the polars/pyarrow stack — for projects that only *consume* cataloged data |
| `chartbook[plotting]` | `chartbook.plotting` (matplotlib, plotly, kaleido) |
| `chartbook[sphinx]` | The `build`/`publish`/`catalog` CLI and its Sphinx stack |
| `chartbook[all]` | All of the above, plus `cruft` for `chartbook init` |
| `chartbook[dev]` | Everything, plus the test toolchain (for contributors) |

The bare package (`pip install chartbook`) contains only the TOML core — install an extra for the feature you need.
````

## Scaffold a project

```console
chartbook init
```

This prompts for a project name and author, then creates a working pipeline from the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook): `chartbook.toml`, `README.md`, a `dodo.py` task runner, and `src/` scripts that pull data and build charts. Because the project is created with [cruft](https://cruft.github.io/cruft/), you can pull template improvements later with `cruft update`.

```console
cd <your-project>
chartbook build
chartbook browse
```

You already have a documentation site.

## Or build one by hand

The scaffold is convenience, not magic. A pipeline is any directory with a `chartbook.toml` — here is the whole thing from scratch.

**1. Create the project.** The manifest can start nearly empty; `README.md` is required, and its content becomes the site's front page.

```console
mkdir my-pipeline && cd my-pipeline
git init
mkdir _data _output src
```

`chartbook.toml`:

```toml
[project]
name = "My Pipeline"
description = "A demo pipeline"
```

`README.md`:

```markdown
# My Pipeline

A demo pipeline showing two random walks.
```

**2. Produce the artifacts.** ChartBook doesn't run your analysis — any script that leaves a parquet file and a chart HTML behind will do. `src/build_chart.py`:

```python
import numpy as np
import pandas as pd

import chartbook

df = pd.DataFrame({
    "date": pd.date_range("2024-01-01", periods=365, freq="D"),
    "walk_a": np.random.randn(365).cumsum() + 100,
    "walk_b": np.random.randn(365).cumsum() + 100,
})
df.to_parquet("_data/walks.parquet")

chartbook.plotting.line(
    df,
    x="date",
    y=["walk_a", "walk_b"],
    title="Two Random Walks",
).save(chart_id="random_walks", output_dir="_output")
```

```console
python src/build_chart.py
```

This writes `_data/walks.parquet` plus five chart files in `_output/` — interactive HTML and static PNG/PDF in two sizes (see {doc}`guide/plotting`).

**3. Describe the artifacts.** Add them to `chartbook.toml`:

```toml
[charts.random_walks]
name = "Two Random Walks"
description = "Cumulative sums of daily standard-normal draws"
dataframe = "walks"
path = "./_output/random_walks.html"
docs = """
Both series are pure noise. Any pattern you see is your brain's doing.
"""

[dataframes.walks]
name = "Random Walks"
description = "Two simulated random walk series"
sources = ["Simulated"]
path = "./_data/walks.parquet"
date_col = "date"
docs = "365 daily observations of two cumulative-sum series."
```

Every chart and dataframe carries a short write-up: inline `docs` as above, or `docs_path` pointing at a markdown file once the write-up outgrows a string.

**4. Build and view.**

```console
chartbook build
chartbook browse
```

The site lands in `./docs/`: a front page from your README, a page per chart (the interactive plot, your write-up, a spec table), and a page per dataframe (a schema glimpse read from the parquet, plus a provenance table). Rebuild after changes with `chartbook build -f`.

## Where next

- {doc}`guide/documenting-a-pipeline` — the full manifest vocabulary: notebooks, metadata, custom site pages
- {doc}`guide/catalogs-and-data` — register pipelines in a catalog and `data.load()` from anywhere
- {doc}`reference/configuration` — every field, type, and default
