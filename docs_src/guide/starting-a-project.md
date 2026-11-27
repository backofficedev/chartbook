# Start from the Full Template

The {doc}`../getting-started` shows how minimal a ChartBook pipeline can be (just `chartbook.toml` and any script).

If you're starting a larger research or analytics project from scratch and want a **batteries-included setup**—complete with a `doit` task runner, example Jupyter notebooks, custom site pages, and optional pre-wired data pullers—use `chartbook init`:

```bash
chartbook init
```

It runs completely offline using the template bundled with ChartBook.

## Answering the prompts

`chartbook init` walks through a short list of options (press **Enter** to accept any default):

- **Project name** — the title shown in your catalog (e.g., `Rates Study`).
- **Folder name** — generated automatically from the project name (`rates_study`; lowercase letters, digits, and `_`).
- **Environment tool** — choose `pip`, `uv`, `conda`, or `pixi`.
- **Optional data sources** — toggle on ready-to-run pullers and charts for **FRED**, the **Fed yield curve**, **OFR repo rates**, **Bloomberg**, **CRSP**, or **CRSP-Compustat**. Each one you enable comes with a working script, dataframe entry, and chart declared in `chartbook.toml`.

:::{tip} Want git and GitHub set up automatically?
- `chartbook init --git` initializes a git repo with your first commit.
- `chartbook init --github` also creates a private GitHub repository and pushes it (requires the [GitHub CLI](https://cli.github.com)).
:::

## Build and snapshot your new project

Once `chartbook init` finishes, install its dependencies and run the standard ChartBook loop:

```bash
cd rates_study
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

chartbook run                    # runs `doit` to execute scripts, notebooks, and docs
chartbook docs open              # preview this pipeline's own site
```

When you're ready to share outputs with other pipelines and your agents:

```bash
git add -A && git commit -m "Initial build"
chartbook snapshot
chartbook catalog open
```

:::{dropdown} Good to know: `doit`, CI checks, and template updates
- **Task runner:** The template sets `[scripts] build = "doit"` in `chartbook.toml`. Running `chartbook run` executes every task in `dodo.py` (except tests, which run with `doit run_pytest`).
- **CI validation:** Run `chartbook run --check` to verify `chartbook.toml` and declared paths without running the build.
- **Pulling template updates later:** `chartbook init` writes a `.cruft.json` file so you can pull future template improvements with [`cruft update`](https://cruft.github.io/cruft/).
- **Trust:** Folders created by `chartbook init` are automatically trusted on your machine (`chartbook trust --list`).
:::
