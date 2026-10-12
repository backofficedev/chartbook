# Design: models

```{note}
A design document. It says how a trained model becomes an asset a pipeline can declare,
document, version and hand to other code. Read {doc}`references` first, since a model is
addressed in that grammar. New to the project? Start with {doc}`overview`.

Status: **direction accepted 2026-10-12; the first slice, declared models, is built.** A
pipeline can declare a model, ask for its path, check it, and get a page and an index record for
it. Versions, labels, parts and other pipelines' models are not built. {ref}`models-built` says
exactly what is there. Each section below says whether it is *decided* or *proposed*. Proposed
parts are the author's best design and still need the maintainer's review, including the ones
that are now implemented.
```

## The problem

A pipeline that trains a model leaves a file behind: a pickle, a `.pt`, a directory of weights.
Six months later, nobody can answer the questions that matter:

- Where is the model file?
- What data was it trained on, and which version of that data?
- What code trained it?
- How good is it?
- Which version is the one in use?

ChartBook already answers the first three for dataframes. The maintainer's direction is that
**machine-learning operations should be a central use case**, and models are the asset that makes
it one.

## What a model is, to ChartBook

*Decided.* A model is **a file or a directory that a pipeline produces**, declared in
`chartbook.toml` like any other asset. ChartBook records where it is, what it was trained on,
its scores, and (later) its versions. It shows all of that on a page.

ChartBook does not know what is inside the file. It never imports PyTorch, scikit-learn or any
other framework, and never loads, runs or serves a model.

### A registry, not an experiment tracker

*Decided.* Training a model means trying many things: hundreds of runs, most thrown away. Tools
like MLflow and Weights & Biases record every attempt. ChartBook does not. It records the
models a pipeline **declares**: the ones worth keeping.

| ChartBook does | ChartBook does not |
|---|---|
| Record each declared model: its file, the data it was trained on, the code commit, its scores | Log every training run |
| Keep versions of a declared model, and labels like `champion` | Compare hyperparameter sweeps |
| Give any program the path to a model, at any version | Load a model, or run predictions |
| Show a page per model: description, scores, lineage | Serve a model behind an API |
| Say which models are out of date when their data changes | Decide when to retrain |

These follow from the {ref}`not-doing list <not-doing>`: no required service, no orchestration,
no run history. A team that wants an experiment tracker uses one, and declares in ChartBook the
model it finally chose.

## In the manifest

*Decided: the table and its four core fields. Proposed: the rest.*

```toml
[models.rate_forecaster]
name = "Rate Forecaster"
description = "Forecasts the 10-year Treasury yield one month ahead."
path = "./_models/rate_forecaster.joblib"
trained_on = ["treasury_rates"]
metrics_path = "./_output/rate_forecaster_metrics.json"
docs_path = "./docs_src/models/rate_forecaster.md"
tags = ["Forecast", "Treasury"]
```

| Field | Required | Meaning |
|---|---|---|
| `path` | yes | The model file, or a directory holding the model's files. Relative to the pipeline root. *Decided* |
| `trained_on` | no | A list of {doc}`references <references>` to the data it was trained on. The default kind is dataframe, so `"treasury_rates"` is a local dataframe and `"ftsfr/fed_yield_curve:treasury_rates"` is another pipeline's. *Decided* |
| `metrics_path` | no | A JSON file of scores, written by the training code. See below. *Decided* |
| `docs_path` or `docs` | no | The model's write-up (a "model card"): what it is for, how it was built, where it should not be used. Same convention as every other table. *Decided* |
| `name`, `description`, `tags` | no | As for dataframes and charts. *Proposed* |
| `[models.x.aliases]` | no | Labels that point at a version, such as `champion = "v3"`. See "Versions". *Proposed* |

`trained_on` becomes the model's `inputs` in the index, the same field every other asset uses
for "what was this made from". The manifest keeps the friendlier word.

### The metrics file

*Proposed, and implemented.* One flat JSON object, names to numbers. A value may also be a
string or `true`/`false`:

```json
{ "rmse": 0.214, "mae": 0.171, "n_train": 5120, "n_test": 1280 }
```

Scores live in a file, not in `chartbook.toml`, because they are an *output*. They change every
time the model is retrained, and the manifest is source that a person edits. ChartBook reads the
file when it builds, copies the numbers into the index, and shows them on the model's page.
Anything that is not such a flat object is reported by `chartbook check`, and a build leaves the
scores off the page and out of the index (with a warning) instead of failing.

## Addressing a model

*Decided.* A model is addressed like every other asset, with `model/` in front:

```text
model/rate_forecaster                          the model, in this pipeline
model/rate_forecaster#weights/best.pt          one file inside it, if it is a directory
model/rate_forecaster@v3                       version 3
model/rate_forecaster@champion                 the version labelled champion
ftsfr/fed_yield_curve:model/rate_forecaster    the model, in another pipeline
```

```python
from chartbook import assets, models

assets.path("model/rate_forecaster")       # works for every kind
models.path("rate_forecaster")             # models only: the typed front door
```

```console
$ chartbook path model/rate_forecaster
/work/fed_yield_curve/_models/rate_forecaster.joblib
```

`chartbook.models` is to models what `chartbook.data` is to dataframes: the same call with the
kind fixed, which refuses anything else.

There is deliberately **no `models.load()`**. Loading is one line in the user's own code, and
keeping it there keeps every ML framework out of ChartBook:

```python
import joblib
from chartbook import models

model = joblib.load(models.path("rate_forecaster"))
```

Code in any other language gets the path from `chartbook path`, as for dataframes.

## The model's page

*Proposed, and implemented.* One page per model in the generated site, beside the dataframe and
chart pages, at `cb/models/<pipeline>/<model>.html`:

- the freshness line ("Model updated 2 days ago"), as dataframe pages have;
- the write-up from `docs_path` or `docs`, if there is one;
- **Scores**: the metrics file as a table;
- **Trained On**: links to each dataframe's page;
- **Files**: for a directory, each file and its size;
- **Model Manifest**: name, address, description, tags, the declared path, and the command that
  prints its path. The page shows the path as declared, never the absolute path on the machine
  that built the site;
- once versions exist: a table of versions with their scores, and which labels point where.

A pipeline's front page lists its models. A catalog gets a "Models" page and a card on its front
page, but only when some pipeline declares a model, so a catalog without models is unchanged.

## In the index

*Proposed, and implemented.* A `Model` record, shaped like the other asset records in
{doc}`index-schema` (it has no `built_by` yet, since build records do not exist):

```json
{
  "kind": "Model", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:model/rate_forecaster",
  "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
           "kind": "model", "name": "rate_forecaster" },
  "pipeline": "ftsfr/fed_yield_curve",
  "name": "Rate Forecaster",
  "description": "Forecasts the 10-year Treasury yield one month ahead.",
  "location": { "kind": "file", "path": "./_models/rate_forecaster.joblib",
                "resolved_path": "/work/fed_yield_curve/_models/rate_forecaster.joblib" },
  "content_hash": "sha256:…",
  "size_bytes": 18234,
  "inputs": ["ftsfr/fed_yield_curve:treasury_rates"],
  "metrics": { "rmse": 0.214, "mae": 0.171 },
  "tags": ["Forecast", "Treasury"],
  "docs": { "path": "./docs_src/models/rate_forecaster.md", "rendered": "…" },
  "built_by": "sha256:…"
}
```

A model that is a directory also carries `files`, a list of `{ "path", "size_bytes",
"content_hash" }`, and its own `content_hash` covers all of them (the rule for hashing a
directory is in {doc}`index-schema`).

## Versions

```{admonition} Proposed
:class: warning

*Decided:* a model has versions; an exact version (`@v3`) and a label that moves (`@champion`)
are both needed; each version records the data, the code and the scores. *Proposed:* everything
else in this section. It depends on the store and on build records, which do not exist yet, so
it is settled when they are built.
```

**What a version is.** One content hash of the model, together with the build record that
produced it. The build record ({doc}`asset-graph`) already holds what was asked for: the hash of
every input (which data), the pipeline's git commit (which code), the tool versions, and when.
For a model it also keeps a copy of the metrics.

**When a version is made.** When a build finishes and a declared model's content hash is one
that has not been seen before. Rebuilding and getting the same bytes makes no new version.

**Where the bytes go.** Into the store, by content hash, like every other pinned object. The
file at `path` stays where it is; the store links to it or copies it ({doc}`asset-graph`, "Links,
not copies"). A team that wants to share model versions points at a shared store. That is the
same mechanism as a shared build cache, and it needs no server.

**How versions are named.** `v1`, `v2`, `v3`, in the order they first appear, recorded in the
pipeline's committed `chartbook.lock` so the numbers are the same on every machine and are never
reused.

**Labels.** A label is a name that points at a version, written in the manifest:

```toml
[models.rate_forecaster.aliases]
champion = "v3"
challenger = "v5"
```

Promoting a model is then a one-line change, reviewed in a pull request like any other. There is
no "promote" button and no service behind one.

**How a reference resolves.**

| Reference | Resolves to |
|---|---|
| `model/rate_forecaster` | The file at `path`: what you are working on. Local references are live |
| `model/rate_forecaster@v3` | Version 3, in the store |
| `model/rate_forecaster@champion` | The label is looked up, then as above |
| `other:model/rate_forecaster` | The version this project's lockfile pins. Cross-pipeline references are pinned |
| `other:model/rate_forecaster@champion` | The label is looked up when pinning and frozen in the lockfile, so a build is repeatable. `chartbook update` moves it |

**Garbage collection.** A recorded version is reachable, so `chartbook store gc` never collects
it.

### What this gives an ML team

In order, the loop this is meant to support:

1. **Train.** The pipeline's own code writes the model file and the metrics file.
2. **Record.** The build notices a new model, makes version `v4`, and records the data hashes,
   the code commit and the scores.
3. **Compare.** The model's page lists every version with its scores.
4. **Promote.** Someone changes `champion = "v3"` to `champion = "v4"` in a pull request.
5. **Use.** Serving code, in any language, asks for `model/rate_forecaster@champion` and gets a
   path. It never hardcodes a file name.
6. **Audit.** For the model in use, the page shows exactly which data and which commit made it.
7. **Retrain.** When upstream data changes, the model's inputs no longer match, so it shows as
   out of date. `chartbook update` and a rebuild make `v5`.

Everything outside that loop belongs to another tool: experiment tracking (MLflow, Weights &
Biases), serving (whatever the team runs), scheduling (cron, CI, an orchestrator), feature
stores.

## A worked example

Built, in `examples/yield_curve`. It adds one small model to the pipeline and needs no new
dependency: the model is a two-number regression fitted with NumPy and saved as JSON.

**`chartbook.toml`:**

```toml
[models.term_premium_ar1]
name = "Term Premium AR(1)"
description = "Predicts tomorrow's 10-year minus 2-year spread from today's."
path = "./_models/term_premium_ar1.json"
trained_on = ["term_premium"]
metrics_path = "./_output/term_premium_ar1_metrics.json"
docs_path = "./docs_src/models/term_premium_ar1.md"
tags = ["Yield Curve", "Forecast"]
```

**`src/train_term_premium_ar1.py`**, in outline:

```python
from chartbook import data, models

spread = pd.read_parquet(data.path("term_premium"))["spread_10y_2y"].dropna()
train, test = ...                                       # first 80%, last 20%
slope, intercept = np.polyfit(train.values[:-1], train.values[1:], 1)

model_path = models.path("term_premium_ar1")            # ask the manifest where it goes
model_path.write_text(json.dumps({"intercept": ..., "slope": ...}))
metrics_path.write_text(json.dumps({"rmse": ..., "mae": ..., "n_train": ..., "n_test": ...}))
```

**`dodo.py`** has a task whose `file_dep` is `data.path("term_premium")` and whose `targets` are
`assets.path("model/term_premium_ar1")` and the metrics file.

**`docs_src/models/term_premium_ar1.md`** is four short paragraphs: what the model is, what it is
for (an example, not a forecast to act on), how it was trained, and its limits.

**What you get:**

```console
$ cd examples/yield_curve && doit
$ chartbook path model/term_premium_ar1
/…/examples/yield_curve/_models/term_premium_ar1.json
$ chartbook check
chartbook.toml: OK (1 pipeline(s), 3 dataframes, 5 charts, 4 notebooks, 1 models)
```

On live data the fitted slope is 0.9988: a daily yield spread is so persistent that the model
learns "tomorrow equals today", which is what its write-up says it will. The built site has a
page for the model with its write-up, a "Trained On" link to the Term Premium dataframe's page,
and a table with `rmse`, `mae`, `n_train` and `n_test`. The catalog built over the example has a
Models page listing it, and `index.json` has its `Model` record.

A second example comes later, once dependencies exist: a separate `examples/rate_forecast`
pipeline whose model is `trained_on = ["yield_curve:fed_yield_curve"]`. That one is the first
real cross-pipeline example, for models and dataframes alike.

## Phasing

Each slice is useful by itself. The step numbers are the {doc}`overview`'s build order.

| Slice | Needs | What gets built |
|---|---|---|
| **M1. Declared models** (step 2) — **built** | The index | The `[models]` table in the loader, with validation. `model` added to `RESOLVABLE_KINDS`, so `chartbook path model/x` works. `chartbook.models.path()`. `chartbook check` covers `path`, `metrics_path` and `docs_path` (the first two are build outputs, so `--skip-outputs` skips them). The model page. The `Model` record. Policy support: `[policy.required] models = […]`. The worked example above. **No versions** |
| **M2. Parts** (with M1 or soon after) | M1 | `model/x#file` resolves to a file inside a directory model. Refuse a part that escapes the directory (`..`) |
| **M3. Cross-pipeline** (step 3) | Dependencies, lockfile, store | `other:model/x` resolves through the lockfile. `trained_on` may name another pipeline's dataframe, and must be a declared dependency. The `examples/rate_forecast` pipeline |
| **M4. Versions and labels** (step 4) | Build records | Versions on new content hashes, `@v3`, `[models.x.aliases]`, `@champion`, the versions table on the page, staleness when inputs move |

(models-built)=
## What is built

Slice M1, in these places:

| What | Where |
|---|---|
| The `[models]` table, validated when the manifest loads | `chartbook/manifest.py`, `validate_models()` |
| `model/name` resolves; `chartbook path model/x` | `chartbook/resolve.py` (`RESOLVABLE_KINDS`) |
| `chartbook.models.path()`, `chartbook.models.read_metrics()` | `chartbook/models.py` |
| The model's page, and the lists that link to it | `chartbook/markdown_generator.py` (`generate_model_docs`), `model_manifest.md` and `models.md` in the two theme directories |
| The `Model` record and its JSON Schema | `chartbook/index.py`, `chartbook/schemas/chartbook/v1/Model.json` |
| `check`: missing model, metrics or write-up; a malformed metrics file; required fields | `chartbook/check.py`, `chartbook/conf_validation.py`, `chartbook/diagnostics.py` |
| Incremental builds: a model's files are inputs, its page belongs to its pipeline | `chartbook/incremental.py` |
| The example | `examples/yield_curve` |
| The tests | `tests/test_models.py` |

Not built: versions and labels (`@v3`, `@champion`, `[models.x.aliases]`), parts
(`model/x#file`), and a model or a `trained_on` dataframe in another pipeline. Each is refused
with "reserved syntax and not yet supported".

### Decided while building it

These were open or unstated. All are *proposed*: implemented, and waiting on the maintainer's
yes.

1. **The default policy asks a model for `name`, `description`, `trained_on` and `path`.**
   Lineage is the point of declaring a model, so `chartbook check` reports a model that does not
   say what it was trained on. A catalog can set its own list with
   `[policy.required] models = […]`.
2. **A model's write-up is optional.** Dataframes and charts must have one or the manifest does
   not load. A model without one gets a page with everything else.
3. **`trained_on` may only name dataframes of the same pipeline, for now.** Another pipeline's
   dataframe, a series (`#`) or a version (`@`) is refused as not yet supported, as everywhere
   else, until dependencies exist.
4. **A metrics value may be a number, a string or true/false.** Nothing nested.
5. **A declared model or metrics file that is missing stops a build**, as a missing data file
   does. `chartbook check --skip-outputs` does not report them, since training produces them.
6. **A model's key must be a legal name** (`[A-Za-z0-9._-]+`), or the manifest does not load. The
   older tables are not held to that; a new one can be from its first day.
7. **A catalog has a Models page only when a pipeline declares a model.**
8. **The page shows the declared path, not the absolute one.** (The dataframe page shows the
   absolute path; that is older behaviour and was left alone.)

One thing is open and should be settled before models are used in earnest: **hashing a
directory counts every file, hidden ones included.** A `.DS_Store` appearing in a model's
directory changes the model's hash. That is the rule decided for the index, and the honest one
("the directory is the asset"), but for a model with versions it would make a new version out of
nothing.

## Not doing

- **No experiment tracking.** Declared models only. Not every run.
- **No loading or running models.** `models.path()` returns a path. No `models.load()`, no
  `predict()`, no framework imports.
- **No serving.** No endpoints, no containers, no deployment.
- **No training orchestration.** The pipeline's own `build` trains. ChartBook never decides when.
- **No model-format handling.** No conversion, no ONNX export, no signature inference. The file
  is opaque bytes with a hash.
- **No promotion workflow.** No stages, approvals or buttons. A label is a line in a file under
  version control; the review process is the repository's.
- **No automatic metric comparison or "best model" selection.** The page shows scores; people
  choose.

## Prior art

- **MLflow Model Registry**: registered models, numbered versions, and aliases such as
  `@champion`. The model for versions and labels. Its tracking server and run logging are the
  part deliberately not copied.
- **Hugging Face Hub**: a model is a repository of files with a model card, addressed as
  `org/name@revision`. The model for "a model is a directory with a write-up", and for `@`.
- **DVC**: large files versioned by content hash beside git, with a cache and link strategies.
  The model for where the bytes live.
- **Model Cards** (Mitchell et al., 2019): what a model's write-up should say. The suggested
  outline for `docs_path`.
- **Weights & Biases Artifacts**: versioned artifacts with aliases and lineage between them.
  Confirms that versions plus moving labels plus lineage is the useful core.

## Open questions

1. **Version numbers and branches.** Two branches that each retrain will both create `v4` in
   their lockfiles, and the merge conflicts. Options: accept the conflict and renumber on merge;
   or name versions by a short content hash and keep sequential numbers out of it, leaving
   labels as the only human names. Needs a decision before M4.
2. **Which builds make a version.** Every new content hash, or only builds on the default
   branch, or only when asked (`chartbook pin`)? Every-hash is simplest and fills the store
   fastest.
3. **Retention.** Versions are never collected. A model retrained nightly makes 365 a year.
   Probably a per-model `keep = N` that spares labelled versions, but nothing is designed.
4. **Do other kinds get versions?** A dataframe could keep named versions the same way. Nothing
   stops it; nothing has asked for it. Cross-pipeline pins already keep the versions that are
   depended on.
5. **Non-numeric metrics.** A confusion matrix or a curve is not a flat number. For now such
   things are charts or dataframes the pipeline declares separately.
6. **Models that are not files.** A model held in a registry elsewhere (an MLflow URI, a Hugging
   Face repo). The dataframe design's typed `location` ({doc}`data-access`) is the seam; nothing
   is designed.
