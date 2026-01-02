# Dataframes

Dataframes are the foundation of chartbook analytics. They represent structured datasets with comprehensive metadata for governance, lineage tracking, and discovery.

## Overview

A dataframe in chartbook:
- Stores data in efficient Parquet format
- Includes detailed metadata about sources and licensing
- Links to charts that use the data
- Supports documentation and lineage tracking

## Defining Dataframes

### Basic Configuration

In `chartbook.toml`:

```toml
[dataframes.sales_data]
dataframe_name = "Sales Transaction Data"
short_description_df = "Daily sales transactions with customer details"
data_sources = ["CRM System"]
path_to_parquet_data = "./_data/sales_data.parquet"
date_col = "transaction_date"
```

### Complete Configuration

All available fields:

```toml
[dataframes.market_data]
# Basic Information
dataframe_name = "Financial Market Data"
short_description_df = "Daily stock prices and trading volumes for S&P 500"

# Data Sources
data_sources = ["Bloomberg", "Reuters", "Yahoo Finance"]
data_providers = ["Bloomberg LP", "Refinitiv", "Yahoo"]
links_to_data_providers = [
    "https://www.bloomberg.com/professional",
    "https://www.refinitiv.com",
    "https://finance.yahoo.com"
]

# Access and Licensing
type_of_data_access = ["Subscription", "Subscription", "Public"]
need_to_contact_provider = ["Yes", "Yes", "No"]
data_on_pre_approved_list = ["Yes", "Yes", "N/A"]
data_license = "Bloomberg Data License Agreement"
license_expiration_date = "2025-12-31"
provider_contact_info = "marketdata@bloomberg.com"
restriction_on_use = "Internal use only, no redistribution"

# Technical Details
how_is_pulled = "Python API with daily scheduled job"
topic_tags = ["Market Data", "Equities", "S&P 500"]
date_col = "date"

# File Paths
path_to_parquet_data = "./_data/market_data.parquet"
path_to_excel_data = "./_data/market_data.xlsx"
dataframe_docs_path = "./docs_src/dataframes/market_data.md"
```

## Creating Dataframes

### Step 1: Data Collection

```python
import pandas as pd
import chartbook
from pathlib import Path

# Example: Load from multiple sources
def collect_market_data():
    # Bloomberg data
    bloomberg_df = fetch_bloomberg_data()
    
    # Yahoo Finance data
    yahoo_df = fetch_yahoo_data()
    
    # Merge and clean
    df = pd.merge(
        bloomberg_df,
        yahoo_df,
        on=['date', 'ticker'],
        how='outer'
    )
    
    return df

df = collect_market_data()
```

### Step 2: Data Processing

```python
# Standardize and clean data
def process_market_data(df):
    # Ensure date column is datetime
    df['date'] = pd.to_datetime(df['date'])
    
    # Remove duplicates
    df = df.drop_duplicates(['date', 'ticker'])
    
    # Sort by date
    df = df.sort_values(['date', 'ticker'])
    
    # Add calculated fields
    df['returns'] = df.groupby('ticker')['close'].pct_change()
    
    # Handle missing values
    df = df.fillna(method='ffill')
    
    return df

df_processed = process_market_data(df)
```

### Step 3: Save to Parquet

```python
# Save with optimization
output_path = Path("_data/market_data.parquet")
output_path.parent.mkdir(exist_ok=True)

df_processed.to_parquet(
    output_path,
    engine='pyarrow',
    compression='snappy',
    index=False
)

# Also save Excel for non-technical users
df_processed.to_excel(
    "_data/market_data.xlsx",
    index=False,
    freeze_panes=(1, 2)
)
```

### Step 4: Documentation

Create `docs_src/dataframes/market_data.md`:

```markdown
# Financial Market Data

## Overview
Daily stock prices and trading volumes for all S&P 500 constituents.

## Data Dictionary

| Column | Type | Description |
|--------|------|-------------|
| date | datetime | Trading date |
| ticker | string | Stock symbol |
| open | float | Opening price |
| high | float | Daily high |
| low | float | Daily low |
| close | float | Closing price |
| volume | int | Shares traded |
| returns | float | Daily returns |

## Data Sources
- **Bloomberg**: Primary source for pricing data
- **Yahoo Finance**: Backup and validation source

## Update Schedule
- Frequency: Daily at 6 PM ET
- Lag: T+0 (same day)
- History: January 2010 - present

## Quality Checks
- Missing data: Forward-filled for holidays
- Outliers: Flagged if daily move > 20%
- Validation: Cross-checked between sources

## Usage Notes
- Prices are adjusted for splits and dividends
- Volume is unadjusted
- Returns calculated as simple returns
```

## Data Management

### Data Governance

Track data lineage and compliance:

```toml
# Licensing information
data_license = "Bloomberg Data License"
license_expiration_date = "2025-12-31"
restriction_on_use = "Internal analytics only"

# Access control
need_to_contact_provider = ["Yes"]
data_on_pre_approved_list = ["Yes"]
```

### Data Quality

Implement quality checks:

```python
def validate_dataframe(df, config):
    """Validate dataframe meets quality standards."""
    
    # Check required columns exist
    date_col = config['date_col']
    assert date_col in df.columns, f"Missing date column: {date_col}"
    
    # Check data types
    assert pd.api.types.is_datetime64_any_dtype(df[date_col]), \
        f"{date_col} must be datetime"
    
    # Check for duplicates
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        print(f"Warning: {dup_count} duplicate rows found")
    
    # Check date range
    date_range = df[date_col].max() - df[date_col].min()
    print(f"Date range: {date_range.days} days")
    
    return True
```

### Data Versioning

Track data changes:

```python
# Add version metadata
def add_version_info(df):
    df.attrs['version'] = '1.2.0'
    df.attrs['created_date'] = pd.Timestamp.now()
    df.attrs['created_by'] = 'analytics_pipeline'
    return df

# Save with metadata
df_versioned = add_version_info(df)
df_versioned.to_parquet('_data/market_data_v1.2.0.parquet')
```

## Best Practices

### 1. File Organization

Structure your data files:
```
_data/
├── raw/              # Original data files
│   ├── bloomberg_20240115.csv
│   └── yahoo_20240115.csv
├── processed/        # Cleaned data
│   └── market_data_clean.parquet
├── market_data.parquet  # Final output
└── archive/          # Historical versions
    └── market_data_v1.1.0.parquet
```

### 2. Efficient Storage

Optimize Parquet files:
```python
# Use appropriate data types
df['ticker'] = df['ticker'].astype('category')
df['date'] = pd.to_datetime(df['date'])

# Partition large datasets
df.to_parquet(
    '_data/market_data',
    partition_cols=['year', 'month'],
    engine='pyarrow'
)
```

### 3. Documentation Standards

Every dataframe should document:
- **Purpose**: Why this data exists
- **Sources**: Where data comes from
- **Schema**: Column definitions
- **Quality**: Known issues or limitations
- **Updates**: How often refreshed

### 4. Access Patterns

Design for common queries:
```python
# Index for fast lookups
df = df.set_index(['date', 'ticker']).sort_index()

# Create summary tables
daily_summary = df.groupby('date').agg({
    'volume': 'sum',
    'returns': 'mean'
})
daily_summary.to_parquet('_data/daily_summary.parquet')
```

## Loading Data

### From chartbook

```python
import chartbook

# Load from current pipeline
df = chartbook.data.load(dataframe_id="market_data")

# Load from specific pipeline
df = chartbook.data.load(
    pipeline_id="MARKETS",
    dataframe_id="market_data"
)

# Load from different chartbook
df = chartbook.data.load(
    chartbook="analytics_book",
    pipeline_id="MARKETS",
    dataframe_id="market_data"
)
```

### Direct Loading

```python
# Load Parquet file
df = pd.read_parquet("_data/market_data.parquet")

# Load specific columns
df = pd.read_parquet(
    "_data/market_data.parquet",
    columns=['date', 'ticker', 'close']
)

# Load with filters
df = pd.read_parquet(
    "_data/market_data.parquet",
    filters=[('date', '>=', '2024-01-01')]
)
```

## Integration with Trino

Upload dataframes to Trino:

```bash
chartbook upload-to-trino --database-name analytics_db
```

Query from Trino:
```python
import chartbook

query = """
SELECT date, ticker, close
FROM analytics_db.market_data
WHERE date >= DATE '2024-01-01'
"""

df = chartbook.trino.submit_query(query)
```

## Next Steps

- Explore {doc}`charts` to visualize your data
- See {doc}`../examples/data-pipeline` for complete examples