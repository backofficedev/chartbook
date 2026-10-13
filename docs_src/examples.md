# Examples

The repository ships a complete, buildable demonstration in [`examples/`](https://github.com/backofficedev/chartbook/tree/main/examples): three pipelines aggregated by a catalog.

| Project | What it demonstrates |
|---------|----------------------|
| [`fred_charts`](https://github.com/backofficedev/chartbook/tree/main/examples/fred_charts) | A full pipeline: one dataframe pulled from FRED, six charts (including a dual-axis and a scatter), and two notebooks. Mixes `docs_path` write-up files with inline `docs` strings. |
| [`yield_curve`](https://github.com/backofficedev/chartbook/tree/main/examples/yield_curve) | A larger pipeline: three dataframes, five charts, four notebooks and a model. `rate_forecast` depends on it. |
| [`rate_forecast`](https://github.com/backofficedev/chartbook/tree/main/examples/rate_forecast) | A pipeline that depends on another: one model, trained on `yield_curve`'s data. It declares the dependency, pins `yield_curve`'s snapshot with `chartbook pin`, and loads the pinned copy with `data.load("yield_curve:fed_yield_curve")`. |
| [`catalog`](https://github.com/backofficedev/chartbook/tree/main/examples/catalog) | A catalog registering all three pipelines under scoped IDs. |

The `_data`, `_output`, and built `docs/` artifacts are generated rather than committed (they're gitignored), so each pipeline is built before the catalog aggregates it. [`examples/dodo.py`](https://github.com/backofficedev/chartbook/blob/main/examples/dodo.py) orchestrates the whole sequence — build each pipeline to produce its parquet files and charts, build the catalog site, then copy it to a root `docs/` directory for GitHub Pages:

```console
git clone https://github.com/backofficedev/chartbook
cd chartbook/examples
doit
```

Individual pipelines have their own inputs (`fred_charts` and `yield_curve` pull from FRED), so the `chartbook.toml` files are also worth reading on their own as complete, real-world manifests.

`rate_forecast` is built after `yield_curve`, because it reads what that pipeline produces. It never reads `yield_curve`'s folder. Between the two builds, `examples/dodo.py` runs `chartbook snapshot` in `yield_curve`, which copies what it built into the store at `~/.chartbook/store/`, labelled with the commit. `rate_forecast`'s first build step is `chartbook pin`, which pins that snapshot and writes `chartbook.lock`. Its README walks through what happens when `yield_curve` is rebuilt afterwards: nothing, until `yield_curve` makes a new snapshot and `rate_forecast` runs `chartbook update`.

A snapshot needs everything in the pipeline's folder to be committed, so if you edit `examples/yield_curve`, commit before running `doit` in `examples/`.

Each example names its build command, `[scripts] build = "doit"`. The same three steps by hand: `chartbook run` in `examples/yield_curve` builds that pipeline, `chartbook snapshot` there declares the build ready, and `chartbook run` in `examples/rate_forecast` pins it and builds `rate_forecast`. That last command does not build `yield_curve`: a folder you depend on is its owner's to build.

The scaffold produced by `chartbook init` is itself a smaller worked example — see the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook).
