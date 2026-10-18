# Getting Started

## Install

ChartBook needs Python 3.10 or newer.

```console
pip install chartbook
```

One install, everything included: the site-building CLI, the plotting module, data loading, and the `chartbook init` scaffolder. (Two extras: `chartbook[s3]` for a team whose store is an S3 bucket, and `chartbook[mkdocs]` to build the site with MkDocs instead of Sphinx.) For an isolated CLI install, `pipx install chartbook` works the same way. (Contributors: `pip install -e ".[dev]"` adds the test toolchain — see {doc}`contributing`.)

## Scaffold a project

```console
chartbook init
```

It asks 19 questions, each with its default in parentheses; Enter takes the default. Two answers matter for a first project:

- **Project name**: the site's title, say `Rates Study`.
- **Folder name**, the second question: the project's folder, made from the name (`rates_study`). Press Enter to keep it. It must start with a lowercase letter and hold only lowercase letters, digits and `_`; anything else stops the command, with nothing created, and it says what to type next time.

The other seventeen can stay as they are: a one-line description, your name and email, the Python version, how to install the dependencies (pip, uv, conda or pixi; pip is the default), and which examples to include. The defaults include an example notebook and the ChartBook site, and leave out LaTeX reports (they need TeX installed), R, Stata, a GitHub Actions workflow and the data sources (FRED, the Fed's yield curve and the OFR API download data; Bloomberg needs a Terminal and CRSP a WRDS account).

It then creates the project from the [cookiecutter template](https://github.com/backofficedev/chartbook/tree/main/template) that came with your ChartBook, so the two always match, and it needs no network to do it: `chartbook.toml`, `README.md`, a `dodo.py` task runner, scripts and a notebook in `src/`, and the project's own pages in `docs_src/site/`. Its environment files ask for your ChartBook's version or later. It ends by printing the next steps, which the rest of this section walks through. Its `.cruft.json` names the template on GitHub and the commit the template is at (when your ChartBook cannot name that commit, there is none, and `chartbook init` says how to make one), so you can pull template improvements later with [cruft](https://cruft.github.io/cruft/): `cruft update`.

```console
cd rates_study
chartbook docs
chartbook browse
```

You already have a documentation site: the README as its front page, the project's own pages, and the example notebook. Nothing is built yet, so the notebook's page says "Not built yet", and `chartbook docs` warns:

```text
Warning: rates_study has built nothing it declares yet, so the site shows each as not built:
  - notebook: _output/01_example_notebook_interactive.ipynb
`chartbook build` runs its build script and renders the site again.
With --strict, this is an error.
```

To build it, install the project's dependencies (with pip here; the project's README says how for uv, conda and pixi) and run `chartbook build`:

```console
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
chartbook build -f
chartbook browse
```

`chartbook build` runs the build script that `chartbook.toml` names, `[scripts] build = "doit"`. `doit` runs every task in `dodo.py` but the tests (`doit run_pytest` runs those): here it executes the notebook into `_output/`. Then `chartbook build` renders the site again, now with the notebook in it; `-f` replaces the site that is there.

```console
chartbook check
```

This checks `chartbook.toml` and the files it names against the default policy. Once built, a new project has one thing to fix: its `repo_url`, which a git remote fills in.

To start under version control as well, `chartbook init --git` makes the new project a git repository with its first commit, and `chartbook init --github` goes on to create a private GitHub repository for it and push (it needs the [GitHub CLI](https://cli.github.com), logged in), which gives it its `repo_url`. See {doc}`reference/cli`.

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
chartbook docs
chartbook browse
```

The site lands in `./docs/`: a front page from your README, a page per chart (the interactive plot, your write-up, a spec table), and a page per dataframe (a schema glimpse read from the parquet, plus a provenance table). Rebuild after changes with `chartbook docs -f`.

Beside the site is `docs/index.json`, the **index**: one record for the pipeline, the dataframe, each of its columns and the chart, with an ID (`my_pipeline:walks`, `my_pipeline:chart/random_walks`: the folder's name with `-` written `_`, until `[project] id` or a git remote gives the pipeline a scoped one), a content hash for each file and what each asset was made from. The pages were written from it, and anything else can read it too. {doc}`guide/vocabulary` says what the words mean; {doc}`guide/how-the-build-works` says what happened.

## Where next

- {doc}`guide/documenting-a-pipeline` — the full manifest vocabulary: notebooks, metadata, custom site pages
- {doc}`guide/catalogs-and-data` — register pipelines in a catalog and `data.load()` from anywhere
- {doc}`reference/configuration` — every field, type, and default
