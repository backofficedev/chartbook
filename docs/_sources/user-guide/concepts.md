# Core Concepts

ChartBook uses a hierarchical system for organizing and sharing data science work. Understanding these concepts will help you structure your projects effectively.

## Terminology Overview

| Term | Description |
|------|-------------|
| **Pipeline** | A single reproducible analytics project with charts, dataframes, and documentation |
| **Catalog** | A collection of pipelines aggregated into a unified, browsable documentation site |
| **ChartBook** | A curated narrative document combining charts and text from one or more pipelines |
| **ChartHub** | The global platform for sharing ChartBooks and Catalogs publicly |

## System Hierarchy

```
ChartHub (global sharing platform)
│
├── Organization A's Catalog
│   ├── Pipeline 1 → produces → ChartBook(s)
│   ├── Pipeline 2 → produces → ChartBook(s)
│   └── Pipeline 3 → produces → ChartBook(s)
│
└── Organization B's Catalog
    └── ...
```

## Pipeline

A **Pipeline** is the fundamental unit in ChartBook. It represents a single, self-contained analytics project.

### What a Pipeline Contains

- **Source code** for data processing and analysis
- **Dataframes** with documented schemas and metadata
- **Charts** with interactive visualizations
- **Notebooks** for exploratory analysis
- **Documentation** generated from your configuration

### When to Use a Pipeline

Use a Pipeline when you have:

- A single analytics project or workflow
- One team working on related analyses
- Data that flows through a defined process
- Charts and outputs that belong together logically

### Pipeline Configuration

Pipelines are configured with `chartbook.toml`:

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.1.0"

[site]
title = "My Analytics Pipeline"
author = "Data Team"

[pipeline]
id = "ANALYTICS"
pipeline_name = "Quarterly Analytics"
pipeline_description = "Quarterly business metrics and analysis"
```

See {doc}`pipelines` for detailed configuration options.

## Catalog

A **Catalog** aggregates multiple Pipelines into a unified documentation site, making it easy to discover and connect related work across teams.

### What a Catalog Provides

- **Unified search** across all pipelines
- **Cross-pipeline navigation** and discovery
- **Centralized documentation** for an organization or team
- **Data connectivity** between pipelines via the Python API

### When to Use a Catalog

Use a Catalog when you have:

- Multiple related pipelines to organize
- Teams that need to discover each other's work
- Data that flows between different pipelines
- An organization-wide analytics portal

### Catalog Configuration

```toml
[config]
type = "catalog"
chartbook_format_version = "0.1.0"

[site]
title = "Analytics Catalog"
author = "Data Science Team"

[pipelines.quarterly]
path_to_pipeline = "./pipelines/quarterly"

[pipelines.monthly]
path_to_pipeline = "./pipelines/monthly"
```

See {doc}`catalog-projects` for detailed configuration options.

### Connecting Pipelines

One of the key benefits of a Catalog is the ability to load data from any pipeline programmatically:

```python
from chartbook import data

# Load data from any pipeline in your catalog
quarterly_df = data.load(pipeline_id="QUARTERLY", dataframe_id="summary")
monthly_df = data.load(pipeline_id="MONTHLY", dataframe_id="metrics")
```

## ChartBook (Future Feature)

A **ChartBook** is a curated narrative document that combines charts, data, and explanatory text from one or more pipelines into a polished, shareable report.

```{note}
ChartBook creation is a planned feature. Currently, pipelines generate documentation automatically. The ChartBook feature will allow you to create custom narrative documents by selecting and arranging content from your pipelines.
```

### Vision for ChartBooks

- Select charts from multiple pipelines
- Add narrative text between visualizations
- Create executive summaries and reports
- Share as standalone documents

## ChartHub (Future Feature)

**ChartHub** is envisioned as a global platform for sharing ChartBooks and Catalogs publicly—similar to how GitHub enables sharing code repositories.

```{note}
ChartHub is a planned platform. Currently, you can host your generated documentation on any static site hosting service (GitHub Pages, Netlify, etc.).
```

### Vision for ChartHub

- Public catalog of shared analytics work
- Discover and learn from others' pipelines
- Fork and adapt existing analyses
- Build a community around reproducible analytics

## Choosing Between Pipeline and Catalog

```{list-table}
:header-rows: 1
:widths: 20 40 40

* - Consideration
  - Choose Pipeline
  - Choose Catalog
* - Scope
  - Single project or workflow
  - Multiple related projects
* - Team size
  - One team, focused work
  - Multiple teams, shared resources
* - Data relationships
  - Self-contained data
  - Data shared across projects
* - Documentation
  - Single documentation site
  - Unified portal for discovery
```

## Next Steps

- {doc}`pipelines` — Learn how to build your first pipeline
- {doc}`charts` — Create interactive visualizations
- {doc}`dataframes` — Document your data sources
- {doc}`catalog-projects` — Aggregate pipelines into a catalog
