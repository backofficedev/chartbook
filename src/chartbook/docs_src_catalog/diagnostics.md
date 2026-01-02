# Diagnostics

This page provides metadata quality diagnostics for all pipelines, dataframes, and charts in the system.

## Download Report

[Download CSV Report](_static/diagnostics/chartbook_metadata_diagnostics.csv)

## Metadata Completeness Report

```{raw} html
{% if diagnostics_data %}
<div style="overflow-x: auto; margin: 20px 0;">
<table border="1" style="border-collapse: collapse; width: 100%;">
  <thead>
    <tr style="background-color: #f0f0f0;">
      <th style="padding: 8px; text-align: left;">Name</th>
      <th style="padding: 8px; text-align: center;">Complete</th>
      <th style="padding: 8px; text-align: left;">Object Type</th>
      <th style="padding: 8px; text-align: left;">Identifier</th>
      <th style="padding: 8px; text-align: left;">Pipeline</th>
      <th style="padding: 8px; text-align: left;">Missing Fields</th>
      <th style="padding: 8px; text-align: left;">URL</th>
    </tr>
  </thead>
  <tbody>
{% for row in diagnostics_data %}
    <tr {% if not row['Metadata Complete'] %}style="background-color: #fff3cd;"{% endif %}>
      <td style="padding: 8px;">{{ row['Name'] }}</td>
      <td style="padding: 8px; text-align: center;">
{% if row['Metadata Complete'] %}✅{% else %}❌{% endif %}
      </td>
      <td style="padding: 8px;">{{ row['Object Type'] }}</td>
      <td style="padding: 8px;">
{% if row['Page Link (HTML)'] %}
        <a href="{{ row['Page Link (HTML)'] }}"><code>{{ row['Identifier'] }}</code></a>
{% else %}
        <code>{{ row['Identifier'] }}</code>
{% endif %}
      </td>
      <td style="padding: 8px;"><code>{{ row['Pipeline'] }}</code></td>
      <td style="padding: 8px; font-size: 0.9em;">{{ row['Missing Fields'] }}</td>
      <td style="padding: 8px; font-size: 0.9em;">
{% if row['Page Link (HTML)'] %}
        <a href="{{ row['Page Link (HTML)'] }}">{{ row['Page Link (HTML)'] }}</a>
{% endif %}
      </td>
    </tr>
{% endfor %}
  </tbody>
</table>
</div>
{% else %}
<p>No diagnostics data available.</p>
{% endif %}
```

## What This Report Contains

- **Pipeline Diagnostics**: Checks for missing required fields in pipeline metadata
- **Dataframe Diagnostics**: Validates dataframe documentation completeness
- **Chart Diagnostics**: Ensures all charts have complete metadata

## Required Fields by Object Type

### Pipeline Fields ({{ pipeline_field_count }} required)
- Pipeline name and description
- Lead developer and contributors
- Git repository URL
- Software modules/dependencies
- README file path

### Dataframe Fields ({{ dataframe_field_count }} required)
- Data sources and providers
- Topic tags and data access info
- License information
- File paths (Parquet, Excel, docs)
- Date column specification

### Chart Fields ({{ chart_field_count }} required)
- Chart name and description
- Legal clearance information
- Data characteristics (frequency, units, etc.)
- File paths for HTML and Excel outputs
- Associated dataframe reference

## How to Use This Report

1. **Identify Incomplete Metadata**: Rows highlighted in yellow indicate incomplete metadata
2. **Check Missing Fields**: Review the "Missing Fields" column for specific gaps
3. **Update Configuration**: Add missing fields to your pipeline's `chartbook.toml` file
4. **Verify Changes**: Rebuild the documentation to see updated diagnostics

## Summary Statistics

{% if diagnostics_summary %}
- **Total Objects**: {{ diagnostics_summary.total_count }}
- **Complete**: {{ diagnostics_summary.complete_count }} ({{ diagnostics_summary.complete_pct }}%)
- **Incomplete**: {{ diagnostics_summary.incomplete_count }} ({{ diagnostics_summary.incomplete_pct }}%)
{% endif %}
