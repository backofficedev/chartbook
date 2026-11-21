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
chartbook trust .
doit
```

`chartbook trust .` says the examples are yours to run. Two of them are built with `chartbook run`, which runs a pipeline's build script only in a folder you have trusted ({ref}`chartbook trust <chartbook-trust>`). Without it, `doit` stops at `yield_curve` and says which command trusts it.

Individual pipelines have their own inputs (`fred_charts` and `yield_curve` pull from FRED), so the `chartbook.toml` files are also worth reading on their own as complete, real-world manifests.

`rate_forecast` is built after `yield_curve`, because it reads what that pipeline produces. It never reads `yield_curve`'s folder. Between the two builds, `examples/dodo.py` runs `chartbook snapshot` in `yield_curve`, which copies what it built into the store at `~/.chartbook/store/`, labelled with the commit. `rate_forecast`'s first build step is `chartbook pin`, which pins that snapshot and writes `chartbook.lock`. Its README walks through what happens when `yield_curve` is rebuilt afterwards: nothing, until `yield_curve` makes a new snapshot and `rate_forecast` runs `chartbook pin --update`.

A snapshot needs everything in the pipeline's folder to be committed, so if you edit `examples/yield_curve`, commit before running `doit` in `examples/`.

## Two ways to a snapshot

`examples/dodo.py` shows both ways of declaring a build ready.

**Built by `chartbook run`: `yield_curve` and `rate_forecast`.** Each names its build command, `[scripts] build = "doit"`, and `examples/dodo.py` types what you would type by hand:

```console
chartbook run --project-dir yield_curve         # runs its build script, and leaves a note of the build
chartbook snapshot --project-dir yield_curve    # held against that note
chartbook run --project-dir rate_forecast       # pins yield_curve's snapshot, and builds rate_forecast
chartbook snapshot --project-dir rate_forecast
```

The second `chartbook run` does not build `yield_curve`: a folder you depend on is its owner's to build. And a snapshot typed with no option is {ref}`held against what the run built <snapshot-held-against-a-run>`: where a file was changed after the build, it stops and names the file. `doit` here types `chartbook run` again before a snapshot that would stop for that, as you would, and first names the built files that run finds changed: a run rebuilds what its build finds out of date, and takes the rest as it is.

**Built some other way, and taken as it is: `fred_charts`.** `examples/dodo.py` builds this one with the pipeline's own `doit`, as a job elsewhere or a Makefile would. No `chartbook run` built its files, so there is nothing to hold them against, and its snapshot is typed with `--as-is`:

```console
doit -f fred_charts/dodo.py
chartbook snapshot --as-is --project-dir fred_charts
```

Without the option, that snapshot stops and gives both ways on:

```text
$ cd fred_charts
$ chartbook snapshot
Error: backofficedev/fred_charts has not been built by `chartbook run` here, so there is nothing to hold its files against.
  Build it: `chartbook run` (a build with nothing left to do takes a moment). Or, to take what is on disk as it is: `chartbook snapshot --as-is`.
```

`--as-is` is for files you know are right and that ChartBook did not see built. Where `chartbook run` can build the pipeline, build it that way and type no option.

The scaffold produced by `chartbook init` is itself a smaller worked example — see the [cookiecutter template](https://github.com/backofficedev/chartbook/tree/main/template).
