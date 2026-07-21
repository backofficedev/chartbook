# Examples

The repository ships a complete, buildable demonstration in [`examples/`](https://github.com/backofficedev/chartbook/tree/main/examples): two pipelines aggregated by a catalog.

| Project | What it demonstrates |
|---------|----------------------|
| [`fred_charts`](https://github.com/backofficedev/chartbook/tree/main/examples/fred_charts) | A full pipeline: one dataframe pulled from FRED, six charts (including a dual-axis and a scatter), and two notebooks. Mixes `docs_path` write-up files with inline `docs` strings. |
| [`yield_curve`](https://github.com/backofficedev/chartbook/tree/main/examples/yield_curve) | A larger pipeline: three dataframes, six charts, four notebooks, and a multi-line `build` script. |
| [`catalog`](https://github.com/backofficedev/chartbook/tree/main/examples/catalog) | A catalog registering both pipelines under scoped IDs. |

The data and chart artifacts are committed, so you can build the combined site immediately:

```console
git clone https://github.com/backofficedev/chartbook
cd chartbook/examples/catalog
chartbook build -f
chartbook browse
```

[`examples/dodo.py`](https://github.com/backofficedev/chartbook/blob/main/examples/dodo.py) shows the full deployment pattern: run each pipeline's `doit` build to regenerate its artifacts, build the catalog site, then copy it to a `docs/` directory for GitHub Pages.

The scaffold produced by `chartbook init` is itself a smaller worked example — see the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook).
