# Stability

**ChartBook is experimental.** It is in early development and anything can change from one release to the next: the `chartbook.toml` format, the commands, the Python functions, and the files it writes.

Breaking changes are listed in the {doc}`changelog <../changelog>`, marked **breaking**, with what to do about each.

If you depend on ChartBook for something that must keep working, pin the version you tested with:

```text
chartbook==0.2.0
```

A real stability promise will come with 1.0.

## Removed so far

| What | Removed in | Use instead |
|---|---|---|
| The `[all]`, `[data]`, `[plotting]` and `[sphinx]` install extras | 0.2.0 | `pip install chartbook`, which installs everything a pipeline on one machine needs (`chartbook[s3]` and `chartbook[mkdocs]`, added later, are a kind of store and a second site tool, not parts of the package held back) |
| The v1 `chartbook.toml` format (`[config]` / `[site]` / `[pipeline]`) | 0.1.0 | Format v2; `python scripts/migrate_toml_v2.py <project>` rewrites a v1 file |
