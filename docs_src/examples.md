# Examples

The repository ships a complete, buildable demonstration in [`examples/`](https://github.com/backofficedev/chartbook/tree/main/examples): two pipelines aggregated by a catalog.

| Project | What it demonstrates |
|---------|----------------------|
| [`fred_charts`](https://github.com/backofficedev/chartbook/tree/main/examples/fred_charts) | A full pipeline: one dataframe pulled from FRED, six charts (including a dual-axis and a scatter), and two notebooks. Mixes `docs_path` write-up files with inline `docs` strings. |
| [`yield_curve`](https://github.com/backofficedev/chartbook/tree/main/examples/yield_curve) | A larger pipeline: three dataframes, five charts, four notebooks, and a `build` command that loads HPC environment modules. |
| [`catalog`](https://github.com/backofficedev/chartbook/tree/main/examples/catalog) | A catalog registering both pipelines under scoped IDs. |

The `_data`, `_output`, and built `docs/` artifacts are generated rather than committed (they're gitignored), so each pipeline is built before the catalog aggregates it. [`examples/dodo.py`](https://github.com/backofficedev/chartbook/blob/main/examples/dodo.py) orchestrates the whole sequence — build each pipeline to produce its parquet files and charts, build the catalog site, then copy it to a root `docs/` directory for GitHub Pages:

```console
git clone https://github.com/backofficedev/chartbook
cd chartbook/examples
doit
```

Individual pipelines have their own inputs (`fred_charts` pulls from FRED; `yield_curve`'s `build` loads HPC modules), so the `chartbook.toml` files are also worth reading on their own as complete, real-world manifests.

The scaffold produced by `chartbook init` is itself a smaller worked example — see the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook).
