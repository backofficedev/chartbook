# {py:mod}`chartbook.lock`

```{py:module} chartbook.lock
```

```{autodoc2-docstring} chartbook.lock
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`FrozenProblem <chartbook.lock.FrozenProblem>`
  - ```{autodoc2-docstring} chartbook.lock.FrozenProblem
    :summary:
    ```
* - {py:obj}`FrozenReport <chartbook.lock.FrozenReport>`
  - ```{autodoc2-docstring} chartbook.lock.FrozenReport
    :summary:
    ```
* - {py:obj}`GcPlan <chartbook.lock.GcPlan>`
  - ```{autodoc2-docstring} chartbook.lock.GcPlan
    :summary:
    ```
* - {py:obj}`Lock <chartbook.lock.Lock>`
  - ```{autodoc2-docstring} chartbook.lock.Lock
    :summary:
    ```
* - {py:obj}`PinEvent <chartbook.lock.PinEvent>`
  - ```{autodoc2-docstring} chartbook.lock.PinEvent
    :summary:
    ```
* - {py:obj}`PinReport <chartbook.lock.PinReport>`
  - ```{autodoc2-docstring} chartbook.lock.PinReport
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`by_its_id <chartbook.lock.by_its_id>`
  - ```{autodoc2-docstring} chartbook.lock.by_its_id
    :summary:
    ```
* - {py:obj}`choose_for_rev <chartbook.lock.choose_for_rev>`
  - ```{autodoc2-docstring} chartbook.lock.choose_for_rev
    :summary:
    ```
* - {py:obj}`clone_instead <chartbook.lock.clone_instead>`
  - ```{autodoc2-docstring} chartbook.lock.clone_instead
    :summary:
    ```
* - {py:obj}`is_read_only <chartbook.lock.is_read_only>`
  - ```{autodoc2-docstring} chartbook.lock.is_read_only
    :summary:
    ```
* - {py:obj}`label_remedy <chartbook.lock.label_remedy>`
  - ```{autodoc2-docstring} chartbook.lock.label_remedy
    :summary:
    ```
* - {py:obj}`name_it_by_its_id <chartbook.lock.name_it_by_its_id>`
  - ```{autodoc2-docstring} chartbook.lock.name_it_by_its_id
    :summary:
    ```
* - {py:obj}`note_this_machine <chartbook.lock.note_this_machine>`
  - ```{autodoc2-docstring} chartbook.lock.note_this_machine
    :summary:
    ```
* - {py:obj}`pin <chartbook.lock.pin>`
  - ```{autodoc2-docstring} chartbook.lock.pin
    :summary:
    ```
* - {py:obj}`pinned_hash <chartbook.lock.pinned_hash>`
  - ```{autodoc2-docstring} chartbook.lock.pinned_hash
    :summary:
    ```
* - {py:obj}`plan_gc <chartbook.lock.plan_gc>`
  - ```{autodoc2-docstring} chartbook.lock.plan_gc
    :summary:
    ```
* - {py:obj}`read_lock <chartbook.lock.read_lock>`
  - ```{autodoc2-docstring} chartbook.lock.read_lock
    :summary:
    ```
* - {py:obj}`run_gc <chartbook.lock.run_gc>`
  - ```{autodoc2-docstring} chartbook.lock.run_gc
    :summary:
    ```
* - {py:obj}`schema_path <chartbook.lock.schema_path>`
  - ```{autodoc2-docstring} chartbook.lock.schema_path
    :summary:
    ```
* - {py:obj}`store_has_for <chartbook.lock.store_has_for>`
  - ```{autodoc2-docstring} chartbook.lock.store_has_for
    :summary:
    ```
* - {py:obj}`update <chartbook.lock.update>`
  - ```{autodoc2-docstring} chartbook.lock.update
    :summary:
    ```
* - {py:obj}`verify <chartbook.lock.verify>`
  - ```{autodoc2-docstring} chartbook.lock.verify
    :summary:
    ```
* - {py:obj}`write_lock <chartbook.lock.write_lock>`
  - ```{autodoc2-docstring} chartbook.lock.write_lock
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOCK_FILE <chartbook.lock.LOCK_FILE>`
  - ```{autodoc2-docstring} chartbook.lock.LOCK_FILE
    :summary:
    ```
* - {py:obj}`NOT_SYNCED_YET <chartbook.lock.NOT_SYNCED_YET>`
  - ```{autodoc2-docstring} chartbook.lock.NOT_SYNCED_YET
    :summary:
    ```
* - {py:obj}`PIN_LINKS <chartbook.lock.PIN_LINKS>`
  - ```{autodoc2-docstring} chartbook.lock.PIN_LINKS
    :summary:
    ```
* - {py:obj}`PROBLEM_STATUSES <chartbook.lock.PROBLEM_STATUSES>`
  - ```{autodoc2-docstring} chartbook.lock.PROBLEM_STATUSES
    :summary:
    ```
* - {py:obj}`RECENT_SECONDS <chartbook.lock.RECENT_SECONDS>`
  - ```{autodoc2-docstring} chartbook.lock.RECENT_SECONDS
    :summary:
    ```
* - {py:obj}`SCHEMA <chartbook.lock.SCHEMA>`
  - ```{autodoc2-docstring} chartbook.lock.SCHEMA
    :summary:
    ```
````

### API

`````{py:class} FrozenProblem
:canonical: chartbook.lock.FrozenProblem

```{autodoc2-docstring} chartbook.lock.FrozenProblem
```

````{py:attribute} asset
:canonical: chartbook.lock.FrozenProblem.asset
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.lock.FrozenProblem.asset
```

````

````{py:attribute} dependency
:canonical: chartbook.lock.FrozenProblem.dependency
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.lock.FrozenProblem.dependency
```

````

````{py:attribute} kind
:canonical: chartbook.lock.FrozenProblem.kind
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lock.FrozenProblem.kind
```

````

````{py:attribute} message
:canonical: chartbook.lock.FrozenProblem.message
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.lock.FrozenProblem.message
```

````

`````

`````{py:class} FrozenReport
:canonical: chartbook.lock.FrozenReport

```{autodoc2-docstring} chartbook.lock.FrozenReport
```

````{py:attribute} dependencies
:canonical: chartbook.lock.FrozenReport.dependencies
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.lock.FrozenReport.dependencies
```

````

````{py:attribute} lockfile
:canonical: chartbook.lock.FrozenReport.lockfile
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.lock.FrozenReport.lockfile
```

````

````{py:attribute} noted
:canonical: chartbook.lock.FrozenReport.noted
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.lock.FrozenReport.noted
```

````

````{py:attribute} pins
:canonical: chartbook.lock.FrozenReport.pins
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.lock.FrozenReport.pins
```

````

````{py:attribute} problems
:canonical: chartbook.lock.FrozenReport.problems
:type: list[chartbook.lock.FrozenProblem]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.FrozenReport.problems
```

````

````{py:attribute} unrooted
:canonical: chartbook.lock.FrozenReport.unrooted
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lock.FrozenReport.unrooted
```

````

`````

````{py:exception} GcError(removed_snapshots: int, removed: int, size_bytes: int, failures: list[tuple[str, str]])
:canonical: chartbook.lock.GcError

Bases: {py:obj}`chartbook.lock.LockError`

```{autodoc2-docstring} chartbook.lock.GcError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.lock.GcError.__init__
```

````

`````{py:class} GcPlan
:canonical: chartbook.lock.GcPlan

```{autodoc2-docstring} chartbook.lock.GcPlan
```

````{py:attribute} aggressive
:canonical: chartbook.lock.GcPlan.aggressive
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.lock.GcPlan.aggressive
```

````

````{py:attribute} delete
:canonical: chartbook.lock.GcPlan.delete
:type: list[tuple[str, int]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.delete
```

````

````{py:attribute} elsewhere
:canonical: chartbook.lock.GcPlan.elsewhere
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.elsewhere
```

````

````{py:attribute} forget
:canonical: chartbook.lock.GcPlan.forget
:type: list[pathlib.Path]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.forget
```

````

````{py:attribute} forget_missing
:canonical: chartbook.lock.GcPlan.forget_missing
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.lock.GcPlan.forget_missing
```

````

````{py:attribute} forget_old
:canonical: chartbook.lock.GcPlan.forget_old
:type: list[pathlib.Path]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.forget_old
```

````

````{py:attribute} keep_days
:canonical: chartbook.lock.GcPlan.keep_days
:type: float
:value: >
   None

```{autodoc2-docstring} chartbook.lock.GcPlan.keep_days
```

````

````{py:attribute} keep_lineage
:canonical: chartbook.lock.GcPlan.keep_lineage
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.lock.GcPlan.keep_lineage
```

````

````{py:attribute} kept
:canonical: chartbook.lock.GcPlan.kept
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.lock.GcPlan.kept
```

````

````{py:attribute} kept_versions
:canonical: chartbook.lock.GcPlan.kept_versions
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.kept_versions
```

````

````{py:attribute} lockfiles
:canonical: chartbook.lock.GcPlan.lockfiles
:type: list[tuple[pathlib.Path, bool]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.lockfiles
```

````

````{py:attribute} not_read
:canonical: chartbook.lock.GcPlan.not_read
:type: list[pathlib.Path]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.not_read
```

````

````{py:attribute} read_here
:canonical: chartbook.lock.GcPlan.read_here
:type: list[pathlib.Path]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.read_here
```

````

````{py:attribute} recent
:canonical: chartbook.lock.GcPlan.recent
:type: list[str]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.recent
```

````

````{py:attribute} recent_seconds
:canonical: chartbook.lock.GcPlan.recent_seconds
:type: float
:value: >
   None

```{autodoc2-docstring} chartbook.lock.GcPlan.recent_seconds
```

````

````{py:property} size_bytes
:canonical: chartbook.lock.GcPlan.size_bytes
:type: int

```{autodoc2-docstring} chartbook.lock.GcPlan.size_bytes
```

````

````{py:attribute} snapshots
:canonical: chartbook.lock.GcPlan.snapshots
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.lock.GcPlan.snapshots
```

````

````{py:attribute} snapshots_delete
:canonical: chartbook.lock.GcPlan.snapshots_delete
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.snapshots_delete
```

````

````{py:attribute} snapshots_kept
:canonical: chartbook.lock.GcPlan.snapshots_kept
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.GcPlan.snapshots_kept
```

````

`````

````{py:data} LOCK_FILE
:canonical: chartbook.lock.LOCK_FILE
:value: >
   'chartbook.lock'

```{autodoc2-docstring} chartbook.lock.LOCK_FILE
```

````

`````{py:class} Lock
:canonical: chartbook.lock.Lock

```{autodoc2-docstring} chartbook.lock.Lock
```

````{py:attribute} assets
:canonical: chartbook.lock.Lock.assets
:type: dict[str, dict]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.Lock.assets
```

````

````{py:method} assets_of(dependency: str) -> dict[str, dict]
:canonical: chartbook.lock.Lock.assets_of

```{autodoc2-docstring} chartbook.lock.Lock.assets_of
```

````

````{py:attribute} dependencies
:canonical: chartbook.lock.Lock.dependencies
:type: list[dict]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.Lock.dependencies
```

````

````{py:method} hashes() -> set[str]
:canonical: chartbook.lock.Lock.hashes

```{autodoc2-docstring} chartbook.lock.Lock.hashes
```

````

````{py:method} labelled() -> set[tuple[str, str, str, str]]
:canonical: chartbook.lock.Lock.labelled

```{autodoc2-docstring} chartbook.lock.Lock.labelled
```

````

````{py:attribute} root
:canonical: chartbook.lock.Lock.root
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.lock.Lock.root
```

````

````{py:method} snapshots() -> set[tuple[str, str]]
:canonical: chartbook.lock.Lock.snapshots

```{autodoc2-docstring} chartbook.lock.Lock.snapshots
```

````

````{py:method} to_document() -> dict
:canonical: chartbook.lock.Lock.to_document

```{autodoc2-docstring} chartbook.lock.Lock.to_document
```

````

`````

````{py:exception} LockError()
:canonical: chartbook.lock.LockError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.lock.LockError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.lock.LockError.__init__
```

````

````{py:data} NOT_SYNCED_YET
:canonical: chartbook.lock.NOT_SYNCED_YET
:value: >
   'In a store that machines share through a synced folder, the likeliest cause is a sync that has not f...'

```{autodoc2-docstring} chartbook.lock.NOT_SYNCED_YET
```

````

````{py:data} PIN_LINKS
:canonical: chartbook.lock.PIN_LINKS
:value: >
   None

```{autodoc2-docstring} chartbook.lock.PIN_LINKS
```

````

````{py:data} PROBLEM_STATUSES
:canonical: chartbook.lock.PROBLEM_STATUSES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.lock.PROBLEM_STATUSES
```

````

`````{py:class} PinEvent
:canonical: chartbook.lock.PinEvent

```{autodoc2-docstring} chartbook.lock.PinEvent
```

````{py:attribute} asset
:canonical: chartbook.lock.PinEvent.asset
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.lock.PinEvent.asset
```

````

````{py:attribute} dependency
:canonical: chartbook.lock.PinEvent.dependency
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.lock.PinEvent.dependency
```

````

````{py:attribute} detail
:canonical: chartbook.lock.PinEvent.detail
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lock.PinEvent.detail
```

````

````{py:attribute} new
:canonical: chartbook.lock.PinEvent.new
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.lock.PinEvent.new
```

````

````{py:attribute} old
:canonical: chartbook.lock.PinEvent.old
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.lock.PinEvent.old
```

````

````{py:attribute} status
:canonical: chartbook.lock.PinEvent.status
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.lock.PinEvent.status
```

````

`````

`````{py:class} PinReport
:canonical: chartbook.lock.PinReport

```{autodoc2-docstring} chartbook.lock.PinReport
```

````{py:method} count(*statuses: str) -> int
:canonical: chartbook.lock.PinReport.count

```{autodoc2-docstring} chartbook.lock.PinReport.count
```

````

````{py:attribute} events
:canonical: chartbook.lock.PinReport.events
:type: list[chartbook.lock.PinEvent]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.PinReport.events
```

````

````{py:attribute} git
:canonical: chartbook.lock.PinReport.git
:type: set
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.PinReport.git
```

````

````{py:attribute} lockfile
:canonical: chartbook.lock.PinReport.lockfile
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.lock.PinReport.lockfile
```

````

````{py:property} problems
:canonical: chartbook.lock.PinReport.problems
:type: list[chartbook.lock.PinEvent]

```{autodoc2-docstring} chartbook.lock.PinReport.problems
```

````

````{py:attribute} snapshots
:canonical: chartbook.lock.PinReport.snapshots
:type: dict
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lock.PinReport.snapshots
```

````

````{py:attribute} unrooted
:canonical: chartbook.lock.PinReport.unrooted
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lock.PinReport.unrooted
```

````

````{py:attribute} written
:canonical: chartbook.lock.PinReport.written
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.lock.PinReport.written
```

````

`````

````{py:data} RECENT_SECONDS
:canonical: chartbook.lock.RECENT_SECONDS
:value: >
   3600

```{autodoc2-docstring} chartbook.lock.RECENT_SECONDS
```

````

````{py:data} SCHEMA
:canonical: chartbook.lock.SCHEMA
:value: >
   'chartbook/lock/v1'

```{autodoc2-docstring} chartbook.lock.SCHEMA
```

````

````{py:function} by_its_id(key: str, pinned: typing.Optional[dict], found: typing.Callable[[], list]) -> str
:canonical: chartbook.lock.by_its_id

```{autodoc2-docstring} chartbook.lock.by_its_id
```
````

````{py:function} choose_for_rev(entry: dict, root: str, was: typing.Optional[dict], may_move: bool, snapshots: typing.Callable[[], list], host: str, git_cache: chartbook.gitcache.GitCache, project_dir: pathlib.Path, *, pinned: bool) -> tuple
:canonical: chartbook.lock.choose_for_rev

```{autodoc2-docstring} chartbook.lock.choose_for_rev
```
````

````{py:function} clone_instead(entry: dict, root: str, was: typing.Optional[dict], may_move: bool, snapshots: typing.Callable[[], list], host: str, built_here: typing.Iterable[str] = (), *, pinned: bool) -> dict
:canonical: chartbook.lock.clone_instead

```{autodoc2-docstring} chartbook.lock.clone_instead
```
````

````{py:function} is_read_only(error: Exception) -> bool
:canonical: chartbook.lock.is_read_only

```{autodoc2-docstring} chartbook.lock.is_read_only
```
````

````{py:function} label_remedy(missing: typing.Optional[str], key: str) -> str
:canonical: chartbook.lock.label_remedy

```{autodoc2-docstring} chartbook.lock.label_remedy
```
````

````{py:function} name_it_by_its_id(key: str, pinned: typing.Optional[dict], found: typing.Callable[[], list]) -> str
:canonical: chartbook.lock.name_it_by_its_id

```{autodoc2-docstring} chartbook.lock.name_it_by_its_id
```
````

````{py:function} note_this_machine(lock_path: pathlib.Path, locked: chartbook.lock.Lock, store: chartbook.store.Store) -> tuple[bool, str]
:canonical: chartbook.lock.note_this_machine

```{autodoc2-docstring} chartbook.lock.note_this_machine
```
````

````{py:function} pin(project_dir: typing.Union[str, pathlib.Path] = '.', store: typing.Optional[chartbook.store.Store] = None, git_cache: typing.Optional[chartbook.gitcache.GitCache] = None, only: typing.Optional[typing.Iterable[str]] = None, clone_missing: bool = True, built_here: typing.Iterable[str] = ()) -> chartbook.lock.PinReport
:canonical: chartbook.lock.pin

```{autodoc2-docstring} chartbook.lock.pin
```
````

````{py:function} pinned_hash(records: typing.Iterable[dict]) -> typing.Optional[str]
:canonical: chartbook.lock.pinned_hash

```{autodoc2-docstring} chartbook.lock.pinned_hash
```
````

````{py:function} plan_gc(store: typing.Optional[chartbook.store.Store] = None, forget_missing: bool = False, recent_seconds: float = RECENT_SECONDS, keep_days: float = snapshot.KEEP_DAYS, keep_lineage: bool = False, aggressive: bool = False) -> chartbook.lock.GcPlan
:canonical: chartbook.lock.plan_gc

```{autodoc2-docstring} chartbook.lock.plan_gc
```
````

````{py:function} read_lock(path: typing.Union[str, pathlib.Path]) -> typing.Optional[chartbook.lock.Lock]
:canonical: chartbook.lock.read_lock

```{autodoc2-docstring} chartbook.lock.read_lock
```
````

````{py:function} run_gc(plan: chartbook.lock.GcPlan, store: typing.Optional[chartbook.store.Store] = None) -> tuple[int, int]
:canonical: chartbook.lock.run_gc

```{autodoc2-docstring} chartbook.lock.run_gc
```
````

````{py:function} schema_path() -> pathlib.Path
:canonical: chartbook.lock.schema_path

```{autodoc2-docstring} chartbook.lock.schema_path
```
````

````{py:function} store_has_for(entry: dict, snapshots: typing.Callable[[], list], first_commit: typing.Optional[str] = None, from_repository: bool = False) -> bool
:canonical: chartbook.lock.store_has_for

```{autodoc2-docstring} chartbook.lock.store_has_for
```
````

````{py:function} update(project_dir: typing.Union[str, pathlib.Path] = '.', dependencies: typing.Iterable[str] = (), store: typing.Optional[chartbook.store.Store] = None, git_cache: typing.Optional[chartbook.gitcache.GitCache] = None) -> chartbook.lock.PinReport
:canonical: chartbook.lock.update

```{autodoc2-docstring} chartbook.lock.update
```
````

````{py:function} verify(project_dir: typing.Union[str, pathlib.Path] = '.', store: typing.Optional[chartbook.store.Store] = None, note: bool = False) -> chartbook.lock.FrozenReport
:canonical: chartbook.lock.verify

```{autodoc2-docstring} chartbook.lock.verify
```
````

````{py:function} write_lock(lock: chartbook.lock.Lock, path: typing.Union[str, pathlib.Path]) -> bool
:canonical: chartbook.lock.write_lock

```{autodoc2-docstring} chartbook.lock.write_lock
```
````
