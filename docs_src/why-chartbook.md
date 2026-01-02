# Why ChartBook?

Data science teams face a common challenge: analytics work is scattered across notebooks, scripts, and shared drives. Documentation is an afterthought. When someone needs to find existing analysis or understand how a dataset was created, they spend hours searching or rebuild from scratch.

ChartBook solves this by providing a centralized platform for cataloging and documenting data science work.

## The Backstage Analogy

If you're familiar with [Backstage](https://backstage.io/), Spotify's open-source developer platform, ChartBook serves a similar purpose for data science teams.

| Backstage (Software Teams) | ChartBook (Data Science Teams) |
|----------------------------|--------------------------------|
| Software catalog | Pipeline catalog |
| Service documentation | Chart and dataframe documentation |
| API references | Dataset references |
| Tech docs | Analytics documentation |
| Templates and scaffolding | Pipeline templates |

Where Backstage helps software engineers discover microservices and APIs, ChartBook helps data scientists discover pipelines, datasets, and analytics.

## Key Benefits

### Discovery

Find existing work before starting new analysis. ChartBook generates searchable documentation sites where team members can browse pipelines, charts, and datasets.

### Documentation

Documentation is generated from your pipeline configuration, not maintained separately. Define your charts and dataframes in a TOML file, and ChartBook builds a complete documentation website.

### Governance

Track data sources, licenses, and access permissions for every dataset. Know where your data comes from, who can access it, and what restrictions apply.

### Reproducibility

Each pipeline is self-contained with its code, configuration, and outputs. Version control your pipelines and regenerate documentation as work evolves.

### Programmatic Access

Load any cataloged dataset directly into your analysis:

```python
from chartbook import data

df = data.load(pipeline_id="sales", dataframe_id="quarterly_summary")
```

## Who It's For

**Data science teams** building recurring analytics and reports.

**Analytics engineers** maintaining data pipelines and transformations.

**Research teams** producing charts and datasets that need to be discoverable.

**Organizations** that need governance and traceability for their analytics work.

## Project Types

ChartBook supports two project types:

- **Pipeline** — A single analytics pipeline with its own charts, dataframes, and documentation (`type = "pipeline"`)
- **Catalog** — A collection of multiple pipelines aggregated into a unified documentation site (`type = "catalog"`)

Start with a pipeline to document a single project, then create a catalog when you want to aggregate multiple pipelines into a searchable portal.

## How It Works

1. **Organize your work into pipelines** — Each pipeline contains code, data, and outputs
2. **Configure with TOML** — Define charts, dataframes, and metadata in `chartbook.toml`
3. **Build documentation** — Run `chartbook build` to generate an HTML site
4. **Share and discover** — Host the site internally for your team to browse

See the [Getting Started](getting-started.md) guide to create your first pipeline.
