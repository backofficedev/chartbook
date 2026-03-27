# Notebooks

Integrate Jupyter notebooks into your chartbook documentation.

## Overview

Notebooks in chartbook:
- Document analytical workflows
- Provide interactive exploration
- Show methodology and code
- Support reproducible research

## Configuration

The notebook name is automatically inferred from the first `# Heading` in the notebook. You only need `notebook_description` and `notebook_path`:

```toml
[notebooks]

[notebooks.analysis]
notebook_description = "Initial data exploration and insights"
notebook_path = "_output/01_analysis.ipynb"
```

Set `notebook_name` explicitly to override the inferred title.

## Best Practices

- Clear notebook outputs before committing
- Use meaningful cell tags and headings
- Document assumptions and methodology
- Include requirements.txt for dependencies 