Rate Forecast
=============

## About this project

A small model in one pipeline, trained on data from another.

The data is the Federal Reserve's zero-coupon yield curve. The `yield_curve` example next door pulls it and declares it as the dataframe `fed_yield_curve`. This pipeline does not pull it again. It says that it depends on that pipeline, in `chartbook.toml`:

```toml
[dependencies]
"backofficedev/yield_curve" = { path = "../yield_curve" }

[models.rate_forecast]
path = "./_models/rate_forecast.json"
trained_on = ["yield_curve:fed_yield_curve"]
```

and its training script asks for the dataframe by name:

```python
from chartbook import data

curve = data.load("yield_curve:fed_yield_curve", format="pandas")
```

## Quick Start

Build `yield_curve` first, in its own folder, since this pipeline reads what it produces. Then, here:

```bash
chartbook run
```

That one command does two things, in order:

1. Pins what `yield_curve` has now, and writes `chartbook.lock`.
2. Builds this pipeline: trains the model on the pinned copy, and builds the site.

"Builds" means it runs the `build` script this pipeline names in its `chartbook.toml`:

```toml
[scripts]
build = "doit"
```

`chartbook run` does not build `yield_curve`. That folder is somebody's work, and this pipeline reads the pinned copy of its data, not the folder.

The same by hand:

```bash
chartbook pin      # freeze what yield_curve has now; writes chartbook.lock
doit               # train the model on the pinned copy, and build the site
```

`doit` runs `chartbook pin` itself, so the second command alone is enough.

## What pinning does here

`chartbook pin` copies `yield_curve`'s data into the store (`~/.chartbook/store/`) and writes the hash of each file to `chartbook.lock`. From then on, `data.load("yield_curve:fed_yield_curve")` reads that copy, not `../yield_curve/_data/`.

So if `yield_curve` is rebuilt tomorrow with a newer download, this model is **not** retrained on it, and `chartbook pin` says so:

```console
$ chartbook pin
backofficedev/yield_curve: 12 already pinned, 1 changed upstream since it was pinned
  changed upstream: backofficedev/yield_curve:fed_yield_curve
chartbook.lock is unchanged.
1 pinned asset(s) have changed upstream. `chartbook update` moves the pins.
```

`chartbook run` says the same: it never moves a pin.

To train on the newer data, move the pin and build again:

```bash
chartbook update
doit
```

`doit` retrains exactly when `chartbook.lock` changes, because the lockfile is the training task's dependency.

## A note on `chartbook.lock`

In your own project, **commit `chartbook.lock`**. It is what records which data the project was built against, and a change to it should show up in a diff.

This example git-ignores it, and that is an exception. `yield_curve` pulls live data, so the bytes differ on every build and a committed lockfile would name data nobody could get back.
