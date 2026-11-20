## ChartBook

This project is a ChartBook pipeline. `chartbook.toml` declares what it builds (dataframes, charts, notebooks, models) and which other pipelines it reads. `chartbook.lock` pins what it reads, and is committed. `chartbook --help` lists every command.

- **Build:** `chartbook run`. It pins what has no pin yet, runs the `build` script of `[scripts]`, fails if the build did not write something `chartbook.toml` declares, and makes a snapshot when everything is committed. To build the pipeline, run this, not the build script by itself.
- **Check, building nothing:** `chartbook run --check`.
- **Read another pipeline's data:** in Python, `from chartbook import data`, then `data.load("owner/pipeline:name")` for a table or `data.path("owner/pipeline:name")` for its file. The pipeline is declared in `[dependencies]` (`chartbook add owner/pipeline` writes the entry). Never read its files by a path into its folder.
- **Take newer data of what it reads:** `chartbook pin --update`. Never edit `chartbook.lock` by hand.
- **Add an output:** declare it in `chartbook.toml` first (a `[dataframes.NAME]` table with `path` and `docs`, or `[charts.NAME]`, `[notebooks.NAME]`, `[models.NAME]`), then have the build write that path.
- **Find what there is to read:** `chartbook ls --json` lists every pipeline and asset in the catalog, and `chartbook get-docs ID` prints one's page. Both only read.
- **When a command stops,** its message says what is wrong and what a person would type next. Show it to the person. Do not answer a question it asks, add `--force` or `-f`, or run `chartbook trust` on your own: each of those can replace files or run code the person has not looked at.

The reference written for agents is at https://backofficedev.github.io/chartbook/llms.txt (short) and https://backofficedev.github.io/chartbook/llms-full.txt (whole). Claude Code has the same as a skill: `chartbook install claude-skill`.
