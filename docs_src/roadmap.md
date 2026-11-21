# Roadmap

What ChartBook does now, what is an early experiment, and what may come next. Nothing below the first
section is a promise; it is where the work is pointed.

## Now: catalogs of snapshots across several stores

ChartBook is meant to be useful on one laptop with nothing but `pip install chartbook`:

- A pipeline documents its charts, dataframes, notebooks and models in `chartbook.toml`, and
  `chartbook docs build` makes a site of them.
- A catalog lists stores in `catalog.toml` and renders hubs over every pipeline and snapshot in them. New snapshots follow catalog routing; reads search every store.
- One pipeline reads another's data by name, from a **snapshot** in the **store**, pinned in its
  lockfile, so that what it read is recorded and can be read again
  ({doc}`guide/depending-on-pipelines`).

Several machines share by sharing the store: point each one at the same folder, on a network drive
or in a synced folder such as Google Drive, Dropbox or OneDrive (`CHARTBOOK_STORE`, or `[store] url`
in the settings; see {doc}`reference/configuration`).

The work now is to make this smooth from end to end, for one person on one machine first.

## 0.3.0

0.3.0 carries out {design}`plan-0.3.0`. At its centre is a store a person can find their way
around: one folder for each pipeline, which can be sent to someone else and added to their store,
by hand or with `chartbook store export` and `store import`. Inside it, each snapshot has a folder
holding the pipeline's files under their own names, and each file is kept once, however many
snapshots hold it, so a dataset that grows by a file a year no longer stores a full copy each time.
With it come files that are not tables, tables stored as CSV, JSON lines or Arrow IPC, more for
datasets of many files, and a clear message about long paths on Windows. A store made by 0.2 is
moved to it once with `chartbook store migrate` (the {doc}`changelog`, "Read this first").

## 0.4.0

0.4.0 carries out {design}`plan-0.4.0`. A catalog becomes a list of stores, and nothing else:
every pipeline with a snapshot in any of them, every version of each rendered from the store alone,
with the data dictionary as it was then and what changed between versions, and a page for the
stores themselves. A machine may have several stores, one Drive folder per collaborator, say, with
each pipeline's new snapshots routed to the stores that should hold it, and a dependency may name a
public store by URL so that a stranger who clones a downstream repository can fetch what its
lockfile pins. Working folders leave the catalog; a `chartbook.links.toml` beside a pipeline's
manifest is how two pipelines are worked on at once. `chartbook build` goes: `chartbook run` runs
the build script, `chartbook docs build` renders the site.

## 0.5.0: data reads

0.5.0 carries out {design}`plan-data-reads` (proposed 2026-10-31, released 2026-11-02). A version of a dataset whose files are kept
in several snapshot folders is read from where they sit: no gathered copy on each machine, so
nothing under `~/.chartbook` grows with every catalog build. The catalog renders a version from
its snapshot's index and documents alone, reading no data. `data.path` writes your own outputs
and gives one path, `data.load` and `data.sql` read anyone's data in any shape, and `data.files`
lists the files for a build tool. The store says in plain words which snapshot folders stand
alone and which share files, and `store gc` is the one way to remove them. The guide is
rewritten around what a person is trying to do.

## 0.6.0: pins a rebuild can meet, and fewer commands to know

Two things, both being built. Where no store is shared, each person builds the pipelines they
depend on themselves, and what they build now meets a pin: a lockfile holds dataframes and models
only, and a dataframe is pinned by its rows as well as its file ({design}`pins-and-rebuilds`). And
the commands are fewer to learn: `chartbook run` builds and checks what it built; `chartbook
snapshot` puts the build in your store, for other pipelines; `chartbook pin --update` takes newer
data; `chartbook catalog open` shows it all ({design}`one-command`).

A store in a bucket is withdrawn in this version. 0.6.0 lays a store out anew (complete snapshots
and increments), and a bucket has not been brought to that layout: a command that meets one stops
and says so, and says to use a store in a folder. The bucket is as it was, and 0.5 still reads and
writes it.

## Experimental: Databricks

A dataframe can be a table or a query in a Databricks SQL warehouse
({doc}`guide/reading-a-warehouse`). It is an early experiment, more so than the rest of ChartBook: it
has been tested against a stand-in for the warehouse, not yet against a real workspace, and how it
works may change. It is here to make sure ChartBook can grow adapters for other warehouses: the
engine behind a source is a plugin (`chartbook.backends`), as a kind of store is
(`chartbook.stores`).

Reading works: `data.load()`, `data.sql()`, `data.ref()`, and the site's pages for such a dataframe.
What another pipeline cannot do yet is pin a Databricks table.

## Next, to research

**A store in a bucket, brought to the layout of 0.6.** Complete snapshots and increments in a
bucket, and a move of an existing bucket to that layout, as `chartbook store migrate` moves a
folder. It waited because the priority is one person on one machine, and a store in a folder: one
on a network drive or in a synced folder is already shared between machines.

**`chartbook run` builds what is not in your store.** From 0.6.0 a run that reads a pipeline your
store does not have says which pipelines to build, in order, with the commands. The next step is
to do it: clone each one into a folder of ChartBook's own and run it there, after asking whether
you trust it and showing its repository. A pipeline's secrets would be kept in one place,
`~/.chartbook/envs/<pipeline>/`, and not scattered across clones: one file holding every variable
any version needs, checked against the `.env.example` of the version being built so that what is
missing is named, with a folder for one version only where the same name needs another value.
What is not settled: whether one file can serve every version of a pipeline, which renames its
variables over time, or the secrets have to follow the version; and each pipeline needs its own
packages, which works where its build command brings its own environment (`uv run doit`) and not
where it assumes yours
({design}`one-command`, "Later").

**`chartbook publish`:** move a pipeline's snapshots from your own store to one you share, and
keep sending them there, asked for and chosen at a prompt. Today that is `chartbook store move
PIPELINE --to NAME --keep`. A snapshot is not "published" by being made: it is in your store, and
nobody else's.

**`chartbook run --clean`:** build this commit in a clean copy, as someone who depends on it
would, to be sure a snapshot came from the commit alone. Until then a run takes its build tool's
word for what is out of date: a built file changed by hand since the last run, and not rebuilt by
the next, is noted as it is, and the snapshot holds it with nothing said. A smaller step is a line
from `chartbook run` that names such files, as the examples' own `doit` prints one before it types
the run; it would also name every file a build tool rebuilt between two runs.

**Pinning a Delta table by its version.** Delta tables keep a history of versions, so a pin could
name a version, `VERSION AS OF 42`, rather than copy the rows out of the warehouse. This is built,
and reviewed three times, in [pull request 90](https://github.com/backofficedev/chartbook/pull/90), and is held back for one question about
Databricks itself: how long an old version stays readable. Delta keeps the files of old versions for
7 days by default, and newer runtimes refuse to read a version "older than" that. If the 7 days count
from when a version was written, a pin of a table no one has changed for a week breaks at its next
commit, and Databricks' own optimization of a Unity Catalog table makes such commits. The way to
find out is a pin on a real workspace (Databricks Free Edition is enough). If version pins hold up,
they come in; if not, the choice is between copying a table's rows into the store and asking a
table's owner to keep more history.

**Snowflake.** The same kind of adapter, for a Snowflake warehouse. Snowflake keeps history for time
travel too, a day by default, so the same question about pins arises there.

**Other warehouses** (Postgres, BigQuery) as plugins, once two are built and the interface has
settled.

**A database as the store,** for an organization that keeps everything in one warehouse
({design}`stores-and-backends` leaves its layout open).

**An MCP server,** so that an assistant can browse a catalog and read what it describes.

**A build line that says which commit it is of.** The list of what is not in your store gives each
pipeline's commands on lines of their own, which every shell reads, PowerShell among them. A line
no longer stops the next where it fails. Typed one at a time, as the list says, a failure is seen.
Typed together, a build runs after a `git checkout` that failed, and is of the commit its folder is
on. What is read through a pin is safe from it, since a pin is met only by the same file or, for
a dataframe, the same rows. An option
that names the commit (`chartbook run --snapshot --commit 7802799a41c2`), refused anywhere else,
would make each line safe by itself. It waits until a list is meant to be typed whole, by a class
say, or a build of the wrong commit is met ({design}`one-command`).

**Without git.** Today git is asked a good deal: the commit a snapshot is labelled with, whether
everything is committed, a file as it was at a commit, a repository's address. The direction is to
need no version control system in particular. A first step is the note a run leaves of what it
built, for a snapshot to be held against ({design}`one-command`): it is kept in ChartBook's own
folder, in plain hashes, and asks git only which files of a folder are its source. What a snapshot
would be labelled with where there is no commit is not settled.

## Smaller things, noted so they are not lost

Found by reviews and by the first runs on Windows, and left for a later version:

- After a run at a pinned commit, the `chartbook.lock` it wrote can stop the next `git checkout` in
  the same clone, where that commit has no lockfile and the next one has.
- Two lists of what is not in your store cannot be followed to their end: a pipeline that is built
  already and another wanted at an older commit, in one repository read by `path`; and a pinned
  `path` folder that is in no git repository.
- The tests that type a list's lines type them in a POSIX shell. On Windows they were typed by
  hand, into Windows PowerShell, `cmd.exe` and Git Bash.
- On Windows the `cruft link` line that `chartbook init` prints holds JSON, which no one way of
  quoting gives to `cmd.exe` and PowerShell alike.
- On Windows the closing line of a run names a pipeline on a connected drive letter by its network
  folder (`\\server\…`), where the letter was typed.
- A pipeline that another one depends on, in a network folder with no drive letter, is refused
  when its build is reached, and not before the run starts.
- `doit` in `examples/`, typed a second time with nothing changed, types two of its three
  `chartbook snapshot` commands again, and they make nothing: each is asked again when any
  snapshot was made in the store since, and another example's was. `uv run doit` at the top of
  the repository runs nothing the second time.
- The `dodo.py` in `examples/` hands its commands their folders unquoted, so the examples do not
  build in a checkout whose path has a space.
- In a network folder that git does not trust, a clone that is beside the pipeline is not taken
  for one, and the list of what is not in your store says to clone it again under another name.
  A clone the list has made there is such a folder too: its own build says the command that
  makes git trust it, and a list made again before that is typed says to clone once more.
- `chartbook init` from a source checkout of ChartBook that is on a network share names the
  checkout's own path in its `safe.directory` command, and not the form git writes for a share.
