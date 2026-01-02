# Examples

Learn by example with these practical demonstrations of chartbook features.

## Quick Examples

### Basic Pipeline

Create a simple analytics pipeline:

```python
import pandas as pd
from pathlib import Path

# Generate sample data
import numpy as np
df = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=365, freq='D'),
    'sales': np.random.randint(1000, 5000, 365),
    'costs': np.random.randint(500, 2000, 365)
})
df['profit'] = df['sales'] - df['costs']

# Save data
df.to_parquet('_data/financial_data.parquet')
```

### Loading Data

```python
import chartbook

# Load from a specific directory
df = chartbook.data.load(
    base_dir="_data",
    pipeline_id="EX",
    dataframe_id="repo_public"
)
```

### Generating Documentation

```console
# Generate documentation website
chartbook generate ./docs --force-write

# View locally
python -m http.server -d ./docs
```

## Complete Examples

- **Pipeline Example**: A complete analytics pipeline with charts and dataframes
- **Catalog Example**: Multi-pipeline catalog project
- **Data Pipeline**: End-to-end data processing workflow

```{toctree}
:hidden:
:maxdepth: 2

pipeline-example
chartbook-example
data-pipeline
```
