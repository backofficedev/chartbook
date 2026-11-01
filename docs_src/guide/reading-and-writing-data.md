# Reading and Writing Data

Your code names a dataset, and ChartBook knows where it is. This page is the whole of that: how
you write your own outputs, how you read any pipeline's data, and the one case that has files and
no path.

Every example runs in a pipeline made by `chartbook init`, once its `chartbook.toml` declares the
dataframe with a `path`:

```toml
[dataframes.repo_public]
path = "./_data/repo_public.parquet"
date_col = "date"
docs = "Overnight repo rates and volumes."
```

## Write your own outputs

```python
# src/pull_repo.py, run from anywhere
from chartbook import data

df = fetch_from_fred()                        # your code
df.write_parquet(data.path("repo_public"))    # <pipeline>/_data/repo_public.parquet
```

`data.path` finds `chartbook.toml` by walking up from the file that called it, so a script three
folders deep in `src/` gets the same answer wherever it is run from; a notebook, which has no file,
is resolved from its working directory, usually its own folder. It reads the entry's `path`, joins
it to the pipeline's folder, and returns the absolute path. The
file need not exist yet. The folder it goes in is made if it is not there, so the first run of a
new pipeline does not fail for want of `_data/`.

The declaration must exist. Asking for a name that `[dataframes]` does not declare stops at once
and names the `chartbook.toml` it searched and the table to add:

```text
No dataframe named 'merged_rates' is declared in /work/rates/chartbook.toml.

To register it, add a table to that file, for example:

    [dataframes.merged_rates]
    path = "./_data/merged_rates.parquet"
```

ChartBook never invents a path. A dataset with no declaration would have no description, no page
and no snapshot.

**A dataset of many files is declared as a folder.** Polars writes it with `partition_by`, and
`data.path` hands over the folder:

```toml
[dataframes.articles]
path = "./_data/articles"
docs = "One parquet file a year, Hive style: year=2024/part-0.parquet."
```

```python
df.write_parquet(data.path("articles"), partition_by="year")
```

A glob, `./_data/articles/**/*.parquet`, reads the same, for a layout that needs one. It is not a
place to write.

Charts, models and files assets are written the same way, with their kind in front:
`assets.path("chart/repo_rates")`, `models.path("rate_forecaster")`. Write the format the
declaration names, since that is how it is read back: a `.parquet` ending is parquet, `.csv` is
CSV, and `format` in the entry says otherwise.

## Read any pipeline's data

One call reads a dataset of any shape, from your own pipeline or another's:

```python
from chartbook import data

mine  = data.load("repo_public")                        # my own, from my folder: a polars LazyFrame
rates = data.load("fed_yield_curve:treasury_rates")     # another pipeline's, as pinned
news  = data.load("news_headlines:articles")            # a Hive folder, its year= keys as a column
frame = data.load("repo_public", format="pandas")       # or "polars_eager"
```

Your own dataset is read from your folder, because it is built there and may not be snapshotted
yet. Another pipeline's is read from the **store**, at the snapshot your lockfile pins, so it does
not change under you until you run `chartbook update` ({doc}`depending-on-pipelines`). Nothing is
copied: the files are read where the store keeps them.

SQL reads the same datasets, named in braces. ChartBook puts each name in and DuckDB runs the rest:

```python
joined = data.sql("""
    select a.date, a.sofr, b.dgs10
    from {repo_public} a
    join {fed_yield_curve:treasury_rates} b using (date)
""")
```

`data.ref("repo_public")` gives the text that stands for a dataset in SQL you run yourself, and
`data.connect(source)` the raw connection to one of the pipeline's `[sources]`
({doc}`reading-a-warehouse`).

## Another pipeline's folder has files and no path

The store keeps each file once, usually in the first snapshot that had it. A dataset that grew by a year
between two snapshots has its files in two snapshot folders. There is no one folder to hand out,
so `data.path` of another pipeline's folder or glob dataset raises, whatever the folders happen to
hold today, and says what to call instead:

```text
'news_headlines:articles' is a dataset of 14 files, kept in 3 places in the store, so there is no
one folder. Read it with data.load('news_headlines:articles'), or hand
data.files('news_headlines:articles') to your own reader.
```

`data.files` lists every file, sorted by its path inside the dataset, wherever each is kept.
Polars and DuckDB take the list, Hive keys included, and so does a build tool:

```python
# dodo.py
from chartbook import data

def task_merge():
    return {
        "file_dep": data.files("news_headlines:articles"),   # every file, wherever kept
        "targets": [data.path("merged")],                    # my own output
        "actions": ["python src/merge.py"],
    }
```

A model that is a folder has files too. A loader that takes a directory gets a temporary one:

```python
from chartbook import assets

with assets.gathered("forecasting:model/rate_forecaster") as folder:
    model = AutoModel.from_pretrained(folder)      # the folder goes when the block ends
```

A dataframe of one file, which most are, has a path as before: `data.path("fed_yield_curve:treasury_rates")`
is the parquet file in the store. Read it; never write to it.

## Throwaway files

For intermediates that are not assets, a partial download or a file between two steps,
`data.scratch()` is a folder inside the pipeline that git ignores and nothing documents:

```python
raw = data.scratch() / "raw_download.csv"      # <pipeline>/_data/_scratch/raw_download.csv
```

`scratch = "./_tmp"` under `[project]` puts it elsewhere in the pipeline. Delete it whenever you
like.

## From the command line

`chartbook path` is `data.path` for Make, a shell, R or Stata, and `--files` is `data.files`:

```console
$ chartbook path repo_public
/work/rates/_data/repo_public.parquet
$ chartbook path news_headlines:articles --files
/Users/x/Google Drive/chartbook-store/pipelines/news_headlines/2026-05-01T120000Z_a1b2c3d4e5f6/_data/articles/year=2023/part-0.parquet
/Users/x/Google Drive/chartbook-store/pipelines/news_headlines/2026-06-01T120000Z_e5f6a7b8c9d0/_data/articles/year=2024/part-0.parquet
```

```makefile
MERGED := $(shell chartbook path merged_rates)
```

## Where next

- {doc}`depending-on-pipelines`: declaring the other pipeline, pinning its snapshot, updating
- {doc}`documenting-a-pipeline`: what goes in each `[dataframes]` entry
- {doc}`../reference/api`: every call and option of `chartbook.data` and `chartbook.assets`
