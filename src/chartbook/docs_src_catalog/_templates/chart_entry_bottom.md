## Chart Specs

| Chart Name             | {{name}}                                                   |
|------------------------|------------------------------------------------------------|
| Chart ID               | {{chart_id}}                                               |
| Tags                   | {{tags | join(', ')}}                                      |
| Data Series Start Date | {{start_date}}                                             |
| Data Frequency         | {{frequency}}                                              |
| Observation Period     | {{observation_period}}                                     |
| Lag in Data Release    | {{release_lag}}                                            |
| Data Release Timing    | {{release_timing}}                                         |
| Seasonal Adjustment    | {{seasonal_adjustment}}                                    |
| Units                  | {{units}}                                                  |
{% if series %}| Data Series            | {{series | join(', ')}}                                            |
{% endif %}| HTML Chart             | [HTML](../download_chart/{{pipeline_id | replace('/', '--')}}/{{chart_id}}.html)    |
{% if excel_chart_exists %}| Excel Chart             | [Excel]({{excel_chart_download_path}})    |{% endif %}

## Dataframe Manifest

{% include "dataframe_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}
