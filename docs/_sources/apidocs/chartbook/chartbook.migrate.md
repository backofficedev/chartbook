# {py:mod}`chartbook.migrate`

```{py:module} chartbook.migrate
```

```{autodoc2-docstring} chartbook.migrate
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MigrationPlan <chartbook.migrate.MigrationPlan>`
  - ```{autodoc2-docstring} chartbook.migrate.MigrationPlan
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`plan <chartbook.migrate.plan>`
  - ```{autodoc2-docstring} chartbook.migrate.plan
    :summary:
    ```
* - {py:obj}`run <chartbook.migrate.run>`
  - ```{autodoc2-docstring} chartbook.migrate.run
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`JOURNAL <chartbook.migrate.JOURNAL>`
  - ```{autodoc2-docstring} chartbook.migrate.JOURNAL
    :summary:
    ```
* - {py:obj}`SENTINEL_SCHEMA <chartbook.migrate.SENTINEL_SCHEMA>`
  - ```{autodoc2-docstring} chartbook.migrate.SENTINEL_SCHEMA
    :summary:
    ```
````

### API

````{py:data} JOURNAL
:canonical: chartbook.migrate.JOURNAL
:value: >
   None

```{autodoc2-docstring} chartbook.migrate.JOURNAL
```

````

````{py:exception} MigrateError()
:canonical: chartbook.migrate.MigrateError

Bases: {py:obj}`chartbook.store.StoreError`

```{autodoc2-docstring} chartbook.migrate.MigrateError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.migrate.MigrateError.__init__
```

````

`````{py:class} MigrationPlan
:canonical: chartbook.migrate.MigrationPlan

```{autodoc2-docstring} chartbook.migrate.MigrationPlan
```

````{py:attribute} done
:canonical: chartbook.migrate.MigrationPlan.done
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.done
```

````

````{py:attribute} layout
:canonical: chartbook.migrate.MigrationPlan.layout
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.layout
```

````

````{py:attribute} lost
:canonical: chartbook.migrate.MigrationPlan.lost
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.lost
```

````

````{py:property} needed
:canonical: chartbook.migrate.MigrationPlan.needed
:type: bool

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.needed
```

````

````{py:attribute} objects
:canonical: chartbook.migrate.MigrationPlan.objects
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.objects
```

````

````{py:attribute} records
:canonical: chartbook.migrate.MigrationPlan.records
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.records
```

````

````{py:attribute} root
:canonical: chartbook.migrate.MigrationPlan.root
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.root
```

````

````{py:attribute} shared
:canonical: chartbook.migrate.MigrationPlan.shared
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.shared
```

````

````{py:attribute} size_bytes
:canonical: chartbook.migrate.MigrationPlan.size_bytes
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.size_bytes
```

````

````{py:attribute} to_read
:canonical: chartbook.migrate.MigrationPlan.to_read
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.to_read
```

````

````{py:attribute} unfinished
:canonical: chartbook.migrate.MigrationPlan.unfinished
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.unfinished
```

````

````{py:attribute} unowned
:canonical: chartbook.migrate.MigrationPlan.unowned
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.migrate.MigrationPlan.unowned
```

````

`````

````{py:data} SENTINEL_SCHEMA
:canonical: chartbook.migrate.SENTINEL_SCHEMA
:value: >
   'chartbook/snapshot/moved-to-store-v2'

```{autodoc2-docstring} chartbook.migrate.SENTINEL_SCHEMA
```

````

````{py:function} plan(root) -> chartbook.migrate.MigrationPlan
:canonical: chartbook.migrate.plan

```{autodoc2-docstring} chartbook.migrate.plan
```
````

````{py:function} run(root, echo: typing.Callable[[str], None] = lambda line: None) -> chartbook.migrate.MigrationPlan
:canonical: chartbook.migrate.run

```{autodoc2-docstring} chartbook.migrate.run
```
````
