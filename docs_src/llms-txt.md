# LLMs.txt

ChartBook provides an `llms.txt` file following the [llmstxt.org specification](https://llmstxt.org/) to help Large Language Models (LLMs) understand and work with your ChartBook projects.

## What is llms.txt?

The `llms.txt` file is a proposed standard for providing LLM-friendly documentation. It uses Markdown format with a specific structure designed to help AI assistants quickly understand a project's purpose, structure, and usage.

## File Locations

ChartBook provides llms.txt files in multiple locations:

| File | Description |
|------|-------------|
| `/llms.txt` | Main file at project root |
| `/llm/llms.txt` | Copy in dedicated directory |
| `/llm/llms-full.txt` | Comprehensive version with all documentation inline |

## Using llms.txt with AI Assistants

When working with an AI assistant (like Claude, ChatGPT, or Copilot), you can provide the llms.txt content to give the AI context about ChartBook:

### Quick Context
```bash
# Copy the concise version
cat llms.txt
```

### Full Context
```bash
# Copy the comprehensive version with all documentation
cat llm/llms-full.txt
```

### In a Chat Session
Simply paste the contents of `llms.txt` or `llm/llms-full.txt` at the beginning of your conversation with an AI assistant to provide it with context about how to work with ChartBook projects.

## Claude Code Skills

For Claude Code users, ChartBook provides a ready-to-use skill in `.claude/skills/chartbook/`. Copy this directory to your personal skills folder to enable Claude to automatically understand ChartBook projects.

See the [Claude Code Skills documentation](https://code.claude.com/docs/en/skills) for more information on using skills.

## llms.txt Content

Here is the content of the main `llms.txt` file:

```markdown
# ChartBook

> A developer platform for data science teams to discover, document, and share analytics work. Provides a centralized catalog for pipelines, charts, and dataframes with automatic documentation website generation.

ChartBook organizes analytics work into **pipelines** (self-contained projects) or **catalogs** (multi-pipeline collections). All configuration uses TOML format (`chartbook.toml`).

## Quick Start

- [Installation](docs_src/getting-started.md): `pip install chartbook` for data loading, `pipx install chartbook` for CLI
- [CLI Reference](docs_src/cli-reference.md): `chartbook build`, `chartbook publish`, `chartbook create-data-glimpses`

## Core Concepts

- [Pipelines](docs_src/user-guide/pipelines.md): Self-contained analytics projects with charts, dataframes, and documentation
- [Charts](docs_src/user-guide/charts.md): Interactive HTML visualizations with metadata and governance tracking
- [Dataframes](docs_src/user-guide/dataframes.md): Data sources in Parquet format with licensing and lineage tracking
- [Catalog Projects](docs_src/user-guide/catalog-projects.md): Aggregate multiple pipelines into unified documentation

## Configuration

- [Configuration Guide](docs_src/configuration.md): Complete `chartbook.toml` reference with all available fields

## API

- [Python API](docs_src/api/chartbook.md): `from chartbook import data; lf = data.load(pipeline="my_pipeline", dataframe="df_id")` — pipeline accepts a bare name or a scoped name (`myorg/my_pipeline`)

## Key Commands

chartbook build           # Generate HTML documentation website
chartbook build -f        # Force overwrite existing docs
chartbook publish            # Publish to directory
chartbook create-data-glimpses  # Create data summary report
chartbook config             # Configure default catalog path

## Minimal Configuration Example

All [project] keys are optional (an empty chartbook.toml is a valid pipeline manifest). Project type is inferred: a [pipelines] registry table means catalog, otherwise pipeline. Each chart and dataframe needs exactly one of docs_path (external markdown file) or docs (inline markdown).

[project]
name = "My Pipeline"
description = "Analytics pipeline description"
maintainer = "Your Name"

[charts.my_chart]
name = "My Chart"
description = "Chart description"
dataframe = "my_data"
path = "./_output/chart.html"
docs_path = "./docs_src/charts/chart.md"

[dataframes.my_data]
name = "My Data"
description = "Data description"
sources = ["Source"]
path = "./_data/data.parquet"
date_col = "date"
docs = "Documentation for this dataset."

## Directory Structure

my-pipeline/
├── chartbook.toml      # Configuration
├── _data/               # Parquet data files
├── _output/             # Generated HTML charts
├── docs_src/            # Markdown documentation
│   ├── charts/
│   └── dataframes/
└── src/                 # Python source code
```

## Resources

- [llmstxt.org](https://llmstxt.org/) - The llms.txt specification
- [Claude Code Skills](https://code.claude.com/docs/en/skills) - Using skills with Claude Code
