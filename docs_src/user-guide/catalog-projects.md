# Catalog Projects

A catalog project aggregates multiple pipelines into a unified documentation site.

## Overview

Catalog projects allow you to:
- Combine multiple analytics pipelines
- Create a centralized chart catalog
- Maintain consistent documentation
- Share analytics across teams

## Configuration

```toml
[config]
type = "catalog"
chartbook_format_version = "0.0.1"

[pipelines]

[pipelines.SALES]
path_to_pipeline = "../pipelines/sales"

[pipelines.MARKETING]
path_to_pipeline = "../pipelines/marketing"

[pipelines.FINANCE]
path_to_pipeline = "../pipelines/finance"
```

## Platform-Specific Paths

```toml
[pipelines.DATA.MONTHLY]
Unix = "/data/pipelines/monthly"
Windows = "T:/pipelines/monthly"
```

## Best Practices

- Organize pipelines by business domain
- Use consistent naming conventions
- Document pipeline relationships
- Maintain version compatibility

For examples, see {doc}`../examples/chartbook-example`.
