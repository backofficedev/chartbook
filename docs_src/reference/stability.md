# Stability

**ChartBook is experimental.** It is in early development and anything can change from one release to the next: the `chartbook.toml` format, the commands, the Python functions, and the files it writes.

What you can count on:

- **Breaking changes are listed in the {doc}`changelog <../changelog>`**, marked **breaking**, with what to do about each.
- **An old manifest is refused, not misread.** When the `chartbook.toml` format changes, a file in the old format fails to load with a message saying how to update it. It is never silently interpreted as something else.
- **Breaking changes come in minor releases** (`0.2.0`, `0.3.0`), not patch releases (`0.2.1`).

If you depend on ChartBook for something that must keep working, pin the version you tested with:

```text
chartbook==0.2.0
```

A firmer promise, about which parts are stable and how much notice a change gets, will come with 1.0.

## Removed so far

| What | Removed in | Use instead |
|---|---|---|
| The `[all]`, `[data]`, `[plotting]` and `[sphinx]` install extras | 0.2.0 | `pip install chartbook`, which installs everything |
| The v1 `chartbook.toml` format (`[config]` / `[site]` / `[pipeline]`) | 0.1.0 | Format v2; `python scripts/migrate_toml_v2.py <project>` rewrites a v1 file |
