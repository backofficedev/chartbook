# Start a Project From the Template

The {doc}`../getting-started` builds a pipeline from three files. For a real project,
`chartbook init` scaffolds one: a manifest, a build script that runs your notebooks and scripts in
order, an example notebook, and the project's own pages. It renders the template that came with
your ChartBook, so it needs no network.

```console
chartbook init
```

It asks 19 questions, each with its default in parentheses; Enter takes the default. Two answers matter for a first project:

- **Project name**: the site's title, say `Rates Study`.
- **Folder name**, the second question: the project's folder, made from the name (`rates_study`). Press Enter to keep it. It must start with a lowercase letter and hold only lowercase letters, digits and `_`; anything else stops the command, with nothing created, and it says what to type next time.

The other seventeen can stay as they are: a one-line description, your name and email, the Python version, how to install the dependencies (pip, uv, conda or pixi; pip is the default), and which examples to include. The defaults include an example notebook and the ChartBook site, and leave out LaTeX reports (they need TeX installed), R, Stata, a GitHub Actions workflow and the data sources (FRED, the Fed's yield curve and the OFR API download data; Bloomberg needs a Terminal and CRSP a WRDS account).

**Choose a data source to start with real pages.** Each source you say yes to brings the script that pulls it, a dataframe of what it pulls, and a chart of it, all declared in `chartbook.toml`, so the first `chartbook run` builds a site with a page for each. FRED gives the Fed's policy rates; the Fed's yield curve, 2-, 10- and 30-year Treasury yields; the OFR API, repo reference rates; Bloomberg, the S&P 500; CRSP, a dollar in the value-weighted index; CRSP-Compustat, the Fama-French factors. Each chart is one short script in `src/` (`chart_fred.py`, say) that reads its dataframe by name with `data.load` and saves the chart with `chartbook.plotting`: a pattern to copy for your own. FRED, the Fed's curve and the OFR need only the network; Bloomberg needs a Terminal, and CRSP a WRDS account.

It then creates the project from the [cookiecutter template](https://github.com/backofficedev/chartbook/tree/main/template) that came with your ChartBook, so the two always match, and it needs no network to do it: `chartbook.toml`, `README.md`, a `dodo.py` task runner, scripts and a notebook in `src/`, and the project's own pages in `docs_src/site/`. Its environment files ask for your ChartBook's version or later. It ends by printing the next steps, which the rest of this section walks through. The new project is trusted as it is made (`Trusted: this folder` among the next steps; `chartbook trust --list` shows it): a build of it runs as your own, where a folder you cloned is rendered as a version from a store, and not built, until {ref}`chartbook trust <chartbook-trust>` says it is yours. Its `.cruft.json` names the template on GitHub and the commit the template is at (when your ChartBook cannot name that commit, there is none, and `chartbook init` says how to make one), so you can pull template improvements later with [cruft](https://cruft.github.io/cruft/): `cruft update`.

```console
cd rates_study
chartbook docs build
chartbook docs open
```

You already have a documentation site: the README as its front page, the project's own pages, and the example notebook. Nothing is built yet, so the notebook's page says "Not built yet", and `chartbook docs build` warns:

```text
Warning: rates_study has built nothing it declares yet, so the site shows each as not built:
  - notebook: _output/01_example_notebook_interactive.ipynb
`chartbook run` runs its build script. `chartbook docs build` renders the site.
With --strict, this is an error.
```

To build it, install the project's dependencies (with pip here; the project's README says how for uv, conda and pixi) and run `chartbook run`:

```console
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
chartbook run
chartbook docs open
```

`chartbook run` runs the build script that `chartbook.toml` names, `[scripts] build = "doit"`. `doit` runs every task in `dodo.py` but the tests (`doit run_pytest` runs those): here it executes the notebook into `_output/`. The final documentation task runs `chartbook docs build -f`, replacing the site with one that includes the executed notebook. Your build script owns that documentation step; `chartbook run` only runs the script.

```console
chartbook check
```

This checks `chartbook.toml` and the files it names against the default policy. Once built, a new project has one thing to fix: its `repo_url`, which a git remote fills in.

To start under version control as well, `chartbook init --git` makes the new project a git repository with its first commit, and `chartbook init --github` goes on to create a private GitHub repository for it and push (it needs the [GitHub CLI](https://cli.github.com), logged in), which gives it its `repo_url`. See {doc}`../reference/cli`.
